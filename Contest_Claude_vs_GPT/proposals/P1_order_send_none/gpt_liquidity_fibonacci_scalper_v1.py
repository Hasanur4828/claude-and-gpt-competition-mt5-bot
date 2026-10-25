"""
GPT Liquidity-Fibonacci Scalper v1.0
Python + MetaTrader5 strategy module.

Strategy:
- Symbols: broker-specific BTCUSDm and XAUUSDm by default
- Trend timeframe: H1 (EMA 50/200 + ADX >= 20)
- Entry timeframe: M15
- Entry concept: confirmed market-structure break, Fibonacci 50%-61.8% pullback,
  liquidity sweep, then candle-close confirmation
- Risk: 1% of current balance per trade
- Daily stop: stop opening new trades after 2 losing closed positions
- One position per symbol
- SL: beyond the liquidity-sweep extreme + 0.3 * ATR
- TP: 2R
- Gold entry session: weekdays 07:00-20:00 UTC
- Crypto entry session: weekdays only
- Spread filter: spread <= 0.15 * M15 ATR

IMPORTANT:
1. This module has not been backtested or forward-tested. Start with MT5 demo.
2. Broker symbol names/contract specifications differ. Confirm symbols in Market Watch.
3. Attach this module to the user's existing MT5 connection; it does not initialize/login
   MT5 automatically and does not interfere with other strategy magic numbers.
4. The USD high-impact news filter from the Claude document is NOT included here.
   Add the user's trusted calendar provider before live Gold trading if that filter is required.
5. A strategy can lose money; 1% risk is a target estimate, not a guarantee against slippage/gaps.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional, List

import MetaTrader5 as mt5
import pandas as pd
import numpy as np


MAGIC = 26102402
ORDER_COMMENT = "GPT_LF_SCALP_v1"


@dataclass
class StrategyConfig:
    symbols: tuple = ("BTCUSDm", "XAUUSDm")
    risk_percent: float = 1.0
    max_daily_losses: int = 2
    max_positions_per_symbol: int = 1
    trend_ema_fast: int = 50
    trend_ema_slow: int = 200
    adx_period: int = 14
    adx_min: float = 20.0
    atr_period: int = 14
    swing_left: int = 2
    swing_right: int = 2
    structure_lookback: int = 80
    impulse_lookback: int = 30
    sweep_lookback: int = 5
    fib_low: float = 0.50
    fib_high: float = 0.618
    sl_atr_buffer: float = 0.30
    sl_min_atr: float = 0.80
    sl_max_atr: float = 2.50
    tp_r: float = 2.0
    max_spread_atr: float = 0.15
    deviation_points: int = 30


class GPTLiquidityFibonacciScalper:
    def __init__(self, config: Optional[StrategyConfig] = None):
        self.cfg = config or StrategyConfig()
        self._last_m15_bar: Dict[str, int] = {}

    # ---------- Market data / indicators ----------

    @staticmethod
    def _rates(symbol: str, timeframe: int, count: int) -> Optional[pd.DataFrame]:
        # start_pos=1 excludes the currently forming candle.
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 1, count)
        if rates is None or len(rates) < max(20, count // 2):
            return None
        df = pd.DataFrame(rates)
        df["time"] = df["time"].astype("int64")
        return df.reset_index(drop=True)

    @staticmethod
    def _ema(series: pd.Series, period: int) -> pd.Series:
        return series.ewm(span=period, adjust=False).mean()

    @staticmethod
    def _atr(df: pd.DataFrame, period: int) -> pd.Series:
        prev_close = df["close"].shift(1)
        tr = pd.concat(
            [
                df["high"] - df["low"],
                (df["high"] - prev_close).abs(),
                (df["low"] - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        # Wilder-like smoothing
        return tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()

    @staticmethod
    def _adx(df: pd.DataFrame, period: int) -> pd.Series:
        high, low, close = df["high"], df["low"], df["close"]
        up = high.diff()
        down = -low.diff()
        plus_dm = pd.Series(
            np.where((up > down) & (up > 0), up, 0.0), index=df.index
        )
        minus_dm = pd.Series(
            np.where((down > up) & (down > 0), down, 0.0), index=df.index
        )
        prev_close = close.shift(1)
        tr = pd.concat(
            [
                high - low,
                (high - prev_close).abs(),
                (low - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atr = tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
        plus_di = 100 * plus_dm.ewm(
            alpha=1.0 / period, adjust=False, min_periods=period
        ).mean() / atr.replace(0, np.nan)
        minus_di = 100 * minus_dm.ewm(
            alpha=1.0 / period, adjust=False, min_periods=period
        ).mean() / atr.replace(0, np.nan)
        dx = 100 * (plus_di - minus_di).abs() / (
            plus_di + minus_di
        ).replace(0, np.nan)
        return dx.ewm(
            alpha=1.0 / period, adjust=False, min_periods=period
        ).mean()

    def _trend(self, symbol: str) -> tuple[str, Optional[float], str]:
        h1 = self._rates(symbol, mt5.TIMEFRAME_H1, 650)
        if h1 is None or len(h1) < 600:
            return "NONE", None, "SKIP_NO_H1_HISTORY"

        h1["ema_fast"] = self._ema(h1["close"], self.cfg.trend_ema_fast)
        h1["ema_slow"] = self._ema(h1["close"], self.cfg.trend_ema_slow)
        h1["adx"] = self._adx(h1, self.cfg.adx_period)
        last = h1.iloc[-1]

        if pd.isna(last["adx"]) or float(last["adx"]) < self.cfg.adx_min:
            return "NONE", float(last["adx"]) if not pd.isna(last["adx"]) else None, "ADX_LOW"

        if last["close"] > last["ema_slow"] and last["ema_fast"] > last["ema_slow"]:
            return "BUY", float(last["adx"]), "H1_BULL_TREND"
        if last["close"] < last["ema_slow"] and last["ema_fast"] < last["ema_slow"]:
            return "SELL", float(last["adx"]), "H1_BEAR_TREND"
        return "NONE", float(last["adx"]), "NO_TREND"

    def _new_closed_m15_bar(self, symbol: str) -> bool:
        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 1, 2)
        if rates is None or len(rates) < 2:
            return False
        bar_time = int(rates[-1]["time"])
        if self._last_m15_bar.get(symbol) == bar_time:
            return False
        self._last_m15_bar[symbol] = bar_time
        return True

    # ---------- Structure / setup ----------

    def _confirmed_swings(self, df: pd.DataFrame) -> tuple[List[int], List[int]]:
        highs, lows = [], []
        left, right = self.cfg.swing_left, self.cfg.swing_right
        # Last right bars cannot be confirmed pivots.
        for i in range(left, len(df) - right):
            h = float(df["high"].iloc[i])
            l = float(df["low"].iloc[i])
            if all(h > float(df["high"].iloc[j]) for j in range(i-left, i)) and \
               all(h > float(df["high"].iloc[j]) for j in range(i+1, i+right+1)):
                highs.append(i)
            if all(l < float(df["low"].iloc[j]) for j in range(i-left, i)) and \
               all(l < float(df["low"].iloc[j]) for j in range(i+1, i+right+1)):
                lows.append(i)
        return highs, lows

    def _setup(self, symbol: str, direction: str) -> Dict[str, Any]:
        m15 = self._rates(symbol, mt5.TIMEFRAME_M15, 350)
        if m15 is None or len(m15) < 250:
            return {"signal": "NO_TRADE", "reason": "SKIP_NO_M15_HISTORY"}

        m15["atr"] = self._atr(m15, self.cfg.atr_period)
        m15["ema20"] = self._ema(m15["close"], 20)
        m15["ema50"] = self._ema(m15["close"], 50)
        m15 = m15.dropna().reset_index(drop=True)
        if len(m15) < 100:
            return {"signal": "NO_TRADE", "reason": "SKIP_INDICATOR_WARMUP"}

        i = len(m15) - 1
        bar = m15.iloc[i]        # last fully closed candle
        prev = m15.iloc[i - 1]
        atr = float(bar["atr"])
        if not np.isfinite(atr) or atr <= 0:
            return {"signal": "NO_TRADE", "reason": "SKIP_BAD_ATR"}

        swing_highs, swing_lows = self._confirmed_swings(m15.iloc[-self.cfg.structure_lookback:].reset_index(drop=True))
        offset = len(m15) - min(len(m15), self.cfg.structure_lookback)
        swing_highs = [x + offset for x in swing_highs]
        swing_lows = [x + offset for x in swing_lows]

        # Use only confirmed swing points that occurred before the trigger candle.
        prior_highs = [x for x in swing_highs if x < i - 1]
        prior_lows = [x for x in swing_lows if x < i - 1]
        if not prior_highs or not prior_lows:
            return {"signal": "NO_TRADE", "reason": "SKIP_NO_CONFIRMED_SWINGS"}

        # Require a recent BOS (within 12 closed M15 candles).
        bos_candidates = []
        for k in range(max(2, i - 12), i):
            highs_before_k = [x for x in prior_highs if x < k]
            lows_before_k = [x for x in prior_lows if x < k]
            if direction == "BUY" and highs_before_k:
                level_idx = highs_before_k[-1]
                if float(m15["close"].iloc[k]) > float(m15["high"].iloc[level_idx]):
                    bos_candidates.append((k, level_idx))
            elif direction == "SELL" and lows_before_k:
                level_idx = lows_before_k[-1]
                if float(m15["close"].iloc[k]) < float(m15["low"].iloc[level_idx]):
                    bos_candidates.append((k, level_idx))

        if not bos_candidates:
            return {"signal": "NO_TRADE", "reason": "NO_RECENT_BOS"}

        bos_idx, _ = bos_candidates[-1]
        impulse_start_min = max(0, bos_idx - self.cfg.impulse_lookback)
        if direction == "BUY":
            starts = [x for x in prior_lows if impulse_start_min <= x < bos_idx]
            if not starts:
                return {"signal": "NO_TRADE", "reason": "NO_IMPULSE_SWING_LOW"}
            start_idx = min(starts, key=lambda x: float(m15["low"].iloc[x]))
            impulse_low = float(m15["low"].iloc[start_idx])
            impulse_high = float(m15["high"].iloc[bos_idx])
            span = impulse_high - impulse_low
            if span <= 0:
                return {"signal": "NO_TRADE", "reason": "BAD_IMPULSE"}
            fib_50 = impulse_high - 0.50 * span
            fib_618 = impulse_high - 0.618 * span
            zone_low, zone_high = min(fib_50, fib_618), max(fib_50, fib_618)

            # Sweep: current candle pierces the lowest low of the previous N bars,
            # then closes back above that prior-low level.
            look = m15.iloc[max(0, i-self.cfg.sweep_lookback):i]
            sweep_level = float(look["low"].min())
            swept = float(bar["low"]) < sweep_level and float(bar["close"]) > sweep_level
            in_zone = float(bar["low"]) <= zone_high and float(bar["high"]) >= zone_low
            confirm = float(bar["close"]) > float(prev["high"]) and float(bar["close"]) > zone_low
            if not (in_zone and swept and confirm):
                return {
                    "signal": "NO_TRADE",
                    "reason": "WAIT_FIB_SWEEP_CONFIRM",
                    "fib_zone": [zone_low, zone_high],
                    "bos_time": int(m15["time"].iloc[bos_idx]),
                }
            entry = float(mt5.symbol_info_tick(symbol).ask)
            sweep_extreme = float(bar["low"])
            sl = sweep_extreme - self.cfg.sl_atr_buffer * atr
            risk_distance = entry - sl
            side = "BUY"

        else:
            starts = [x for x in prior_highs if impulse_start_min <= x < bos_idx]
            if not starts:
                return {"signal": "NO_TRADE", "reason": "NO_IMPULSE_SWING_HIGH"}
            start_idx = max(starts, key=lambda x: float(m15["high"].iloc[x]))
            impulse_high = float(m15["high"].iloc[start_idx])
            impulse_low = float(m15["low"].iloc[bos_idx])
            span = impulse_high - impulse_low
            if span <= 0:
                return {"signal": "NO_TRADE", "reason": "BAD_IMPULSE"}
            fib_50 = impulse_low + 0.50 * span
            fib_618 = impulse_low + 0.618 * span
            zone_low, zone_high = min(fib_50, fib_618), max(fib_50, fib_618)

            look = m15.iloc[max(0, i-self.cfg.sweep_lookback):i]
            sweep_level = float(look["high"].max())
            swept = float(bar["high"]) > sweep_level and float(bar["close"]) < sweep_level
            in_zone = float(bar["high"]) >= zone_low and float(bar["low"]) <= zone_high
            confirm = float(bar["close"]) < float(prev["low"]) and float(bar["close"]) < zone_high
            if not (in_zone and swept and confirm):
                return {
                    "signal": "NO_TRADE",
                    "reason": "WAIT_FIB_SWEEP_CONFIRM",
                    "fib_zone": [zone_low, zone_high],
                    "bos_time": int(m15["time"].iloc[bos_idx]),
                }
            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                return {"signal": "NO_TRADE", "reason": "SKIP_NO_TICK"}
            entry = float(tick.bid)
            sweep_extreme = float(bar["high"])
            sl = sweep_extreme + self.cfg.sl_atr_buffer * atr
            risk_distance = sl - entry
            side = "SELL"

        if risk_distance <= 0:
            return {"signal": "NO_TRADE", "reason": "SKIP_INVALID_SL"}
        if risk_distance < self.cfg.sl_min_atr * atr:
            return {"signal": "NO_TRADE", "reason": "SKIP_SL_TOO_SMALL"}
        if risk_distance > self.cfg.sl_max_atr * atr:
            return {"signal": "NO_TRADE", "reason": "SKIP_SL_TOO_BIG"}

        tp = entry + self.cfg.tp_r * risk_distance if side == "BUY" else entry - self.cfg.tp_r * risk_distance
        info = mt5.symbol_info(symbol)
        tick = mt5.symbol_info_tick(symbol)
        if info is None or tick is None or info.point <= 0:
            return {"signal": "NO_TRADE", "reason": "SKIP_SYMBOL_INFO"}

        spread = float(tick.ask - tick.bid)
        if spread > self.cfg.max_spread_atr * atr:
            return {"signal": "NO_TRADE", "reason": "SKIP_SPREAD"}

        digits = int(info.digits)
        return {
            "engine": "GPT_LIQUIDITY_FIBONACCI",
            "symbol": symbol,
            "mode": "SCALPING",
            "timeframe": "M15",
            "signal": side,
            "entry": round(entry, digits),
            "stop_loss": round(sl, digits),
            "take_profit": round(tp, digits),
            "risk_percent": self.cfg.risk_percent,
            "risk_distance": risk_distance,
            "atr": atr,
            "fib_zone": [round(zone_low, digits), round(zone_high, digits)],
            "reason": "H1_TREND + RECENT_BOS + FIB_PULLBACK + LIQUIDITY_SWEEP + CLOSE_CONFIRM",
        }

    # ---------- Risk / execution ----------

    @staticmethod
    def _session_allowed(symbol: str) -> bool:
        now = datetime.now(timezone.utc)
        # No new entries Saturday/Sunday for either symbol.
        if now.weekday() >= 5:
            return False
        if "XAU" in symbol.upper() or "GOLD" in symbol.upper():
            return 7 <= now.hour < 20
        return True

    @staticmethod
    def _daily_loss_count(symbols: tuple) -> int:
        now = datetime.now(timezone.utc)
        start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
        deals = mt5.history_deals_get(start, now)
        if deals is None:
            return 0
        # Count unique strategy position IDs whose total net P/L is <= -0.2R.
        # This conservative implementation approximates R by 1% of balance at close.
        acc = mt5.account_info()
        if acc is None:
            return 0
        threshold = -0.002 * float(acc.balance)
        totals: Dict[int, float] = {}
        for d in deals:
            if getattr(d, "magic", None) != MAGIC:
                continue
            if getattr(d, "symbol", "") not in symbols:
                continue
            pid = int(getattr(d, "position_id", 0))
            net = float(getattr(d, "profit", 0.0)) + float(getattr(d, "commission", 0.0)) + float(getattr(d, "swap", 0.0))
            totals[pid] = totals.get(pid, 0.0) + net
        return sum(1 for pnl in totals.values() if pnl <= threshold)

    @staticmethod
    def _normalize_volume(symbol: str, raw_volume: float) -> float:
        info = mt5.symbol_info(symbol)
        if info is None:
            return 0.0
        step = float(info.volume_step)
        vmin = float(info.volume_min)
        vmax = float(info.volume_max)
        if step <= 0:
            return 0.0
        volume = np.floor((raw_volume + 1e-12) / step) * step
        volume = min(volume, vmax)
        # Do not force minimum volume if it would exceed risk.
        if volume < vmin:
            return 0.0
        decimals = max(0, len(str(step).split(".")[-1].rstrip("0")))
        return round(float(volume), decimals)

    def _calc_lot(self, symbol: str, side: str, entry: float, sl: float) -> float:
        account = mt5.account_info()
        info = mt5.symbol_info(symbol)
        if account is None or info is None:
            return 0.0
        risk_money = float(account.balance) * self.cfg.risk_percent / 100.0
        order_type = mt5.ORDER_TYPE_BUY if side == "BUY" else mt5.ORDER_TYPE_SELL
        # Calculate the P/L for 1 lot if the stop loss is hit.
        loss = mt5.order_calc_profit(order_type, symbol, 1.0, entry, sl)
        if loss is None:
            return 0.0
        loss_per_lot = abs(float(loss))
        if loss_per_lot <= 0:
            return 0.0
        return self._normalize_volume(symbol, risk_money / loss_per_lot)

    def _has_position(self, symbol: str) -> bool:
        positions = mt5.positions_get(symbol=symbol)
        if positions is None:
            return False
        # Do not stack strategies on the same symbol.
        return len(positions) > 0

    def _send_order(self, signal: Dict[str, Any]) -> Dict[str, Any]:
        symbol = signal["symbol"]
        side = signal["signal"]
        entry = float(signal["entry"])
        sl = float(signal["stop_loss"])
        tp = float(signal["take_profit"])
        info = mt5.symbol_info(symbol)
        tick = mt5.symbol_info_tick(symbol)
        if info is None or tick is None:
            return {"status": "FAILED", "reason": "SKIP_SYMBOL_INFO"}

        volume = self._calc_lot(symbol, side, entry, sl)
        if volume <= 0:
            return {"status": "SKIPPED", "reason": "SKIP_LOT_TOO_SMALL_OR_CALC_FAILED"}

        # Use the latest executable price, and re-check risk distance at that price.
        price = float(tick.ask if side == "BUY" else tick.bid)
        risk_distance = price - sl if side == "BUY" else sl - price
        if risk_distance <= 0:
            return {"status": "SKIPPED", "reason": "SKIP_PRICE_MOVED_PAST_SL"}

        # Recompute TP from latest executable price to preserve 2R.
        tp = price + self.cfg.tp_r * risk_distance if side == "BUY" else price - self.cfg.tp_r * risk_distance
        digits = int(info.digits)
        price, sl, tp = round(price, digits), round(sl, digits), round(tp, digits)

        stops_level = int(getattr(info, "trade_stops_level", 0))
        min_distance = stops_level * float(info.point)
        if abs(price - sl) < min_distance or abs(tp - price) < min_distance:
            return {"status": "SKIPPED", "reason": "SKIP_BROKER_STOP_LEVEL"}

        order_type = mt5.ORDER_TYPE_BUY if side == "BUY" else mt5.ORDER_TYPE_SELL
        filling_candidates = []
        for mode in (mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_RETURN):
            if mode not in filling_candidates:
                filling_candidates.append(mode)

        last_result = None
        for filling in filling_candidates:
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": volume,
                "type": order_type,
                "price": price,
                "sl": sl,
                "tp": tp,
                "deviation": self.cfg.deviation_points,
                "magic": MAGIC,
                "comment": ORDER_COMMENT,
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": filling,
            }
            result = mt5.order_send(request)
            last_result = result
            if result is None:
                # [P1] Outcome unknown (the order may have reached the broker).
                # Never resend with another filling mode - that could open a duplicate position.
                return {
                    "status": "UNKNOWN",
                    "reason": "ORDER_SEND_NONE",
                    "symbol": symbol,
                    "side": side,
                    "requested_volume": volume,
                    "type_filling": filling,
                    "magic": MAGIC,
                    "last_error": str(mt5.last_error()),
                    "note": "order_send returned None; not resent - check MT5 positions/history",
                }
            if result is not None and result.retcode in (
                mt5.TRADE_RETCODE_DONE,
                mt5.TRADE_RETCODE_PLACED,
                mt5.TRADE_RETCODE_DONE_PARTIAL,
            ):
                return {
                    "status": "OPENED",
                    "ticket": int(result.order),
                    "deal": int(result.deal),
                    "symbol": symbol,
                    "side": side,
                    "volume": volume,
                    "entry": price,
                    "sl": sl,
                    "tp": tp,
                    "risk_percent": self.cfg.risk_percent,
                    "magic": MAGIC,
                }

        return {
            "status": "FAILED",
            "reason": "ORDER_SEND_FAILED",
            "retcode": getattr(last_result, "retcode", None),
            "comment": getattr(last_result, "comment", None),
            "last_error": str(mt5.last_error()),
        }

    # ---------- Public API for integration ----------

    def evaluate_symbol(self, symbol: str) -> Dict[str, Any]:
        if not mt5.terminal_info() or not mt5.account_info():
            return {"signal": "NO_TRADE", "reason": "SKIP_MT5_NOT_CONNECTED"}

        if not mt5.symbol_select(symbol, True):
            return {"signal": "NO_TRADE", "reason": "SKIP_SYMBOL_NOT_AVAILABLE"}

        if not self._session_allowed(symbol):
            return {"signal": "NO_TRADE", "reason": "SKIP_SESSION"}

        if self._daily_loss_count(self.cfg.symbols) >= self.cfg.max_daily_losses:
            return {"signal": "NO_TRADE", "reason": "SKIP_DAILY_LOSS_LIMIT"}

        if self._has_position(symbol):
            return {"signal": "NO_TRADE", "reason": "SKIP_POSITION_EXISTS"}

        trend, adx, trend_reason = self._trend(symbol)
        if trend == "NONE":
            return {"signal": "NO_TRADE", "reason": trend_reason, "adx": adx}

        result = self._setup(symbol, trend)
        result["adx"] = adx
        result["trend_reason"] = trend_reason
        return result

    def run_once(self, execute: bool = False) -> List[Dict[str, Any]]:
        """
        Call from the existing app loop.
        execute=False: signal-only mode (recommended for first integration).
        execute=True: sends live orders; use only after demo testing.
        """
        outputs = []
        for symbol in self.cfg.symbols:
            if not self._new_closed_m15_bar(symbol):
                continue
            signal = self.evaluate_symbol(symbol)
            if signal.get("signal") in ("BUY", "SELL") and execute:
                signal["execution"] = self._send_order(signal)
            outputs.append(signal)
        return outputs


if __name__ == "__main__":
    # This module intentionally does not call mt5.initialize() or login().
    # Your existing application should establish the MT5 connection first.
    print("GPT Liquidity-Fibonacci Scalper v1.0 loaded.")
    print("Integrate with your existing MT5 loop; start with execute=False.")
