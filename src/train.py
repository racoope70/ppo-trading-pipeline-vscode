"""Train PPO models with walk-forward validation.

This script is the local VS Code replacement for the PPO walk-forward training
section of the original notebook. It loads the prepared dataset, trains PPO
models per ticker/window, saves model artifacts, saves predictions, and writes
summary results to local report folders.
"""

from __future__ import annotations

import gc
import heapq
import logging
import time
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from stable_baselines3 import PPO
from stable_baselines3.common.utils import set_random_seed
from stable_baselines3.common.vec_env import DummyVecEnv, VecNormalize

from src.artifacts import (
    missing_artifacts,
    required_artifacts_exist,
    save_quantconnect_model,
)
from src.config import (
    DATA_PATH,
    ENABLE_SENTIMENT,
    ENABLE_SLO,
    ENABLE_WAVELET,
    FINAL_MODEL_DIR,
    INITIAL_BALANCE,
    MAX_WORKERS,
    MIN_ROWS_BUFFER,
    RANDOM_SEED,
    SYMBOLS,
    TEST_MODE,
    TIMESTEPS,
    TOP_N_WINDOWS,
    WINDOW_SIZE,
    STEP_SIZE,
    make_results_dir,
    pick_params,
)
from src.env import ContinuousPositionEnv
from src.training_utils import (
    get_mu_sigma,
    get_walk_forward_windows,
    record_skips_global,
    summarize_skip_log,
)


def load_training_dataset(path: Path = DATA_PATH) -> pd.DataFrame:
    """Load the prepared model dataset."""
    if not path.exists():
        raise FileNotFoundError(
            f"Prepared dataset not found: {path}. "
            "Run `python -m src.prepare_data` first."
        )

    df = pd.read_csv(path)

    if "Datetime" not in df.columns:
        raise ValueError("Dataset must contain a Datetime column.")

    if "Symbol" not in df.columns:
        raise ValueError("Dataset must contain a Symbol column.")

    df["Datetime"] = pd.to_datetime(df["Datetime"], utc=True)
    df = df.sort_values(["Symbol", "Datetime"]).reset_index(drop=True)

    return df


def validate_symbol_data(df: pd.DataFrame, symbol: str) -> bool:
    """Return whether a ticker dataframe has the minimum columns needed."""
    required_columns = ["Close", "Datetime"]

    if ENABLE_WAVELET:
        required_columns.append("Denoised_Close")

    if ENABLE_SENTIMENT:
        required_columns.append("SentimentScore")

    missing = [col for col in required_columns if col not in df.columns]

    if missing:
        logging.warning("Skipping %s: missing required columns %s", symbol, missing)
        return False

    min_rows = WINDOW_SIZE + MIN_ROWS_BUFFER

    if len(df) < min_rows:
        logging.warning(
            "Skipping %s: only %s rows (< %s required)",
            symbol,
            len(df),
            min_rows,
        )
        return False

    return True


def make_training_env(df_window: pd.DataFrame):
    """Create the VecNormalize-wrapped PPO training environment."""
    frame_bound = (50, len(df_window) - 3)

    env = DummyVecEnv(
        [
            lambda: ContinuousPositionEnv(
                df=df_window,
                frame_bound=frame_bound,
                window_size=10,
                cost_rate=(0.0002 if ENABLE_SLO else 0.0),
                slip_rate=(0.0003 if ENABLE_SLO else 0.0),
                k_alpha=0.20,
                k_mom=0.05,
                k_sent=(0.01 if ENABLE_SENTIMENT else 0.0),
                mom_source="denoised",
                mom_lookback=20,
                min_trade_delta=0.01,
                cooldown=5,
                reward_clip=1.0,
            )
        ]
    )

    env = VecNormalize(
        env,
        norm_obs=True,
        norm_reward=True,
        clip_obs=10.0,
    )

    return env


