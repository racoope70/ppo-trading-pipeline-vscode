# 2026-05-06 — Five-Ticker PPO Validation Run After Selector Update

## Objective

This run was performed to validate the local VS Code PPO research pipeline after two implementation changes:

1. Model selection was updated to prefer windows where PPO outperformed Buy & Hold when such windows are available.
2. QuantConnect signal export was updated so generated signals remain valid for 24 hours instead of 90 minutes.

The goal was not to prove production readiness. The goal was to confirm that the local workflow can run end-to-end across a small multi-ticker universe and produce usable artifacts, diagnostics, model-selection output, and QuantConnect-compatible signals.

Workflow tested:

- data preparation
- walk-forward PPO training
- model artifact export
- latest-signal prediction
- diagnostics
- QuantConnect signal export

## Run Configuration

| Setting | Value |
|---|---|
| Test mode | Enabled |
| Symbols | GE, UNH, AAPL, MSFT, NVDA |
| PPO timesteps per window | 50,000 |
| Max workers | 1 |
| Window size | 3,500 rows |
| Step size | 500 rows |
| Data interval | 1 hour |
| Walk-forward windows per ticker | 3 |

This was intentionally kept to five tickers to validate the pipeline after the selector change before expanding to a larger universe.

## Data Validation

Data preparation completed successfully with no missing values detected in the final processed dataset.

| Metric | Value |
|---|---:|
| Combined dataset rows | 24,753 |
| Combined dataset columns | 34 |
| Missing values detected | No |

### Symbol Counts

| Symbol | Rows |
|---|---:|
| AAPL | 4,951 |
| MSFT | 4,951 |
| NVDA | 4,951 |
| GE | 4,950 |
| UNH | 4,950 |

### Target Distribution

| Target | Count | Share |
|---:|---:|---:|
| 0 | 17,492 | 70.67% |
| 1 | 4,043 | 16.33% |
| -1 | 3,218 | 13.00% |

The target distribution remains heavily neutral, which is important when interpreting action frequency and the tendency of some models to remain in HOLD.

## Training Coverage

Training completed for all configured symbols and windows.

| Metric | Value |
|---|---:|
| Tickers trained | 5 |
| Windows per ticker | 3 |
| Total trained windows | 15 |

Training output folder:

`reports/backtests/ppo_walkforward_results_20260506_200459`

Diagnostics confirmed complete model artifacts for all trained windows across AAPL, GE, MSFT, NVDA, and UNH.

## Walk-Forward Results

| Ticker | Window | PPO Portfolio | Buy & Hold | Sharpe | Drawdown % | Winner |
|---|---:|---:|---:|---:|---:|---|
| GE | 0-3500 | 98,383.83 | 287,942.35 | -0.066 | 10.95 | Buy & Hold |
| GE | 500-4000 | 99,629.21 | 341,793.41 | -0.029 | 6.52 | Buy & Hold |
| GE | 1000-4500 | 102,699.45 | 302,714.75 | 0.315 | 2.58 | Buy & Hold |
| UNH | 0-3500 | 113,371.54 | 64,896.60 | 0.698 | 2.97 | PPO |
| UNH | 500-4000 | 102,490.90 | 66,542.40 | 0.276 | 2.58 | PPO |
| UNH | 1000-4500 | 100,911.46 | 68,525.31 | 0.151 | 1.52 | PPO |
| AAPL | 0-3500 | 111,190.24 | 104,786.19 | 0.491 | 3.05 | PPO |
| AAPL | 500-4000 | 122,454.88 | 143,431.97 | 0.542 | 6.61 | Buy & Hold |
| AAPL | 1000-4500 | 106,085.26 | 128,105.87 | 0.355 | 3.00 | Buy & Hold |
| MSFT | 0-3500 | 99,978.45 | 144,518.53 | -0.000 | 2.96 | Buy & Hold |
| MSFT | 500-4000 | 105,213.96 | 161,208.37 | 0.264 | 6.29 | Buy & Hold |
| MSFT | 1000-4500 | 106,629.69 | 107,699.05 | 0.369 | 2.56 | Buy & Hold |
| NVDA | 0-3500 | 107,538.77 | 345,853.76 | 0.548 | 3.04 | Buy & Hold |
| NVDA | 500-4000 | 93,238.65 | 407,686.56 | -0.398 | 10.77 | Buy & Hold |
| NVDA | 1000-4500 | 101,684.47 | 288,987.29 | 0.145 | 2.27 | Buy & Hold |

## Result Interpretation

The run produced two PPO-favorable cases: UNH and AAPL.

UNH showed consistent PPO outperformance versus Buy & Hold across all three windows. The behavior appears defensive rather than highly active, which suggests the model may be adding value primarily through capital preservation and reduced exposure during unfavorable periods.

AAPL produced one PPO-winning window. Although AAPL window 2 had the highest Sharpe among AAPL windows, that window still underperformed Buy & Hold. The updated selector correctly preferred AAPL window 1 because it was the window where PPO actually outperformed Buy & Hold.

