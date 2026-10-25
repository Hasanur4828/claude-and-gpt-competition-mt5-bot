"""
Claude Pullback Strategy v1.0 — MT5 bot module
==============================================
PDF "Claude_Pullback_Strategy_v1.0.pdf" অনুযায়ী হুবহু লেখা। সব প্যারামিটার ফিক্সড।

* এই module নিজে MT5-এ initialize/login করে না — সফটওয়্যারের চলমান সংযোগ ব্যবহার করে।
* শুধু নিজের magic (26102401)-এর পজিশন ম্যানেজ করে। অন্য কারো পজিশন বন্ধ/বদল করে না —
  প্রতিটি close/modify request-এ পজিশনের magic আবার যাচাই করা হয়।
* অবস্থা (state) ও খোলা ট্রেডের তথ্য JSON ফাইলে রাখা হয়, তাই restart-এর পরও চলতে থাকে।

সফটওয়্যারের loop থেকে প্রতি ~১ সেকেন্ডে:
    bot = ClaudePullbackV1(log=my_log, notify=my_telegram)
    bot.run_once(active_strategy)        # "claude_pb_v1" বা "contest" হলে নতুন entry হবে
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import MetaTrader5 as mt5

VERSION = "1.0"
MAGIC = 26102401
GPT_MAGIC = 26102402
COMMENT = "CLAUDE_PB_v1"
NAME = "Claude Pullback v1"

# ---------------- ফিক্সড প্যারামিটার (PDF অধ্যায় ২) ----------------
SYMBOLS = ("BTCUSDm", "ETHUSDm", "XAUUSDm")
GOLD_SYMBOLS = ("XAUUSDm",)
CRYPTO_LOCK = ("BTCUSDm", "ETHUSDm")
EMA_FAST_H1, EMA_SLOW_H1 = 50, 200
ADX_PERIOD, ADX_MIN = 14, 20.0
EMA_PB, EMA_DEEP = 20, 50
RSI_PERIOD = 14
RSI_BUY_ZONE = (40.0, 50.0)
RSI_SELL_ZONE = (50.0, 60.0)
PB_MAX_BARS = 12
REARM_ATR = 1.0
SWING_LOOKBACK_H1, SWING_LEFT, SWING_RIGHT = 50, 2, 2
ROOM_MIN_R = 1.5
ATR_PERIOD = 14
SL_SWING_BARS, SL_BUFFER_ATR = 5, 0.3
SL_MIN_ATR, SL_MAX_ATR = 0.8, 2.5
TP1_R, TP2_R = 1.0, 2.5
TIME_STOP_BARS, MAX_HOLD_BARS = 16, 48
RISK_PER_TRADE = 1.0
MAX_DAILY_LOSSES = 2
LOSS_COUNT_THRESHOLD_R = -0.2
MAX_SPREAD_ATR = 0.15
GOLD_SESSION_UTC = (7, 20)
NEWS_WINDOW_MIN = 30
H1_BARS, M15_BARS = 600, 300
DEVIATION = 30
LIVE_STOP_DD = 0.20
LIVE_STOP_CONSEC = 8
M15_SEC = 900

WAIT_REARM, ARMED, PB_ACTIVE, IN_TRADE = "WAIT_REARM", "ARMED", "PB_ACTIVE", "IN_TRADE"
OK_RETCODES = (10008, 10009, 10010)        # PLACED, DONE, DONE_PARTIAL
RETRY_RETCODES = (10004, 10020, 10021)     # REQUOTE, PRICE_CHANGED, PRICE_OFF


class MT5Unavailable(Exception):
    """MT5 সাময়িকভাবে উত্তর দিচ্ছে না (positions_get / history_deals_get → None)।
    তখন "পজিশন নেই" ধরে নেওয়া যাবে না — এই চক্রে কিছু না করে পরের চক্রে আবার চেষ্টা।"""


def plan_partial_close(volume: float, si) -> Tuple[Optional[Tuple[float, float]], str]:
    """অর্ধেক বন্ধের পরিকল্পনা। ফেরত: ((close_vol, remaining_vol), "") অথবা (None, কারণ)।
    বন্ধের অংশ ও বাকি অংশ — দুটোই broker-এর volume_min, volume_max, volume_step মানতে হবে।"""
    step, vmin, vmax = float(si.volume_step), float(si.volume_min), float(si.volume_max)
    if step <= 0:
        return None, f"volume_step {step} <= 0"
    close = round(math.floor(volume / 2.0 / step + 1e-9) * step, 8)
    rem = round(volume - close, 8)

    def aligned(v):
        return abs(v / step - round(v / step)) < 1e-6

    if close < vmin - 1e-12:
        return None, f"close {close} < volume_min {vmin}"
    if rem < vmin - 1e-12:
        return None, f"remaining {rem} < volume_min {vmin}"
    if close > vmax + 1e-12 or rem > vmax + 1e-12:
        return None, f"close {close} / remaining {rem} > volume_max {vmax}"
    if not aligned(close) or not aligned(rem):
        return None, f"close {close} / remaining {rem} not a multiple of volume_step {step}"
    return (close, rem), ""


# ---------------- ইন্ডিকেটর (PDF অধ্যায় ৩) ----------------
def ema(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if len(x) < n:
        return out
    out[n - 1] = x[:n].mean()
    a = 2.0 / (n + 1)
    for i in range(n, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out


def _rma(x: np.ndarray, n: int, start: int) -> np.ndarray:
    """Wilder smoothing; x[start:start+n]-এর গড় দিয়ে শুরু।"""
    out = np.full(len(x), np.nan)
    if len(x) < start + n:
        return out
    out[start + n - 1] = x[start:start + n].mean()
    for i in range(start + n, len(x)):
        out[i] = (out[i - 1] * (n - 1) + x[i]) / n
    return out


def true_range(h, l, c):
    tr = np.empty(len(h))
    tr[0] = h[0] - l[0]
    pc = c[:-1]
    tr[1:] = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - pc), np.abs(l[1:] - pc)))
    return tr


def atr(h, l, c, n=ATR_PERIOD):
    return _rma(true_range(h, l, c), n, 0)


def rsi(c, n=RSI_PERIOD):
    d = np.diff(c, prepend=c[0])
    g = np.where(d > 0, d, 0.0)
    ls = np.where(d < 0, -d, 0.0)
    ag, al = _rma(g, n, 1), _rma(ls, n, 1)
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = ag / al
        out = 100 - 100 / (1 + rs)
    out = np.where((al == 0) & ~np.isnan(ag), 100.0, out)
    return out


def adx(h, l, c, n=ADX_PERIOD):
    up = np.diff(h, prepend=h[0])
    dn = -np.diff(l, prepend=l[0])
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    mdm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = true_range(h, l, c)
    atr_ = _rma(tr, n, 1)
    with np.errstate(divide="ignore", invalid="ignore"):
        pdi = 100 * _rma(pdm, n, 1) / atr_
        mdi = 100 * _rma(mdm, n, 1) / atr_
        dx = 100 * np.abs(pdi - mdi) / (pdi + mdi)
    first = n                      # dx-এর প্রথম বৈধ index
    dx = np.nan_to_num(dx, nan=0.0)
    return _rma(dx, n, first)


def swings(h, l, left=SWING_LEFT, right=SWING_RIGHT):
    highs, lows = [], []
    for i in range(left, len(h) - right):
        if all(h[i] > h[j] for j in range(i - left, i)) and all(h[i] > h[j] for j in range(i + 1, i + right + 1)):
            highs.append(float(h[i]))
        if all(l[i] < l[j] for j in range(i - left, i)) and all(l[i] < l[j] for j in range(i + 1, i + right + 1)):
            lows.append(float(l[i]))
    return highs, lows


# ---------------- নিউজ ফিল্টার (অধ্যায় ১১.২) ----------------
class NewsFilter:
    URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

    def __init__(self, cache_file="claude_news_cache.json", fetcher: Optional[Callable[[], list]] = None):
        self.cache_file = cache_file
        self.fetcher = fetcher
        self.events: List[datetime] = []
        self.fetched_at: Optional[datetime] = None
        self.week_ok = False
        self._load_cache()

    def _download(self) -> list:
        if self.fetcher:
            return self.fetcher()
        import requests
        r = requests.get(self.URL, timeout=10)
        r.raise_for_status()
        return r.json()

    def _parse(self, raw: list) -> List[datetime]:
        out = []
        for e in raw:
            if str(e.get("country", "")).upper() == "USD" and str(e.get("impact", "")).lower() == "high":
                try:
                    out.append(datetime.fromisoformat(str(e["date"])).astimezone(timezone.utc))
                except Exception:
                    pass
        return out

    def _load_cache(self):
        try:
            with open(self.cache_file, "r", encoding="utf-8") as f:
                d = json.load(f)
            self.events = [datetime.fromisoformat(x) for x in d["events"]]
            self.fetched_at = datetime.fromisoformat(d["fetched_at"])
        except Exception:
            pass

    def _save_cache(self):
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump({"fetched_at": self.fetched_at.isoformat(),
                           "events": [e.isoformat() for e in self.events]}, f)
        except Exception:
            pass

    def refresh(self, now: datetime):
        if self.fetched_at and now - self.fetched_at < timedelta(hours=6):
            return
        try:
            self.events = self._parse(self._download())
            self.fetched_at = now
            self._save_cache()
        except Exception:
            pass                                  # cache থাকলে সেটাই চলবে

    def status(self, now: datetime) -> str:
        """'OK' | 'BLOCK' | 'UNAVAILABLE'"""
        self.refresh(now)
        same_week = self.fetched_at is not None and \
            self.fetched_at.isocalendar()[:2] == now.isocalendar()[:2]
        if not same_week:
            return "UNAVAILABLE"
        w = timedelta(minutes=NEWS_WINDOW_MIN)
        return "BLOCK" if any(e - w <= now <= e + w for e in self.events) else "OK"


# ---------------- মূল বট ----------------
class ClaudePullbackV1:
    def __init__(self, state_file: str = "claude_pb_v1_state.json",
                 log: Optional[Callable[[str], None]] = None,
                 notify: Optional[Callable[[str], None]] = None,
                 clock: Optional[Callable[[], datetime]] = None,
                 news: Optional[NewsFilter] = None,
                 symbols_enabled: Optional[Dict[str, bool]] = None):
        self.state_file = state_file
        self.log = log or (lambda s: print(s))
        self.notify = notify or (lambda s: None)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.news = news or NewsFilter()
        self.enabled = {s: True for s in SYMBOLS}
        if symbols_enabled:
            self.enabled.update(symbols_enabled)
        self.state: Dict[str, Dict[str, Any]] = {s: self._fresh_state() for s in SYMBOLS}
        self.trades: Dict[str, Dict[str, Any]] = {}     # position ticket -> তথ্য
        self.closed: List[Dict[str, Any]] = []          # বন্ধ ট্রেডের সারাংশ (দৈনিক সীমা, live stop)
        self.halted = False
        self.start_balance: Optional[float] = None
        self._last_bar: Dict[str, int] = {}
        self._load()

    # ---------- state সংরক্ষণ ----------
    @staticmethod
    def _fresh_state():
        return {"phase": WAIT_REARM, "trend": "NONE", "pb_bars": 0, "ext_rsi": None, "last_code": ""}

    def _load(self):
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                d = json.load(f)
            if d.get("version") != VERSION:
                return
            for s in SYMBOLS:
                if s in d.get("state", {}):
                    self.state[s].update(d["state"][s])
            self.trades = {str(k): v for k, v in d.get("trades", {}).items()}
            self.closed = d.get("closed", [])
            self.halted = d.get("halted", False)
            self.start_balance = d.get("start_balance")
            self._last_bar = d.get("last_bar", {})
        except FileNotFoundError:
            pass
        except Exception as e:
            self.log(f"[{NAME}] state file unreadable, starting fresh: {e}")

    def _save(self):
        tmp = self.state_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"version": VERSION, "state": self.state, "trades": self.trades, "closed": self.closed[-500:],
                       "halted": self.halted, "start_balance": self.start_balance,
                       "last_bar": self._last_bar}, f, indent=1)
        os.replace(tmp, self.state_file)            # অর্ধেক লেখা ফাইল এড়াতে

    # ---------- সাহায্যকারী ----------
    @staticmethod
    def _rates(symbol, tf, count):
        r = mt5.copy_rates_from_pos(symbol, tf, 1, count)   # 1 = চলতি candle বাদ
        if r is None or len(r) < count:
            return None
        return r

    def _own_positions(self, symbol=None):
        ps = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
        if ps is None:
            raise MT5Unavailable(f"positions_get(symbol={symbol}) = None {mt5.last_error()}")
        return [p for p in ps if p.magic == MAGIC]

    def _position(self, ticket: int):
        ps = mt5.positions_get(ticket=int(ticket))
        if ps is None:                                       # error ≠ "পজিশন নেই"
            raise MT5Unavailable(f"positions_get(ticket={ticket}) = None {mt5.last_error()}")
        if ps:
            p = ps[0]
            return p if p.magic == MAGIC else None          # অন্য কারো পজিশন — কখনো ছোঁব না
        return None

    def _session_ok(self, symbol, now):
        if now.weekday() >= 5:
            return False
        if symbol in GOLD_SYMBOLS:
            return GOLD_SESSION_UTC[0] <= now.hour < GOLD_SESSION_UTC[1]
        return True

    def _today_losses(self, now):
        day = now.date().isoformat()
        return sum(1 for c in self.closed if c["day"] == day and c["r"] is not None and c["r"] <= LOSS_COUNT_THRESHOLD_R)

    def _log_bar(self, symbol, now, code, extra=""):
        st = self.state[symbol]
        self.state[symbol]["last_code"] = code
        self.log(f"{now:%Y-%m-%d %H:%M} UTC | {symbol} | H1 {st['trend']} | STATE {st['phase']}"
                 f"{(' bar ' + str(st['pb_bars']) + '/12') if st['phase'] == PB_ACTIVE else ''}"
                 f" | {code}{(' | ' + extra) if extra else ''}")

    # ---------- স্তর ১: দিক ----------
    def _trend(self, h1):
        c, h, l = h1["close"], h1["high"], h1["low"]
        e50, e200, a = ema(c, EMA_FAST_H1), ema(c, EMA_SLOW_H1), adx(h, l, c)
        cl, f, s, ax = c[-1], e50[-1], e200[-1], a[-1]
        if any(np.isnan(v) for v in (f, s, ax)):
            return "NONE", "SKIP_NO_HISTORY", ax
        if cl > s and f > s:
            t = "BUY"
        elif cl < s and f < s:
            t = "SELL"
        else:
            return "NONE", "NO_TREND", ax
        if ax < ADX_MIN:
            return "NONE", "ADX_LOW", ax
        return t, "", ax

    # ---------- মূল চক্র ----------
    def run_once(self, active_strategy: str) -> None:
        """প্রতি সেকেন্ডে ডাকুন। ম্যানেজমেন্ট সবসময় চলে; নতুন entry শুধু সক্রিয় থাকলে।"""
        self.manage_open_trades()
        if active_strategy not in ("claude_pb_v1", "contest") or self.halted:
            return
        for s in SYMBOLS:
            if not self.enabled.get(s):
                continue
            r = mt5.copy_rates_from_pos(s, mt5.TIMEFRAME_M15, 1, 1)
            if r is None or len(r) == 0:
                continue
            t = int(r[-1]["time"])
            if self._last_bar.get(s) == t:
                continue
            self._last_bar[s] = t
            try:
                self.on_new_bar(s, active_strategy)
            except Exception as e:
                self.log(f"[{NAME}] {s} error: {type(e).__name__}: {e}")
            self._save()

    def on_new_bar(self, s: str, active: str):
        now = self.clock()
        st = self.state[s]
        h1 = self._rates(s, mt5.TIMEFRAME_H1, H1_BARS)
        m15 = self._rates(s, mt5.TIMEFRAME_M15, M15_BARS)
        if h1 is None or m15 is None:
            return self._log_bar(s, now, "SKIP_NO_HISTORY")
        trend, why, ax = self._trend(h1)
        if trend != st["trend"]:
            st["trend"] = trend
            if st["phase"] != IN_TRADE:
                st.update(phase=WAIT_REARM, pb_bars=0, ext_rsi=None)
        if trend == "NONE":
            return self._log_bar(s, now, why)
        if st["phase"] == IN_TRADE:
            return self._log_bar(s, now, "IN_TRADE")

        c, h, l = m15["close"], m15["high"], m15["low"]
        e20, e50 = ema(c, EMA_PB)[-1], ema(c, EMA_DEEP)[-1]
        a, r = atr(h, l, c)[-1], rsi(c)[-1]
        if any(np.isnan(v) for v in (e20, e50, a, r)) or a <= 0:
            return self._log_bar(s, now, "SKIP_NO_HISTORY")
        d = 1 if trend == "BUY" else -1
        bar_c, bar_h, bar_l = c[-1], h[-1], l[-1]
        prev_h, prev_l = h[-2], l[-2]
        info = f"E20 {e20:.2f} E50 {e50:.2f} ATR {a:.2f} RSI {r:.1f} ADX {ax:.1f}"

        if st["phase"] == WAIT_REARM:
            if d * (bar_c - e20) >= REARM_ATR * a:
                st["phase"] = ARMED
            return self._log_bar(s, now, st["phase"], info)

        if st["phase"] == ARMED:
            touched = bar_l <= e20 if d > 0 else bar_h >= e20
            if not touched:
                return self._log_bar(s, now, ARMED, info)
            st.update(phase=PB_ACTIVE, pb_bars=0, ext_rsi=float(r))

        st["pb_bars"] += 1
        st["ext_rsi"] = min(st["ext_rsi"], float(r)) if d > 0 else max(st["ext_rsi"], float(r))

        if d * (bar_c - e50) < 0:
            st.update(phase=WAIT_REARM)
            return self._log_bar(s, now, "PB_INVALID_EMA50", info)
        if (d > 0 and r < RSI_BUY_ZONE[0]) or (d < 0 and r > RSI_SELL_ZONE[1]):
            st.update(phase=WAIT_REARM)
            return self._log_bar(s, now, "PB_INVALID_RSI", info)

        trigger = (bar_c > prev_h and bar_c > e20) if d > 0 else (bar_c < prev_l and bar_c < e20)
        zone = RSI_BUY_ZONE if d > 0 else RSI_SELL_ZONE
        rsi_ok = zone[0] <= st["ext_rsi"] <= zone[1]
        if trigger and not rsi_ok:
            code = "PB_SHALLOW"
        elif trigger:
            code = self._try_entry(s, d, m15, h1, a, now, active, int(m15["time"][-1]) + M15_SEC)
        else:
            code = "NO_TRIGGER"

        if code == "ENTRY":
            st["phase"] = IN_TRADE
        elif st["pb_bars"] >= PB_MAX_BARS:
            st["phase"] = WAIT_REARM
            code = "PB_EXPIRED" if code in ("NO_TRIGGER", "PB_SHALLOW") else code + "+PB_EXPIRED"
        self._log_bar(s, now, code, info + f" extRSI {st['ext_rsi']:.1f}")

    # ---------- অধ্যায় ১২: entry চেকলিস্ট ----------
    def _try_entry(self, s, d, m15, h1, a, now, active, entry_bar_time) -> str:
        ti, ai = mt5.terminal_info(), mt5.account_info()
        if not ti or not ai or not getattr(ti, "trade_allowed", True):
            return "SKIP_TERMINAL"
        if not self._session_ok(s, now):
            return "SKIP_SESSION"
        if s in GOLD_SYMBOLS:
            ns = self.news.status(now)
            if ns == "BLOCK":
                return "SKIP_NEWS"
            if ns == "UNAVAILABLE":
                return "SKIP_NEWS_UNAVAILABLE"
        if self._today_losses(now) >= MAX_DAILY_LOSSES:
            return "SKIP_DAILY_LIMIT"
        sym_pos = mt5.positions_get(symbol=s)
        if sym_pos is None:                        # MT5 উত্তর দিচ্ছে না — ঝুঁকি নেব না
            return "SKIP_TERMINAL"
        for p in sym_pos:
            if active == "contest" and p.magic == GPT_MAGIC:
                continue                           # প্রতিযোগীর পজিশন আমাকে আটকাবে না
            return "SKIP_POSITION_EXISTS"
        if s in CRYPTO_LOCK:
            other = [x for x in CRYPTO_LOCK if x != s]
            try:
                if any(self._own_positions(o) for o in other):
                    return "SKIP_CORRELATION"
            except MT5Unavailable:
                return "SKIP_TERMINAL"
        tick, si = mt5.symbol_info_tick(s), mt5.symbol_info(s)
        if tick is None or si is None:
            return "SKIP_TERMINAL"
        if (tick.ask - tick.bid) > MAX_SPREAD_ATR * a:
            return "SKIP_SPREAD"
        entry = float(tick.ask if d > 0 else tick.bid)
        lows, highs = m15["low"][-SL_SWING_BARS:], m15["high"][-SL_SWING_BARS:]
        sl = float(lows.min() - SL_BUFFER_ATR * a) if d > 0 else float(highs.max() + SL_BUFFER_ATR * a)
        dist = abs(entry - sl)
        if (d > 0 and sl >= entry) or (d < 0 and sl <= entry) or dist < SL_MIN_ATR * a:
            return "SKIP_SL_SMALL"
        if dist > SL_MAX_ATR * a:
            return "SKIP_SL_BIG"
        if dist < si.trade_stops_level * si.point:
            return "SKIP_SL_SMALL"
        hs, ls = swings(h1["high"][-SWING_LOOKBACK_H1:], h1["low"][-SWING_LOOKBACK_H1:])
        walls = [x for x in hs if x > entry] if d > 0 else [x for x in ls if x < entry]
        if walls:
            wall = min(walls) if d > 0 else max(walls)
            if abs(wall - entry) < ROOM_MIN_R * dist:
                return "SKIP_LOCATION"
        risk_money = float(ai.balance) * RISK_PER_TRADE / 100.0
        otype = mt5.ORDER_TYPE_BUY if d > 0 else mt5.ORDER_TYPE_SELL
        loss = mt5.order_calc_profit(otype, s, 1.0, entry, sl)
        if loss is None or abs(loss) <= 0:
            return "SKIP_TERMINAL"
        step = float(si.volume_step)
        lot = math.floor(risk_money / abs(loss) / step + 1e-9) * step
        lot = round(min(lot, float(si.volume_max)), 8)
        if lot < float(si.volume_min):
            return "SKIP_LOT_TOO_SMALL"
        digits = int(si.digits)
        tp1 = round(entry + d * TP1_R * dist, digits)
        tp2 = round(entry + d * TP2_R * dist, digits)
        sl = round(sl, digits)
        res = self._send({"action": mt5.TRADE_ACTION_DEAL, "symbol": s, "volume": lot, "type": otype,
                          "sl": sl, "tp": tp2}, s, d)
        if res is None:
            return "ORDER_FAILED"
        ticket = int(res.order)
        try:
            pos = self._position(ticket)
        except MT5Unavailable:
            pos = None
        if pos is None and getattr(res, "deal", 0):      # কিছু broker-এ position ticket ≠ order ticket
            dl = mt5.history_deals_get(ticket=int(res.deal)) or ()
            if dl:
                ticket = int(dl[0].position_id)
                try:
                    pos = self._position(ticket)
                except MT5Unavailable:
                    pos = None
        entry_fill = float(pos.price_open) if pos else entry
        if self.start_balance is None:
            self.start_balance = float(ai.balance)
        self.trades[str(ticket)] = {
            "symbol": s, "side": "BUY" if d > 0 else "SELL", "entry": entry_fill, "sl": sl,
            "tp1": tp1, "tp2": tp2, "lot": lot, "risk_money": abs(loss) * lot,
            "entry_bar_time": entry_bar_time, "tp1_done": False, "open_utc": now.isoformat()}
        self.notify(f"🟦 {NAME} — ট্রেড খোলা\n{s} {'BUY' if d > 0 else 'SELL'} {lot} lot @ {entry_fill}\n"
                    f"SL {sl} (1R = {dist:.2f} · {dist / a:.2f} ATR)\nTP1 {tp1} · TP2 {tp2}\n"
                    f"ঝুঁকি ${abs(loss) * lot:.2f}")
        return "ENTRY"

    def _send(self, req: Dict[str, Any], s: str, d: int, position: Optional[int] = None):
        """order পাঠানো: filling mode বদলে চেষ্টা, requote হলে সর্বোচ্চ ২ বার নতুন দামে।"""
        last = None
        for attempt in range(3):
            tick = mt5.symbol_info_tick(s)
            if tick is None:
                return None
            req = dict(req, price=float(tick.ask if d > 0 else tick.bid), deviation=DEVIATION,
                       magic=MAGIC, comment=COMMENT, type_time=mt5.ORDER_TIME_GTC)
            if position is not None:
                req["position"] = int(position)
            for filling in (mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_RETURN):
                req["type_filling"] = filling
                last = mt5.order_send(req)
                if last is None:
                    # ফল অজানা (order হয়তো পৌঁছেছে) — আবার পাঠালে দ্বিগুণ পজিশনের ঝুঁকি, তাই থামি
                    self.log(f"[{NAME}] order_send returned None for {s} ({mt5.last_error()}) — not resending")
                    return None
                if last.retcode in OK_RETCODES:
                    return last
                if last is not None and last.retcode in RETRY_RETCODES:
                    break
            if last is None or last.retcode not in RETRY_RETCODES:
                break
        self.log(f"[{NAME}] order failed {s}: retcode {getattr(last, 'retcode', None)} "
                 f"{getattr(last, 'comment', '')} {mt5.last_error()}")
        return None

    # ---------- অধ্যায় ৯: ট্রেড ম্যানেজমেন্ট ----------
    def _close(self, pos, volume: float, reason: str) -> bool:
        if pos.magic != MAGIC:                     # দ্বিতীয় নিরাপত্তা চেক
            return False
        d = -1 if pos.type == mt5.POSITION_TYPE_BUY else 1   # বন্ধ করতে উল্টো order
        otype = mt5.ORDER_TYPE_SELL if pos.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
        ok = self._send({"action": mt5.TRADE_ACTION_DEAL, "symbol": pos.symbol, "volume": volume,
                         "type": otype}, pos.symbol, d, position=pos.ticket) is not None
        if ok:
            self.log(f"[{NAME}] {pos.symbol} #{pos.ticket} {reason} {volume} lot")
        return ok

    def _modify_sl(self, pos, sl: float, tp: float) -> bool:
        if pos.magic != MAGIC:
            return False
        r = mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "symbol": pos.symbol, "position": int(pos.ticket),
                            "sl": sl, "tp": tp, "magic": MAGIC})
        return r is not None and r.retcode in OK_RETCODES

    def manage_open_trades(self):
        if not self.trades:
            return
        try:
            self._manage_open_trades()
        except MT5Unavailable as e:                  # সংযোগ নেই: কিছু বন্ধ/মুছে না দিয়ে পরের চক্রে আবার
            self.log(f"[{NAME}] MT5 unavailable — trade management skipped this cycle: {e}")

    def _manage_open_trades(self):
        now = self.clock()
        changed = False
        for key, t in list(self.trades.items()):
            pos = self._position(int(key))
            if pos is None:
                self._record_close(int(key), t, now)
                changed = True
                continue
            tick = mt5.symbol_info_tick(t["symbol"])
            si = mt5.symbol_info(t["symbol"])
            if tick is None or si is None:
                continue
            buy = t["side"] == "BUY"
            price = tick.bid if buy else tick.ask
            if not t["tp1_done"] and ((buy and price >= t["tp1"]) or (not buy and price <= t["tp1"])):
                plan, why = plan_partial_close(float(pos.volume), si)
                if plan:
                    self._close(pos, plan[0], "EXIT_TP1")
                else:
                    self.log(f"[{NAME}] {t['symbol']} #{key} TP1 partial close skipped ({why}) — SL→BE only")
                pos2 = self._position(int(key))
                if pos2 is not None:
                    self._modify_sl(pos2, round(t["entry"], int(si.digits)), pos2.tp)
                t["tp1_done"] = True
                changed = True
                self.notify(f"🟦 {NAME} — TP1 ✓\n{t['symbol']} #{key}\nSL → breakeven {t['entry']}")
                pos = self._position(int(key))
                if pos is None:
                    continue
            r = mt5.copy_rates_from_pos(t["symbol"], mt5.TIMEFRAME_M15, 1, 1)
            if r is not None and len(r):
                last_closed = int(r[-1]["time"])
                bars = (last_closed - t["entry_bar_time"]) // M15_SEC + 1 if last_closed >= t["entry_bar_time"] else 0
                if not t["tp1_done"] and bars >= TIME_STOP_BARS:
                    if self._close(pos, pos.volume, "EXIT_TIME"):
                        t["exit_hint"] = "EXIT_TIME"
                        changed = True
                elif bars >= MAX_HOLD_BARS:
                    if self._close(pos, pos.volume, "EXIT_MAXHOLD"):
                        t["exit_hint"] = "EXIT_MAXHOLD"
                        changed = True
        if changed:
            self._save()

    def _record_close(self, ticket: int, t: Dict[str, Any], now: datetime):
        deals = mt5.history_deals_get(position=ticket)
        if deals is None:                            # history পাওয়া যায়নি — ভুল নিট লিখব না
            raise MT5Unavailable(f"history_deals_get(position={ticket}) = None {mt5.last_error()}")
        net = sum(float(d.profit) + float(d.commission) + float(d.swap) + float(getattr(d, "fee", 0.0)) for d in deals)
        r = net / t["risk_money"] if t.get("risk_money") else None
        self.closed.append({"ticket": ticket, "symbol": t["symbol"], "net": round(net, 2), "r": r,
                            "day": now.date().isoformat()})
        self.trades.pop(str(ticket), None)
        st = self.state[t["symbol"]]
        if st["phase"] == IN_TRADE:
            st.update(phase=WAIT_REARM, pb_bars=0, ext_rsi=None)
        day_losses = self._today_losses(now)
        self.notify(f"🟦 {NAME} — ট্রেড বন্ধ\n{t['symbol']} #{ticket}\nনিট ${net:+.2f}"
                    f"{'' if r is None else f' ({r:+.2f}R)'}\nআজ লস {day_losses}/{MAX_DAILY_LOSSES}")
        self.log(f"[{NAME}] closed #{ticket} {t['symbol']} net {net:+.2f}")
        self._check_live_stop()

    def _check_live_stop(self):
        """অধ্যায় ১৮.৫: drawdown ২০% বা পরপর ৮ লস → নিজে বন্ধ।"""
        consec = 0
        for c in reversed(self.closed):
            if c["r"] is not None and c["r"] <= LOSS_COUNT_THRESHOLD_R:
                consec += 1
            elif c["r"] is not None and c["r"] > 0.1:
                break
        eq = peak = 0.0
        dd = 0.0
        for c in self.closed:
            eq += c["net"]
            peak = max(peak, eq)
            dd = max(dd, peak - eq)
        base = self.start_balance or 0
        if consec >= LIVE_STOP_CONSEC or (base > 0 and dd >= LIVE_STOP_DD * base):
            if not self.halted:
                self.halted = True
                self.notify(f"🛑 {NAME} নিজে থেকে বন্ধ হয়েছে (পরপর লস {consec}, drawdown ${dd:.2f}). বিশ্লেষণ করে সিদ্ধান্ত নিন।")
