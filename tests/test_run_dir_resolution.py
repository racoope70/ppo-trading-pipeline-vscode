from pathlib import Path

import pytest

from src.analyze_execution_realism import resolve_summary_path
from src.export_selected_dynamic_lean_signals import resolve_training_run as resolve_export_run
from src.simulate_dynamic_signal_execution import resolve_training_run as resolve_sim_run
from src.select_quality_tickers import resolve_training_run as resolve_selector_run


def make_run_dir(tmp_path: Path) -> Path:
    run_dir = tmp_path / "ppo_walkforward_results_test"
    run_dir.mkdir()
    (run_dir / "summary_test_mode.csv").write_text("Ticker,Window\nAAPL,0-3500\n")
    return run_dir


def test_analyze_execution_realism_accepts_run_dir(tmp_path):
    run_dir = make_run_dir(tmp_path)

    assert resolve_summary_path(run_dir) == run_dir / "summary_test_mode.csv"


def test_analyze_execution_realism_accepts_summary_file(tmp_path):
    run_dir = make_run_dir(tmp_path)
    summary_path = run_dir / "summary_test_mode.csv"

    assert resolve_summary_path(summary_path) == summary_path


@pytest.mark.parametrize("resolver", [resolve_export_run, resolve_sim_run, resolve_selector_run])
def test_run_dir_resolvers_accept_run_dir(tmp_path, resolver):
    run_dir = make_run_dir(tmp_path)

    assert resolver(run_dir) == run_dir


@pytest.mark.parametrize("resolver", [resolve_export_run, resolve_sim_run, resolve_selector_run])
def test_run_dir_resolvers_accept_summary_file(tmp_path, resolver):
    run_dir = make_run_dir(tmp_path)
    summary_path = run_dir / "summary_test_mode.csv"

    assert resolver(summary_path) == run_dir


@pytest.mark.parametrize(
    "resolver",
    [resolve_summary_path, resolve_export_run, resolve_sim_run, resolve_selector_run],
)
def test_run_dir_resolvers_reject_missing_summary(tmp_path, resolver):
    run_dir = tmp_path / "bad_run"
    run_dir.mkdir()

    with pytest.raises(FileNotFoundError):
        resolver(run_dir)


@pytest.mark.parametrize(
    "resolver",
    [resolve_summary_path, resolve_export_run, resolve_sim_run, resolve_selector_run],
)
def test_run_dir_resolvers_reject_wrong_file(tmp_path, resolver):
    bad_file = tmp_path / "not_summary.csv"
    bad_file.write_text("x\n")

    with pytest.raises(ValueError):
        resolver(bad_file)