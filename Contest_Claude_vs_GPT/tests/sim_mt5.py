"""
নকল (simulated) MT5 broker — শুধু পরীক্ষার জন্য। আসল বাজার নয়, আসল টাকা নয়।

* Hedging বা Netting অ্যাকাউন্ট
* broker server time = UTC + SERVER_OFFSET (ইচ্ছে করে আলাদা রাখা যায়)
* প্রতিটা M15 candle-এর ভেতরে ৪টা tick: open → (low/high) → close; প্রতিটা tick-এ SL/TP চেক
* প্রতিটা order_send request রেকর্ড হয়, মালিকানা যাচাইয়ের জন্য
"""
from types import SimpleNamespace as NS
from datetime import datetime, timezone
import numpy as np

# ---- MT5 constants ----
TIMEFRAME_M15, TIMEFRAME_H1 = 15, 16385
ORDER_TYPE_BUY, ORDER_TYPE_SELL = 0, 1
POSITION_TYPE_BUY, POSITION_TYPE_SELL = 0, 1
TRADE_ACTION_DEAL, TRADE_ACTION_SLTP = 1, 6
ORDER_FILLING_FOK, ORDER_FILLING_IOC, ORDER_FILLING_RETURN = 0, 1, 2
ORDER_TIME_GTC = 0
TRADE_RETCODE_DONE, TRADE_RETCODE_PLACED, TRADE_RETCODE_DONE_PARTIAL = 10009, 10008, 10010
ACCOUNT_MARGIN_MODE_RETAIL_NETTING, ACCOUNT_MARGIN_MODE_RETAIL_HEDGING = 0, 2
ACCOUNT_TRADE_MODE_DEMO, ACCOUNT_TRADE_MODE_REAL = 0, 2
DEAL_REASON_EXPERT, DEAL_REASON_SL, DEAL_REASON_TP = 3, 4, 5

SPEC = {  # contract, digits, spread, commission per lot per side
    "BTCUSDm": dict(contract=1.0, digits=2, spread=8.0, comm=0.0),
    "ETHUSDm": dict(contract=1.0, digits=2, spread=0.4, comm=0.0),
    "XAUUSDm": dict(contract=100.0, digits=3, spread=0.12, comm=0.05),
}


