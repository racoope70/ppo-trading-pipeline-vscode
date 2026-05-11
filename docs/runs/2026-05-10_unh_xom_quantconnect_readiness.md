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

```text
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
