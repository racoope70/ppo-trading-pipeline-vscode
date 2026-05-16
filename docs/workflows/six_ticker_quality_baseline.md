# Six-Ticker Quality Baseline Workflow

## Objective

This workflow documents the reproducible validation path for the current six-ticker PPO quality baseline.

The purpose is to preserve the exact command sequence used to regenerate the selected data set, training artifacts, execution-realism diagnostics, LEAN-compatible signal payload, local mark-to-market simulation, and validation comparison summary.

This workflow avoids manual edits to `src/config.py` by using CLI overrides.

---

## Baseline Universe

Current baseline universe:

```text
AAPL, PFE, UNH, XOM, AMD, MRK
````

The six-ticker set was selected after comparing the four-ticker and eight-ticker dynamic signal simulations.

Excluded from the eight-ticker expansion:

```text
META, ORCL
```

Rationale: META and ORCL did not pass the moderate execution-realism filter. Their best moderate-scenario result favored Buy & Hold over PPO, so they were excluded from the quality-filtered set.

---

## Current Baseline Result

Six-ticker local mark-to-market simulation:

| Metric                 |      Value |
| ---------------------- | ---------: |
| Final equity           | 112,982.27 |
| Net PnL                |  12,982.27 |
| Net return             |     12.98% |
| Gross PnL before costs |  14,983.23 |
| Transaction costs      |   2,000.96 |
| Sharpe estimate        |       3.80 |
| Max drawdown           |      8.96% |
| Total turnover         |    36.8929 |
| Trade events           |        198 |
| Simulation rows        |        250 |

Comparison across validation sets:

| Validation set                        | Final equity | Net return | Sharpe estimate | Max drawdown | Trade events |
| ------------------------------------- | -----------: | ---------: | --------------: | -----------: | -----------: |
| UNH/XOM local MTM                     |   107,004.06 |      7.00% |            2.78 |        6.59% |           46 |
| Four-ticker selected local MTM        |   108,909.18 |      8.91% |            3.40 |        6.49% |          184 |
| Eight-ticker selected local MTM       |   107,686.02 |      7.69% |            2.03 |       10.19% |          547 |
| Six-ticker quality-filtered local MTM |   112,982.27 |     12.98% |            3.80 |        8.96% |          198 |

Current conclusion: the six-ticker quality-filtered set is the primary local validation baseline.

---

## Reproducible Command Sequence

### 1. Confirm clean repository state

```bash
git status --short
```

Expected: no output.

---

### 2. Prepare feature-engineered data

```bash
python -m src.prepare_data \
  --tickers AAPL PFE UNH XOM AMD MRK
```

Expected log:

```text
Preparing data for 6 symbols: ['AAPL', 'PFE', 'UNH', 'XOM', 'AMD', 'MRK']
```

Primary outputs:

```text
data/processed/multi_stock_feature_engineered_dataset.csv
data/processed/train.csv
data/processed/val.csv
data/processed/features_full.parquet
data/processed/train.parquet
data/processed/val.parquet
```

---

### 3. Train PPO walk-forward models

```bash
python -m src.train \
  --tickers AAPL PFE UNH XOM AMD MRK
```

Expected log:

```text
Running in TEST_MODE on symbols: ['AAPL', 'PFE', 'UNH', 'XOM', 'AMD', 'MRK']
```

Training outputs are written to:

```text
reports/backtests/ppo_walkforward_results_<timestamp>/
```

Expected files:

```text
summary_test_mode.csv
*_predictions.csv
*_predictions_compat.csv
skipped_windows_global.csv
```

Note: if existing model artifacts are already present, some windows may be skipped. Confirm that the intended run folder still contains the required summary and prediction compatibility files.

---

### 4. Run execution-realism analysis

```bash
python -m src.analyze_execution_realism \
  --run-dir reports/backtests/ppo_walkforward_results_<timestamp>
