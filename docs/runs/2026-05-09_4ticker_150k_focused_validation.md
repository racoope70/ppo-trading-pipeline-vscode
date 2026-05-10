# 2026-05-09 — Four-Ticker 150k Focused PPO Validation Run

## Objective

This run focused on the four strongest candidates identified in the prior ten-ticker 50k validation run: XOM, UNH, AAPL, and PFE.

The purpose was to test whether the observed PPO advantage remained stable with longer training. This run increased PPO training from 50,000 timesteps per window to 150,000 timesteps per window while keeping the universe intentionally narrow.

This was not intended to establish production readiness. The objective was to validate whether the most promising symbols continued to show PPO outperformance before expanding to a larger universe or moving toward deeper execution testing.

## Run Configuration

| Setting | Value |
|---|---|
| Test mode | Enabled |
| Symbols | XOM, UNH, AAPL, PFE |
| PPO timesteps per window | 150,000 |
| Max workers | 1 |
| Window size | 3,500 rows |
| Step size | 500 rows |
| Data interval | 1 hour |
| Walk-forward windows per ticker | 3 |

## Training Coverage

Training completed for all configured symbols and windows.

| Metric | Value |
|---|---:|
| Tickers trained | 4 |
| Windows per ticker | 3 |
| Total trained windows | 12 |

Training output folder:

`reports/backtests/ppo_walkforward_results_20260509_172626`

The automated review helper confirmed the expected run structure:

| Check | Value |
|---|---:|
| Summary rows | 12 |
| Ticker count | 4 |
| Expected rows | 12 |

## Primary Findings

The focused 150k run showed stronger PPO performance than the prior broader 50k run. PPO outperformed Buy & Hold in 11 of 12 walk-forward windows.

| Symbol | Best PPO-Winning Window | Sharpe | PPO Portfolio | Buy & Hold | Drawdown % | Assessment |
|---|---:|---:|---:|---:|---:|---|
| UNH | 0-3500 | 0.735 | 178,521.03 | 65,254.99 | 12.91 | Strongest Sharpe result, but drawdown increased |
| XOM | 1000-4500 | 0.652 | 176,599.41 | 130,844.79 | 11.51 | Strongest consistency across all windows |
| AAPL | 500-4000 | 0.646 | 186,019.27 | 145,969.33 | 15.86 | Strong active candidate, but higher drawdown |
| PFE | 1000-4500 | 0.500 | 109,991.55 | 94,276.77 | 3.05 | Lowest-risk candidate, but lower return profile |

The most important result was that XOM continued to outperform Buy & Hold across all three windows. UNH also remained strong, although drawdown increased materially relative to the prior 50k run.

## Full Window Summary

| Symbol | Window | PPO Portfolio | Buy & Hold | Sharpe | Drawdown % | Winner |
|---|---|---:|---:|---:|---:|---|
| XOM | 0-3500 | 177,885.17 | 106,554.36 | 0.592 | 11.08 | PPO |
| XOM | 500-4000 | 184,988.37 | 102,273.24 | 0.637 | 12.16 | PPO |
| XOM | 1000-4500 | 176,599.41 | 130,844.79 | 0.652 | 11.51 | PPO |
| UNH | 0-3500 | 178,521.03 | 65,254.99 | 0.735 | 12.91 | PPO |
| UNH | 500-4000 | 132,523.30 | 68,928.84 | 0.373 | 21.82 | PPO |
| UNH | 1000-4500 | 115,279.08 | 69,365.35 | 0.362 | 11.07 | PPO |
| AAPL | 0-3500 | 152,004.43 | 104,585.49 | 0.551 | 11.40 | PPO |
| AAPL | 500-4000 | 186,019.27 | 145,969.33 | 0.646 | 15.86 | PPO |
| AAPL | 1000-4500 | 129,622.19 | 133,640.57 | 0.474 | 9.64 | Buy & Hold |
| PFE | 0-3500 | 100,571.61 | 68,060.62 | 0.070 | 2.33 | PPO |
| PFE | 500-4000 | 103,771.31 | 78,700.58 | 0.243 | 2.81 | PPO |
| PFE | 1000-4500 | 109,991.55 | 94,276.77 | 0.500 | 3.05 | PPO |

