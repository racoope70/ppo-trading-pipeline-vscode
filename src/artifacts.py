"""Model artifact utilities for the PPO trading pipeline.

This module centralizes saving and loading of PPO model artifacts:

- Stable-Baselines3 PPO model .zip files
- VecNormalize .pkl files
- feature JSON files
- probability config JSON files
- model info JSON files

The functions here are platform-neutral. QuantConnect and Alpaca adapters can
both use these artifacts, but broker-specific execution logic belongs elsewhere.
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from stable_baselines3 import PPO
from stable_baselines3.common.vec_env import DummyVecEnv, VecNormalize

from src.config import ENABLE_SENTIMENT, ENABLE_SLO, FINAL_MODEL_DIR
from src.env import ContinuousPositionEnv


@dataclass(frozen=True)
class ArtifactPaths:
    """Resolved artifact paths for a single ticker/window prefix."""

    prefix: str
    model_path: Path
    vecnorm_path: Path
    features_path: Path
    probability_config_path: Path
    model_info_path: Path


def get_artifact_paths(
    prefix: str,
    model_dir: Path = FINAL_MODEL_DIR,
) -> ArtifactPaths:
    """Return all standard artifact paths for a model prefix.

    Example prefix:
        ppo_AAPL_window1
    """
    model_dir = Path(model_dir)

    return ArtifactPaths(
        prefix=prefix,
        model_path=model_dir / f"{prefix}_model.zip",
        vecnorm_path=model_dir / f"{prefix}_vecnorm.pkl",
        features_path=model_dir / f"{prefix}_features.json",
        probability_config_path=model_dir / f"{prefix}_probability_config.json",
        model_info_path=model_dir / f"{prefix}_model_info.json",
    )


def save_json(path: Path, payload: dict[str, Any]) -> None:
    """Save a dictionary as formatted JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w") as file:
        json.dump(payload, file, indent=2, default=str)


def load_json(path: Path) -> dict[str, Any]:
    """Load a JSON file."""
    with path.open("r") as file:
        return json.load(file)


def save_feature_list(
    prefix: str,
    features: list[str],
    model_dir: Path = FINAL_MODEL_DIR,
) -> Path:
    """Save feature list for a model prefix."""
    paths = get_artifact_paths(prefix, model_dir)

    save_json(
        paths.features_path,
        {
            "features": list(features),
        },
    )

    return paths.features_path


def load_feature_list(
    prefix: str,
    model_dir: Path = FINAL_MODEL_DIR,
) -> list[str]:
    """Load feature list for a model prefix."""
    paths = get_artifact_paths(prefix, model_dir)

    payload = load_json(paths.features_path)

    if isinstance(payload, list):
        return payload

    if "features" not in payload:
        raise KeyError(f"No 'features' key found in {paths.features_path}")

    return list(payload["features"])


def save_probability_config(
    prefix: str,
    threshold: float = 0.05,
    use_confidence: bool = True,
    inference_mode: str = "deterministic",
    model_dir: Path = FINAL_MODEL_DIR,
    extra_config: dict[str, Any] | None = None,
) -> Path:
    """Save probability/inference configuration for a model prefix."""
    paths = get_artifact_paths(prefix, model_dir)

    payload: dict[str, Any] = {
        "threshold": float(threshold),
        "use_confidence": bool(use_confidence),
        "inference_mode": inference_mode,
    }

    if extra_config:
        payload.update(extra_config)

    save_json(paths.probability_config_path, payload)

    return paths.probability_config_path


def save_model_info(
    prefix: str,
    result: dict[str, Any],
    features: list[str],
    model_dir: Path = FINAL_MODEL_DIR,
    extra_info: dict[str, Any] | None = None,
) -> Path:
    """Save metadata describing a trained PPO artifact."""
    paths = get_artifact_paths(prefix, model_dir)

    payload: dict[str, Any] = {
        "model": "PPO",
        "ticker": result.get("Ticker"),
        "window": result.get("Window"),
        "date_trained": datetime.today().strftime("%Y-%m-%d"),
        "framework": "stable-baselines3",
        "input_features": list(features),
        "final_portfolio": result.get("PPO_Portfolio"),
        "buy_hold": result.get("BuyHold"),
        "sharpe": result.get("Sharpe"),
        "drawdown_pct": result.get("Drawdown_%"),
        "winner": result.get("Winner"),
        "model_path": str(paths.model_path),
        "vecnorm_path": str(paths.vecnorm_path),
        "features_path": str(paths.features_path),
        "probability_config_path": str(paths.probability_config_path),
    }

    if extra_info:
        payload.update(extra_info)

    save_json(paths.model_info_path, payload)

    return paths.model_info_path


