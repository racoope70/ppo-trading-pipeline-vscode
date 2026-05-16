# Six-Ticker Quality Baseline Workflow

## Objective

This document defines the reproducible validation path for the six-ticker PPO quality baseline.

The purpose is to preserve the exact command sequence used to regenerate the selected data set, training artifacts, execution-realism diagnostics, LEAN-compatible signal payload, payload manifest, local mark-to-market simulation, and validation comparison summary.

The workflow avoids manual edits to `src/config.py` by using explicit CLI overrides. This keeps the research process auditable and reduces the risk of comparing artifacts from inconsistent ticker universes or run directories.

---

## Baseline Universe

Current baseline universe:

```text
AAPL, PFE, UNH, XOM, AMD, MRK
```

The six-ticker set was selected after comparing the four-ticker and eight-ticker dynamic signal simulations.

Excluded from the eight-ticker expansion:

```text
META, ORCL
```

Rationale: META and ORCL did not pass the moderate execution-realism filter. Their best moderate-scenario result favored Buy & Hold over PPO, so they were excluded from the quality-filtered baseline.

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

Conclusion: the six-ticker quality-filtered simulation is the primary local validation baseline.

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

This reproduces the six-ticker quality baseline used for the validation workflow.

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

### 7. Verify payload structure and manifest metadata

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

This check confirms that the exported payload and manifest are structurally present and internally readable.

---

### 8. Validate payload manifest

After exporting the payload and manifest, verify that the payload still matches the manifest record.

```bash
python -m src.validate_payload_manifest \
  --manifest quantconnect/test_payloads/selected_dynamic_signals_6ticker_quality_250marketbars.manifest.json
```

Expected checks:

```text
payload_exists: PASS
sha256_match: PASS
symbols_match: PASS
selected_models_match: PASS
rows_per_symbol_match: PASS
signal_rows_match: PASS
first_timestamp_match: PASS
last_timestamp_match: PASS
```

This closes the audit loop for the exported signal payload. The exporter writes the manifest, and the validator confirms that the payload file still matches the saved reproducibility record.

---

### 9. Run local mark-to-market dynamic signal simulation

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

### 10. Regenerate validation comparison summary

```bash
python -m src.summarize_selected_dynamic_validation \
  --output-dir reports/validation_summary
```

Expected output:

```text
reports/validation_summary/selected_dynamic_validation_comparison.csv
```

The comparison should identify the six-ticker quality-filtered simulation as the primary baseline.

---

### 11. Run final lightweight test suite

```bash
python -m pytest tests -q
git log --oneline -6
```

Expected:

```text
26 passed
```

The documentation update does not affect baseline metrics.

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

## Five-Ticker Sharpe-Filtered Sensitivity Check

A stricter sensitivity test was run using the non-negative Sharpe filter:

```bash
python -m src.select_quality_tickers \
  --run-dir reports/backtests/ppo_walkforward_results_20260512_8ticker_combined \
  --scenario moderate \
  --min-sharpe 0 \
  --output-dir reports/validation_summary
```

This selected:

```text
AAPL, AMD, MRK, UNH, XOM
```

and excluded:

```text
META, ORCL, PFE
```

The five-ticker Sharpe-filtered payload was exported and simulated locally against the same run directory. The result was identical to the six-ticker quality-filtered baseline:

| Validation set                        | Final equity | Net return | Sharpe estimate | Max drawdown | Trade events |
| ------------------------------------- | -----------: | ---------: | --------------: | -----------: | -----------: |
| Five-ticker Sharpe-filtered local MTM |   112,982.27 |     12.98% |            3.80 |        8.96% |          198 |
| Six-ticker quality-filtered local MTM |   112,982.27 |     12.98% |            3.80 |        8.96% |          198 |

Interpretation: excluding PFE did not change the local mark-to-market result because PFE generated only `HOLD` signals in the exported six-ticker dynamic payload. Therefore, PFE contributed no active exposure, turnover, or PnL in the local MTM simulation.

The five-ticker payload was not committed because it is redundant with the documented six-ticker baseline under the current signal thresholding and execution simulator.

---

## Transaction-Cost Sensitivity Check

A transaction-cost sensitivity test was run against the six-ticker quality-filtered dynamic signal payload to evaluate whether the baseline remains viable under higher execution-cost assumptions.

The baseline local mark-to-market simulation uses:

```text
Cost bps: 5.00
```

Additional simulations were run at:

```text
10 bps
15 bps
```

Commands:

```bash
python -m src.simulate_dynamic_signal_execution \
  --run-dir reports/backtests/ppo_walkforward_results_20260512_8ticker_combined \
  --payload quantconnect/test_payloads/selected_dynamic_signals_6ticker_quality_250marketbars.json \
  --cost-bps 10

python -m src.simulate_dynamic_signal_execution \
  --run-dir reports/backtests/ppo_walkforward_results_20260512_8ticker_combined \
  --payload quantconnect/test_payloads/selected_dynamic_signals_6ticker_quality_250marketbars.json \
  --cost-bps 15

python -m src.simulate_dynamic_signal_execution \
  --run-dir reports/backtests/ppo_walkforward_results_20260512_8ticker_combined \
  --payload quantconnect/test_payloads/selected_dynamic_signals_6ticker_quality_250marketbars.json \
  --cost-bps 5
```

