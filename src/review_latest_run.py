"""Review the newest PPO walk-forward training run.

This helper is intended for local VS Code runs. It prevents manual mistakes
caused by copying old timestamped report folders.

It automatically finds the newest training folder that contains
summary_test_mode.csv, then reviews the matching summary and prediction files.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


BACKTESTS_DIR = Path("reports/backtests")


def find_latest_summary() -> Path:
    """Return the newest summary_test_mode.csv from PPO walk-forward runs."""
    summaries = sorted(
        BACKTESTS_DIR.glob("ppo_walkforward_results_*/summary_test_mode.csv")
    )

    if not summaries:
        raise FileNotFoundError(
            "No summary_test_mode.csv files found under reports/backtests. "
            "Run python -m src.train first, then rerun this review helper."
        )

    return summaries[-1]


def review_summary(summary_path: Path) -> pd.DataFrame:
    """Print high-level summary tables for the newest training run."""
    df = pd.read_csv(summary_path)

    required_columns = {"Ticker", "Sharpe", "Winner"}
    missing_columns = required_columns - set(df.columns)

    if missing_columns:
        raise ValueError(
            f"Summary file is missing required columns: {sorted(missing_columns)}. "
            f"File: {summary_path}"
        )

    tickers = sorted(df["Ticker"].unique())
    expected_rows = len(tickers) * 3

    print("=" * 80)
    print("LATEST PPO TRAINING RUN")
    print("=" * 80)
    print("Using newest summary:", summary_path)
    print("Using newest run folder:", summary_path.parent)
    print("Rows:", len(df))
    print("Ticker count:", len(tickers))
    print("Tickers:", tickers)
    print("Expected rows:", expected_rows)

    if len(df) != expected_rows:
        print(
            "\nWARNING: Summary row count does not match ticker_count x 3 windows."
        )
        print(
            "This may be okay if you changed the number of walk-forward windows, "
            "but verify before trusting the review."
        )

    print("\nFull summary:")
    print(df)

    print("\nBest by ticker using raw Sharpe ranking:")
    print(
        df.sort_values(["Ticker", "Sharpe"], ascending=[True, False])
        .groupby("Ticker")
        .head(1)
    )

    print("\nRanked by Sharpe:")
    print(df.sort_values("Sharpe", ascending=False))

    ppo_winners = df[df["Winner"].astype(str).str.upper().eq("PPO")].copy()

    print("\nPPO-winning windows only:")
    if ppo_winners.empty:
        print("No PPO-winning windows found.")
    else:
        print(ppo_winners.sort_values("Sharpe", ascending=False))

    return df


def review_signal_counts(run_dir: Path) -> None:
    """Print signal counts and action statistics for the newest run folder."""
    prediction_files = sorted(run_dir.glob("*_predictions_compat.csv"))

    print("\n" + "=" * 80)
    print("SIGNAL COUNTS AND ACTION STATISTICS")
    print("=" * 80)
    print("Using run folder:", run_dir)

    if not prediction_files:
        print(
            "No *_predictions_compat.csv files found in this training folder."
        )
        print(
            "This usually means prediction files were not saved during training, "
            "or you are reviewing a folder that only contains latest prediction output."
        )
        return

    for file in prediction_files:
        df = pd.read_csv(file)

        print("\n", file.name)
        print("rows:", len(df))

        if "Signal" in df.columns:
            print(df["Signal"].value_counts(dropna=False))
        else:
            print("Signal column missing.")

        if "Action" in df.columns:
            print("Action summary:")
            print(df["Action"].describe())
        else:
            print("Action column missing.")


def main() -> None:
    """Review the newest PPO walk-forward training run."""
    summary_path = find_latest_summary()
    review_summary(summary_path)
    review_signal_counts(summary_path.parent)


if __name__ == "__main__":
    main()