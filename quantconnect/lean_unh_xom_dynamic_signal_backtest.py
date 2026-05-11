# region imports
from AlgorithmImports import *
import json
from datetime import datetime, timedelta
# endregion


class UnhXomDynamicSignalBacktest(QCAlgorithm):
    """
    Full LEAN backtest using precomputed PPO signals for UNH and XOM.

    This test does not run PPO inference inside QuantConnect.
    It reads precomputed dynamic signals from Object Store and applies them
    through time using set_holdings().

    Required Object Store key:
        unh_xom_dynamic_signals.json

    Expected payload shape:
        {
          "producer": "ppo_research_pipeline",
          "interval": "1h",
          "symbols": ["UNH", "XOM"],
          "signals": [
            {
              "timestamp": "2026-02-10T09:30:00+00:00",
              "symbol": "UNH",
              "prefix": "ppo_UNH_window1",
              "signal": "SELL",
              "confidence": 0.5823,
              "action": -0.5823,
              "target_weight": -0.25
            }
          ]
        }
    """

    def initialize(self):
        self.set_start_date(2026, 2, 10)
        self.set_end_date(2026, 2, 13)
        self.set_cash(100000)

        self.object_store_key = "unh_xom_dynamic_signals.json"

        self.symbols = {
            "UNH": self.add_equity("UNH", Resolution.HOUR).symbol,
            "XOM": self.add_equity("XOM", Resolution.HOUR).symbol,
        }

        self.max_abs_weight = 0.25
        self.min_confidence = 0.10
        self.max_signal_age = timedelta(hours=2)

        # Avoid repeated same-target order submissions.
        self.last_target_by_ticker = {
            "UNH": None,
            "XOM": None,
        }

        self.last_signal_time_by_ticker = {
            "UNH": None,
            "XOM": None,
        }

        self.payload = self._load_payload_from_object_store()
        self.signals_by_symbol = self._build_signal_index(self.payload)

        self.debug("UNH/XOM dynamic signal backtest initialized.")
        self.debug(f"Object Store key: {self.object_store_key}")
        self.debug(f"Loaded symbols: {list(self.signals_by_symbol.keys())}")

        for ticker in ["UNH", "XOM"]:
            count = len(self.signals_by_symbol.get(ticker, []))
            self.debug(f"{ticker} | loaded signal rows: {count}")

    def on_data(self, data: Slice):
        for ticker, symbol in self.symbols.items():
            signal_row = self._get_latest_valid_signal(ticker)

            if signal_row is None:
                self.debug(f"{self.time} | {ticker} | no valid dynamic signal")
                continue

            signal = str(signal_row.get("signal", "HOLD")).upper()
            confidence = float(signal_row.get("confidence", 0.0))
            action = float(signal_row.get("action", 0.0))
            prefix = str(signal_row.get("prefix", ""))
            signal_time = signal_row.get("_parsed_time")

            target_weight = self._map_signal_to_target_weight(
                signal=signal,
                confidence=confidence,
                action=action,
                payload_target=signal_row.get("target_weight", None),
            )

            # Prevent excessive repeated orders when the target has not changed.
            prior_target = self.last_target_by_ticker.get(ticker)

            if prior_target is not None and abs(prior_target - target_weight) < 0.0001:
                continue

            self.debug(
                f"{self.time} | {ticker} | signal_time={signal_time} | "
                f"prefix={prefix} | signal={signal} | confidence={confidence:.4f} | "
                f"action={action:.4f} | target_weight={target_weight:.4f}"
            )

            self.set_holdings(symbol, target_weight)
            self.last_target_by_ticker[ticker] = target_weight
            self.last_signal_time_by_ticker[ticker] = signal_time

    def _load_payload_from_object_store(self) -> dict:
        key = self.object_store_key

        if not self.object_store.contains_key(key):
            self.debug(f"Object Store key not found: {key}")
            return {}

        raw = self.object_store.read(key)

        if raw is None or len(raw) == 0:
            self.debug(f"Object Store payload empty: {key}")
            return {}

        try:
            payload = json.loads(raw)
        except Exception as exc:
            self.debug(f"Failed to parse dynamic signal JSON: {exc}")
            return {}

        self.debug(f"Loaded dynamic signal payload from Object Store key: {key}")
        return payload

    def _build_signal_index(self, payload: dict) -> dict:
        output = {
            "UNH": [],
            "XOM": [],
        }

        rows = payload.get("signals", [])

        if not rows:
            self.debug("No signal rows found in dynamic payload.")
            return output

        for row in rows:
            ticker = str(row.get("symbol", "")).upper()

            if ticker not in output:
                continue

            parsed_time = self._parse_signal_time(row.get("timestamp"))

            if parsed_time is None:
                self.debug(f"{ticker} | skipped row with invalid timestamp: {row.get('timestamp')}")
                continue

            row["_parsed_time"] = parsed_time
            output[ticker].append(row)

        for ticker in output:
            output[ticker] = sorted(output[ticker], key=lambda item: item["_parsed_time"])

        return output

    def _parse_signal_time(self, timestamp_raw):
        if timestamp_raw is None:
            return None

        text = str(timestamp_raw).replace("T", " ").replace("+00:00", "")

        try:
            return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
        except Exception:
            return None

    def _get_latest_valid_signal(self, ticker: str):
        rows = self.signals_by_symbol.get(ticker, [])

        if not rows:
            return None

        latest = None

        for row in rows:
            signal_time = row["_parsed_time"]

            if signal_time <= self.time:
                latest = row
            else:
                break

        if latest is None:
            return None

        signal_age = self.time - latest["_parsed_time"]

        if signal_age < timedelta(0):
            return None

        if signal_age > self.max_signal_age:
            return None

        return latest

    def _map_signal_to_target_weight(
        self,
        signal: str,
        confidence: float,
        action: float,
        payload_target,
    ) -> float:
        if confidence < self.min_confidence:
            return 0.0

        # Prefer the precomputed target_weight from VS Code if present.
        if payload_target is not None:
            try:
                target = float(payload_target)
                return max(min(target, self.max_abs_weight), -self.max_abs_weight)
            except Exception:
                pass

        clipped_action = max(min(action, 1.0), -1.0)

        if signal == "BUY":
            return min(abs(clipped_action), self.max_abs_weight)

        if signal == "SELL":
            return -min(abs(clipped_action), self.max_abs_weight)

        return 0.0