def build_ppo_model(
    env,
    learning_rate: float,
    ppo_overrides: dict | None = None,
) -> PPO:
    """Build a Stable-Baselines3 PPO model using configured overrides."""
    ppo_overrides = ppo_overrides or {}
    device = "cuda" if torch.cuda.is_available() else "cpu"

    return PPO(
        "MlpPolicy",
        env,
        verbose=0,
        device=device,
        learning_rate=ppo_overrides.get("lr", learning_rate),
        n_steps=ppo_overrides.get("n_steps", 256),
        batch_size=ppo_overrides.get("batch", 64),
        n_epochs=5,
        gamma=0.99,
        gae_lambda=0.95,
        clip_range=ppo_overrides.get("clip", 0.2),
        ent_coef=ppo_overrides.get("ent", 0.005),
        policy_kwargs={"net_arch": [64, 64]},
        seed=RANDOM_SEED,
    )


def evaluate_model_on_window(
    model: PPO,
    env,
    df_window: pd.DataFrame,
) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    """Evaluate a trained PPO model on one window and return metrics/logs."""
    env.training = False
    env.norm_reward = False

    obs = env.reset()

    if isinstance(obs, tuple):
        obs, _ = obs

    nav_track = [1.0]
    buy_hold_track = [1.0]
    step_log = []

    for step_idx in range(len(df_window) - 1):
        action, _ = model.predict(obs, deterministic=True)
        mu, sigma = get_mu_sigma(model, obs)

        obs, _reward, dones, infos = env.step(action)
        info = infos[0] if isinstance(infos, (list, tuple)) else infos

        nav_track.append(float(info.get("nav", nav_track[-1])))

        ret_t = float(info.get("ret_t", 0.0))
        buy_hold_track.append(buy_hold_track[-1] * (1.0 + ret_t))

        action_value = float(np.array(action).squeeze())

        dt_value = (
            df_window["Datetime"].iloc[step_idx + 1]
            if "Datetime" in df_window.columns
            else None
        )

        close_price = (
            float(df_window["Close"].iloc[step_idx + 1])
            if "Close" in df_window.columns
            else np.nan
        )

        step_log.append(
            {
                "Index": step_idx + 1,
                "Datetime": dt_value,
                "Close": close_price,
                "Action": action_value,
                "mu": mu,
                "sigma": sigma,
                "nav": nav_track[-1],
                "ret_t": ret_t,
                "pos": float(info.get("pos", 0.0)),
                "trade_cost": float(info.get("trade_cost", 0.0)),
                "base_ret": float(info.get("base_ret", 0.0)),
                "rel_alpha": float(info.get("rel_alpha", 0.0)),
                "mom": float(info.get("mom", 0.0)),
            }
        )

        if isinstance(dones, (np.ndarray, list, tuple)):
            if bool(dones[0]):
                break
        elif dones:
            break

    nav_series = pd.Series(nav_track, dtype="float64")
    returns = nav_series.pct_change().fillna(0.0)

    final_value = float(nav_track[-1]) * INITIAL_BALANCE
    buy_hold_value = float(buy_hold_track[-1]) * INITIAL_BALANCE

    sharpe = float((returns.mean() / (returns.std() + 1e-9)) * np.sqrt(252))
    drawdown = float(((nav_series.cummax() - nav_series) / nav_series.cummax()).max() * 100)

    metrics = {
        "PPO_Portfolio": round(final_value, 2),
        "BuyHold": round(buy_hold_value, 2),
        "Sharpe": round(sharpe, 3),
        "Drawdown_%": round(drawdown, 2),
        "Winner": "PPO" if final_value > buy_hold_value else "Buy & Hold",
    }

    predictions_df = pd.DataFrame(step_log)
    compat_df = build_compat_predictions(predictions_df)

    return metrics, predictions_df, compat_df