class Broker:
    def __init__(self, margin_mode=ACCOUNT_MARGIN_MODE_RETAIL_HEDGING, trade_mode=ACCOUNT_TRADE_MODE_DEMO,
                 server_offset_h=3, balance=10000.0, seed=11, n_bars=7000, start_utc=datetime(2026, 3, 2, tzinfo=timezone.utc)):
        self.margin_mode, self.trade_mode = margin_mode, trade_mode
        self.offset = int(server_offset_h * 3600)
        self.balance = balance
        self.t0 = int(start_utc.timestamp())
        self.m15 = {s: self._gen(i + seed, n_bars, s) for i, s in enumerate(SPEC)}
        self.h1 = {s: self._to_h1(a) for s, a in self.m15.items()}
        self.pos_idx = 0                  # চলতি (গঠনরত) candle-এর index
        self.tick_i = 0                   # candle-এর ভেতরের tick (0..3)
        self.positions = {}               # ticket -> NS
        self.deals, self.orders, self.requests = [], [], []
        self._ticket = 5000
        self.truth = {}                   # position_id -> {"magic","symbol","net"}

    # ---------- ডেটা ----------
    def _gen(self, seed, n, s):
        r = np.random.default_rng(seed)
        base = {"BTCUSDm": 80000.0, "ETHUSDm": 2400.0, "XAUUSDm": 2650.0}[s]
        vol = base * 0.0016
        drift = np.zeros(n)
        i = 0
        while i < n:                       # পালা করে ট্রেন্ড ও sideways অংশ
            L = int(r.integers(150, 500))
            drift[i:i + L] = r.choice([-1, 0, 1]) * vol * r.uniform(0.08, 0.22)
            i += L
        c = base + np.cumsum(r.normal(0, vol, n) + drift)
        c = np.maximum(c, base * 0.3)
        o = np.r_[c[0], c[:-1]]
        h = np.maximum(o, c) + np.abs(r.normal(0, vol * 0.5, n))
        l = np.minimum(o, c) - np.abs(r.normal(0, vol * 0.5, n))
        a = np.zeros(n, dtype=[("time", "i8"), ("open", "f8"), ("high", "f8"), ("low", "f8"), ("close", "f8"),
                               ("tick_volume", "i8"), ("spread", "i4"), ("real_volume", "i8")])
        a["time"] = self.t0 + np.arange(n) * 900 + 0   # UTC; server offset যোগ হয় পড়ার সময়
        a["open"], a["high"], a["low"], a["close"] = o, h, l, c
        return a

    @staticmethod
    def _to_h1(m):
        n = len(m) // 4
        h = np.zeros(n, dtype=m.dtype)
        for i in range(n):
            s = m[i * 4:i * 4 + 4]
            h[i] = (s["time"][0], s["open"][0], s["high"].max(), s["low"].min(), s["close"][-1], 0, 0, 0)
        return h

    def now_utc_ts(self):
        return self.t0 + self.pos_idx * 900 + self.tick_i * 225

    def now_utc(self):
        return datetime.fromtimestamp(self.now_utc_ts(), tz=timezone.utc)

    def server_ts(self):
        return self.now_utc_ts() + self.offset

    def _price(self, s):
        b = self.m15[s][self.pos_idx]
        up = b["close"] >= b["open"]
        path = [b["open"], b["low"] if up else b["high"], b["high"] if up else b["low"], b["close"]]
        return float(path[self.tick_i])

    def _nt(self):
        self._ticket += 1
        return self._ticket

    # ---------- সময় এগোনো ----------
    def advance_tick(self):
        """পরের tick-এ যাও, তারপর সব পজিশনের SL/TP চেক।"""
        self.tick_i += 1
        if self.tick_i == 4:
            self.tick_i = 0
            self.pos_idx += 1
        self._check_stops()

    def _check_stops(self):
        for t, p in list(self.positions.items()):
            bid = self._price(p.symbol)
            ask = bid + SPEC[p.symbol]["spread"]
            if p.type == POSITION_TYPE_BUY:
                if p.sl and bid <= p.sl:
                    self._close(p, p.volume, p.sl, DEAL_REASON_SL, p.magic)
                elif p.tp and bid >= p.tp:
                    self._close(p, p.volume, p.tp, DEAL_REASON_TP, p.magic)
            else:
                if p.sl and ask >= p.sl:
                    self._close(p, p.volume, p.sl, DEAL_REASON_SL, p.magic)
                elif p.tp and ask <= p.tp:
                    self._close(p, p.volume, p.tp, DEAL_REASON_TP, p.magic)

    # ---------- হিসাব ----------
    def _pnl(self, s, typ, vol, open_p, close_p):
        d = (close_p - open_p) if typ == POSITION_TYPE_BUY else (open_p - close_p)
        return d * vol * SPEC[s]["contract"]

    def _deal(self, p, entry, vol, price, profit, reason, magic, order):
        comm = -SPEC[p.symbol]["comm"] * vol
        ts = self.server_ts()
        d = NS(ticket=self._nt(), order=order, position_id=p.ticket, magic=magic, symbol=p.symbol, entry=entry,
               type=(p.type if entry == 0 else 1 - p.type), volume=vol, price=price, profit=round(profit, 2),
               commission=round(comm, 2), swap=0.0, fee=0.0, time=ts, time_msc=ts * 1000 + len(self.deals),
               reason=reason, comment="")
        self.deals.append(d)
        self.balance += d.profit + d.commission
        tr = self.truth.setdefault(p.ticket, {"magic": p.magic, "symbol": p.symbol, "net": 0.0, "closed": False})
        tr["net"] += d.profit + d.commission
        return d

    def _close(self, p, vol, price, reason, magic, order=0):
        vol = round(min(vol, p.volume), 8)
        prof = self._pnl(p.symbol, p.type, vol, p.price_open, price)
        d = self._deal(p, 1, vol, price, prof, reason, magic, order)
        p.volume = round(p.volume - vol, 8)
        if p.volume <= 1e-9:
            del self.positions[p.ticket]
            self.truth[p.ticket]["closed"] = True
        return d

    # ================= MT5 API =================
    def terminal_info(self):
        return NS(connected=True, trade_allowed=True)

    def account_info(self):
        return NS(login=1234567, balance=round(self.balance, 2), margin_mode=self.margin_mode,
                  trade_mode=self.trade_mode, trade_allowed=True)

    def symbol_select(self, s, enable=True):
        return s in SPEC

    def symbol_info(self, s):
        if s not in SPEC:
            return None
        sp = SPEC[s]
        return NS(name=s, digits=sp["digits"], point=10 ** -sp["digits"], volume_step=0.01, volume_min=0.01, trade_contract_size=sp["contract"],
                  volume_max=100.0, trade_stops_level=0, filling_mode=3)

    def symbol_info_tick(self, s):
        if s not in SPEC:
            return None
        bid = self._price(s)
        return NS(bid=bid, ask=bid + SPEC[s]["spread"], time=self.server_ts())

    def copy_rates_from_pos(self, s, tf, start, count):
        if tf == TIMEFRAME_M15:
            end = self.pos_idx - (start - 1)              # start=1 → গঠনরত candle বাদ
            a = self.m15[s][max(0, end - count):end].copy()
        else:
            closed_h1 = self.pos_idx // 4                 # সম্পূর্ণ বন্ধ H1 candle
            end = closed_h1 - (start - 1)
            a = self.h1[s][max(0, end - count):end].copy()
        a["time"] += self.offset
        return a

    def positions_get(self, symbol=None, ticket=None):
        ps = list(self.positions.values())
        if symbol is not None:
            ps = [p for p in ps if p.symbol == symbol]
        if ticket is not None:
            ps = [p for p in ps if p.ticket == ticket]
        out = []
        for p in ps:
            bid = self._price(p.symbol)
            cp = bid if p.type == POSITION_TYPE_BUY else bid + SPEC[p.symbol]["spread"]
            out.append(NS(**{**vars(p), "profit": round(self._pnl(p.symbol, p.type, p.volume, p.price_open, cp), 2)}))
        return tuple(out)

    def history_deals_get(self, a=None, b=None, position=None, ticket=None):
        ds = self.deals
        if position is not None:
            return tuple(d for d in ds if d.position_id == position)
        if ticket is not None:
            return tuple(d for d in ds if d.ticket == ticket)
        lo, hi = a.timestamp(), b.timestamp()
        return tuple(d for d in ds if lo <= d.time <= hi)

    def history_orders_get(self, position=None):
        return tuple(o for o in self.orders if o.position_id == position)

    def order_calc_profit(self, otype, s, vol, open_p, close_p):
        return self._pnl(s, POSITION_TYPE_BUY if otype == ORDER_TYPE_BUY else POSITION_TYPE_SELL, vol, open_p, close_p)

    def last_error(self):
        return (1, "Success")

    def order_send(self, req):
        req = dict(req)
        rec = {"req": req, "time": self.now_utc_ts(), "target_magic": None}
        self.requests.append(rec)
        s = req["symbol"]
        tick = self.symbol_info_tick(s)
        if req["action"] == TRADE_ACTION_SLTP:
            p = self.positions.get(req.get("position"))
            if p is None:
                return NS(retcode=10013, order=0, deal=0, comment="invalid position")
            rec["target_magic"] = p.magic
            p.sl, p.tp = float(req.get("sl", p.sl)), float(req.get("tp", p.tp))
            return NS(retcode=TRADE_RETCODE_DONE, order=0, deal=0, comment="done")
        typ = req["type"]
        price = tick.ask if typ == ORDER_TYPE_BUY else tick.bid
        order_t = self._nt()
        if req.get("position"):                       # নির্দিষ্ট পজিশন বন্ধ
            p = self.positions.get(req["position"])
            if p is None:
                return NS(retcode=10013, order=0, deal=0, comment="invalid position")
            rec["target_magic"] = p.magic
            d = self._close(p, float(req["volume"]), price, DEAL_REASON_EXPERT, req.get("magic", 0), order_t)
            return NS(retcode=TRADE_RETCODE_DONE, order=order_t, deal=d.ticket, comment="done", volume=d.volume)
        if self.margin_mode == ACCOUNT_MARGIN_MODE_RETAIL_NETTING:
            for p in list(self.positions.values()):    # netting: একই symbol-এ একটাই পজিশন
                if p.symbol == s:
                    rec["target_magic"] = p.magic
                    if p.type != typ:
                        d = self._close(p, float(req["volume"]), price, DEAL_REASON_EXPERT, req.get("magic", 0), order_t)
                        return NS(retcode=TRADE_RETCODE_DONE, order=order_t, deal=d.ticket, comment="netted")
                    p.volume += float(req["volume"])
                    return NS(retcode=TRADE_RETCODE_DONE, order=order_t, deal=0, comment="netted add")
        p = NS(ticket=order_t, identifier=order_t, magic=req.get("magic", 0), symbol=s, type=typ,
               volume=float(req["volume"]), price_open=price, sl=float(req.get("sl", 0.0)),
               tp=float(req.get("tp", 0.0)), swap=0.0, time=self.server_ts(), comment=req.get("comment", ""))
        self.positions[order_t] = p
        self.orders.append(NS(ticket=order_t, position_id=order_t, time_setup_msc=self.server_ts() * 1000,
                              sl=p.sl, tp=p.tp, magic=p.magic))
        d = self._deal(p, 0, p.volume, price, 0.0, DEAL_REASON_EXPERT, p.magic, order_t)
        return NS(retcode=TRADE_RETCODE_DONE, order=order_t, deal=d.ticket, comment="done", volume=p.volume)


def install(broker, module):
    """একটা module-কে (MetaTrader5 নামে) broker-এর সাথে যুক্ত করো।"""
    for name in dir(broker):
        if not name.startswith("_"):
            setattr(module, name, getattr(broker, name))
    for k, v in globals().items():
        if k.isupper():
            setattr(module, k, v)
