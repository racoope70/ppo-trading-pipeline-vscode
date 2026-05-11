# region imports
from AlgorithmImports import *
import json
from datetime import datetime, timedelta
# endregion


class UnhXomObjectStoreSignalSmokeTest(QCAlgorithm):

    def initialize(self):
        self.set_start_date(2026, 5, 8)
        self.set_end_date(2026, 5, 11)
        self.set_cash(100000)

        # Keep True for this smoke test because the signal timestamp
        # may not align with the backtest clock.
        self.bypass_stale_check = True

        self.symbols = {
            "UNH": self.add_equity("UNH", Resolution.HOUR).symbol,
            "XOM": self.add_equity("XOM", Resolution.HOUR).symbol,
        }

        self.max_abs_weight = 0.25
        self.min_confidence = 0.10
        self.max_signal_age = timedelta(hours=72)

        self.signal_payload = self._load_signal_payload_from_object_store()
        self.signals = self._load_signals_from_payload(self.signal_payload)
        self.last_trade_date = None

        self.debug("UNH/XOM Object Store signal smoke test initialized.")
        self.debug(f"Loaded signal symbols: {list(self.signals.keys())}")

    def on_data(self, data: Slice):
        if self.last_trade_date == self.time.date():
            return

        self.last_trade_date = self.time.date()

        for ticker, symbol in self.symbols.items():
            if symbol not in data.bars:
                self.debug(f"{self.time} | {ticker} | no hourly bar available")
                continue

            signal_row = self.signals.get(ticker)

            if signal_row is None:
                self.debug(f"{self.time} | {ticker} | no signal found")
                continue

            if not self._signal_is_valid(signal_row):
                if not self.bypass_stale_check:
                    self.debug(f"{self.time} | {ticker} | stale or invalid signal rejected")
                    self.set_holdings(symbol, 0)
                    continue

                self.debug(
                    f"{self.time} | {ticker} | signal timestamp would be stale/invalid, "
                    "but bypassing freshness check for smoke test"
                )

            signal = str(signal_row.get("signal", "HOLD")).upper()
            confidence = float(signal_row.get("confidence", 0.0))
            action = float(signal_row.get("action", 0.0))
            prefix = str(signal_row.get("prefix", ""))

            target_weight = self._map_signal_to_target_weight(signal, confidence, action)

            self.debug(
                f"{self.time} | {ticker} | prefix={prefix} | "
                f"signal={signal} | confidence={confidence:.4f} | "
                f"action={action:.4f} | target_weight={target_weight:.4f}"
            )

            self.set_holdings(symbol, target_weight)

    def _load_signal_payload_from_object_store(self) -> str:
        key = "signals/live_signals.json"

        if not self.object_store.contains_key(key):
            self.debug(f"Object Store key not found: {key}")
            return ""

        payload = self.object_store.read(key)

        self.debug(f"Loaded signal payload from Object Store key: {key}")
        return payload

    def _load_signals_from_payload(self, payload: str) -> dict:
        if not payload:
            self.debug("Empty signal payload.")
            return {}

        try:
            parsed = json.loads(payload)
        except Exception as exc:
            self.debug(f"Signal JSON parse failed: {exc}")
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

        signal_age = self.time - signal_time

        if signal_age < timedelta(0):
            return False

        if signal_age > self.max_signal_age:
            return False

        return True

    def _map_signal_to_target_weight(self, signal: str, confidence: float, action: float) -> float:
        if confidence < self.min_confidence:
            return 0.0

        clipped_action = max(min(action, 1.0), -1.0)

        if signal == "BUY":
            return min(abs(clipped_action), self.max_abs_weight)

        if signal == "SELL":
            return -min(abs(clipped_action), self.max_abs_weight)

        return 0.0