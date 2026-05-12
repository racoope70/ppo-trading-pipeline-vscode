# 2026-05-10 — UNH/XOM QuantConnect Readiness Check

## Objective

This check validated whether the local PPO research pipeline was ready to move from research diagnostics into a minimal QuantConnect/LEAN validation test.

The focus was limited to the two lead candidates from the four-ticker 150k validation work:

- UNH
- XOM

This phase did not evaluate profitability. The goal was to confirm that the selected PPO artifacts, execution-adjusted model selection, and QuantConnect signal export were aligned before building a LEAN smoke test.

## Background

The prior four-ticker 150k validation identified UNH and XOM as the strongest lead candidates after several filters:

- model-selection review
- turnover and transaction-cost review
- execution-realism review
- lead-candidate trade-ledger backtest

The final selected lead windows were:

| Symbol | Selected Window | Selected Prefix | Selection Reason |
| --- | --- | --- | --- |
| UNH | 0-3500 | ppo_UNH_window1 | Strongest execution-adjusted edge |
| XOM | 500-4000 | ppo_XOM_window2 | Strongest moderate execution-adjusted edge |

A prior issue was found where the QuantConnect export still selected `ppo_XOM_window3` because the prediction selector ranked by raw Sharpe. That was corrected by updating `src/predict.py` to prefer the moderate execution-adjusted result when `execution_realism_analysis.csv` exists.

## Commands Run

Artifact availability check:

```bash
ls models/ppo_models_master | grep "ppo_UNH_window1"
ls models/ppo_models_master | grep "ppo_XOM_window2"
```

Full readiness sequence:

```bash
python -m src.review_latest_run
python -m src.analyze_execution_realism
python -m src.backtest_lead_candidates
python -m src.adapters.quantconnect --symbols "UNH,XOM"
```

Latest signal inspection:

```bash
python - <<'PY'
import json
from pathlib import Path

latest = sorted(Path("reports/backtests").glob("quantconnect_signals_*/live_signals.json"))[-1]
print("LATEST:", latest)

with open(latest, "r") as f:
    data = json.load(f)

for model in data["models"]:
    print(model["symbol"], model["prefix"], model["signal"], model["confidence"])
PY
```

## Artifact Check

The required model artifacts existed for both selected lead models.

UNH artifacts:

```
ppo_UNH_window1_features.json
ppo_UNH_window1_model.zip
ppo_UNH_window1_model_info.json
ppo_UNH_window1_probability_config.json
ppo_UNH_window1_vecnorm.pkl
```

XOM artifacts:

```text
ppo_XOM_window2_features.json
ppo_XOM_window2_model.zip
ppo_XOM_window2_model_info.json
ppo_XOM_window2_probability_config.json
ppo_XOM_window2_vecnorm.pkl
```

## Readiness Results

All local readiness checks completed successfully.

| Check | Result |
| --- | --- |
| Latest run review | Passed |
| Execution-realism analysis | Passed |
| Lead-candidate backtest | Passed |
| QuantConnect signal export | Passed |
| UNH selected prefix | ppo_UNH_window1 |
| XOM selected prefix | ppo_XOM_window2 |

The final signal export used the execution-adjusted selector:

```text
Selected execution-adjusted model for UNH: ppo_UNH_window1
Selected execution-adjusted model for XOM: ppo_XOM_window2
```

The latest signal file confirmed:

```text
UNH ppo_UNH_window1 SELL 0.5823357701301575
XOM ppo_XOM_window2 BUY 1.0
```

Latest signal output folder:

```text
reports/backtests/quantconnect_signals_20260510_212219
```

Latest signal file:

```text
reports/backtests/quantconnect_signals_20260510_212219/live_signals.json
```

## Lead Candidate Backtest Confirmation

The lead-candidate execution-aware backtest selected the correct execution-adjusted windows:

| Symbol | Window | Prefix | Execution Edge vs Buy & Hold |
| --- | --- | --- | ---: |
| UNH | 0-3500 | ppo_UNH_window1 | 107,023.61 |
| XOM | 500-4000 | ppo_XOM_window2 | 50,976.85 |

Under the 5 bps execution-cost assumption, both remained PPO-favorable:

| Symbol | Execution Final Equity | Buy & Hold | Edge | Estimated Sharpe | Win Rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| UNH | 172,278.60 | 65,254.99 | 107,023.61 | 1.661 | 53.7% |
| XOM | 153,250.09 | 102,273.24 | 50,976.85 | 1.105 | 42.0% |

## Important Fix Confirmed

The prior issue was that QuantConnect export selected:

```text
XOM -> ppo_XOM_window3
```

That was not aligned with the execution-adjusted research result.

After updating `src/predict.py`, the export now correctly selects:

```text
XOM -> ppo_XOM_window2
```

