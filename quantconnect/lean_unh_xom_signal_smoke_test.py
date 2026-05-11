# region imports
from AlgorithmImports import *
import json
from datetime import timedelta
# endregion


class UnhXomSignalSmokeTest(QCAlgorithm):
    """
    Minimal QuantConnect/LEAN smoke test for UNH and XOM PPO signals.

    Purpose:
    - Confirm LEAN can add UNH and XOM.
    - Confirm a PPO-style signal payload can be parsed.
    - Reject stale signals.
    - Map BUY/SELL/HOLD into target portfolio weights.
    - Log intended holdings before moving to a fuller backtest.

    This is not a production strategy.
    """

    def Initialize(self):
        self.SetStartDate(2026, 5, 8)
        self.SetEndDate(2026, 5, 11)
        self.SetCash(100000)

        self.symbols = {
            "UNH": self.AddEquity("UNH", Resolution.Hour).Symbol,
            "XOM": self.AddEquity("XOM", Resolution.Hour).Symbol,
        }

        # Keep this conservative for smoke testing.
        self.max_abs_weight = 0.25
        self.min_confidence = 0.10
        self.max_signal_age = timedelta(hours=24)

        # Paste the latest exported signal payload here.
        # Later, this can be replaced with ObjectStore loading.
        self.signal_payload = """
{
  "generated_utc": "2026-05-11T00:45:10.051487+00:00",
  "valid_until_utc": "2026-05-12T00:45:10.051487+00:00",
  "producer": "ppo_research_pipeline",
  "interval": "1h",
  "models": [
    {
      "symbol": "UNH",
      "prefix": "ppo_UNH_window1",
      "timestamp": "2026-05-08 19:30:00+00:00",
      "price": 379.82000732421875,
      "signal": "SELL",
      "confidence": 0.5823357701301575,
      "action": -0.5823357701301575
    },
    {
      "symbol": "XOM",
      "prefix": "ppo_XOM_window2",
      "timestamp": "2026-05-08 19:30:00+00:00",
      "price": 144.39999389648438,
      "signal": "BUY",
      "confidence": 1.0,
      "action": 1.0
    }
  ]
}
"""

        self.signals = self._load_signals_from_payload(self.signal_payload)
        self.last_trade_date = None

        self.Debug("UNH/XOM PPO signal smoke test initialized.")
        self.Debug(f"Loaded signal symbols: {list(self.signals.keys())}")

    def OnData(self, data: Slice):
        # Run once per trading day for smoke testing.
        if self.last_trade_date == self.Time.date():
            return

        self.last_trade_date = self.Time.date()

        for ticker, symbol in self.symbols.items():
            if symbol not in data.Bars:
                self.Debug(f"{self.Time} | {ticker} | no hourly bar available")
                continue

            signal_row = self.signals.get(ticker)

            if signal_row is None:
                self.Debug(f"{self.Time} | {ticker} | no signal found")
                continue

            if not self._signal_is_valid(signal_row):
                self.Debug(f"{self.Time} | {ticker} | stale or invalid signal rejected")
                self.SetHoldings(symbol, 0)
                continue

            signal = str(signal_row.get("signal", "HOLD")).upper()
            confidence = float(signal_row.get("confidence", 0.0))
            action = float(signal_row.get("action", 0.0))
            prefix = str(signal_row.get("prefix", ""))

            target_weight = self._map_signal_to_target_weight(
                signal=signal,
                confidence=confidence,
                action=action,
            )

            self.Debug(
                f"{self.Time} | {ticker} | prefix={prefix} | "
                f"signal={signal} | confidence={confidence:.4f} | "
                f"action={action:.4f} | target_weight={target_weight:.4f}"
            )

            # For smoke test, this can be left active because this is LEAN backtest only.
            # If you want log-only behavior first, comment this line out.
            self.SetHoldings(symbol, target_weight)

    def _load_signals_from_payload(self, payload: str) -> dict:
        try:
            parsed = json.loads(payload)
        except Exception as exc:
            self.Debug(f"Signal JSON parse failed: {exc}")
            return {}

        output = {}

        for row in parsed.get("models", []):
            symbol = str(row.get("symbol", "")).upper()

            if symbol in ["UNH", "XOM"]:
                output[symbol] = row

        return output

    def _signal_is_valid(self, signal_row: dict) -> bool:
        timestamp_raw = signal_row.get("timestamp")

        if timestamp_raw is None:
            return False

        try:
            signal_time = datetime.strptime(
                str(timestamp_raw).replace("+00:00", ""),
                "%Y-%m-%d %H:%M:%S",
            )
        except Exception:
            return False

        signal_age = self.Time - signal_time

        if signal_age < timedelta(0):
            # Signal timestamp is ahead of current backtest time.
            return False

        if signal_age > self.max_signal_age:
            return False

        return True

    def _map_signal_to_target_weight(
        self,
        signal: str,
        confidence: float,
        action: float,
    ) -> float:
        if confidence < self.min_confidence:
            return 0.0

        clipped_action = max(min(action, 1.0), -1.0)

        if signal == "BUY":
            return min(abs(clipped_action), self.max_abs_weight)

        if signal == "SELL":
            return -min(abs(clipped_action), self.max_abs_weight)

        return 0.0