GE, MSFT, and NVDA did not produce PPO-winning selected windows in this run. Their PPO portfolios were either modestly positive or defensive in some windows, but they generally lagged Buy & Hold, especially in strong trend environments. NVDA is the clearest example of the PPO model being too conservative relative to a strong momentum benchmark.

The main conclusion is that PPO behavior is not uniform across symbols. It appears more promising on AAPL and UNH under this configuration, while GE, MSFT, and NVDA require further research before being treated as candidates for deployment.

## Model Selection Validation

The updated selector behaved as intended.

| Symbol | Selected Model | Winner | Selection Reason |
|---|---|---|---|
| GE | ppo_GE_window3 | Buy & Hold | No PPO-winning candidate; fallback to Sharpe |
| UNH | ppo_UNH_window1 | PPO | PPO-winning candidate |
| AAPL | ppo_AAPL_window1 | PPO | PPO-winning candidate |
| MSFT | ppo_MSFT_window3 | Buy & Hold | No PPO-winning candidate; fallback to Sharpe |
| NVDA | ppo_NVDA_window1 | Buy & Hold | No PPO-winning candidate; fallback to Sharpe |

The most important selector check was AAPL. The selector chose `ppo_AAPL_window1` even though `ppo_AAPL_window2` had a higher Sharpe, because window 1 was the PPO-winning candidate. This is the intended behavior for the current selector design.

## QuantConnect Signal Export

QuantConnect export completed successfully.

Export folder:

`reports/backtests/quantconnect_signals_20260507_125742`

The exported `live_signals.json` contained all five configured symbols.

| Field | Value |
|---|---|
| generated_utc | 2026-05-07T16:57:52+00:00 |
| valid_until_utc | 2026-05-08T16:57:52+00:00 |

The 24-hour validity window confirms that the signal staleness fix is working as expected.

### Exported Signals

| Symbol | Prefix | Signal | Action | Confidence |
|---|---|---:|---:|---:|
| GE | ppo_GE_window3 | HOLD | 0.0710 | 0.0710 |
| UNH | ppo_UNH_window1 | HOLD | -0.1268 | 0.1268 |
| AAPL | ppo_AAPL_window1 | BUY | 0.2774 | 0.2774 |
| MSFT | ppo_MSFT_window3 | HOLD | -0.1627 | 0.1627 |
| NVDA | ppo_NVDA_window1 | HOLD | 0.0845 | 0.0845 |

## Signal Behavior

Signal counts were reviewed to check whether the selected models were active, defensive, or effectively flat.

| Selected Model | HOLD | BUY | SELL | Interpretation |
|---|---:|---:|---:|---|
| ppo_AAPL_window1 | 2,351 | 1,083 | 12 | Active, long-biased behavior with limited short exposure |
| ppo_UNH_window1 | 3,141 | 305 | 0 | Defensive behavior; mostly out of market |
| ppo_GE_window3 | 3,311 | 135 | 0 | Mostly inactive; weak trade density |
| ppo_MSFT_window3 | 2,340 | 1,106 | 0 | Active, but did not beat Buy & Hold |
| ppo_NVDA_window1 | 3,371 | 75 | 0 | Mostly inactive; too conservative for a strong trend stock |

AAPL is the strongest active signal candidate from this run. UNH is the strongest defensive candidate. GE, MSFT, and NVDA should remain in monitoring rather than being treated as primary deployment candidates.

## Research Conclusion

This run successfully validated the local five-ticker PPO workflow after the selector and QuantConnect export fixes.

### Engineering Status

| Component | Status |
|---|---|
| Data preparation | Pass |
| Walk-forward training | Pass |
| Artifact saving | Pass |
| Model selection | Pass |
| Latest prediction generation | Pass |
| Diagnostics | Pass |
| QuantConnect signal export | Pass |

## Limitations

This run should be interpreted as a controlled validation pass, not a production backtest.

Key limitations:

- The test universe was limited to five symbols.
- Each ticker used three walk-forward windows.
- PPO was evaluated against Buy & Hold, but not yet against transaction-cost-adjusted benchmark strategies such as simple trend-following, volatility targeting, or regime-filtered long-only exposure.
- The results are sensitive to the current feature set, reward design, and action-to-signal thresholds.
- QuantConnect export was validated structurally, but the external signal consumer still needs to be tested in a full LEAN backtest workflow.

Because of these limitations, AAPL and UNH should be treated as candidates for further validation rather than deployment-ready strategies.

### Research Status

| Symbol | Current Assessment |
|---|---|
| AAPL | Candidate for further validation as an active PPO signal |
| UNH | Candidate for further validation as a defensive PPO signal |
| GE | Monitor only |
| MSFT | Monitor only |
| NVDA | Monitor only |

The results do not establish production readiness. They do establish that the local pipeline is functioning and that the updated model selector changes the selected model in a meaningful way.

The next research step is to test the QuantConnect external signal consumer using AAPL and UNH as the initial focus set. GE, MSFT, and NVDA can remain in the exported signal set for monitoring, but they should not drive deployment decisions from this run.