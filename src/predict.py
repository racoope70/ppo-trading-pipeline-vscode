"""Prediction utilities for the PPO trading pipeline.

This module loads trained PPO artifacts, rebuilds the latest feature window,
runs inference, and emits a platform-neutral signal. The output can later be
used by QuantConnect, Alpaca, or local backtesting adapters.
"""

from __future__ import annotations

import json
import logging
import math
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf

from src.artifacts import (
    get_artifact_paths,
    list_model_prefixes,
    load_feature_list,
    load_json,
    load_model_and_env,
)
from src.config import (
    BROKER,
    ENABLE_SENTIMENT,
    FINAL_MODEL_DIR,
    LIVE_MODE,
    SIM_LATENCY_MS,
    SYMBOLS,
    make_results_dir,
)
from src.data_download import postprocess_download
from src.features import compute_enhanced_features
from src.training_utils import get_mu_sigma


def normal_cdf(x: float) -> float:
    """Standard normal cumulative distribution function."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def action_to_signal(
    action: float,
    buy_threshold: float = 0.10,
    sell_threshold: float = -0.30,
) -> str:
    """Convert a continuous PPO action into a discrete signal label."""
    if action > buy_threshold:
        return "BUY"

    if action < sell_threshold:
        return "SELL"

    return "HOLD"


def load_probability_config(
    prefix: str,
    model_dir: Path = FINAL_MODEL_DIR,
) -> dict[str, Any]:
    """Load probability/inference config for a trained model."""
    paths = get_artifact_paths(prefix, model_dir)

    if not paths.probability_config_path.exists():
        logging.warning(
            "Probability config not found for %s. Using default config.",
            prefix,
        )
        return {
            "threshold": 0.05,
            "use_confidence": True,
            "inference_mode": "deterministic",
        }

    return load_json(paths.probability_config_path)


def choose_execution_adjusted_prefix(
    symbol: str,
    model_dir: Path = FINAL_MODEL_DIR,
) -> str | None:
    """Choose prefix using the latest execution-realism analysis when available.

    This keeps live/QuantConnect export aligned with the research conclusion:
    prefer the best moderate-scenario execution-adjusted window when
    execution_realism_analysis.csv exists.
    """
    search_root = Path("reports/backtests")

    analysis_files = sorted(
        search_root.glob("ppo_walkforward_results_*/execution_realism_analysis.csv")
    )

    if not analysis_files:
        return None

    latest_analysis = analysis_files[-1]

    try:
        execution = pd.read_csv(latest_analysis)
    except Exception as exc:
        logging.warning(
            "Could not read execution realism analysis at %s: %s",
            latest_analysis,
            exc,
        )
        return None

    required_columns = {
        "Ticker",
        "Scenario",
        "Prefix",
        "Execution_Edge_vs_BuyHold",
    }
    missing_columns = required_columns - set(execution.columns)

    if missing_columns:
        logging.warning(
            "Execution realism analysis missing columns %s. Falling back to metadata selector.",
            sorted(missing_columns),
        )
        return None

    candidates = execution[
        (execution["Ticker"].astype(str).eq(symbol))
        & (execution["Scenario"].astype(str).str.lower().eq("moderate"))
    ].copy()

    if candidates.empty:
        return None

    candidates["Execution_Edge_vs_BuyHold"] = pd.to_numeric(
        candidates["Execution_Edge_vs_BuyHold"],
        errors="coerce",
    )

    candidates = candidates.dropna(subset=["Execution_Edge_vs_BuyHold"])

    if candidates.empty:
        return None

    best = candidates.sort_values(
        "Execution_Edge_vs_BuyHold",
        ascending=False,
    ).iloc[0]

    prefix = str(best["Prefix"])
    paths = get_artifact_paths(prefix, model_dir)

    required_artifacts = [
        paths.model_path,
        paths.vecnorm_path,
        paths.features_path,
        paths.model_info_path,
        paths.probability_config_path,
    ]

    missing_artifacts = [path for path in required_artifacts if not path.exists()]

    if missing_artifacts:
        logging.warning(
            "Execution-adjusted prefix %s selected for %s, but artifacts are missing: %s. "
            "Falling back to metadata selector.",
            prefix,
            symbol,
            missing_artifacts,
        )
        return None

    logging.info(
        (
            "Selected execution-adjusted model for %s: %s | "
            "ExecutionEdge=%.2f | Source=%s"
        ),
        symbol,
        prefix,
        float(best["Execution_Edge_vs_BuyHold"]),
        latest_analysis,
    )

    return prefix


def choose_best_prefix(
    symbol: str,
    model_dir: Path = FINAL_MODEL_DIR,
    min_sharpe: float | None = None,
    max_drawdown_pct: float | None = None,
    min_final_portfolio: float | None = None,
    prefer_winner_ppo: bool = True,
) -> str:
    """Choose the best available model prefix for a symbol using model metadata.

    Selection priority:
        1. Prefer complete artifact sets with readable model_info.json.
        2. Optionally filter by Sharpe, drawdown, and final portfolio.
        3. If prefer_winner_ppo=True, prefer windows where Winner == PPO.
        4. Rank by Sharpe, final portfolio, and window number.
        5. Fall back to highest window number if metadata is missing.
    """
    execution_adjusted_prefix = choose_execution_adjusted_prefix(
        symbol=symbol,
        model_dir=model_dir,
    )

    if execution_adjusted_prefix is not None:
        return execution_adjusted_prefix

    prefixes = [
        prefix
        for prefix in list_model_prefixes(model_dir)
        if prefix.startswith(f"ppo_{symbol}_window")
    ]

    if not prefixes:
        raise FileNotFoundError(
            f"No PPO model artifacts found for {symbol} in {model_dir}"
        )

    candidates: list[dict[str, Any]] = []

    def window_number(prefix: str) -> int:
        try:
            return int(prefix.split("_window")[-1])
        except Exception:
            return -1

    for prefix in prefixes:
        paths = get_artifact_paths(prefix, model_dir)

        if not paths.model_info_path.exists():
            logging.warning(
                "Model info missing for %s. It will only be used as fallback.",
                prefix,
            )
            continue

        try:
            info = load_json(paths.model_info_path)

            sharpe = float(info.get("sharpe", float("-inf")))
            final_portfolio = float(info.get("final_portfolio", 0.0))
            buy_hold = float(info.get("buy_hold", 0.0))
            winner = str(info.get("winner", "")).strip()

            drawdown = info.get("drawdown_pct", info.get("drawdown_%", None))
            if drawdown is not None:
                drawdown = float(drawdown)

            if min_sharpe is not None and sharpe < min_sharpe:
                continue

            if (
                max_drawdown_pct is not None
                and drawdown is not None
                and drawdown > max_drawdown_pct
            ):
                continue

            if (
                min_final_portfolio is not None
                and final_portfolio < min_final_portfolio
            ):
                continue

            is_winner_ppo = winner.upper() == "PPO"

            candidates.append(
                {
                    "prefix": prefix,
                    "sharpe": sharpe,
                    "final_portfolio": final_portfolio,
                    "buy_hold": buy_hold,
                    "drawdown": drawdown,
                    "winner": winner,
                    "is_winner_ppo": is_winner_ppo,
                    "window": window_number(prefix),
                }
            )

        except Exception as exc:
            logging.warning("Could not read model info for %s: %s", prefix, exc)

    if candidates:
        ranking_pool = candidates

        if prefer_winner_ppo:
            winner_pool = [
                item for item in candidates
                if item["is_winner_ppo"]
            ]

            if winner_pool:
                ranking_pool = winner_pool
            else:
                logging.info(
                    "No Winner=PPO candidates found for %s. Ranking all candidates by Sharpe.",
                    symbol,
                )

        best = sorted(
            ranking_pool,
            key=lambda item: (
                item["sharpe"],
                item["final_portfolio"],
                item["window"],
            ),
            reverse=True,
        )[0]

        logging.info(
            (
                "Selected model for %s: %s | Sharpe=%.3f | "
                "FinalPortfolio=%.2f | BuyHold=%.2f | Drawdown=%s | Winner=%s"
            ),
            symbol,
            best["prefix"],
            best["sharpe"],
            best["final_portfolio"],
            best["buy_hold"],
            best["drawdown"],
            best["winner"],
        )

        return str(best["prefix"])

    logging.warning(
        "No usable model_info.json metadata found for %s. Falling back to latest window.",
        symbol,
    )

    return sorted(prefixes, key=window_number)[-1]


def choose_latest_prefix(
    symbol: str,
    model_dir: Path = FINAL_MODEL_DIR,
) -> str:
    """Backward-compatible alias for model selection.

    Kept so older code does not break. New code should use choose_best_prefix().
    """
    return choose_best_prefix(symbol=symbol, model_dir=model_dir)


def fetch_latest_raw_data(
    symbol: str,
    horizon_days: int = 30,
    interval: str = "1h",
) -> pd.DataFrame | None:
    """Fetch recent raw OHLCV data for inference."""
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=horizon_days)

    raw = yf.download(
        symbol,
        start=start.strftime("%Y-%m-%d"),
        end=end.strftime("%Y-%m-%d"),
        interval=interval,
        progress=False,
        auto_adjust=False,
        group_by="column",
        threads=False,
        prepost=False,
        repair=True,
    )

    if raw is None or raw.empty:
        logging.warning("No recent raw data returned for %s.", symbol)
        return None

    return postprocess_download(raw, symbol)


def latest_df_for_symbol(
    symbol: str,
    horizon_days: int = 30,
    interval: str = "1h",
) -> pd.DataFrame | None:
    """Fetch recent bars and rebuild features exactly like training."""
    raw = fetch_latest_raw_data(
        symbol=symbol,
        horizon_days=horizon_days,
        interval=interval,
    )

    if raw is None or raw.empty:
        return None

    features = compute_enhanced_features(
        raw,
        use_sentiment=ENABLE_SENTIMENT,
    )

    if features is None or features.empty:
        logging.warning("Feature engineering returned no rows for %s.", symbol)
        return None

    features["Datetime"] = pd.to_datetime(features["Datetime"], utc=True)

    return features.sort_values("Datetime").reset_index(drop=True)


def align_to_training_features(
    df: pd.DataFrame,
    trained_features: list[str],
) -> pd.DataFrame:
    """Align inference dataframe to the trained feature list while preserving env columns.

    The PPO environment still needs columns such as Datetime and Close for
    timestamping, pricing, and reward mechanics. Missing trained feature columns
    are filled with 0.0, extra columns are kept only when required by the env.
    """
    aligned = df.copy()

    for col in trained_features:
        if col not in aligned.columns:
            aligned[col] = 0.0

    required_env_columns = [
        "Datetime",
        "Symbol",
        "Open",
        "High",
        "Low",
        "Close",
        "Volume",
        "Denoised_Close",
        "MACD_Line",
        "SentimentScore",
    ]

    output_columns = []
    for col in trained_features + required_env_columns:
        if col in aligned.columns and col not in output_columns:
            output_columns.append(col)

    return aligned[output_columns].copy()

def prepare_inference_window(
    symbol: str,
    prefix: str,
    horizon_days: int = 30,
    interval: str = "1h",
    max_window_rows: int = 2500,
) -> pd.DataFrame | None:
    """Fetch, rebuild, and align the latest inference window."""
    live_df = latest_df_for_symbol(
        symbol=symbol,
        horizon_days=horizon_days,
        interval=interval,
    )

    if live_df is None or live_df.empty:
        return None

    if len(live_df) < 100:
        logging.warning(
            "Not enough recent rows for %s inference: %s rows.",
            symbol,
            len(live_df),
        )
        return None

    trained_features = load_feature_list(prefix, FINAL_MODEL_DIR)

    aligned_df = align_to_training_features(live_df, trained_features)

    if len(aligned_df) > max_window_rows:
        aligned_df = aligned_df.iloc[-max_window_rows:].reset_index(drop=True)
    else:
        aligned_df = aligned_df.reset_index(drop=True)

    return aligned_df


def fast_forward_env_to_latest(env, df_window: pd.DataFrame):
    """Advance environment to the latest bar using flat/hold actions."""
    obs = env.reset()

    if isinstance(obs, tuple):
        obs, _ = obs

    for _ in range(len(df_window) - 1):
        obs, _reward, dones, _infos = env.step(
            [np.array([0.0], dtype=np.float32)]
        )

        if isinstance(dones, (np.ndarray, list, tuple)):
            if bool(dones[0]):
                break
        elif dones:
            break

    return obs


def predict_latest(
    symbol: str,
    prefix: str | None = None,
    horizon_days: int = 30,
    interval: str = "1h",
    deterministic: bool = True,
) -> dict[str, Any] | None:
    """Run latest PPO inference for one symbol."""
    if prefix is None:
        prefix = choose_best_prefix(symbol)

    probability_config = load_probability_config(prefix)
    inference_mode = probability_config.get("inference_mode", "deterministic")

    if inference_mode == "stochastic":
        deterministic = False

    df_window = prepare_inference_window(
        symbol=symbol,
        prefix=prefix,
        horizon_days=horizon_days,
        interval=interval,
    )

    if df_window is None or df_window.empty:
        return None

    model, env = load_model_and_env(
        prefix=prefix,
        df_window=df_window,
        model_dir=FINAL_MODEL_DIR,
        device="cpu",
    )

    try:
        obs = fast_forward_env_to_latest(env, df_window)

        action, _state = model.predict(obs, deterministic=deterministic)
        mu, sigma = get_mu_sigma(model, obs)

        action_value = float(np.array(action).squeeze())

        p_long = 1.0 - normal_cdf((0.0 - mu) / max(sigma, 1e-6))
        p_short = 1.0 - p_long

        signal = action_to_signal(action_value)
        confidence = abs(action_value)

        timestamp = (
            df_window["Datetime"].iloc[-1]
            if "Datetime" in df_window.columns
            else None
        )

        price = (
            float(df_window["Close"].iloc[-1])
            if "Close" in df_window.columns
            else np.nan
        )

        prediction = {
            "symbol": symbol,
            "prefix": prefix,
            "timestamp": str(timestamp),
            "price": price,
            "signal": signal,
            "confidence": confidence,
            "action": action_value,
            "p_long": float(p_long),
            "p_short": float(p_short),
            "mu": float(mu),
            "sigma": float(sigma),
            "deterministic": deterministic,
            "rows_used": int(len(df_window)),
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
        }

        return prediction

    finally:
        try:
            env.close()
        except Exception:
            pass


def save_prediction(
    prediction: dict[str, Any],
    output_dir: Path,
) -> Path:
    """Save a prediction signal JSON file."""
    output_dir.mkdir(parents=True, exist_ok=True)

    symbol = prediction["symbol"]
    prefix = prediction["prefix"]

    output_path = output_dir / f"{prefix}_latest_signal.json"

    with output_path.open("w") as file:
        json.dump(prediction, file, indent=2, default=str)

    logging.info("Saved latest prediction for %s to %s", symbol, output_path)

    return output_path


def predict_symbols(
    symbols: list[str] | None = None,
    output_dir: Path | None = None,
    horizon_days: int = 30,
    interval: str = "1h",
) -> list[dict[str, Any]]:
    """Run latest prediction for multiple symbols."""
    symbols = symbols or SYMBOLS
    output_dir = output_dir or make_results_dir()

    predictions = []

    for symbol in symbols:
        try:
            prediction = predict_latest(
                symbol=symbol,
                prefix=None,
                horizon_days=horizon_days,
                interval=interval,
            )

            if prediction is None:
                logging.warning("No prediction generated for %s.", symbol)
                continue

            predictions.append(prediction)
            save_prediction(prediction, output_dir=output_dir)

            logging.info(
                "%s | %s | action=%.4f | conf=%.4f | price=%.2f | prefix=%s",
                symbol,
                prediction["signal"],
                prediction["action"],
                prediction["confidence"],
                prediction["price"],
                prediction["prefix"],
            )

        except Exception as exc:
            logging.exception("Prediction failed for %s: %s", symbol, exc)

    return predictions


def place_order(signal: str, quantity: float = 1.0) -> None:
    """Temporary broker stub.

    Alpaca integration should live in a later adapter module. For now, this
    keeps the same behavior as the notebook: log the intended action.
    """
    if SIM_LATENCY_MS > 0:
        time.sleep(SIM_LATENCY_MS / 1000.0)

    if BROKER == "log":
        logging.info("[PAPER/STUB] %s x%s", signal, quantity)
    else:
        logging.info("[BROKER=%s] %s x%s not implemented.", BROKER, signal, quantity)


def live_loop(
    symbol: str,
    prefix: str | None = None,
    poll_seconds: int = 60,
) -> None:
    """Simple polling loop for paper/live inference.

    This is intentionally broker-neutral. Alpaca order execution should be
    implemented later in src/adapters/alpaca.py.
    """
    while LIVE_MODE:
        try:
            prediction = predict_latest(symbol=symbol, prefix=prefix)

            if prediction:
                logging.info(
                    "%s %s | %s @ %.2f | conf %.2f",
                    symbol,
                    prediction["timestamp"],
                    prediction["signal"],
                    prediction["price"],
                    prediction["confidence"],
                )
                place_order(prediction["signal"], quantity=1)

        except Exception as exc:
            logging.exception("Live loop error for %s: %s", symbol, exc)

        time.sleep(poll_seconds)


def main() -> None:
    """Command-line entry point for local PPO prediction."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        force=True,
    )

    results_dir = make_results_dir()

    logging.info("Prediction output directory: %s", results_dir)
    logging.info("Available model prefixes: %s", list_model_prefixes(FINAL_MODEL_DIR))

    predictions = predict_symbols(
        symbols=SYMBOLS,
        output_dir=results_dir,
    )

    if not predictions:
        logging.warning("No predictions generated.")
        return

    output_path = results_dir / "latest_predictions.csv"
    pd.DataFrame(predictions).to_csv(output_path, index=False)

    logging.info("Saved prediction table to %s", output_path)


if __name__ == "__main__":
    main()