This confirms that the prediction/export path is now aligned with the final research selection logic.

## Interpretation

The local research-to-export pipeline is now internally consistent for UNH and XOM.

UNH remains the strongest lead candidate. XOM remains viable and now uses the correct execution-adjusted window. The QuantConnect export is no longer using raw-Sharpe selection for XOM.

This means the next validation stage can move from local research diagnostics to a minimal QuantConnect/LEAN smoke test.

## Limitations

This was still a local readiness check.

It did not yet test:

- QuantConnect ObjectStore loading
- LEAN historical data behavior
- order execution inside QuantConnect
- portfolio target sizing inside LEAN
- stale-signal rejection inside QuantConnect
- brokerage model fees or fills
- live/paper trading behavior

## Research Conclusion

The UNH/XOM QuantConnect readiness check passed.

Current lead candidates:

| Rank | Symbol | Prefix | Current Status |
| ---: | --- | --- | --- |
| 1 | UNH | ppo_UNH_window1 | Strongest lead candidate |
| 2 | XOM | ppo_XOM_window2 | Viable active candidate |

Recommended next step:

`Build a minimal QuantConnect/LEAN smoke test for UNH and XOM that loads the exported signal file, rejects stale signals, maps BUY/SELL/HOLD to target weights, and logs intended portfolio targets before attempting a fuller backtest.`

This should be a separate file because it marks a new phase: **research validation has reached the point where LEAN integration testing is justified for UNH and XOM only**.

---

## Addendum — QuantConnect Smoke Test Result

A minimal QuantConnect/LEAN smoke test was run for the selected lead candidates, UNH and XOM.

The goal was not to evaluate profitability. The goal was to confirm that QuantConnect could parse the PPO-style signal payload, map the signals to target holdings, and submit trades inside the LEAN backtest environment.

The first run initialized correctly but produced zero orders because the signal timestamps were rejected as stale. For smoke-test purposes, timestamp freshness was temporarily bypassed using:

`self.bypass_stale_check = True`

After bypassing stale-signal rejection, the smoke test successfully placed trades.

## Smoke Test Result

| Metric | Result |
|---|---:|
| Start equity | 100,000.00 |
| End equity | 100,447.58 |
| Net profit | 447.58 |
| Total orders | 2 |
| Holdings | 49,397.43 |
| Fees | 2.00 |
| Portfolio turnover | 49.29% |

## Interpretation

The QuantConnect smoke test passed.

The result confirms that LEAN can:

- add UNH and XOM as hourly equities
- parse the embedded PPO signal payload
- map `SELL` and `BUY` signals to target portfolio weights
- submit holdings changes through `set_holdings`
- generate orders and update portfolio equity

This was not a real performance validation because the stale-signal check was bypassed and the test used an embedded static signal payload. However, it confirms that the basic QuantConnect execution path works.

## Updated Research Status

The local research pipeline and the QuantConnect smoke-test path are now aligned for the lead candidates.

Current validated flow:

| Step | Status |
|---|---|
| Local model selection | Passed |
| Execution-adjusted selector | Passed |
| Lead-candidate backtest | Passed |
| QuantConnect signal export | Passed |
| QuantConnect signal smoke test | Passed |

## Next Recommended Step

The next step should be an Object Store signal-ingestion test.

Instead of hardcoding the signal payload inside the algorithm, upload `live_signals.json` to QuantConnect Object Store and modify the algorithm to read the JSON from Object Store at runtime.

Recommended next test:

`QuantConnect Object Store signal ingestion test for UNH and XOM using live_signals.json.`
---

## Addendum — Object Store Signal Ingestion Test

A second QuantConnect/LEAN smoke test was completed using `live_signals.json` loaded from QuantConnect Object Store.

The prior smoke test used a hardcoded embedded signal payload. This follow-up test replaced the embedded payload with Object Store loading to confirm that QuantConnect could read the exported VS Code signal file at runtime.

Object Store file used:

`live_signals.json`

Source file from local VS Code export:

`reports/backtests/quantconnect_signals_20260510_212219/live_signals.json`

## Test Result

The Object Store ingestion test passed.

| Metric | Result |
|---|---:|
| Start equity | 100,000.00 |
| End equity | 100,447.58 |
| Net profit | 447.58 |
| Total orders | 2 |
| Holdings | 49,397.43 |
| Fees | 2.00 |
| Portfolio turnover | 49.29% |

## Interpretation

This confirms that QuantConnect can load `live_signals.json` from Object Store, parse the selected PPO signals, and submit holdings changes for UNH and XOM.

The test still used `self.bypass_stale_check = True`, so this was not a date-accurate or production-ready validation. The purpose was to confirm Object Store ingestion and order-path functionality.

## Updated Validation Status