def build_compat_predictions(predictions_df: pd.DataFrame) -> pd.DataFrame:
    """Create a compatibility signal file for downstream consumers."""
    if predictions_df.empty:
        return pd.DataFrame(
            columns=[
                "Index",
                "Datetime",
                "Close",
                "Action",
                "Signal",
                "PortfolioValue",
                "Reward",
            ]
        )

    compat_rows = []

    for _, row in predictions_df.iterrows():
        action_value = float(row["Action"])

        if action_value > 0.1:
            signal = "BUY"
        elif action_value < -0.3:
            signal = "SELL"
        else:
            signal = "HOLD"

        compat_rows.append(
            {
                "Index": row["Index"],
                "Datetime": row["Datetime"],
                "Close": row["Close"],
                "Action": action_value,
                "Signal": signal,
                "PortfolioValue": row["nav"],
                "Reward": np.nan,
            }
        )

    return pd.DataFrame(compat_rows)


def save_window_outputs(
    prefix: str,
    predictions_df: pd.DataFrame,
    compat_df: pd.DataFrame,
    results_dir: Path,
) -> tuple[Path, Path]:
    """Save prediction logs for one walk-forward window."""
    results_dir.mkdir(parents=True, exist_ok=True)

    predictions_path = results_dir / f"{prefix}_predictions.csv"
    compat_path = results_dir / f"{prefix}_predictions_compat.csv"

    predictions_df.to_csv(predictions_path, index=False)
    compat_df.to_csv(compat_path, index=False)

    logging.info("Saved predictions to %s", predictions_path)
    logging.info("Saved compatibility predictions to %s", compat_path)

    return predictions_path, compat_path