The final `--cost-bps 5` run restores the standard baseline output file after the higher-cost sensitivity runs.

| Cost assumption | Final equity | Net return | Sharpe estimate | Max drawdown | Transaction costs | Total turnover | Trade events |
| --------------: | -----------: | ---------: | --------------: | -----------: | ----------------: | -------------: | -----------: |
|           5 bps |   112,982.27 |     12.98% |          3.8048 |        8.96% |          2,000.96 |        36.8929 |          198 |
|          10 bps |   110,916.76 |     10.92% |          3.2663 |        9.17% |          3,965.18 |        36.8929 |          198 |
|          15 bps |   108,888.68 |      8.89% |          2.7275 |        9.38% |          5,893.32 |        36.8929 |          198 |

Interpretation: the strategy degrades as transaction costs rise, as expected, but remains positive under the tested 10 bps and 15 bps assumptions. The 15 bps stress case still produced an 8.89% net return and a 2.73 Sharpe estimate in the local mark-to-market simulation.

The cost sensitivity does not change turnover or trade count because it reuses the same dynamic signal payload and only changes the transaction-cost assumption.

---

## Weight-Cap Sensitivity Check

A weight-cap sensitivity test was run against the six-ticker quality-filtered dynamic signal payload to evaluate whether the strategy remains viable under more conservative position-sizing assumptions.

The standard payload uses the exported target weights directly. In this baseline, the effective maximum absolute target weight is approximately 25% per active symbol.

A simulator-level override was added:

```bash
--max-abs-weight
```

This allows the same dynamic signal payload to be tested under lower exposure caps without regenerating the signal file.

Example commands:

```bash
python -m src.simulate_dynamic_signal_execution \
  --run-dir reports/backtests/ppo_walkforward_results_20260512_8ticker_combined \
  --payload quantconnect/test_payloads/selected_dynamic_signals_6ticker_quality_250marketbars.json \
  --cost-bps 5 \
  --max-abs-weight 0.25

python -m src.simulate_dynamic_signal_execution \
  --run-dir reports/backtests/ppo_walkforward_results_20260512_8ticker_combined \
  --payload quantconnect/test_payloads/selected_dynamic_signals_6ticker_quality_250marketbars.json \
  --cost-bps 5 \
  --max-abs-weight 0.15

python -m src.simulate_dynamic_signal_execution \
  --run-dir reports/backtests/ppo_walkforward_results_20260512_8ticker_combined \
  --payload quantconnect/test_payloads/selected_dynamic_signals_6ticker_quality_250marketbars.json \
  --cost-bps 5 \
  --max-abs-weight 0.10

python -m src.simulate_dynamic_signal_execution \
  --run-dir reports/backtests/ppo_walkforward_results_20260512_8ticker_combined \
  --payload quantconnect/test_payloads/selected_dynamic_signals_6ticker_quality_250marketbars.json \
  --cost-bps 5
```

The final command restores the standard payload-weight baseline output after the sensitivity runs.

| Weight assumption | Final equity | Net return | Sharpe estimate | Max drawdown | Transaction costs | Total turnover | Trade events |
| ----------------- | -----------: | ---------: | --------------: | -----------: | ----------------: | -------------: | -----------: |
| Payload weights   |   112,982.27 |     12.98% |          3.8048 |        8.96% |          2,000.96 |        36.8929 |          198 |
| 25% cap           |   112,982.27 |     12.98% |          3.8048 |        8.96% |          2,000.96 |        36.8929 |          198 |
| 15% cap           |   107,741.96 |      7.74% |          3.8242 |        5.44% |          1,203.65 |        22.8964 |          165 |
| 10% cap           |   105,106.90 |      5.11% |          3.8082 |        3.65% |            796.17 |        15.4000 |          149 |

Interpretation: reducing the maximum absolute position size lowers net return, turnover, transaction costs, and drawdown. However, the Sharpe estimate remains stable around 3.8 across the 25%, 15%, and 10% cap tests. This suggests that the signal quality is not solely dependent on aggressive sizing; the strategy remains risk-adjusted positive under more conservative exposure assumptions.

The 15% and 10% caps are not proposed replacements for the primary baseline at this stage. They are sensitivity checks showing how the same signal payload behaves when position sizing is reduced.

## Known Limitations

---

The six-ticker baseline is based on local mark-to-market simulation, not a full broker-accurate fill simulator.

QuantConnect validation has been used primarily for Object Store ingestion, timestamp alignment, payload compatibility, and order-path validation. Longer-window performance evaluation remains more reliable in the local/VS Code simulation environment until the QuantConnect data-availability limitation is resolved.

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
git status --short
git add docs/workflows/six_ticker_quality_baseline.md
git commit -m "Document payload manifest validation workflow"
git pull --rebase origin main
git push
git status --short
```