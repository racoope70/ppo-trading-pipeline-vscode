# Reproducibility and Validation Improvements — 2026-05-13

## Summary

This update documents the reproducibility improvements made after the UNH/XOM QuantConnect readiness check exposed a data-availability limitation in the longer historical LEAN test.

The primary objective was not to change the trading logic. The objective was to make the research workflow more controlled, reproducible, and auditable across data preparation, model training, execution-realism analysis, signal export, local mark-to-market simulation, and validation summary generation.

## Background

The QuantConnect diagnostic confirmed that the UNH/XOM hourly data feed only produced bars for Feb 10 during the tested window. That meant QuantConnect was useful for validating Object Store ingestion, timestamp handling, and order-path behavior, but it was not reliable as the main environment for longer-window performance evaluation in this phase.

The longer-window evaluation was therefore moved back to the local VS Code workflow, where the saved prediction files and exported dynamic signal payloads could be aligned and tested consistently.

## What Changed

The following scripts were updated to reduce hardcoded assumptions:

| Script | Improvement |
|---|---|
| `src/prepare_data.py` | Added `--tickers` override |
| `src/train.py` | Added `--tickers` override |
| `src/analyze_execution_realism.py` | Added `--run-dir` override |
| `src/export_selected_dynamic_lean_signals.py` | Added `--run-dir` override |
| `src/simulate_dynamic_signal_execution.py` | Added `--run-dir` override |
| `src/summarize_selected_dynamic_validation.py` | Added `--output-dir` override |
| `src/select_quality_tickers.py` | Added automated quality-filtered ticker selection |

A workflow document was also added:

```text
docs/workflows/six_ticker_quality_baseline.md
```

The README now links to that workflow.

## Validation Sequence

The workflow now supports the following sequence without manually editing `src/config.py`:

```bash
python -m src.prepare_data \
  --tickers AAPL PFE UNH XOM AMD MRK

python -m src.train \
  --tickers AAPL PFE UNH XOM AMD MRK

python -m src.analyze_execution_realism \
  --run-dir reports/backtests/<run_dir>

python -m src.select_quality_tickers \
  --run-dir reports/backtests/<run_dir> \
  --scenario moderate \
  --output-dir reports/validation_summary

python -m src.export_selected_dynamic_lean_signals \
  --run-dir reports/backtests/<run_dir> \
  --symbols AAPL,PFE,UNH,XOM,AMD,MRK \
  --output quantconnect/test_payloads/selected_dynamic_signals_6ticker_quality_250marketbars.json

python -m src.simulate_dynamic_signal_execution \
  --run-dir reports/backtests/<run_dir> \
  --payload quantconnect/test_payloads/selected_dynamic_signals_6ticker_quality_250marketbars.json

python -m src.summarize_selected_dynamic_validation \
  --output-dir reports/validation_summary
```

## Quality-Filtered Baseline

The current baseline set is:

```text
AAPL, AMD, MRK, PFE, UNH, XOM
```

This set was selected using the default quality rule:

```text
Execution_Winner == PPO
Execution_Edge_vs_BuyHold > 0
```

The eight-ticker test included:

```text
AAPL, PFE, UNH, XOM, AMD, META, ORCL, MRK
```

The automated selector excluded:

```text
META, ORCL
```

because their moderate execution-realism results favored Buy & Hold rather than PPO.

A stricter optional filter was also tested:

```bash
python -m src.select_quality_tickers \
  --run-dir reports/backtests/ppo_walkforward_results_20260512_8ticker_combined \
  --scenario moderate \
  --min-sharpe 0 \
  --output-dir reports/validation_summary
```

Under this stricter filter, PFE is excluded because its moderate-scenario `Sharpe_Est` is negative. The documented six-ticker baseline still uses the default execution-edge rule.

## Current Baseline Result

The six-ticker local mark-to-market simulation is the current primary validation baseline:

| Metric | Value |
|---|---:|
| Final equity | 112,982.27 |
| Net PnL | 12,982.27 |
| Net return | 12.98% |
| Gross PnL before costs | 14,983.23 |
| Transaction costs | 2,000.96 |
| Sharpe estimate | 3.80 |
| Max drawdown | 8.96% |
| Total turnover | 36.8929 |
| Trade events | 198 |
| Simulation rows | 250 |

## Interpretation

This was a reproducibility-control update, not a strategy-optimization pass.

Before this update, several scripts depended on implicit defaults such as the latest run folder or hardcoded ticker lists. That made it easier to accidentally compare the wrong run, export from the wrong folder, or rely on manually edited configuration.

After this update, the workflow can explicitly state:

```text
which tickers were prepared,
which tickers were trained,
which run directory was analyzed,
which payload was exported,
which run directory supplied prediction returns,
and which validation summary was regenerated.
```

This makes backtesting comparisons more reliable and easier to audit.

## Current Engineering Conclusion

QuantConnect remains useful for:

```text
Object Store ingestion checks
timestamp alignment checks
payload compatibility checks
order-path validation
```

Local simulation remains the preferred environment for longer-window validation until the QuantConnect data-availability issue is resolved.

The current baseline should remain:

```text
AAPL, AMD, MRK, PFE, UNH, XOM
```

Future ticker additions should pass the quality selector before inclusion.

## Next Recommended Work

1. Add a single orchestration command or script that runs the full validation chain.
2. Add a reproducibility manifest for each exported signal payload.
3. Add lightweight tests for ticker parsing, run-directory resolution, and quality filtering.
4. Revisit stricter quality rules after more local validation runs.
5. Use QuantConnect only for execution-path validation until data availability is resolved.