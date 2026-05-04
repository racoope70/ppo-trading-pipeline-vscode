from AlgorithmImports import *  # noqa

from collections import deque
import json
import math
from datetime import datetime, timezone, timedelta


class ExternalSignalConsumer(QCAlgorithm):
    """
    Consume external PPO signal JSON and map BUY / SELL / HOLD signals
    into long-only target portfolio weights.

    Expected JSON shape:

    {
      "generated_utc": "...",
      "valid_until_utc": "...",
      "producer": "ppo_research_pipeline",
      "interval": "1h",
      "models": [
        {
          "symbol": "GE",
          "prefix": "ppo_GE_window1",
          "signal": "BUY",
          "confidence": 0.72,
          "action": 0.18,
          "p_long": 0.56,
          "p_short": 0.44
        }
      ]
    }

    QuantConnect project parameters:

      SignalsUrl       = raw JSON URL
      Symbols          = GE, UNH, GE,UNH, or AUTO
      Mode             = json-live
      PollingMinutes   = 60
      SizingMode       = threshold or linear
      WeightCap        = 0.60
      ConfidenceFloor  = 0.55
    """

    def Initialize(self):
        # Backtest window.
        # For live/paper trading, omit SetEndDate or update these dates.
        self.SetStartDate(2024, 1, 1)
        self.SetEndDate(2024, 12, 31)
        self.SetCash(100000)

        gp = self.GetParameter

        self.mode = (gp("Mode") or "json-live").strip().lower()
        self.json_url = (gp("SignalsUrl") or "").strip()
        self.symbols_param = (gp("Symbols") or "GE").strip()
        self.poll_minutes = int(gp("PollingMinutes") or 60)

        self.sizing_mode = (gp("SizingMode") or "threshold").strip().lower()
        self.w_cap = float(gp("WeightCap") or 0.60)
        self.conf_floor = float(gp("ConfidenceFloor") or 0.55)

        if not self.json_url:
            raise ValueError(
                "Parameter 'SignalsUrl' not provided. "
                "Set it in Project → Parameters."
            )

        # Broker/slippage assumptions for backtesting.
        self.SetSecurityInitializer(
            lambda security: security.SetSlippageModel(ConstantSlippageModel(0.01))
        )
        self.SetBrokerageModel(
            BrokerageName.INTERACTIVE_BROKERS_BROKERAGE,
            AccountType.MARGIN,
        )

        # Long-only risk/execution guards.
        self.UniverseSettings.Leverage = 1.0
        self.Settings.FreePortfolioValuePercentage = 0.05
        self.Settings.MinimumOrderMarginPortfolioPercentage = 0.0
        self.Settings.RebalancePortfolioOnSecurityChanges = False

        # Symbols use hourly resolution to match the current VS Code producer.
        self.symbols = {}
        requested = [
            symbol.strip().upper()
            for symbol in self.symbols_param.split(",")
            if symbol.strip()
        ]

        if requested and requested != ["AUTO"]:
            for ticker in requested:
                self.symbols[ticker] = self.AddEquity(ticker, Resolution.HOUR).Symbol

        self._auto_symbols = requested == ["AUTO"]
        self._added_from_feed = set()

        # Poll external JSON on the requested schedule.
        self.Schedule.On(
            self.DateRules.EveryDay(),
            self.TimeRules.Every(timedelta(minutes=self.poll_minutes)),
            self.PollJsonAndTrade,
        )

        self.SetWarmup(5, Resolution.HOUR)

        # Benchmark/risk plots.
        self.spy = self.AddEquity("SPY", Resolution.DAILY).Symbol
        self.SetBenchmark(self.spy)

        self.Schedule.On(
            self.DateRules.EveryDay(self.spy),
            self.TimeRules.AfterMarketClose(self.spy, 1),
            self.PushDailyMetrics,
        )

        # State.
        self.fill_count = 0
        self.last_equity = float(self.Portfolio.TotalPortfolioValue)
        self.daily_returns = []
        self.valid_until_epoch = None
        self.last_poll_minute = None
        self.last_logged_sig = {}

        self._order_ids = set()
        self._fills = 0
        self._p_rets = deque(maxlen=63)
        self._b_rets = deque(maxlen=63)
        self._last_bench_close = None
        self._last_eod_date = None

        self.Log(
            f"Params OK | mode={self.mode} "
            f"poll={self.poll_minutes}m "
            f"sizing={self.sizing_mode} "
            f"cap={self.w_cap:.2f} "
            f"floor={self.conf_floor:.2f} "
            f"symbols={self.symbols_param} "
            f"url={self.json_url[:60]}..."
        )

    def PollJsonAndTrade(self):
        """Poll JSON endpoint and rebalance portfolio from signals."""
        if self.IsWarmingUp:
            return

        cur_minute = int(self.Time.timestamp()) // 60
        if self.last_poll_minute == cur_minute:
            return

        self.last_poll_minute = cur_minute

        raw = self.DownloadSignalJson()

        if not raw:
            if cur_minute % 10 == 0:
                self.Log(f"[WARN] Empty response from endpoint: {self.json_url[:80]}...")
            return

        data = self.ParseSignalPayload(raw)

        if data is None:
            return

        if self.IsStalePayload(data):
            if cur_minute % 10 == 0:
                self.Log(f"[STALE] now>{data.get('valid_until_utc')}, skipping")
            return

        models = data.get("models") or []
        by_symbol = self.MapModelsBySymbol(models)

        self.SubscribeAutoSymbols(by_symbol)

        if not self.symbols:
            self.Log("[WARN] No symbols to act on yet.")
            return

        weights, counts = self.BuildTargetWeights(by_symbol)

        if not weights:
            return

        weights = self.NormalizeWeights(weights)

        targets = [
            PortfolioTarget(symbol, weight)
            for symbol, weight in weights.items()
        ]

        self.SetHoldings(targets)

        self.Log(
            f"Rebalance: buys={counts['buy']}, "
            f"sells={counts['sell']}, "
            f"holds={counts['hold']}, "
            f"gross={sum(max(0.0, w) for w in weights.values()):.2f}"
        )

    def DownloadSignalJson(self):
        """Download signal JSON with cache-buster to avoid stale CDN response."""
        base = self.json_url
        separator = "&" if "?" in base else "?"
        url = f"{base}{separator}t={int(self.UtcTime.timestamp())}"

        return self.Download(url)

    def ParseSignalPayload(self, raw):
        """Parse and validate downloaded JSON text."""
        stripped = raw.lstrip()

        if not (stripped.startswith("{") or stripped.startswith("[")):
            snippet = raw[:200].replace("\n", " ").replace("\r", " ")
            self.Log(
                f"[WARN] Non-JSON response ({len(raw)} bytes) "
                f"from {self.json_url[:80]}... sample: {snippet}"
            )
            return None

        try:
            return json.loads(raw)
        except Exception as error:
            self.Log(f"[WARN] JSON parse error: {error}; first bytes: {raw[:120]!r}")
            return None

    def IsStalePayload(self, data):
        """Return True if JSON signal payload is stale."""
        valid_until = self.ParseUtcAny(
            data.get("valid_until_utc") or data.get("valid_until")
        )

        self.valid_until_epoch = self.ToUtcEpoch(valid_until) if valid_until else None

        if self.mode == "json-live" and self.valid_until_epoch:
            return self.ToUtcEpoch(self.UtcTime) > self.valid_until_epoch

        return False

    def MapModelsBySymbol(self, models):
        """Map model payloads by uppercase ticker."""
        by_symbol = {}

        for model in models:
            ticker = (model.get("symbol") or "").upper()
            if ticker:
                by_symbol[ticker] = model

        return by_symbol

    def SubscribeAutoSymbols(self, by_symbol):
        """Subscribe symbols dynamically when Symbols=AUTO."""
        if not self._auto_symbols:
            return

        for ticker in by_symbol.keys():
            if ticker not in self.symbols and ticker not in self._added_from_feed:
                self.symbols[ticker] = self.AddEquity(ticker, Resolution.HOUR).Symbol
                self._added_from_feed.add(ticker)
                self.Log(f"[AUTO] Subscribed {ticker} from feed")

    def BuildTargetWeights(self, by_symbol):
        """Build target long-only weights from JSON signals."""
        weights = {}
        counts = {
            "buy": 0,
            "sell": 0,
            "hold": 0,
        }

        for ticker, symbol in self.symbols.items():
            model_signal = by_symbol.get(ticker)

            if not model_signal or model_signal.get("error"):
                counts["hold"] += 1
                weights[symbol] = 0.0
                continue

            security = self.Securities[symbol]

            if (
                not security.HasData
                or security.Price <= 0
                or not security.Exchange.ExchangeOpen
            ):
                counts["hold"] += 1
                weights[symbol] = 0.0
                continue

            signal = (model_signal.get("signal") or "").upper()
            confidence = self.ExtractConfidence(model_signal)

            if signal == "BUY":
                weights[symbol] = self.SizeBuySignal(confidence)
                counts["buy"] += 1

            elif signal == "SELL":
                weights[symbol] = 0.0
                counts["sell"] += 1

            else:
                weights[symbol] = 0.0
                counts["hold"] += 1

            if self.last_logged_sig.get(ticker) != signal:
                self.last_logged_sig[ticker] = signal
                self.Log(f"{ticker}: {signal} (conf={confidence:.2f})")

        return weights, counts

    def ExtractConfidence(self, model_signal):
        """Extract confidence from signal payload."""
        confidence = model_signal.get("confidence")

        if confidence is None:
            action = model_signal.get("action")
            if action is not None:
                confidence = abs(float(action))
            else:
                confidence = float(model_signal.get("p_long") or 0.0)

        confidence = float(confidence or 0.0)

        return max(0.0, min(1.0, confidence))

    def SizeBuySignal(self, confidence):
        """Convert a BUY confidence into a long-only target weight."""
        if self.sizing_mode == "linear":
            weight = self.w_cap * confidence
        else:
            if confidence >= self.conf_floor:
                weight = self.w_cap * (
                    (confidence - self.conf_floor)
                    / max(1.0 - self.conf_floor, 1e-9)
                )
            else:
                weight = 0.0

        return max(0.0, min(self.w_cap, weight))

    def NormalizeWeights(self, weights):
        """Scale target weights to preserve cash buffer."""
        cap = 1.0 - self.Settings.FreePortfolioValuePercentage
        gross = sum(max(0.0, weight) for weight in weights.values())

        if gross > cap and gross > 0:
            scale = cap / gross
            for symbol in list(weights):
                weights[symbol] *= scale

        return weights

    def OnOrderEvent(self, orderEvent):
        """Track order and fill statistics."""
        self._order_ids.add(orderEvent.OrderId)

        if orderEvent.Status == OrderStatus.Filled:
            self._fills += 1

        if orderEvent.Status != OrderStatus.Filled:
            return

        self.fill_count += 1
        self.Plot("Execs", "Fills", self.fill_count)

        closed = list(self.TradeBuilder.ClosedTrades)
        wins = sum(1 for trade in closed if trade.ProfitLoss > 0)
        losses = sum(1 for trade in closed if trade.ProfitLoss <= 0)

        self.Plot("Execs", "ClosedWins", wins)
        self.Plot("Execs", "ClosedLosses", losses)

    def OnEndOfDay(self, symbol):
        """Track portfolio and benchmark returns once per day."""
        if symbol != self.spy:
            return

        current_date = self.Time.date()

        if self._last_eod_date == current_date:
            return

        self._last_eod_date = current_date

        current_equity = float(self.Portfolio.TotalPortfolioValue)
        portfolio_return = 0.0

        if self.last_equity > 0:
            portfolio_return = (current_equity / self.last_equity) - 1.0
            self.daily_returns.append(portfolio_return)

            if len(self.daily_returns) > 400:
                self.daily_returns = self.daily_returns[-300:]

        self.last_equity = current_equity

        benchmark_close = float(self.Securities[self.spy].Close)
        benchmark_return = (
            0.0
            if self._last_bench_close in (None, 0)
            else (benchmark_close / self._last_bench_close) - 1.0
        )

        self._last_bench_close = benchmark_close

        self._p_rets.append(portfolio_return)
        self._b_rets.append(benchmark_return)

        if len(self._b_rets) >= 20:
            beta = self.CalculateBeta()
            self.Plot("Risk", "Beta(63d)", beta)

    def CalculateBeta(self):
        """Calculate rolling beta versus benchmark returns."""
        mean_portfolio = sum(self._p_rets) / len(self._p_rets)
        mean_benchmark = sum(self._b_rets) / len(self._b_rets)

        covariance = sum(
            (portfolio_return - mean_portfolio)
            * (benchmark_return - mean_benchmark)
            for portfolio_return, benchmark_return in zip(self._p_rets, self._b_rets)
        ) / max(len(self._b_rets) - 1, 1)

        variance = sum(
            (benchmark_return - mean_benchmark) ** 2
            for benchmark_return in self._b_rets
        ) / max(len(self._b_rets) - 1, 1)

        return covariance / variance if variance > 0 else 0.0

    def PushDailyMetrics(self):
        """Plot rolling risk metrics."""
        count = len(self.daily_returns)

        if count < 10:
            return

        mean_return = sum(self.daily_returns) / count

        variance = sum(
            (daily_return - mean_return) ** 2
            for daily_return in self.daily_returns
        ) / max(count - 1, 1)

        standard_deviation = math.sqrt(max(variance, 1e-12))

        sharpe = (
            (mean_return / standard_deviation) * math.sqrt(252.0)
            if standard_deviation > 0
            else 0.0
        )

        z_score = (
            (mean_return / standard_deviation) * math.sqrt(count)
            if standard_deviation > 0
            else 0.0
        )

        psr = 0.5 * (1.0 + math.erf(z_score / math.sqrt(2.0)))

        self.Plot("Risk", "Sharpe(rolling)", sharpe)
        self.Plot("Risk", "PSR_vs0", psr)

        closed = list(self.TradeBuilder.ClosedTrades)

        if closed:
            wins = sum(1 for trade in closed if trade.ProfitLoss > 0)
            self.Plot("Risk", "WinRate", wins / float(len(closed)))

    def OnEndOfAlgorithm(self):
        """Log summary statistics at end of backtest."""
        closed = list(self.TradeBuilder.ClosedTrades)
        wins = sum(1 for trade in closed if trade.ProfitLoss > 0)
        win_rate = wins / len(closed) if closed else float("nan")

        self.Log(
            f"RUN_SUMMARY | orders={len(self._order_ids)} | "
            f"fills={self._fills} | "
            f"closed_trades={len(closed)} | "
            f"win_rate={win_rate:.2%}"
        )

    def ParseUtcAny(self, value):
        """Parse ISO string or epoch into timezone-aware UTC datetime."""
        if not value:
            return None

        value = str(value)

        try:
            normalized = value.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(normalized)

            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)

            return parsed.astimezone(timezone.utc)

        except Exception:
            pass

        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except Exception:
            return None

    def ToUtcEpoch(self, value):
        """Convert datetime or number to UTC epoch seconds."""
        if value is None:
            return None

        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)

            return value.timestamp()

        try:
            return float(value)
        except Exception:
            return None