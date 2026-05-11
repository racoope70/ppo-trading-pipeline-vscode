Create a **new `.md` file** now.

The `2026-05-09_4ticker_150k_focused_validation.md` file has done its job. It documents the research run and its addendums. If we keep adding to it, it will become too long and harder to follow.

The next phase is no longer “4-ticker 150k validation.” It is **QuantConnect/LEAN readiness for the selected lead candidates**.

Use this filename:

```text
docs/runs/2026-05-10_unh_xom_quantconnect_readiness.md
```

Paste this:

````markdown
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
|---|---|---|---|
| UNH | 0-3500 | ppo_UNH_window1 | Strongest execution-adjusted edge |
| XOM | 500-4000 | ppo_XOM_window2 | Strongest moderate execution-adjusted edge |

A prior issue was found where the QuantConnect export still selected `ppo_XOM_window3` because the prediction selector ranked by raw Sharpe. That was corrected by updating `src/predict.py` to prefer the moderate execution-adjusted result when `execution_realism_analysis.csv` exists.

## Commands Run

Artifact availability check:

```bash
ls models/ppo_models_master | grep "ppo_UNH_window1"
ls models/ppo_models_master | grep "ppo_XOM_window2"
````

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

| Check                      | Result          |
| -------------------------- | --------------- |
| Latest run review          | Passed          |
| Execution-realism analysis | Passed          |
| Lead-candidate backtest    | Passed          |
| QuantConnect signal export | Passed          |
| UNH selected prefix        | ppo_UNH_window1 |
| XOM selected prefix        | ppo_XOM_window2 |

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

| Symbol | Window   | Prefix          | Execution Edge vs Buy & Hold |
| ------ | -------- | --------------- | ---------------------------: |
| UNH    | 0-3500   | ppo_UNH_window1 |                   107,023.61 |
| XOM    | 500-4000 | ppo_XOM_window2 |                    50,976.85 |

Under the 5 bps execution-cost assumption, both remained PPO-favorable:

| Symbol | Execution Final Equity | Buy & Hold |       Edge | Estimated Sharpe | Win Rate |
| ------ | ---------------------: | ---------: | ---------: | ---------------: | -------: |
| UNH    |             172,278.60 |  65,254.99 | 107,023.61 |            1.661 |    53.7% |
| XOM    |             153,250.09 | 102,273.24 |  50,976.85 |            1.105 |    42.0% |

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

* QuantConnect ObjectStore loading
* LEAN historical data behavior
* order execution inside QuantConnect
* portfolio target sizing inside LEAN
* stale-signal rejection inside QuantConnect
* brokerage model fees or fills
* live/paper trading behavior

## Research Conclusion

The UNH/XOM QuantConnect readiness check passed.

Current lead candidates:

| Rank | Symbol | Prefix          | Current Status           |
| ---: | ------ | --------------- | ------------------------ |
|    1 | UNH    | ppo_UNH_window1 | Strongest lead candidate |
|    2 | XOM    | ppo_XOM_window2 | Viable active candidate  |

Recommended next step:

`Build a minimal QuantConnect/LEAN smoke test for UNH and XOM that loads the exported signal file, rejects stale signals, maps BUY/SELL/HOLD to target weights, and logs intended portfolio targets before attempting a fuller backtest.`

````

Then commit it locally like this:

```bash
git status --short
git add docs/runs/2026-05-10_unh_xom_quantconnect_readiness.md
git commit -m "Document UNH XOM QuantConnect readiness check"
git stash push -m "local experiment config"
git pull --rebase origin main
git push
git stash pop
git status --short
````

This should be a separate file because it marks a new phase: **rresearch validation has reached the point where LEAN integration testing is justified for UNH and XOM only**.