| Step | Status |
|---|---|
| Hardcoded signal smoke test | Passed |
| Object Store signal ingestion | Passed |
| UNH signal path | Passed |
| XOM signal path | Passed |
| LEAN order creation | Passed |

## Next Recommended Step

The next step should be a stale-signal validation test.

Recommended test:

`Create a date-aligned Object Store signal file and rerun the QuantConnect smoke test with self.bypass_stale_check = False.`

---

## Addendum — Date-Aligned Object Store Signal Validation

A date-aligned QuantConnect/LEAN Object Store signal validation test was completed for the selected lead candidates, UNH and XOM.

This test was the next step after the Object Store smoke test. The earlier smoke test confirmed that QuantConnect could read `live_signals.json` from Object Store and submit orders, but it used `self.bypass_stale_check = True`.

This follow-up test turned stale-signal validation back on:

`self.bypass_stale_check = False`

The goal was to confirm that QuantConnect could still read the Object Store signal payload, validate signal freshness, map signals to target holdings, and submit orders when the signal timestamps were aligned with the backtest clock.

## Test Payload

A dedicated date-aligned test payload was created and uploaded to QuantConnect Object Store.

Object Store key:

`live_signals_date_aligned_feb10.json`

Local repository file:

`quantconnect/test_payloads/live_signals_date_aligned_feb10.json`

The test payload used the same selected PPO prefixes:

| Symbol | Prefix | Signal | Action | Confidence |
|---|---|---|---:|---:|
| UNH | ppo_UNH_window1 | SELL | -0.5823 | 0.5823 |
| XOM | ppo_XOM_window2 | BUY | 1.0000 | 1.0000 |

The signal timestamp was aligned to the QuantConnect test window:

`2026-02-10 09:30:00+00:00`

## QuantConnect Test Configuration

| Setting | Value |
|---|---|
| Start date | 2026-02-10 |
| End date | 2026-02-13 |
| Resolution | Hour |
| Symbols | UNH, XOM |
| Object Store key | live_signals_date_aligned_feb10.json |
| Stale-check bypass | False |
| Max signal age | 10 days |
| Max absolute target weight | 25% |
| Minimum confidence | 0.10 |

The QuantConnect code used:

`quantconnect/lean_unh_xom_date_aligned_signal_test.py`

## Test Result

The date-aligned Object Store signal validation passed.

| Metric | Result |
|---|---:|
| Start equity | 100,000.00 |
| End equity | 100,447.58 |
| Net profit | 447.58 |
| Total orders | 2 |
| Holdings | 49,397.43 |
| Fees | 2.00 |
| Portfolio turnover | 49.29% |

## Interpretation

This test confirmed that QuantConnect can read a signal payload from Object Store and execute the selected UNH/XOM signals without bypassing stale-signal validation.

The earlier zero-order run was caused by timestamp alignment issues. After the signal timestamps were aligned to the QuantConnect backtest clock, both signals passed validation and generated orders.

This confirms the following path now works:

| Step | Status |
|---|---|
| Object Store JSON upload | Passed |
| Object Store JSON read inside LEAN | Passed |
| Signal payload parsing | Passed |
| Stale-signal validation with bypass disabled | Passed |
| UNH signal mapping | Passed |
| XOM signal mapping | Passed |
| `set_holdings` order path | Passed |
| LEAN order creation | Passed |

## Updated Validation Status

The UNH/XOM QuantConnect validation path has now passed three levels:

| Validation Stage | Status |
|---|---|
| Hardcoded signal smoke test | Passed |
| Object Store signal ingestion with stale-check bypass | Passed |
| Date-aligned Object Store signal validation with stale-check active | Passed |

## Limitation

This was still a controlled validation test. It used a static Object Store JSON payload and did not yet run live model inference inside QuantConnect.

The signal timestamp was intentionally aligned to the QuantConnect test window to validate the freshness-control logic. This was a safety test, not a full profitability backtest.

## Next Recommended Step

The next engineering step should be an Object Store model-artifact loading test.

Recommended next test:

`Upload the selected UNH and XOM PPO artifacts to QuantConnect Object Store and verify that QuantConnect can locate and read the expected model, VecNormalize, feature, model_info, and probability_config files for ppo_UNH_window1 and ppo_XOM_window2.`

---

## Addendum — Object Store Model Artifact Loading Test

An Object Store model-artifact loading test was completed for the selected UNH and XOM PPO models.

The goal was not to run PPO inference inside QuantConnect. The goal was to verify that QuantConnect could locate the selected model artifacts in Object Store and read the JSON metadata files required for later inference or deployment tests.

## Object Store Structure

The selected artifacts were uploaded under:

`ppo_models_master/UNH/`

`ppo_models_master/XOM/`

Selected UNH artifact set:

| Artifact | Status |
|---|---|
| ppo_UNH_window1_model.zip | Found |
| ppo_UNH_window1_vecnorm.pkl | Found |
| ppo_UNH_window1_features.json | Found and readable |
| ppo_UNH_window1_model_info.json | Found and readable |
| ppo_UNH_window1_probability_config.json | Found and readable |

Selected XOM artifact set:

| Artifact | Status |
|---|---|
| ppo_XOM_window2_model.zip | Found |
| ppo_XOM_window2_vecnorm.pkl | Found |
| ppo_XOM_window2_features.json | Found and readable |
| ppo_XOM_window2_model_info.json | Found and readable |
| ppo_XOM_window2_probability_config.json | Found and readable |

## Test Result

The QuantConnect artifact-loading test passed.

Key log result:

`ARTIFACT CHECK PASSED: all selected UNH/XOM artifacts are available and readable.`

## Interpretation

This confirms that QuantConnect Object Store contains the correct selected model-artifact set for the current lead candidates:

| Symbol | Selected Prefix | Artifact Status |
|---|---|---|
| UNH | ppo_UNH_window1 | Passed |
| XOM | ppo_XOM_window2 | Passed |

This was a read-only validation test. It intentionally did not place trades and did not attempt to run Stable-Baselines3/PPO inference inside QuantConnect.

## Updated Validation Status

| Validation Stage | Status |
|---|---|
| Hardcoded signal smoke test | Passed |
| Object Store signal ingestion | Passed |
| Date-aligned Object Store signal validation | Passed |
| Object Store model-artifact loading | Passed |

## Next Recommended Step

The next recommended step is a full LEAN backtest with precomputed dynamic signals.

This should use a signal file generated outside QuantConnect from the VS Code PPO pipeline, then uploaded to Object Store and consumed by LEAN during the backtest.

This is preferred before attempting live PPO model inference inside QuantConnect because it keeps model execution, feature generation, and trading simulation separated for debugging.

---

## Addendum — Full LEAN Backtest With Precomputed Dynamic Signals

A full QuantConnect/LEAN backtest was completed using a precomputed dynamic PPO signal file for UNH and XOM.

This was the next step after the Object Store model-artifact loading test. The goal was not to run Stable-Baselines3/PPO inference inside QuantConnect. Instead, the VS Code research pipeline generated a multi-row historical signal file, which was uploaded to QuantConnect Object Store and consumed by LEAN during the backtest.

## Dynamic Signal File

Local generated file:

`quantconnect/test_payloads/unh_xom_dynamic_signals.json`

QuantConnect Object Store key:

`unh_xom_dynamic_signals.json`

Generated by:

`src/export_dynamic_lean_signals.py`

The export used the selected execution-adjusted PPO models:

| Symbol | Selected Prefix |
|---|---|
| UNH | ppo_UNH_window1 |
| XOM | ppo_XOM_window2 |

The generated signal file contained:

| Symbol | Signal Rows |
|---|---:|
| UNH | 30 |
| XOM | 30 |
| Total | 60 |

Signal count summary:

| Symbol | Signal | Count |
|---|---|---:|
| UNH | SELL | 30 |
| XOM | BUY | 26 |
| XOM | HOLD | 4 |

The generated signal window ran from:

`2026-02-10T09:30:00+00:00`

to:

`2026-02-11T14:30:00+00:00`

## QuantConnect Test Result

The dynamic signal LEAN backtest passed.

Key log confirmations:

```text
Loaded dynamic signal payload from Object Store key: unh_xom_dynamic_signals.json
UNH | loaded signal rows: 30
XOM | loaded signal rows: 30
```

The backtest then mapped signals to target holdings through time.

Example signal executions:

```text
2026-02-10 10:00:00 | UNH | signal_time=2026-02-10 09:30:00 | prefix=ppo_UNH_window1 | signal=SELL | confidence=0.5997 | action=-0.5997 | target_weight=-0.2500

2026-02-10 10:00:00 | XOM | signal_time=2026-02-10 09:30:00 | prefix=ppo_XOM_window2 | signal=BUY | confidence=0.7084 | action=0.7084 | target_weight=0.2500

2026-02-10 16:00:00 | XOM | signal_time=2026-02-10 15:30:00 | prefix=ppo_XOM_window2 | signal=HOLD | confidence=0.0487 | action=-0.0487 | target_weight=0.0000
```

## Backtest Metrics

| Metric | Result |
|---|---:|
| Start equity | 100,000.00 |
| End equity | 100,447.58 |
| Net profit | 447.58 |
| Total orders | 3 |
| Holdings | 49,397.43 |
| Fees | 2.00 |
| Portfolio turnover | 49.29% |

## Interpretation

This test confirms that QuantConnect can run a dynamic precomputed signal backtest using signals exported from the VS Code PPO research pipeline.

The test validated the following path:

| Step | Status |
|---|---|
| Dynamic signal export from VS Code | Passed |
| Object Store upload | Passed |
| Object Store dynamic JSON read inside LEAN | Passed |
| Signal timestamp matching | Passed |
| UNH dynamic signal consumption | Passed |
| XOM dynamic signal consumption | Passed |
| BUY/SELL/HOLD target-weight mapping | Passed |
| LEAN order creation from dynamic signals | Passed |

This is a stronger validation than the prior static signal smoke tests because LEAN consumed a time-series signal file and generated orders from changing signals through time.

## Limitation

This was still a controlled short-window test. It did not run PPO inference inside QuantConnect and did not yet evaluate a full historical period.

The PPO model execution, feature engineering, and signal generation remained outside QuantConnect in the VS Code research pipeline.

## Updated Validation Status

| Validation Stage | Status |
|---|---|
| Hardcoded signal smoke test | Passed |
| Object Store signal ingestion | Passed |
| Date-aligned Object Store signal validation | Passed |
| Object Store model-artifact loading | Passed |
| Full LEAN backtest with precomputed dynamic signals | Passed |

## Next Recommended Step

The next step should be to expand the dynamic signal file from a short controlled test window to a longer historical LEAN backtest window.

Recommended next test:

Generate a longer UNH/XOM dynamic signal file covering the full available prediction compatibility window and run a longer QuantConnect/LEAN backtest using the same Object Store dynamic-signal approach.


## Addendum — Market-Hours Dynamic Signal Alignment and Data Availability Check

A market-hours-aligned dynamic signal test was completed for the UNH/XOM QuantConnect path.

The goal was to confirm whether the longer 250-row dynamic signal file could align correctly with LEAN hourly bars and whether QuantConnect would provide enough UNH/XOM hourly data to evaluate a longer historical window.

## Market-Hours Dynamic Signal Payload

Object Store key:

`unh_xom_dynamic_signals_250marketbars.json`

The market-hours payload was created to avoid the earlier issue where signals were generated every calendar hour, including nights and weekends. The updated payload used only market-hour timestamps:

`10:00, 11:00, 12:00, 13:00, 14:00, 15:00, 16:00 UTC`

The dynamic signal file loaded successfully:

```text
Loaded dynamic signal payload from Object Store key: unh_xom_dynamic_signals_250marketbars.json
UNH | loaded signal rows: 250
XOM | loaded signal rows: 250
```

The signal timestamps aligned directly with LEAN hourly bars:

```text
2026-02-10 10:00:00 | UNH | signal_time=2026-02-10 10:00:00
2026-02-10 10:00:00 | XOM | signal_time=2026-02-10 10:00:00
2026-02-10 12:00:00 | XOM | signal_time=2026-02-10 12:00:00
2026-02-10 15:00:00 | XOM | signal_time=2026-02-10 15:00:00
2026-02-10 16:00:00 | XOM | signal_time=2026-02-10 16:00:00
```

## Backtest Result

| Metric                |     Result |
| --------------------- | ---------: |
| Start equity          | 100,000.00 |
| End equity            | 100,279.97 |
| Net profit            |     271.26 |
| Total orders          |          5 |
| Holdings              |  40,362.25 |
| Fees                  |       4.00 |
| Portfolio turnover    |     90.07% |
| Data points processed |         29 |

## Data Availability Diagnostic

A separate UNH/XOM hourly data availability check was then run with no signals, no Object Store, and no orders.

The diagnostic used the same intended date range:

`2026-02-10 through 2026-03-20`

Result:

```text
UNH SUMMARY | bars=7 | first_bar=2026-02-10 10:00:00 | last_bar=2026-02-10 16:00:00 | unique_trading_dates=1
XOM SUMMARY | bars=7 | first_bar=2026-02-10 10:00:00 | last_bar=2026-02-10 16:00:00 | unique_trading_dates=1
```

This confirmed that QuantConnect only provided Feb 10 hourly bars for UNH and XOM in this current setup, despite the March 20 end date.

## Interpretation

The market-hours dynamic signal logic passed as an engineering validation.

Confirmed:

| Check                                                        | Status |
| ------------------------------------------------------------ | ------ |
| Market-hours dynamic signal payload loaded from Object Store | Passed |
| 250 UNH signal rows loaded                                   | Passed |
| 250 XOM signal rows loaded                                   | Passed |
| Signal timestamps aligned with LEAN hourly bars              | Passed |
| Dynamic target-weight mapping worked                         | Passed |
| LEAN order creation worked                                   | Passed |

Limitation:

The intended longer historical evaluation did not complete because QuantConnect only fed one trading day of UNH/XOM hourly bars in this setup.

## Current Status

Passed: market-hour signal timestamps aligned with LEAN bars.

Blocked: QuantConnect run only processed Feb 10 data despite the March 20 end date, so longer historical behavior was not evaluated.

