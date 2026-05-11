# region imports
from AlgorithmImports import *
# endregion


class UnhXomDataAvailabilityCheck(QCAlgorithm):
    """
    Data availability diagnostic for UNH and XOM.

    Purpose:
    - Confirm whether QuantConnect/LEAN is feeding hourly bars for UNH and XOM
      beyond 2026-02-10.
    - No signals.
    - No Object Store.
    - No orders.
    - No strategy logic.

    This isolates whether the short dynamic-signal test was caused by data
    availability or by the trading/signal code.
    """

    def initialize(self):
        self.set_start_date(2026, 2, 10)
        self.set_end_date(2026, 3, 20)
        self.set_cash(100000)

        self.symbols = {
            "UNH": self.add_equity("UNH", Resolution.HOUR).symbol,
            "XOM": self.add_equity("XOM", Resolution.HOUR).symbol,
        }

        self.bar_counts = {
            "UNH": 0,
            "XOM": 0,
        }

        self.first_bar_time = {
            "UNH": None,
            "XOM": None,
        }

        self.last_bar_time = {
            "UNH": None,
            "XOM": None,
        }

        self.unique_dates = {
            "UNH": set(),
            "XOM": set(),
        }

        self.debug("UNH/XOM hourly data availability check initialized.")
        self.debug("Date range: 2026-02-10 through 2026-03-20")
        self.debug("No signals, no Object Store, no orders.")

    def on_data(self, data: Slice):
        for ticker, symbol in self.symbols.items():
            if symbol not in data.bars:
                return

            self.bar_counts[ticker] += 1

            if self.first_bar_time[ticker] is None:
                self.first_bar_time[ticker] = self.time

            self.last_bar_time[ticker] = self.time
            self.unique_dates[ticker].add(str(self.time.date()))

            # Log one checkpoint per symbol per 10:00 bar.
            if self.time.hour == 10:
                self.debug(
                    f"DATE CHECK | {ticker} | time={self.time} | "
                    f"bar_count={self.bar_counts[ticker]}"
                )

    def on_end_of_algorithm(self):
        self.debug("UNH/XOM data availability check completed.")

        for ticker in ["UNH", "XOM"]:
            dates = sorted(list(self.unique_dates[ticker]))

            self.debug(
                f"{ticker} SUMMARY | bars={self.bar_counts[ticker]} | "
                f"first_bar={self.first_bar_time[ticker]} | "
                f"last_bar={self.last_bar_time[ticker]} | "
                f"unique_trading_dates={len(dates)}"
            )

            if dates:
                self.debug(f"{ticker} FIRST_DATES | {dates[:5]}")
                self.debug(f"{ticker} LAST_DATES | {dates[-5:]}")
            else:
                self.debug(f"{ticker} had no bars.")