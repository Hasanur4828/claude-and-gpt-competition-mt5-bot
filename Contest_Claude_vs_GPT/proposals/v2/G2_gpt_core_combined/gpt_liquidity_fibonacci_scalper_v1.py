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

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional, List

import MetaTrader5 as mt5
import pandas as pd
import numpy as np


MAGIC = 26102402
ORDER_COMMENT = "GPT_LF_SCALP_v1"

# [v2 proposal] execution-safety constants (no strategy parameter changed)
UNCERTAIN_RETCODES = (10012, 10031)   # TRADE_RETCODE_TIMEOUT, TRADE_RETCODE_CONNECTION: outcome not certain
UNKNOWN_RESOLVE_SEC = 60              # [P1r] min. age before "nothing found" may clear an UNKNOWN order
MAX_TICK_AGE_SEC = 120                # [P4r] never send an order from a tick older than this
OFFSET_SYMBOLS = ("BTCUSDm", "XAUUSDm", "ETHUSDm")
# [P1r] unresolved-order blocks survive a restart (file next to this module; written only when a block exists)
EXEC_STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gpt_exec_unknown_state.json")


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
        # [P1r] symbol -> unresolved order whose outcome is unknown; blocks new orders on that symbol
        self._exec_state_file = EXEC_STATE_FILE
        self._exec_state_error: Optional[str] = None
        self._exec_unknown: Dict[str, Dict[str, Any]] = self._load_exec_state()

    def _load_exec_state(self) -> Dict[str, Dict[str, Any]]:
        """[P1r] Missing file = no unresolved orders. Unreadable file = state UNKNOWN:
        no new orders on any symbol until the file is checked (fail safe)."""
        try:
            with open(self._exec_state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("not a JSON object")
            return data
        except FileNotFoundError:
            return {}
        except Exception as e:
            self._exec_state_error = f"{type(e).__name__}: {e}"
            return {}

    def _save_exec_state(self) -> None:
        """[P1r] Atomic write; the file is removed when no block remains."""
        if not self._exec_unknown:
            try:
                os.remove(self._exec_state_file)
            except FileNotFoundError:
                pass
            return
        tmp = self._exec_state_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._exec_unknown, f, indent=1, default=str)
        os.replace(tmp, self._exec_state_file)

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
            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                # [P4] No tick: never send an order; report clearly (same as the SELL branch).
                return {"signal": "NO_TRADE", "reason": "SKIP_NO_TICK"}
            entry = float(tick.ask)
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
    def _server_offset_seconds() -> Optional[int]:
        """[P2r] Broker server time minus UTC, rounded to 30 minutes (brokers use
        whole/half-hour offsets). MT5 history timestamps are broker server time, not UTC.
        Only fresh ticks (within ~5 minutes of a 30-minute offset) are used; stale or
        missing symbols are skipped. Returns None (UNKNOWN) if no fresh tick exists or if
        fresh ticks disagree - an offset is never assumed."""
        now_ts = datetime.now(timezone.utc).timestamp()
        found = set()
        for sym in OFFSET_SYMBOLS:
            tick = mt5.symbol_info_tick(sym)
            if tick is None or not getattr(tick, "time", 0):
                continue
            raw = float(tick.time) - now_ts
            off = int(round(raw / 1800.0)) * 1800
            if abs(raw - off) <= 300 and -14 * 3600 <= off <= 14 * 3600:
                found.add(off)
        if len(found) != 1:
            return None
        return found.pop()

    @staticmethod
    def _daily_loss_count(symbols: tuple) -> Optional[int]:
        """[P2r] Returns today's (UTC day) losing-position count, or None = UNKNOWN
        (offset unknown/inconsistent, deal history or account unavailable).
        The caller must not open new trades while the count is UNKNOWN."""
        now = datetime.now(timezone.utc)
        start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
        offset = GPTLiquidityFibonacciScalper._server_offset_seconds()
        if offset is None:
            return None
        # Wide query window (yesterday .. now + 2 days) so recent deals are never cut off
        # when broker server time != UTC; then keep only today's deals.
        q_from = datetime.fromtimestamp(start.timestamp() - 86400, tz=timezone.utc)
        q_to = datetime.fromtimestamp(now.timestamp() + 2 * 86400, tz=timezone.utc)
        deals = mt5.history_deals_get(q_from, q_to)
        if deals is None:
            return None
        lo = start.timestamp() + offset   # today's UTC midnight in server time
        deals = [d for d in deals if float(getattr(d, "time", 0)) >= lo]
        # Count unique strategy position IDs whose total net P/L is <= -0.2R.
        # This conservative implementation approximates R by 1% of balance at close.
        acc = mt5.account_info()
        if acc is None:
            return None
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

    def _has_position(self, symbol: str) -> Optional[bool]:
        """[H] True = position(s) found, False = query OK and no position,
        None = query failed / state UNKNOWN (caller must not trade)."""
        positions = mt5.positions_get(symbol=symbol)
        if positions is None:
            return None
        # Do not stack strategies on the same symbol.
        return len(positions) > 0

    @staticmethod
    def _deal_window() -> tuple:
        """[P1r] UTC query window wide enough for any broker offset (+/-14h)."""
        now_ts = datetime.now(timezone.utc).timestamp()
        return (datetime.fromtimestamp(now_ts - 2 * 86400, tz=timezone.utc),
                datetime.fromtimestamp(now_ts + 2 * 86400, tz=timezone.utc))

    def _exec_snapshot(self, symbol: str) -> Optional[Dict[str, Any]]:
        """[P1r] State before sending: own positions on the symbol and the highest deal ticket.
        None if either query fails (then no order is sent - it could not be reconciled)."""
        ps = mt5.positions_get(symbol=symbol)
        q_from, q_to = self._deal_window()
        ds = mt5.history_deals_get(q_from, q_to)
        if ps is None or ds is None:
            return None
        return {"positions": sorted(int(p.ticket) for p in ps if getattr(p, "magic", None) == MAGIC),
                "max_deal": max((int(d.ticket) for d in ds), default=0),
                "time": datetime.now(timezone.utc).timestamp()}

    def _reconcile(self, symbol: str, snap: Dict[str, Any]) -> Dict[str, Any]:
        """[P1r] After an ambiguous result: did our order execute? Compares positions and deal
        history with the pre-send snapshot. state: OPENED / NOT_FOUND / UNKNOWN (query failed)."""
        ps = mt5.positions_get(symbol=symbol)
        q_from, q_to = self._deal_window()
        ds = mt5.history_deals_get(q_from, q_to)
        if ps is None or ds is None:
            return {"state": "UNKNOWN", "last_error": str(mt5.last_error())}
        before = set(snap["positions"])
        new_pos = [p for p in ps if getattr(p, "magic", None) == MAGIC and int(p.ticket) not in before]
        entry_in = getattr(mt5, "DEAL_ENTRY_IN", 0)
        new_deals = [d for d in ds if int(d.ticket) > snap["max_deal"] and getattr(d, "magic", None) == MAGIC
                     and getattr(d, "symbol", "") == symbol and getattr(d, "entry", entry_in) == entry_in]
        if new_pos or new_deals:
            return {"state": "OPENED",
                    "position_ids": sorted({int(p.ticket) for p in new_pos} | {int(d.position_id) for d in new_deals}),
                    "deal_tickets": sorted(int(d.ticket) for d in new_deals),
                    "filled_volume": round(sum(float(d.volume) for d in new_deals), 8) if new_deals else None,
                    "still_open": bool(new_pos)}
        return {"state": "NOT_FOUND"}

    def _execution_unknown(self, symbol: str, snap: Dict[str, Any], base: Dict[str, Any]) -> Dict[str, Any]:
        """[P1r] Ambiguous order result: never resend. Reconcile now; if still uncertain,
        block new orders on this symbol until a later reconciliation resolves it."""
        rec = self._reconcile(symbol, snap)
        out = dict(base, reconcile=rec, last_error=str(mt5.last_error()))
        if rec["state"] == "OPENED":
            out.update(status="OPENED_RECONCILED", filled_volume=rec["filled_volume"],
                       fill_status="UNKNOWN_FILL" if rec["filled_volume"] is None else
                       ("PARTIAL" if rec["filled_volume"] + 1e-9 < base["requested_volume"] else "FULL"))
            return out
        self._exec_unknown[symbol] = {"snap": snap, "since": snap["time"], "detail": base}
        self._save_exec_state()
        out.update(status="UNKNOWN",
                   note="order outcome unknown; not resent; new orders on this symbol blocked until reconciled")
        return out

    def _check_exec_unknown(self, symbol: str) -> Optional[Dict[str, Any]]:
        """[P1r] Called before any new order. Returns a NO_TRADE dict while an earlier
        order on this symbol is still unresolved; None when the symbol is clear."""
        if self._exec_state_error is not None:
            return {"signal": "NO_TRADE", "reason": "SKIP_EXEC_STATE_UNREADABLE", "detail": self._exec_state_error,
                    "file": self._exec_state_file}
        pend = self._exec_unknown.get(symbol)
        if pend is None:
            return None
        rec = self._reconcile(symbol, pend["snap"])
        age = datetime.now(timezone.utc).timestamp() - pend["since"]
        if rec["state"] == "OPENED":
            del self._exec_unknown[symbol]
            self._save_exec_state()
            return {"signal": "NO_TRADE", "reason": "EXECUTION_UNKNOWN_RESOLVED_OPENED", "reconcile": rec}
        if rec["state"] == "NOT_FOUND" and age >= UNKNOWN_RESOLVE_SEC:
            del self._exec_unknown[symbol]
            self._save_exec_state()
            return {"signal": "NO_TRADE", "reason": "EXECUTION_UNKNOWN_RESOLVED_NOT_EXECUTED", "reconcile": rec}
        return {"signal": "NO_TRADE", "reason": "SKIP_EXECUTION_UNKNOWN", "reconcile": rec, "age_sec": round(age, 1)}

    def _fill_info(self, result: Any, requested: float) -> Dict[str, Any]:
        """[P3r] Filled volume from the broker's deal record (preferred), else from the
        result; never assumed to equal the requested volume."""
        filled, source, position_id = None, None, None
        deal = int(getattr(result, "deal", 0) or 0)
        if deal > 0:
            ds = mt5.history_deals_get(ticket=deal)
            if ds:
                filled = round(sum(float(d.volume) for d in ds), 8)
                source = "deal_history"
                position_id = int(getattr(ds[0], "position_id", 0)) or None
        if filled is None:
            v = getattr(result, "volume", None)
            if v:
                filled, source = float(v), "order_result"
        if filled is None:
            status = "UNKNOWN_FILL"
        elif filled + 1e-9 < requested or result.retcode == mt5.TRADE_RETCODE_DONE_PARTIAL:
            status = "PARTIAL"
        else:
            status = "FULL"
        return {"requested_volume": requested, "filled_volume": filled, "fill_status": status,
                "fill_source": source, "position_id": position_id}

    def _send_order(self, signal: Dict[str, Any]) -> Dict[str, Any]:
        symbol = signal["symbol"]
        side = signal["signal"]
        entry = float(signal["entry"])
        sl = float(signal["stop_loss"])
        tp = float(signal["take_profit"])
        blocked = self._check_exec_unknown(symbol)          # [P1r] never stack on an unresolved order
        if blocked is not None:
            return {"status": "SKIPPED", "reason": blocked["reason"], "reconcile": blocked.get("reconcile")}
        info = mt5.symbol_info(symbol)
        tick = mt5.symbol_info_tick(symbol)
        if info is None or tick is None:
            return {"status": "FAILED", "reason": "SKIP_SYMBOL_INFO"}
        # [P4r] never price an order from an invalid or stale tick
        if not (float(tick.bid) > 0 and float(tick.ask) > 0 and float(tick.ask) >= float(tick.bid)):
            return {"status": "SKIPPED", "reason": "SKIP_INVALID_TICK"}
        offset = self._server_offset_seconds()
        if offset is None:
            return {"status": "SKIPPED", "reason": "SKIP_TICK_AGE_UNKNOWN"}
        tick_age = datetime.now(timezone.utc).timestamp() + offset - float(getattr(tick, "time", 0))
        if tick_age > MAX_TICK_AGE_SEC:
            return {"status": "SKIPPED", "reason": "SKIP_STALE_TICK", "tick_age_sec": round(tick_age, 1)}

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

        snap = self._exec_snapshot(symbol)                   # [P1r] needed to reconcile an ambiguous result
        if snap is None:
            return {"status": "SKIPPED", "reason": "SKIP_PRECHECK_QUERY_FAILED", "last_error": str(mt5.last_error())}

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
            if result is None or result.retcode in UNCERTAIN_RETCODES:
                # [P1r] Outcome unknown (the order may have reached the broker).
                # Never resend with another filling mode - that could open a duplicate position.
                return self._execution_unknown(symbol, snap, {
                    "reason": "ORDER_SEND_NONE" if result is None else f"UNCERTAIN_RETCODE_{result.retcode}",
                    "symbol": symbol, "side": side, "requested_volume": volume,
                    "type_filling": filling, "magic": MAGIC})
            if result.retcode in (
                mt5.TRADE_RETCODE_DONE,
                mt5.TRADE_RETCODE_PLACED,
                mt5.TRADE_RETCODE_DONE_PARTIAL,
            ):
                out = {
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
                out.update(self._fill_info(result, volume))   # [P3r]
                return out

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

        losses = self._daily_loss_count(self.cfg.symbols)
        if losses is None:                                     # [P2r] fail safe: count unknown
            return {"signal": "NO_TRADE", "reason": "SKIP_DAILY_LOSS_UNKNOWN", "last_error": str(mt5.last_error())}
        if losses >= self.cfg.max_daily_losses:
            return {"signal": "NO_TRADE", "reason": "SKIP_DAILY_LOSS_LIMIT"}

        blocked = self._check_exec_unknown(symbol)             # [P1r] earlier order still unresolved
        if blocked is not None:
            return blocked

        has_pos = self._has_position(symbol)
        if has_pos is None:                                    # [H] fail safe: position state unknown
            return {"signal": "NO_TRADE", "reason": "SKIP_POSITION_STATE_UNKNOWN", "last_error": str(mt5.last_error())}
        if has_pos:
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