def walkforward_ppo(
    df: pd.DataFrame,
    ticker: str,
    results_dir: Path,
    skip_log_path: Path,
    window_size: int = WINDOW_SIZE,
    step_size: int = STEP_SIZE,
    timesteps: int = TIMESTEPS,
    learning_rate: float = 1e-4,
    ppo_overrides: dict | None = None,
) -> list[dict]:
    """Train PPO over rolling walk-forward windows for one ticker."""
    if ppo_overrides is None:
        ppo_overrides = {}

    if len(df) < window_size:
        logging.warning(
            "Skipping %s: only %s rows (min required: %s)",
            ticker,
            len(df),
            window_size,
        )
        return []

    results: list[dict] = []
    windows = get_walk_forward_windows(
        df,
        window_size=window_size,
        step_size=step_size,
    )

    if not windows:
        logging.warning("No walk-forward windows generated for %s.", ticker)
        return []

    top_heap: list[tuple[float, str, dict]] = []
    skipped_windows: list[str] = []

    all_done = all(
        required_artifacts_exist(f"ppo_{ticker}_window{idx + 1}", FINAL_MODEL_DIR)
        for idx in range(len(windows))
    )

    if all_done:
        logging.info(
            "Ticker %s fully skipped: all %s windows already complete.",
            ticker,
            len(windows),
        )
        record_skips_global(
            ticker,
            skipped_windows=[],
            total_windows=len(windows),
            fully_skipped=True,
            output_path=skip_log_path,
        )
        return []

    for window_idx, (start, end) in enumerate(windows):
        window_start_time = time.time()
        gc.collect()

        prefix = f"ppo_{ticker}_window{window_idx + 1}"

        if required_artifacts_exist(prefix, FINAL_MODEL_DIR):
            logging.info("Skipping %s | Window %s already trained.", ticker, window_idx + 1)
            skipped_windows.append(f"{ticker}_window{window_idx + 1}")
            continue

        missing = missing_artifacts(prefix, FINAL_MODEL_DIR)
        logging.info(
            "Will train %s | Window %s because missing: %s",
            ticker,
            window_idx + 1,
            ", ".join(missing),
        )

        df_window = df.iloc[start:end].reset_index(drop=True)

        if len(df_window) <= 52:
            logging.warning(
                "Skipping %s | Window %s: only %s rows after slicing.",
                ticker,
                window_idx + 1,
                len(df_window),
            )
            continue

        if len(df_window) % 2 != 0:
            df_window = df_window.iloc[:-1].reset_index(drop=True)

        env = make_training_env(df_window)
        model = None

        try:
            model = build_ppo_model(
                env=env,
                learning_rate=learning_rate,
                ppo_overrides=ppo_overrides,
            )

            logging.info(
                "Training %s Window %s/%s for %s timesteps.",
                ticker,
                window_idx + 1,
                len(windows),
                timesteps,
            )

            model.learn(total_timesteps=timesteps)

            vecnorm_path = FINAL_MODEL_DIR / f"{prefix}_vecnorm.pkl"
            env.save(str(vecnorm_path))

            model_path = FINAL_MODEL_DIR / f"{prefix}_model.zip"
            model.save(str(model_path))

            metrics, predictions_df, compat_df = evaluate_model_on_window(
                model=model,
                env=env,
                df_window=df_window,
            )

            save_window_outputs(
                prefix=prefix,
                predictions_df=predictions_df,
                compat_df=compat_df,
                results_dir=results_dir,
            )

            result_row = {
                "Ticker": ticker,
                "Window": f"{start}-{end}",
                **metrics,
            }

            results.append(result_row)

            meta = {
                "result": result_row,
                "features": df_window.columns.tolist(),
                "prefix": prefix,
                "model_path": str(model_path),
                "vecnorm_path": str(vecnorm_path),
            }

            item = (float(result_row["Sharpe"]), prefix, meta)

            if len(top_heap) < TOP_N_WINDOWS:
                heapq.heappush(top_heap, item)
            else:
                if item[0] > top_heap[0][0]:
                    heapq.heapreplace(top_heap, item)

            runtime_seconds = round(time.time() - window_start_time, 2)

            logging.info(
                "%s | Window %s runtime: %ss | Sharpe: %s | Winner: %s",
                ticker,
                window_idx + 1,
                runtime_seconds,
                result_row["Sharpe"],
                result_row["Winner"],
            )

        except Exception as exc:
            logging.exception(
                "%s | Window %s failed: %s",
                ticker,
                window_idx + 1,
                exc,
            )

        finally:
            try:
                env.close()
            except Exception:
                pass

            try:
                del env
            except Exception:
                pass

            try:
                del model
            except Exception:
                pass

            gc.collect()

            try:
                torch.cuda.empty_cache()
            except Exception:
                pass

    if skipped_windows:
        logging.info(
            "%s skipped windows already complete: %s",
            ticker,
            ", ".join(skipped_windows),
        )
        record_skips_global(
            ticker,
            skipped_windows=skipped_windows,
            total_windows=len(windows),
            fully_skipped=False,
            output_path=skip_log_path,
        )

    save_top_window_artifacts(top_heap)

    return results


def save_top_window_artifacts(top_heap: list[tuple[float, str, dict]]) -> None:
    """Save metadata/config artifacts for top-N windows."""
    top_list = sorted(top_heap, key=lambda item: item[0], reverse=True)

    for _sharpe, _prefix, meta in top_list:
        artifact_for_save = {
            "model": None,
            "vecnorm_path": meta["vecnorm_path"],
            "features": meta["features"],
            "result": meta["result"],
            "prefix": meta["prefix"],
        }

        save_quantconnect_model(
            artifact=artifact_for_save,
            prefix=meta["prefix"],
            save_dir=FINAL_MODEL_DIR,
        )


