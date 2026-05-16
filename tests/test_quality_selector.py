import pandas as pd

from src.select_quality_tickers import apply_quality_filter, select_best_by_ticker


def sample_execution_realism() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Ticker": "AAPL",
                "Window": "0-3500",
                "Scenario": "moderate",
                "Execution_Winner": "PPO",
                "Execution_Edge_vs_BuyHold": 10_000,
                "Final_Equity": 120_000,
                "Sharpe_Est": 0.50,
                "Max_Drawdown_%": 10.0,
                "Total_Turnover": 100.0,
                "Trade_Events": 10,
                "Total_Cost_$": 100.0,
            },
            {
                "Ticker": "AAPL",
                "Window": "500-4000",
                "Scenario": "moderate",
                "Execution_Winner": "PPO",
                "Execution_Edge_vs_BuyHold": 5_000,
                "Final_Equity": 110_000,
                "Sharpe_Est": 0.40,
                "Max_Drawdown_%": 9.0,
                "Total_Turnover": 80.0,
                "Trade_Events": 8,
                "Total_Cost_$": 80.0,
            },
            {
                "Ticker": "META",
                "Window": "1000-4500",
                "Scenario": "moderate",
                "Execution_Winner": "Buy & Hold",
                "Execution_Edge_vs_BuyHold": -1_000,
                "Final_Equity": 99_000,
                "Sharpe_Est": -0.20,
                "Max_Drawdown_%": 12.0,
                "Total_Turnover": 90.0,
                "Trade_Events": 9,
                "Total_Cost_$": 90.0,
            },
            {
                "Ticker": "PFE",
                "Window": "0-3500",
                "Scenario": "moderate",
                "Execution_Winner": "PPO",
                "Execution_Edge_vs_BuyHold": 2_000,
                "Final_Equity": 102_000,
                "Sharpe_Est": -1.00,
                "Max_Drawdown_%": 8.0,
                "Total_Turnover": 70.0,
                "Trade_Events": 7,
                "Total_Cost_$": 70.0,
            },
            {
                "Ticker": "AAPL",
                "Window": "0-3500",
                "Scenario": "harsh",
                "Execution_Winner": "Buy & Hold",
                "Execution_Edge_vs_BuyHold": -5_000,
                "Final_Equity": 95_000,
                "Sharpe_Est": -0.30,
                "Max_Drawdown_%": 15.0,
                "Total_Turnover": 110.0,
                "Trade_Events": 11,
                "Total_Cost_$": 110.0,
            },
        ]
    )


def test_select_best_by_ticker_uses_requested_scenario_and_best_edge():
    best = select_best_by_ticker(sample_execution_realism(), scenario="moderate")

    assert best["Ticker"].tolist() == ["AAPL", "META", "PFE"]

    aapl = best[best["Ticker"] == "AAPL"].iloc[0]
    assert aapl["Window"] == "0-3500"
    assert aapl["Prefix"] == "ppo_AAPL_window1"
    assert aapl["Execution_Edge_vs_BuyHold"] == 10_000


def test_apply_default_quality_filter():
    best = select_best_by_ticker(sample_execution_realism(), scenario="moderate")

    filtered = apply_quality_filter(
        best=best,
        min_edge=0.0,
        require_ppo_winner=True,
        min_sharpe=None,
        max_drawdown=None,
        max_turnover=None,
    )

    selected = filtered[filtered["Quality_Pass"]]["Ticker"].tolist()
    excluded = filtered[~filtered["Quality_Pass"]]["Ticker"].tolist()

    assert selected == ["AAPL", "PFE"]
    assert excluded == ["META"]

    meta_reason = filtered[filtered["Ticker"] == "META"]["Quality_Reason"].iloc[0]
    assert "edge <= 0" in meta_reason
    assert "winner != PPO" in meta_reason


def test_apply_min_sharpe_filter_excludes_negative_sharpe():
    best = select_best_by_ticker(sample_execution_realism(), scenario="moderate")

    filtered = apply_quality_filter(
        best=best,
        min_edge=0.0,
        require_ppo_winner=True,
        min_sharpe=0.0,
        max_drawdown=None,
        max_turnover=None,
    )

    selected = filtered[filtered["Quality_Pass"]]["Ticker"].tolist()
    excluded = filtered[~filtered["Quality_Pass"]]["Ticker"].tolist()

    assert selected == ["AAPL"]
    assert set(excluded) == {"META", "PFE"}

    pfe_reason = filtered[filtered["Ticker"] == "PFE"]["Quality_Reason"].iloc[0]
    assert "sharpe <= 0" in pfe_reason