```

Expected output:

```text
reports/backtests/ppo_walkforward_results_<timestamp>/execution_realism_analysis.csv
```

For the documented six-ticker baseline, the selected model metadata came from:

```text
reports/backtests/ppo_walkforward_results_20260512_8ticker_combined
```

---

### 5. Select quality-filtered tickers

After execution-realism analysis is complete, run the quality selector to choose the qualifying PPO model per ticker under the documented baseline rule.

```bash
python -m src.select_quality_tickers \
  --run-dir reports/backtests/ppo_walkforward_results_20260512_8ticker_combined \
  --scenario moderate \
  --output-dir reports/validation_summary
```

Default inclusion rule:

```text
Execution_Winner == PPO
Execution_Edge_vs_BuyHold > 0
```

Expected selected symbols:

```text
AAPL, AMD, MRK, PFE, UNH, XOM
```

Expected excluded symbols:

```text
META, ORCL
```

This reproduces the six-ticker quality baseline used for the current validation workflow.

A stricter research screen can also be run by requiring non-negative estimated Sharpe:

```bash
python -m src.select_quality_tickers \
  --run-dir reports/backtests/ppo_walkforward_results_20260512_8ticker_combined \
  --scenario moderate \
  --min-sharpe 0 \
  --output-dir reports/validation_summary
```

Under this stricter screen, PFE is excluded because its moderate-scenario `Sharpe_Est` is negative. This variant is useful for sensitivity analysis, but the documented six-ticker baseline uses the execution-edge rule above.

---

### 6. Export selected dynamic LEAN signal payload

```bash
python -m src.export_selected_dynamic_lean_signals \
  --run-dir reports/backtests/ppo_walkforward_results_20260512_8ticker_combined \
  --symbols AAPL,PFE,UNH,XOM,AMD,MRK \
  --output quantconnect/test_payloads/selected_dynamic_signals_6ticker_quality_250marketbars.json
```

Expected checks:

```text
Signal rows: 1500
Rows per symbol: 250
First timestamp: 2026-02-10T10:00:00+00:00
Last timestamp: 2026-03-31T14:00:00+00:00
```

Expected selected models:

```text
AAPL    ppo_AAPL_window1
PFE     ppo_PFE_window1
UNH     ppo_UNH_window1
XOM     ppo_XOM_window2
AMD     ppo_AMD_window3
MRK     ppo_MRK_window1
```

The exporter also writes a sidecar reproducibility manifest:

```text
quantconnect/test_payloads/selected_dynamic_signals_6ticker_quality_250marketbars.manifest.json
```

The manifest records the source run directory, selected models, payload path, SHA256 hash, symbol list, row count, timestamp range, export configuration, and required source files.

---

### 7. Verify payload structure and manifest

```bash
python - <<'PY'
import json
from pathlib import Path

payload_path = Path("quantconnect/test_payloads/selected_dynamic_signals_6ticker_quality_250marketbars.json")
manifest_path = Path("quantconnect/test_payloads/selected_dynamic_signals_6ticker_quality_250marketbars.manifest.json")

with payload_path.open() as f:
    payload = json.load(f)

with manifest_path.open() as f:
    manifest = json.load(f)

print("symbols:", payload["symbols"])
print("rows_per_symbol:", payload["rows_per_symbol"])
print("signal_rows:", len(payload["signals"]))
print("selected_models:", payload["selected_models"])
print("first_signal:", payload["signals"][0])
print("last_signal:", payload["signals"][-1])
print("manifest_artifact_type:", manifest["artifact_type"])
print("manifest_payload_sha256:", manifest["payload_sha256"][:16] + "...")
PY
```

Expected:

```text
symbols: ['AAPL', 'PFE', 'UNH', 'XOM', 'AMD', 'MRK']
rows_per_symbol: 250
signal_rows: 1500
manifest_artifact_type: dynamic_signal_payload_manifest
```

---

### 8. Run local mark-to-market dynamic signal simulation

```bash
python -m src.simulate_dynamic_signal_execution \
  --run-dir reports/backtests/ppo_walkforward_results_20260512_8ticker_combined \
  --payload quantconnect/test_payloads/selected_dynamic_signals_6ticker_quality_250marketbars.json