def process_ticker(
    ticker: str,
    df: pd.DataFrame,
    results_dir: Path,
    skip_log_path: Path,
) -> list[dict]:
    """Train all eligible walk-forward windows for one ticker."""
    try:
        ticker_df = df[df["Symbol"] == ticker].copy()
        ticker_df = ticker_df.sort_values("Datetime").reset_index(drop=True)

        if not validate_symbol_data(ticker_df, ticker):
            return []

        hyperparams = pick_params(ticker)

        return walkforward_ppo(
            df=ticker_df,
            ticker=ticker,
            results_dir=results_dir,
            skip_log_path=skip_log_path,
            window_size=WINDOW_SIZE,
            step_size=STEP_SIZE,
            timesteps=TIMESTEPS,
            learning_rate=hyperparams["lr"],
            ppo_overrides=hyperparams,
        )

    except Exception as exc:
        logging.exception("%s: training failed with %s", ticker, exc)
        return []


def get_valid_symbols(df: pd.DataFrame, candidate_symbols: list[str]) -> list[str]:
    """Return symbols with enough data and required columns."""
    valid_symbols = []

    for symbol in candidate_symbols:
        ticker_df = df[df["Symbol"] == symbol].copy()

        if ticker_df.empty:
            logging.warning("Skipping %s: no rows in dataset.", symbol)
            continue

        if validate_symbol_data(ticker_df, symbol):
            valid_symbols.append(symbol)

    return valid_symbols


def run_parallel_tickers(
    df: pd.DataFrame,
    tickers: list[str],
    out_path: Path,
    results_dir: Path,
    skip_log_path: Path,
    max_workers: int = MAX_WORKERS,
) -> list[dict]:
    """Train multiple tickers in parallel and incrementally save summary results."""
    results: list[dict] = []
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not tickers:
        logging.warning("No valid tickers provided for training.")
        return results

    worker_count = max(1, min(max_workers, len(tickers)))

    logging.info("Training %s tickers with %s worker(s).", len(tickers), worker_count)

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {
            executor.submit(
                process_ticker,
                ticker,
                df,
                results_dir,
                skip_log_path,
            ): ticker
            for ticker in tickers
        }

        for future, ticker in futures.items():
            try:
                ticker_results = future.result()

                if ticker_results:
                    results.extend(ticker_results)
                    pd.DataFrame(results).to_csv(out_path, index=False)
                    logging.info("Updated summary: %s", out_path)

            except Exception as exc:
                logging.exception("%s: parallel training failed: %s", ticker, exc)

    logging.info("All tickers processed.")
    return results


def main() -> None:
    """Command-line entry point for local PPO training."""
    warnings.filterwarnings("ignore", category=UserWarning, module="gymnasium")
    warnings.filterwarnings("ignore", message=".*Gym has been unmaintained.*")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        force=True,
    )

    set_random_seed(RANDOM_SEED)

    results_dir = make_results_dir()
    summary_path = results_dir / "summary.csv"
    summary_test_mode_path = results_dir / "summary_test_mode.csv"
    skip_log_path = results_dir / "skipped_windows_global.csv"

    FINAL_MODEL_DIR.mkdir(parents=True, exist_ok=True)

    logging.info("Training output directory: %s", results_dir)
    logging.info("Loading training dataset from %s", DATA_PATH)

    df = load_training_dataset(DATA_PATH)
    valid_symbols = get_valid_symbols(df, SYMBOLS)

    if not valid_symbols:
        logging.warning("No valid symbols available for training.")
        return

    if TEST_MODE:
        output_path = summary_test_mode_path
        logging.info("Running in TEST_MODE on symbols: %s", valid_symbols)
    else:
        output_path = summary_path
        logging.info("Running full training on %s symbols.", len(valid_symbols))

    summary_results = run_parallel_tickers(
        df=df,
        tickers=valid_symbols,
        out_path=output_path,
        results_dir=results_dir,
        skip_log_path=skip_log_path,
        max_workers=MAX_WORKERS,
    )

    if not summary_results:
        logging.warning("No results generated.")
    else:
        pd.DataFrame(summary_results).to_csv(output_path, index=False)
        logging.info("Summary saved to %s", output_path)

    summarize_skip_log(skip_log_path)

if __name__ == "__main__":
    main()