def save_ppo_artifacts(
    prefix: str,
    model: PPO | None,
    vecnorm_path: str | Path | None,
    features: list[str],
    result: dict[str, Any],
    model_dir: Path = FINAL_MODEL_DIR,
    probability_threshold: float = 0.05,
) -> ArtifactPaths:
    """Save a complete PPO artifact set for one ticker/window.

    This replaces the notebook's `save_quantconnect_model()` function with a
    platform-neutral implementation.

    Parameters
    ----------
    prefix:
        Artifact prefix, such as ``ppo_AAPL_window1``.

    model:
        Trained Stable-Baselines3 PPO model. If None, the function assumes the
        model was already saved elsewhere and only writes/copies metadata.

    vecnorm_path:
        Source VecNormalize path to copy into the artifact directory.

    features:
        Feature column list used during training.

    result:
        Summary metrics dictionary for the trained window.

    model_dir:
        Destination artifact directory.

    probability_threshold:
        Threshold saved to the probability config JSON.
    """
    model_dir = Path(model_dir)
    model_dir.mkdir(parents=True, exist_ok=True)

    paths = get_artifact_paths(prefix, model_dir)

    if model is not None and not paths.model_path.exists():
        model.save(str(paths.model_path))

    if vecnorm_path is not None:
        source_vecnorm = Path(vecnorm_path)

        if source_vecnorm.exists():
            if source_vecnorm.resolve() != paths.vecnorm_path.resolve():
                shutil.copyfile(source_vecnorm, paths.vecnorm_path)
        else:
            logging.warning("VecNormalize source path does not exist: %s", source_vecnorm)

    save_feature_list(prefix, features, model_dir=model_dir)

    save_probability_config(
        prefix,
        threshold=probability_threshold,
        use_confidence=True,
        inference_mode="deterministic",
        model_dir=model_dir,
    )

    save_model_info(
        prefix,
        result=result,
        features=features,
        model_dir=model_dir,
    )

    logging.info(
        "Saved PPO artifact set for %s | ticker=%s | window=%s",
        prefix,
        result.get("Ticker"),
        result.get("Window"),
    )

    return paths


def save_quantconnect_model(
    artifact: dict[str, Any],
    prefix: str,
    save_dir: str | Path,
) -> ArtifactPaths:
    """Backward-compatible wrapper for the original notebook function.

    The original notebook used `save_quantconnect_model(artifact, prefix, save_dir)`.
    Keeping this wrapper lets `train.py` call the old-style function while the
    underlying implementation remains clean and platform-neutral.
    """
    result = artifact.get("result", {})
    features = artifact.get("features", [])
    model = artifact.get("model", None)
    vecnorm_path = artifact.get("vecnorm_path", None)

    return save_ppo_artifacts(
        prefix=prefix,
        model=model,
        vecnorm_path=vecnorm_path,
        features=features,
        result=result,
        model_dir=Path(save_dir),
        probability_threshold=0.05,
    )


def required_artifacts_exist(
    prefix: str,
    model_dir: Path = FINAL_MODEL_DIR,
    require_metadata: bool = False,
) -> bool:
    """Check whether the required model and VecNormalize artifacts exist."""
    paths = get_artifact_paths(prefix, model_dir)

    required_paths = [
        paths.model_path,
        paths.vecnorm_path,
    ]

    if require_metadata:
        required_paths.extend(
            [
                paths.features_path,
                paths.probability_config_path,
                paths.model_info_path,
            ]
        )

    return all(path.exists() for path in required_paths)


def missing_artifacts(
    prefix: str,
    model_dir: Path = FINAL_MODEL_DIR,
    require_metadata: bool = False,
) -> list[str]:
    """Return a list of missing artifact file labels."""
    paths = get_artifact_paths(prefix, model_dir)

    required = {
        "model.zip": paths.model_path,
        "vecnorm.pkl": paths.vecnorm_path,
    }

    if require_metadata:
        required.update(
            {
                "features.json": paths.features_path,
                "probability_config.json": paths.probability_config_path,
                "model_info.json": paths.model_info_path,
            }
        )

    return [label for label, path in required.items() if not path.exists()]


def make_env_for_artifact(
    df_window,
    enable_slo: bool = ENABLE_SLO,
    enable_sentiment: bool = ENABLE_SENTIMENT,
):
    """Create a vectorized environment matching the training environment."""
    frame_bound = (50, len(df_window) - 3)

    return DummyVecEnv(
        [
            lambda: ContinuousPositionEnv(
                df=df_window,
                frame_bound=frame_bound,
                window_size=10,
                cost_rate=(0.0002 if enable_slo else 0.0),
                slip_rate=(0.0003 if enable_slo else 0.0),
                k_alpha=0.20,
                k_mom=0.05,
                k_sent=(0.01 if enable_sentiment else 0.0),
                mom_source="denoised",
                mom_lookback=20,
                min_trade_delta=0.01,
                cooldown=5,
                reward_clip=1.0,
            )
        ]
    )


def load_model_and_env(
    prefix: str,
    df_window,
    model_dir: Path = FINAL_MODEL_DIR,
    device: str = "cpu",
):
    """Load a PPO model and VecNormalize-wrapped environment for inference.

    This is the cleaned version of the notebook's `load_model_and_env()` helper.
    """
    paths = get_artifact_paths(prefix, model_dir)

    if not paths.model_path.exists():
        raise FileNotFoundError(f"Missing PPO model artifact: {paths.model_path}")

    model = PPO.load(str(paths.model_path), device=device)

    env = make_env_for_artifact(df_window)

    if paths.vecnorm_path.exists():
        env = VecNormalize.load(str(paths.vecnorm_path), env)
    else:
        logging.warning("VecNormalize artifact missing for %s: %s", prefix, paths.vecnorm_path)

    env.training = False
    env.norm_reward = False

    return model, env


def list_model_prefixes(model_dir: Path = FINAL_MODEL_DIR) -> list[str]:
    """Return available PPO model prefixes from the artifact directory."""
    model_dir = Path(model_dir)

    prefixes = []

    for model_path in sorted(model_dir.glob("ppo_*_model.zip")):
        prefixes.append(model_path.name.replace("_model.zip", ""))

    return prefixes