## Model Selection Notes

The selector continued to behave as intended. For each symbol, it selected the strongest PPO-winning candidate based on the available summary results.

Selected models used for the latest QuantConnect signal export:

| Symbol | Selected Prefix | Latest Signal | Confidence | Notes |
|---|---|---|---:|---|
| XOM | ppo_XOM_window3 | BUY | 1.0000 | Strong active signal |
| UNH | ppo_UNH_window1 | SELL | 0.5614 | Active risk-off / short-side signal |
| AAPL | ppo_AAPL_window2 | BUY | 1.0000 | Strong active signal |
| PFE | ppo_PFE_window3 | HOLD | 0.0909 | Low-conviction / defensive signal |

The QuantConnect export completed successfully and produced a 24-hour signal validity window.

Signal export folder:

`reports/backtests/quantconnect_signals_20260509_201621`

## Signal Behavior

Signal counts showed that the longer 150k training run produced materially more active models, especially for XOM and AAPL.

| Symbol / Window | Signal Behavior | Interpretation |
|---|---|---|
| XOM window 1 | BUY 1,668 / SELL 1,586 / HOLD 192 | Very active, high-turnover behavior |
| XOM window 2 | BUY 1,746 / SELL 1,505 / HOLD 195 | Very active, high-turnover behavior |
| XOM window 3 | BUY 1,707 / SELL 1,412 / HOLD 327 | Selected model; strong but requires cost review |
| AAPL window 1 | BUY 1,571 / SELL 1,394 / HOLD 481 | Active, high-turnover behavior |
| AAPL window 2 | BUY 1,829 / SELL 1,339 / HOLD 278 | Selected model; strongest AAPL result but high turnover |
| UNH window 1 | BUY 1,713 / SELL 450 / HOLD 1,283 | Selected model; active but less two-sided than XOM/AAPL |
| PFE window 3 | BUY 1,046 / SELL 9 / HOLD 2,391 | Selected model; mostly defensive with limited sell activity |

The key change from the prior run is that the strongest models became more aggressive. XOM and AAPL in particular now show frequent BUY and SELL signals, which means transaction costs, slippage, and turnover must be evaluated before considering deployment.

## Interpretation

The focused 150k run strengthened the case that PPO behavior is most useful on a narrower set of symbols. XOM remained the cleanest candidate because PPO beat Buy & Hold across all three windows in both the 50k and 150k runs.

UNH also remained strong, but the larger drawdowns in the 150k run suggest that the model may be taking more risk than in the prior validation. AAPL improved materially and produced one of the strongest final portfolio values, but one window still failed to beat Buy & Hold. PFE remained the lowest-volatility candidate, with modest returns and limited drawdown.

Overall, this run supports continued research on the focused universe, but it also shifts the next research question from model selection to execution realism.

## Limitations

This was still a controlled validation run, not a production backtest.

Key limitations:

- The universe was limited to four symbols.
- Each ticker used three walk-forward windows.
- PPO was still compared primarily against Buy & Hold.
- The run does not yet include a full transaction-cost sensitivity study.
- XOM and AAPL showed high BUY/SELL frequency, so execution costs may materially reduce realized performance.
- UNH showed stronger returns but also higher drawdown than the prior run.
- PFE remained low drawdown, but signal activity was weaker than XOM, AAPL, and UNH.
- QuantConnect signal export was validated, but a full LEAN execution/backtest workflow still needs to be tested.

## Research Conclusion

The focused four-ticker 150k run passed from an engineering and workflow perspective and produced stronger PPO results than the prior 50k validation.

Current assessment:

| Symbol | Current Assessment |
|---|---|
| XOM | Highest-priority candidate; consistent PPO outperformance across all windows |
| UNH | Strong Sharpe and return profile, but drawdown needs review |
| AAPL | Strong active candidate, but less consistent than XOM |
| PFE | Defensive candidate with low drawdown and lower return profile |

The next research gate should not be more ticker expansion yet. The next step should be execution-cost and turnover analysis on the focused candidates, especially XOM and AAPL.

Recommended next step:

`Run turnover, slippage, and transaction-cost sensitivity analysis for XOM, UNH, AAPL, and PFE before expanding the universe or moving toward paper-trading deployment.`