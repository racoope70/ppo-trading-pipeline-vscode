# 2026-05-08 — Ten-Ticker PPO Validation Run

## Objective

This run expanded the local PPO walk-forward validation from five symbols to ten symbols. The purpose was to test whether the local workflow remained stable with a broader test universe and to identify whether any additional symbols showed evidence of PPO outperformance relative to Buy & Hold.

This was not intended to establish production readiness. The objective was to validate the workflow at a larger scale and identify candidates for deeper follow-up testing.

## Run Configuration

| Setting | Value |
|---|---|
| Test mode | Enabled |
| Symbols | GE, UNH, AAPL, MSFT, NVDA, AMD, PFE, JPM, XOM, META |
| PPO timesteps per window | 50,000 |
| Max workers | 1 |
| Window size | 3,500 rows |
| Step size | 500 rows |
| Data interval | 1 hour |
| Walk-forward windows per ticker | 3 |

## Training Coverage

Training completed for all configured symbols and windows.

| Metric | Value |
|---|---:|
| Tickers trained | 10 |
| Windows per ticker | 3 |
| Total trained windows | 30 |

Training output folder:

`reports/backtests/ppo_walkforward_results_20260508_145432`

## Primary Findings

The run identified four symbols where PPO outperformed Buy & Hold in at least one walk-forward window.

| Symbol | Best PPO-Winning Window | Sharpe | PPO Portfolio | Buy & Hold | Drawdown % | Assessment |
|---|---:|---:|---:|---:|---:|---|
| XOM | 1000-4500 | 0.632 | 139,848.73 | 130,844.79 | 7.78 | Highest-priority follow-up candidate |
| UNH | 0-3500 | 0.658 | 114,601.32 | 65,254.99 | 3.48 | Consistent defensive candidate |
| AAPL | 0-3500 | 0.478 | 121,472.42 | 104,585.49 | 6.14 | Active candidate, less consistent across windows |
| PFE | 1000-4500 | 0.401 | 101,127.95 | 94,276.77 | 0.62 | Low-drawdown defensive candidate |

XOM was the most notable result. PPO outperformed Buy & Hold across all three XOM windows, making it the strongest follow-up candidate under the current model specification.

## Model Selection Notes

The updated selector continued to behave as intended. It prioritized PPO-winning windows where available and fell back to Sharpe ranking only when a symbol had no PPO-winning window.

AAPL remains an important validation case. The highest-Sharpe AAPL window did not outperform Buy & Hold, so the selector should continue to prefer the PPO-winning AAPL window rather than selecting on Sharpe alone.

## Signal Behavior

| Symbol / Selected Model | Signal Behavior | Interpretation |
|---|---|---|
| XOM window 3 | Active BUY/SELL behavior | Promising active candidate, but requires transaction-cost and slippage review |
| AAPL window 1 | Active BUY/SELL behavior | Active candidate, but turnover should be reviewed before paper-trading use |
| UNH window 1 | Mostly HOLD with some BUY | Defensive / capital-preservation behavior |
| PFE window 3 | Fully HOLD in the reviewed prediction file | Low-drawdown candidate, but not currently producing an active signal |
| NVDA | Mostly HOLD and weak performance | PPO continues to miss high-momentum trend behavior |
| JPM | Fully HOLD across windows | Too inactive to prioritize under the current setup |
| GE, MSFT, AMD, META | Positive or active in some windows, but generally failed to beat Buy & Hold | Not prioritized under the current specification |

## Interpretation

The run suggests that PPO performance is highly symbol-dependent under the current feature set, reward design, and action-to-signal thresholds. Expanding from five to ten symbols did not show broad generalization across the universe. Instead, the evidence points to a narrower subset of symbols where PPO behavior may be more useful.

The strongest candidates for deeper validation are XOM, UNH, AAPL, and PFE. GE, MSFT, AMD, JPM, META, and NVDA should remain secondary monitoring names until model design or selection logic improves.

## Limitations

This was a controlled validation run, not a production backtest.

Key limitations:

- The universe was limited to ten symbols.
- Each ticker used three walk-forward windows.
- PPO was compared primarily against Buy & Hold.
- Turnover, transaction-cost sensitivity, and slippage sensitivity require further review.
- XOM and AAPL showed active BUY/SELL behavior, so execution costs may materially affect realized results.
- PFE showed favorable backtest behavior but was fully HOLD in the reviewed prediction file.
- The QuantConnect external signal consumer still needs to be tested in a full LEAN workflow.

## Research Conclusion

The 10-ticker 50k run passed from an engineering and workflow perspective and produced a clearer research direction.

| Symbol | Current Assessment |
|---|---|
| XOM | Highest-priority follow-up candidate; PPO won across all three windows |
| UNH | Defensive candidate with consistent PPO outperformance |
| AAPL | Active candidate, but less consistent than XOM and UNH |
| PFE | Low-drawdown defensive candidate; signal activity requires further review |
| GE | Secondary monitoring only |
| MSFT | Secondary monitoring only |
| AMD | Secondary monitoring only |
| JPM | Secondary monitoring only |
| META | Secondary monitoring only |
| NVDA | Secondary monitoring only |

The next recommended run is a focused 150k training pass on:

`XOM, UNH, AAPL, PFE`

This will test whether the observed PPO advantage remains stable with longer training before expanding to a larger universe or moving toward deeper QuantConnect testing.