```

Expected checks:

```text
Signal rows: 1500
Return rows: 1500
```

Expected outputs:

```text
reports/dynamic_signal_execution/selected_dynamic_signals_6ticker_quality_250marketbars_mtm_execution_summary.csv
reports/dynamic_signal_execution/selected_dynamic_signals_6ticker_quality_250marketbars_mtm_equity_curve.csv
reports/dynamic_signal_execution/selected_dynamic_signals_6ticker_quality_250marketbars_mtm_trade_ledger.csv
```

---

### 9. Regenerate validation comparison summary

```bash
python -m src.summarize_selected_dynamic_validation \
  --output-dir reports/validation_summary
```

Expected output:

```text
reports/validation_summary/selected_dynamic_validation_comparison.csv
```

The comparison should identify the six-ticker quality-filtered simulation as the current primary baseline.

---

## Orchestrated Validation Chain

The validation workflow can also be run through the orchestration wrapper:

```bash
python -m src.run_validation_chain \
  --tickers AAPL PFE UNH XOM AMD MRK \
  --run-dir reports/backtests/ppo_walkforward_results_20260512_8ticker_combined \
  --payload quantconnect/test_payloads/selected_dynamic_signals_6ticker_quality_250marketbars.json \
  --dry-run
```

The dry run prints the full command sequence without executing it.

For the current baseline, where data preparation, model training, and execution-realism analysis already exist, use:

```bash
python -m src.run_validation_chain \
  --tickers AAPL PFE UNH XOM AMD MRK \
  --run-dir reports/backtests/ppo_walkforward_results_20260512_8ticker_combined \
  --payload quantconnect/test_payloads/selected_dynamic_signals_6ticker_quality_250marketbars.json \
  --skip-data \
  --skip-train \
  --skip-execution-realism
```

This runs the downstream validation chain:

```text
quality selector
dynamic signal export
payload manifest generation
local mark-to-market simulation
validation comparison summary
```

The orchestrator does not replace the underlying scripts. It standardizes the sequence and arguments used to run them.

---

## Selection Rule

Future additions should be screened through the moderate execution-realism output before inclusion.

Minimum filter:

```text
Execution_Winner == PPO
Execution_Edge_vs_BuyHold > 0
```

Preferred secondary checks:

```text
Sharpe_Est > 0
Max_Drawdown_% is not excessive
Trade_Events and Total_Turnover remain controlled
```

---

## Known Limitations

The six-ticker baseline is based on local mark-to-market simulation, not a full broker-accurate fill simulator.

QuantConnect validation has been used primarily for Object Store ingestion, timestamp alignment, and order-path validation. Longer-window performance evaluation remains more reliable in the local/VS Code simulation environment until the QuantConnect data availability limitation is resolved.

The documented six-ticker baseline uses a combined run folder:

```text
reports/backtests/ppo_walkforward_results_20260512_8ticker_combined
```

This combined folder was used to consolidate the original four selected tickers with the later AMD/MRK/META/ORCL expansion. Future runs should prefer a single run directory generated from the full intended ticker universe.

---

## Version-Control Notes

Do not commit regenerated report files unless intentionally adding ignored artifacts.

If a payload JSON changes only because `generated_utc` was refreshed, restore it unless the payload itself is intentionally being updated:

```bash
git restore quantconnect/test_payloads/selected_dynamic_signals_6ticker_quality_250marketbars.json
```

If the payload and manifest are intentionally updated together, commit both so the manifest hash matches the payload content.

Commit workflow documentation changes with:

```bash
git add docs/workflows/six_ticker_quality_baseline.md
git commit -m "Document validation orchestrator and payload manifest"
git pull --rebase origin main
git push
```
