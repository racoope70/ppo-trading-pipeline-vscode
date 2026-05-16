"""Run the PPO validation chain end-to-end.

Purpose:
    Orchestrate the reproducible validation workflow:

    1. prepare_data.py
    2. train.py
    3. analyze_execution_realism.py
    4. select_quality_tickers.py
    5. export_selected_dynamic_lean_signals.py
    6. validate_payload_manifest.py
    7. simulate_dynamic_signal_execution.py
    8. summarize_selected_dynamic_validation.py

This script is intentionally a thin command runner. It does not replace the
individual scripts; it standardizes the sequence and arguments used to run them.

Example dry run:
    python -m src.run_validation_chain \
      --tickers AAPL PFE UNH XOM AMD MRK \
      --run-dir reports/backtests/ppo_walkforward_results_20260512_8ticker_combined \
      --payload quantconnect/test_payloads/selected_dynamic_signals_6ticker_quality_250marketbars.json \
      --dry-run

Example execution:
    python -m src.run_validation_chain \
      --tickers AAPL PFE UNH XOM AMD MRK \
      --run-dir reports/backtests/ppo_walkforward_results_20260512_8ticker_combined \
      --payload quantconnect/test_payloads/selected_dynamic_signals_6ticker_quality_250marketbars.json
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from src.cli_utils import parse_ticker_args


DEFAULT_TICKERS = ["AAPL", "PFE", "UNH", "XOM", "AMD", "MRK"]
DEFAULT_PAYLOAD = Path(
    "quantconnect/test_payloads/selected_dynamic_signals_6ticker_quality_250marketbars.json"
)
DEFAULT_OUTPUT_DIR = Path("reports/validation_summary")
DEFAULT_SCENARIO = "moderate"


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Run the PPO validation chain end-to-end."
    )

    parser.add_argument(
        "--tickers",
        nargs="*",
        default=DEFAULT_TICKERS,
        help=(
            "Ticker universe. Supports space-separated or comma-separated values. "
            "Default: AAPL PFE UNH XOM AMD MRK"
        ),
    )

    parser.add_argument(
        "--run-dir",
        type=Path,
        required=True,
        help=(
            "Run directory containing summary_test_mode.csv, "
            "execution_realism_analysis.csv, and *_predictions_compat.csv files."
        ),
    )

    parser.add_argument(
        "--payload",
        type=Path,
        default=DEFAULT_PAYLOAD,
        help=f"Signal payload output/input path. Default: {DEFAULT_PAYLOAD}",
    )

    parser.add_argument(
        "--scenario",
        type=str,
        default=DEFAULT_SCENARIO,
        help=f"Execution-realism scenario. Default: {DEFAULT_SCENARIO}",
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Validation output directory. Default: {DEFAULT_OUTPUT_DIR}",
    )

    parser.add_argument(
        "--skip-data",
        action="store_true",
        help="Skip data preparation.",
    )

    parser.add_argument(
        "--skip-train",
        action="store_true",
        help="Skip PPO training.",
    )

    parser.add_argument(
        "--skip-execution-realism",
        action="store_true",
        help="Skip execution-realism analysis.",
    )

    parser.add_argument(
        "--skip-selector",
        action="store_true",
        help="Skip quality-filtered ticker selection.",
    )

    parser.add_argument(
        "--skip-export",
        action="store_true",
        help="Skip dynamic signal payload export.",
    )

    parser.add_argument(
        "--skip-manifest-validation",
        action="store_true",
        help="Skip payload manifest validation.",
    )

    parser.add_argument(
        "--skip-simulation",
        action="store_true",
        help="Skip local mark-to-market dynamic signal simulation.",
    )

    parser.add_argument(
        "--skip-summary",
        action="store_true",
        help="Skip validation comparison summary.",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print commands without executing them.",
    )

    return parser.parse_args()


def command_to_text(command: list[str]) -> str:
    """Return shell-readable command text."""
    return " ".join(command)


def run_command(command: list[str], dry_run: bool = False) -> None:
    """Print and optionally execute a command."""
    print("\n" + "=" * 80)
    print(command_to_text(command))
    print("=" * 80)

    if dry_run:
        return

    subprocess.run(command, check=True)

def manifest_path_for_payload(payload_path: Path) -> Path:
    """Return sidecar manifest path for an exported payload."""
    return payload_path.with_suffix(".manifest.json")

def build_commands(args: argparse.Namespace) -> list[list[str]]:
    """Build validation-chain commands from CLI arguments."""
    tickers = parse_ticker_args(args.tickers)

    if not tickers:
        raise ValueError("No tickers supplied.")

    ticker_csv = ",".join(tickers)

    commands: list[list[str]] = []

    if not args.skip_data:
        commands.append(
            [
                sys.executable,
                "-m",
                "src.prepare_data",
                "--tickers",
                *tickers,
            ]
        )

    if not args.skip_train:
        commands.append(
            [
                sys.executable,
                "-m",
                "src.train",
                "--tickers",
                *tickers,
            ]
        )

    if not args.skip_execution_realism:
        commands.append(
            [
                sys.executable,
                "-m",
                "src.analyze_execution_realism",
                "--run-dir",
                str(args.run_dir),
            ]
        )

    if not args.skip_selector:
        commands.append(
            [
                sys.executable,
                "-m",
                "src.select_quality_tickers",
                "--run-dir",
                str(args.run_dir),
                "--scenario",
                args.scenario,
                "--output-dir",
                str(args.output_dir),
            ]
        )

    if not args.skip_export:
        commands.append(
            [
                sys.executable,
                "-m",
                "src.export_selected_dynamic_lean_signals",
                "--run-dir",
                str(args.run_dir),
                "--symbols",
                ticker_csv,
                "--scenario",
                args.scenario,
                "--output",
                str(args.payload),
            ]
        )

    if not args.skip_manifest_validation:
        commands.append(
            [
                sys.executable,
                "-m",
                "src.validate_payload_manifest",
                "--manifest",
                str(manifest_path_for_payload(args.payload)),
            ]
        )
        
    if not args.skip_simulation:
        commands.append(
            [
                sys.executable,
                "-m",
                "src.simulate_dynamic_signal_execution",
                "--run-dir",
                str(args.run_dir),
                "--payload",
                str(args.payload),
            ]
        )

    if not args.skip_summary:
        commands.append(
            [
                sys.executable,
                "-m",
                "src.summarize_selected_dynamic_validation",
                "--output-dir",
                str(args.output_dir),
            ]
        )

    return commands


def main() -> None:
    """Run the validation chain."""
    args = parse_args()

    commands = build_commands(args)

    print("=" * 80)
    print("PPO VALIDATION CHAIN")
    print("=" * 80)
    print("Run directory:", args.run_dir)
    print("Payload:", args.payload)
    print("Scenario:", args.scenario)
    print("Output directory:", args.output_dir)
    print("Dry run:", args.dry_run)
    print("Command count:", len(commands))

    for command in commands:
        run_command(command, dry_run=args.dry_run)

    print("\n" + "=" * 80)
    print("VALIDATION CHAIN COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    main()