---

## Addendum — Local Mark-to-Market Dynamic Signal Execution Simulation

After the QuantConnect data availability check showed that LEAN only supplied one trading day of UNH/XOM hourly bars, a local mark-to-market dynamic signal execution simulation was created and run.

The purpose of this test was to evaluate the full 250-market-bar UNH/XOM dynamic signal payload locally, using saved prediction compatibility files for close-price returns.

Script:

`src/simulate_dynamic_signal_execution.py`

Payload:

`quantconnect/test_payloads/unh_xom_dynamic_signals_250marketbars.json`

Training run used:

`reports/backtests/ppo_walkforward_results_20260509_172626`

## Alignment Method

The simulator aligns the dynamic signal payload to return rows by per-symbol `bar_index`, rather than timestamp lookup.

This avoids timezone/type mismatches between:

- synthetic LEAN payload timestamps, and
- original historical timestamps from the saved prediction compatibility files.

Alignment check:

```text
Signal bar_index range:
        min  max  count
symbol                 
UNH       0  249    250
XOM       0  249    250

Return bar_index range:
        min  max  count
symbol                 
UNH       0  249    250
XOM       0  249    250
```

The first payload timestamps also matched by symbol:

```text
Signal first timestamps:
symbol
UNH   2026-02-10 10:00:00+00:00
XOM   2026-02-10 10:00:00+00:00

Return first payload timestamps:
symbol
UNH   2026-02-10 10:00:00+00:00
XOM   2026-02-10 10:00:00+00:00
```

## Simulation Logic

At each market-bar index, the simulator applies:

1. Mark-to-market PnL using the previous bar's target weights.
2. Rebalancing into the current bar's target weights.
3. Transaction costs based on notional traded.

This avoids lookahead bias because the current bar's return is applied using the weight already held from the previous bar.

## Result Summary

| Metric                  |     Result |
| ----------------------- | ---------: |
| Starting equity         | 100,000.00 |
| Final equity            | 107,004.06 |
| Net PnL                 |   7,004.06 |
| Net return              |      7.00% |
| Gross PnL before costs  |   7,456.44 |
| Total transaction costs |     452.39 |
| Total turnover          |     8.4841 |
| Trade events            |         46 |
| Max drawdown            |      6.59% |
| Sharpe estimate         |       2.78 |
| Simulation rows         |        250 |

## Output Files

The simulator saved:

```text
reports/dynamic_signal_execution/unh_xom_dynamic_signals_250marketbars_mtm_execution_summary.csv
reports/dynamic_signal_execution/unh_xom_dynamic_signals_250marketbars_mtm_equity_curve.csv
reports/dynamic_signal_execution/unh_xom_dynamic_signals_250marketbars_mtm_trade_ledger.csv
```

These files are local report artifacts and may be ignored by Git depending on `.gitignore`.

## Interpretation

This test passed as a local longer-window execution-aware simulation.

Confirmed:

| Check                                           | Status |
| ----------------------------------------------- | ------ |
| Dynamic signal payload loaded                   | Passed |
| 250 UNH signal rows loaded                      | Passed |
| 250 XOM signal rows loaded                      | Passed |
| Return rows aligned by bar index                | Passed |
| Transaction-cost simulation worked              | Passed |
| Mark-to-market PnL simulation worked            | Passed |
| Longer-window local result positive after costs | Passed |

## Current Status

QuantConnect remains useful for validating:

* Object Store ingestion
* artifact loading
* signal parsing
* timestamp alignment
* order-routing behavior

Local/VS Code is currently better for longer-window UNH/XOM evaluation because QuantConnect only supplied one day of hourly bars for these symbols in the tested setup.

## Next Recommended Step

The next recommended step is to create a short comparison table between:

1. original PPO walkforward results,
2. execution realism analysis,
3. QuantConnect one-day dynamic signal test, and
4. local mark-to-market dynamic signal simulation.

---

## Addendum — Reproducible UNH/XOM Validation Comparison Summary

A comparison helper script was created to summarize the main validation stages for the selected UNH/XOM PPO candidates.

Script:

`src/summarize_unh_xom_validation.py`

Output:

`reports/validation_summary/unh_xom_validation_comparison.csv`

The script compares:

1. original PPO walkforward results,
2. execution-realism analysis under the moderate 5 bps scenario,
3. QuantConnect one-day dynamic signal test, and
4. local mark-to-market dynamic signal simulation.

The comparison confirmed the following key results:

