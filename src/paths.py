"""Project-wide filesystem paths.

This module centralizes all local paths used by the PPO trading pipeline.
All paths are resolved relative to the repository root so the project can
run locally without Google Colab, Google Drive, or machine-specific paths.
"""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

DATA_DIR = PROJECT_ROOT / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"

MODELS_DIR = PROJECT_ROOT / "models"
PPO_MODELS_DIR = MODELS_DIR / "ppo_models_master"

# Temporary compatibility folder for older artifacts already stored here.
TRAINED_MODELS_DIR = PROJECT_ROOT / "trained_models"

REPORTS_DIR = PROJECT_ROOT / "reports"
FIGURES_DIR = REPORTS_DIR / "figures"
BACKTESTS_DIR = REPORTS_DIR / "backtests"

CONFIGS_DIR = PROJECT_ROOT / "configs"
LOGS_DIR = PROJECT_ROOT / "logs"


def ensure_project_dirs() -> None:
    """Create required project directories if they do not already exist."""
    required_dirs = [
        RAW_DATA_DIR,
        PROCESSED_DATA_DIR,
        PPO_MODELS_DIR,
        TRAINED_MODELS_DIR,
        FIGURES_DIR,
        BACKTESTS_DIR,
        CONFIGS_DIR,
        LOGS_DIR,
    ]

    for path in required_dirs:
        path.mkdir(parents=True, exist_ok=True)


ensure_project_dirs()