| Validation Stage | Scope | Final Equity | Net Return | Sharpe Estimate | Max Drawdown |
|---|---|---:|---:|---:|---:|
| Original PPO walkforward | UNH | 178,521.03 | 78.52% | 0.735 | 12.91% |
| Original PPO walkforward | XOM | 184,988.37 | 84.99% | 0.637 | 12.16% |
| Execution realism, 5 bps | UNH | 172,278.60 | 72.28% | 1.661 | 12.90% |
| Execution realism, 5 bps | XOM | 153,250.09 | 53.25% | 1.105 | 11.72% |
| QuantConnect one-day signal test | UNH/XOM | 100,279.97 | 0.28% | N/A | N/A |
| Local MTM dynamic signal simulation | UNH/XOM | 107,004.06 | 7.00% | 2.782 | 6.59% |

## Interpretation

The comparison table confirms that the UNH/XOM validation path remains consistent across research, execution-realism analysis, QuantConnect signal plumbing, and local mark-to-market simulation.

The original walkforward and execution-realism results remain strong. QuantConnect successfully validates signal ingestion and order plumbing, but its UNH/XOM hourly data availability limits longer testing in the current setup. The local mark-to-market simulation provides the better current longer-window validation path for these symbols.

## Current Conclusion

UNH and XOM remain the current lead candidates for continued validation.

QuantConnect should continue to be used for integration-path testing, while local/VS Code should remain the main environment for longer-window execution-aware evaluation until the QuantConnect data limitation is resolved. 

## Addendum — Four-Ticker Selected Dynamic Signal Simulation

A generalized four-ticker dynamic signal payload was created and tested locally using the mark-to-market execution simulator.

This test expands the prior UNH/XOM-only simulation to a selected four-ticker validation set:

- AAPL
- PFE
- UNH
- XOM

The purpose was to verify that the dynamic signal export and local execution simulator can scale beyond the original two-symbol test while still:

- loading the correct prediction compatibility files,
- aligning returns correctly,
- applying transaction costs, and
- producing mark-to-market portfolio results.

---

## Scripts

### Exporter

```text
src/export_selected_dynamic_lean_signals.py
```

### Simulator

```text
src/simulate_dynamic_signal_execution.py
```

### Payload

```text
quantconnect/test_payloads/selected_dynamic_signals_4ticker_250marketbars.json
```

### Output Files

```text
reports/dynamic_signal_execution/selected_dynamic_signals_4ticker_250marketbars_mtm_execution_summary.csv
reports/dynamic_signal_execution/selected_dynamic_signals_4ticker_250marketbars_mtm_equity_curve.csv
reports/dynamic_signal_execution/selected_dynamic_signals_4ticker_250marketbars_mtm_trade_ledger.csv
```

---

## Selected Models

The payload selected the following model prefixes:

```text
AAPL    ppo_AAPL_window1
PFE     ppo_PFE_window1
UNH     ppo_UNH_window1
XOM     ppo_XOM_window2
```

The selected models were read directly from the payload via:

```python
payload["selected_models"]
```

rather than being hardcoded in the simulator.

This fixed the earlier issue where the simulator only loaded UNH/XOM return rows even when the four-ticker payload contained AAPL, PFE, UNH, and XOM signals.

---

## Alignment Check

The final successful run confirmed full signal and return coverage for all four symbols.

### Signal bar index range

```text
        min  max  count
symbol
AAPL      0  249    250
PFE       0  249    250
UNH       0  249    250
XOM       0  249    250
```

### Return bar index range

```text
        min  max  count
symbol
AAPL      0  249    250
PFE       0  249    250
UNH       0  249    250
XOM       0  249    250
```

The simulator also confirmed:

```text
Signal rows: 1000
Return rows: 1000
```

This confirms that all four symbols had:

- 250 signal rows, and
- 250 aligned return rows.

---

## Four-Ticker Simulation Result

| Metric | Result |
|---|---|
| Starting equity | 100,000.00 |
| Final equity | 108,909.18 |
| Net PnL | 8,909.18 |
| Net return | 8.91% |
| Gross PnL before costs | 10,715.31 |
| Total transaction costs | 1,806.12 |
| Total turnover | 33.3929 |
| Trade events | 184 |
| Max drawdown | 6.49% |
| Sharpe estimate | 3.40 |
| Simulation rows | 250 |

---

## Comparison to UNH/XOM-Only Simulation

| Simulation | Final Equity | Net Return | Max Drawdown | Sharpe Estimate | Trade Events |
|---|---|---|---|---|---|
| UNH/XOM only | 107,004.06 | 7.00% | 6.59% | 2.78 | 46 |
| Four-ticker selected set | 108,909.18 | 8.91% | 6.49% | 3.40 | 184 |

---

## Interpretation

The four-ticker selected dynamic signal simulation passed.

The result improved versus the prior UNH/XOM-only local simulation:

- higher final equity,
- higher net return,
- slightly lower maximum drawdown,
- higher Sharpe estimate, and
- broader symbol coverage.

The primary tradeoff was higher turnover and more trade events, mostly because AAPL introduced more frequent weight changes while PFE remained largely inactive (`HOLD`) within the signal payload.

This test confirms that the local mark-to-market simulator can now generalize from the original UNH/XOM proof-of-concept to a broader selected validation set.

---

## Current Conclusion

The selected four-ticker set passed the local execution-aware validation checkpoint.

### Validation Status

| Check | Status |
|---|---|
| Payload generated for four selected tickers | Passed |
| Selected model prefixes read from payload | Passed |
| Signal rows loaded for AAPL/PFE/UNH/XOM | Passed |
| Return rows loaded for AAPL/PFE/UNH/XOM | Passed |
| Bar-index alignment worked for all symbols | Passed |
| Transaction-cost simulation worked | Passed |
| Mark-to-market PnL simulation worked | Passed |
| Result remained positive after costs | Passed |

---

## Next Recommended Step

The next recommended step is to update the validation comparison helper so it includes the new four-ticker selected dynamic signal simulation alongside:

1. original PPO walkforward results,
2. execution realism analysis,
3. QuantConnect one-day dynamic signal test,
4. UNH/XOM local mark-to-market simulation, and
5. four-ticker local mark-to-market simulation.

After that, the project can decide whether to expand from four tickers to a broader selected universe rather than jumping directly to all 53 tickers.


## Addendum — Generalized Selected Dynamic Validation Comparison Summary

A generalized validation comparison helper was created to summarize the full selected-ticker validation path in one reproducible CSV.

Script:

`src/summarize_selected_dynamic_validation.py`

Output:

`reports/validation_summary/selected_dynamic_validation_comparison.csv`

This script generalizes the earlier UNH/XOM-only comparison summary and now includes both the original two-ticker validation path and the expanded four-ticker selected dynamic signal simulation.

## Validation Stages Included

The comparison summary includes:

1. original PPO walkforward results,
2. execution-realism analysis under the moderate 5 bps scenario,
3. QuantConnect one-day dynamic signal test,
4. UNH/XOM local mark-to-market dynamic signal simulation, and
5. four-ticker selected local mark-to-market dynamic signal simulation.

## Selected Four-Ticker Models

The generalized summary reads selected model prefixes from:

`quantconnect/test_payloads/selected_dynamic_signals_4ticker_250marketbars.json`

Selected models:

```text
AAPL    ppo_AAPL_window1
PFE     ppo_PFE_window1
UNH     ppo_UNH_window1
XOM     ppo_XOM_window2
```

## Key Comparison Results

| Validation Stage                          | Scope            | Final Equity | Net Return | Sharpe Estimate | Max Drawdown | Trade Events |
| ----------------------------------------- | ---------------- | -----------: | ---------: | --------------: | -----------: | -----------: |
| UNH/XOM local MTM simulation              | UNH/XOM          |   107,004.06 |      7.00% |            2.78 |        6.59% |           46 |
| Four-ticker selected local MTM simulation | AAPL/PFE/UNH/XOM |   108,909.18 |      8.91% |            3.40 |        6.49% |          184 |

The generalized comparison confirmed that the four-ticker selected local simulation improved final equity, net return, and Sharpe estimate versus the UNH/XOM-only simulation, while keeping max drawdown slightly lower. The tradeoff was higher turnover and more trade events.

## Four-Ticker Local MTM Simulation Result

| Metric                  |     Result |
| ----------------------- | ---------: |
| Starting equity         | 100,000.00 |
| Final equity            | 108,909.18 |
| Net PnL                 |   8,909.18 |
| Net return              |      8.91% |
| Gross PnL before costs  |  10,715.31 |
| Total transaction costs |   1,806.12 |
| Total turnover          |    33.3929 |
| Trade events            |        184 |
| Max drawdown            |      6.49% |
| Sharpe estimate         |       3.40 |
| Simulation rows         |        250 |

## Interpretation

This comparison summary confirms that the selected-ticker validation process is now reproducible from scripts rather than being only manually documented.

The project now has a clean validation trail from:

* original model training,
* execution realism adjustment,
* QuantConnect signal ingestion and order plumbing,
* UNH/XOM local execution-aware simulation, and
* generalized four-ticker local execution-aware simulation.

## Current Conclusion

The selected four-ticker validation set remains positive after estimated transaction costs and mark-to-market simulation.

Current best engineering conclusion:

* QuantConnect is useful for Object Store ingestion, artifact checks, timestamp checks, and order-path validation.
* Local/VS Code simulation remains the better environment for longer-window evaluation until the QuantConnect data availability limitation is resolved.
* The four-ticker selected set should be the next baseline before expanding to a broader selected universe.

## Next Recommended Step

The next recommended step is to decide whether to expand from four tickers to a larger selected validation set, such as 8–10 tickers, using the same generalized dynamic signal export, local mark-to-market simulator, and validation comparison summary workflow.