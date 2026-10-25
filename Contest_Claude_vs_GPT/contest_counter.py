"""
Contest Counter — Claude Pullback v1 বনাম GPT Fibonacci & Liquidity Sweep
=========================================================================
দুই strategy-র ট্রেড সরাসরি MT5-এর deal history থেকে magic number দিয়ে গোনে।
কোনো আলাদা ডেটাবেস নেই — সফটওয়্যার restart হলেও হিসাব অক্ষত, আর হাতে বদলানো যায় না।

প্রতিযোগিতার শুরু চিহ্নিত হয় "শুরুর মুহূর্তের সর্বশেষ deal ticket" দিয়ে (contest_start_deal):
MT5-এর deal ticket সবসময় বাড়তে থাকে, তাই broker-এর server time UTC থেকে আলাদা হলেও
কোনো ট্রেড বাদ পড়ে না বা ভুল করে ঢোকে না।

নিয়ম (PDF অধ্যায় ২১.৫):
  * এক "ট্রেড" = একটা সম্পূর্ণ বন্ধ MT5 position (partial close সহ সব deal মিলিয়ে) — position_id দিয়ে একবারই
  * একই deal দুবার এলে (ticket দিয়ে) বাদ — তাই দ্বিগুণ গণনা অসম্ভব
  * নিট = profit + commission + swap + fee
  * R = খোলার মুহূর্তের প্রাথমিক SL পর্যন্ত ঝুঁকি ($)
  * WIN: নিট > +0.1R · LOSS: নিট < −0.1R · BE: মাঝামাঝি (R না জানা গেলে সীমা = balance-এর 0.1%)
  * demo_verification-এর পরীক্ষা-ট্রেড (verification_positions.json-এর position/deal/order নম্বর) সবসময় বাদ
  * MT5 উত্তর না দিলে (None) "০ ট্রেড" দেখানো হয় না — CounterDataError ওঠে
  * verification ফাইল নেই / নষ্ট / অসম্পূর্ণ হলে রিপোর্টে স্পষ্ট warning (data_ok = False হলে ফল অবিশ্বাস্য)
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

import verification_journal as VJ

try:
    import MetaTrader5 as mt5
except ImportError:          # টেস্টের সময় নকল mt5 দেওয়া যায়
    mt5 = None

CLAUDE_MAGIC = 26102401
GPT_MAGIC = 26102402

STRATEGIES = {
    "claude": {"magic": CLAUDE_MAGIC, "name": "Claude Pullback v1"},
    "gpt": {"magic": GPT_MAGIC, "name": "GPT Fibonacci & Liquidity Sweep"},
}

BE_BAND_R = 0.1
MIN_TRADES_FOR_VERDICT = 50
HISTORY_LOOKBACK_DAYS = 400      # প্রতিযোগিতা সর্বোচ্চ এত দিন ধরে চলতে পারে

class CounterDataError(Exception):
    """MT5 থেকে তথ্য পাওয়া যায়নি — ভুল (খালি) হিসাব দেখানোর বদলে এটা ওঠে।"""


DEAL_ENTRY_IN, DEAL_ENTRY_OUT, DEAL_ENTRY_INOUT, DEAL_ENTRY_OUT_BY = 0, 1, 2, 3
DEAL_TYPE_BUY, DEAL_TYPE_SELL = 0, 1
REASON_NAMES = {4: "SL", 5: "TP", 6: "SO"}   # 0-3 = হাতে/EA দিয়ে বন্ধ → "CLOSE"


@dataclass
class ClosedTrade:
    position_id: int
    strategy: str
    symbol: str
    side: str
    open_time: int           # server time (MT5)
    close_time: int
    volume: float
    entry_price: float
    initial_sl: float
    net: float
    risk_money: Optional[float]
    r_multiple: Optional[float]
    result: str              # WIN / LOSS / BE
    exit_reason: str         # SL / TP / CLOSE / SO
    deals: int


@dataclass
class StrategyStats:
    key: str
    name: str
    trades: int = 0
    wins: int = 0
    losses: int = 0
    breakeven: int = 0
    win_rate: float = 0.0
    net_profit: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    profit_factor: Optional[float] = None
    total_r: float = 0.0
    avg_r: Optional[float] = None
    max_drawdown: float = 0.0
    max_consec_losses: int = 0
    current_streak: str = "-"
    best_trade: float = 0.0
    worst_trade: float = 0.0
    today_trades: int = 0
    today_net: float = 0.0
    open_positions: int = 0
    floating: float = 0.0
    by_symbol: Dict[str, dict] = field(default_factory=dict)
    verdict_ready: bool = False


def _classify(net: float, risk_money: Optional[float], balance: float) -> str:
    band = BE_BAND_R * risk_money if risk_money and risk_money > 0 else 0.001 * balance
    if net > band:
        return "WIN"
    if net < -band:
        return "LOSS"
    return "BE"


def compute_stats(key: str, trades: List[ClosedTrade], open_positions=(),
                  today_start_server: Optional[int] = None, per_symbol: bool = True) -> StrategyStats:
    """খাঁটি হিসাব — MT5 লাগে না, তাই আলাদাভাবে টেস্ট করা যায়।"""
    st = StrategyStats(key=key, name=STRATEGIES[key]["name"])
    trades = sorted(trades, key=lambda t: (t.close_time, t.position_id))
    equity = peak = 0.0
    consec = 0
    for t in trades:
        st.trades += 1
        st.net_profit += t.net
        if t.net > 0:
            st.gross_profit += t.net
        else:
            st.gross_loss += -t.net
        if t.r_multiple is not None:
            st.total_r += t.r_multiple
        if t.result == "WIN":
            st.wins += 1
            consec = 0
        elif t.result == "LOSS":
            st.losses += 1
            consec += 1
            st.max_consec_losses = max(st.max_consec_losses, consec)
        else:
            st.breakeven += 1
        equity += t.net
        peak = max(peak, equity)
        st.max_drawdown = max(st.max_drawdown, peak - equity)
        st.best_trade = max(st.best_trade, t.net)
        st.worst_trade = min(st.worst_trade, t.net)
        if today_start_server is not None and t.close_time >= today_start_server:
            st.today_trades += 1
            st.today_net += t.net

    if st.trades:
        st.win_rate = 100.0 * st.wins / st.trades
        r_known = [t.r_multiple for t in trades if t.r_multiple is not None]
        st.avg_r = sum(r_known) / len(r_known) if r_known else None
        last = [t.result for t in trades if t.result != "BE"]
        if last:
            n = 1
            while n < len(last) and last[-1 - n] == last[-1]:
                n += 1
            st.current_streak = f"{n}{'W' if last[-1] == 'WIN' else 'L'}"
    if st.gross_loss > 0:
        st.profit_factor = st.gross_profit / st.gross_loss
    elif st.gross_profit > 0:
        st.profit_factor = float("inf")

    for p in open_positions:
        st.open_positions += 1
        st.floating += float(getattr(p, "profit", 0.0)) + float(getattr(p, "swap", 0.0))
    st.verdict_ready = st.trades >= MIN_TRADES_FOR_VERDICT

    if per_symbol:
        for sym in sorted({t.symbol for t in trades}):
            sub = compute_stats(key, [t for t in trades if t.symbol == sym], (),
                                today_start_server, per_symbol=False)
            st.by_symbol[sym] = {k: getattr(sub, k) for k in (
                "trades", "wins", "losses", "breakeven", "win_rate", "net_profit", "gross_profit",
                "gross_loss", "profit_factor", "max_drawdown", "avg_r")}
    return st


def compare(claude: StrategyStats, gpt: StrategyStats) -> Dict[str, str]:
    def lead(a, b, higher_better=True):
        if a is None and b is None:
            return "="
        if a is None:
            return "gpt"
        if b is None:
            return "claude"
        if abs(a - b) < 1e-9:
            return "="
        return ("claude" if a > b else "gpt") if higher_better else ("claude" if a < b else "gpt")

    out = {
        "net_profit": lead(claude.net_profit, gpt.net_profit),
        "win_rate": lead(claude.win_rate, gpt.win_rate),
        "profit_factor": lead(claude.profit_factor, gpt.profit_factor),
        "avg_r": lead(claude.avg_r, gpt.avg_r),
        "max_drawdown": lead(claude.max_drawdown, gpt.max_drawdown, higher_better=False),
    }
    out["verdict"] = out["net_profit"] if (claude.verdict_ready and gpt.verdict_ready) else "WAIT"
    return out


def _window():
    now = datetime.now(timezone.utc)
    # server time UTC-র চেয়ে এগিয়ে/পিছিয়ে থাকলেও কিছু বাদ না পড়তে দুই দিকেই বাড়তি জায়গা
    return now - timedelta(days=HISTORY_LOOKBACK_DAYS), now + timedelta(days=2)


def latest_deal_ticket() -> int:
    """'Start / Reset' চাপার মুহূর্তে ডাকুন — এর চেয়ে বড় ticket-এর deal থেকেই প্রতিযোগিতা।"""
    a, b = _window()
    deals = mt5.history_deals_get(a, b)
    if deals is None:
        raise CounterDataError(f"history_deals_get = None {mt5.last_error()}")
    return max((int(d.ticket) for d in deals), default=0)


def server_today_start() -> Optional[int]:
    """'আজ'-এর হিসাব broker-এর server দিনের শুরু থেকে (MT5 History-র সাথে মেলাতে)।"""
    times = []
    for s in ("BTCUSDm", "ETHUSDm", "XAUUSDm"):
        t = mt5.symbol_info_tick(s)
        if t is not None and getattr(t, "time", 0):
            times.append(int(t.time))
    if not times:
        return None
    now_server = max(times)
    return now_server - now_server % 86400


class ContestCounter:
    def __init__(self, start_deal_ticket: int, symbols_filter: Optional[set] = None,
                 verification_path: str = VJ.DEFAULT_PATH):
        self.start_deal = int(start_deal_ticket)
        self.symbols_filter = symbols_filter     # None = সব; {"BTCUSDm","XAUUSDm"} = শুধু common
        self.v_status, self.v_message, vdata = VJ.load(verification_path)
        self.ex_pos, self.ex_deals, self.ex_orders = VJ.exclusions(vdata)
        self.excluded_positions: List[int] = []

    def _closed_trades(self) -> Dict[str, List[ClosedTrade]]:
        a, b = _window()
        raw = mt5.history_deals_get(a, b)
        if raw is None:
            raise CounterDataError(f"history_deals_get = None {mt5.last_error()}")
        seen, deals = set(), []
        for d in raw:                              # একই deal দুবার এলে একবারই
            if int(d.ticket) in seen:
                continue
            seen.add(int(d.ticket))
            deals.append(d)
        magic_to_key = {v["magic"]: k for k, v in STRATEGIES.items()}
        # প্রতিযোগিতার position = আমাদের magic-এর opening deal, ticket > start_deal
        ours = {int(d.position_id) for d in deals
                if d.magic in magic_to_key and d.entry == DEAL_ENTRY_IN and int(d.ticket) > self.start_deal}
        groups: Dict[int, list] = {}
        for d in deals:
            if int(d.position_id) in ours:
                groups.setdefault(int(d.position_id), []).append(d)
        open_now = mt5.positions_get()
        if open_now is None:                       # error ≠ "কিছু খোলা নেই"
            raise CounterDataError(f"positions_get = None {mt5.last_error()}")
        open_ids = {int(p.identifier) for p in open_now}
        acc = mt5.account_info()
        if acc is None:
            raise CounterDataError(f"account_info = None {mt5.last_error()}")
        balance = float(acc.balance)
        out: Dict[str, List[ClosedTrade]] = {k: [] for k in STRATEGIES}
        self.excluded_positions = []

        for pid, ds in groups.items():
            # demo_verification-এর পরীক্ষা-ট্রেড: position, যেকোনো deal, বা খোলার order নম্বর মিললেই বাদ
            if pid in self.ex_pos or any(int(d.ticket) in self.ex_deals or int(getattr(d, "order", 0) or 0) in self.ex_orders
                                         for d in ds):
                self.excluded_positions.append(pid)
                continue
            if pid in open_ids:
                continue
            ds = sorted(ds, key=lambda x: (x.time_msc, x.ticket))
            opening = next((d for d in ds if d.entry == DEAL_ENTRY_IN), None)
            closing = [d for d in ds if d.entry in (DEAL_ENTRY_OUT, DEAL_ENTRY_OUT_BY, DEAL_ENTRY_INOUT)]
            if opening is None or not closing:
                continue
            key = magic_to_key[opening.magic]
            if self.symbols_filter and opening.symbol not in self.symbols_filter:
                continue
            net = sum(float(d.profit) + float(d.commission) + float(d.swap) + float(getattr(d, "fee", 0.0)) for d in ds)
            side = "BUY" if opening.type == DEAL_TYPE_BUY else "SELL"
            initial_sl, risk = 0.0, None
            orders = mt5.history_orders_get(position=pid) or ()
            if orders:
                first = min(orders, key=lambda o: (o.time_setup_msc, getattr(o, "ticket", 0)))
                initial_sl = float(first.sl)
            if initial_sl > 0:
                otype = mt5.ORDER_TYPE_BUY if side == "BUY" else mt5.ORDER_TYPE_SELL
                loss = mt5.order_calc_profit(otype, opening.symbol, float(opening.volume),
                                             float(opening.price), initial_sl)
                if loss is not None and abs(loss) > 0:
                    risk = abs(float(loss))
            last = closing[-1]
            out[key].append(ClosedTrade(
                position_id=pid, strategy=key, symbol=opening.symbol, side=side,
                open_time=int(opening.time), close_time=int(last.time), volume=float(opening.volume),
                entry_price=float(opening.price), initial_sl=initial_sl, net=round(net, 2),
                risk_money=risk, r_multiple=(net / risk if risk else None),
                result=_classify(net, risk, balance),
                exit_reason=REASON_NAMES.get(int(getattr(last, "reason", -1)), "CLOSE"),
                deals=len(ds)))
        return out

    def report(self) -> Dict[str, object]:
        trades = self._closed_trades()
        opens = {k: [] for k in STRATEGIES}
        open_now = mt5.positions_get()
        if open_now is None:
            raise CounterDataError(f"positions_get = None {mt5.last_error()}")
        for p in open_now:
            if int(p.identifier) in self.ex_pos or int(p.identifier) in self.ex_orders:
                continue                           # খোলা পরীক্ষা-পজিশন প্রতিযোগিতার "Open now"-এ নয়
            for k, v in STRATEGIES.items():
                if p.magic == v["magic"] and (not self.symbols_filter or p.symbol in self.symbols_filter):
                    opens[k].append(p)
        warnings = []
        if self.v_status == "CORRUPT":
            warnings.append("ERROR: " + self.v_message + " — পরীক্ষা-ট্রেড হিসাবে ঢুকে থাকতে পারে, ফল অবিশ্বাস্য")
        elif self.v_status == "INCOMPLETE":
            warnings.append("WARNING: " + self.v_message + " — demo_verification আবার চালিয়ে orphan সমাধান করুন")
        elif self.v_status == "MISSING":
            warnings.append("NOTE: " + self.v_message + " — এই ফোল্ডারে verification চালালে ফাইলটা এখানেই থাকার কথা")
        today = server_today_start()
        claude = compute_stats("claude", trades["claude"], opens["claude"], today)
        gpt = compute_stats("gpt", trades["gpt"], opens["gpt"], today)
        return {
            "start_deal": self.start_deal,
            "updated": datetime.now(timezone.utc).isoformat(),
            "claude": asdict(claude),
            "gpt": asdict(gpt),
            "compare": compare(claude, gpt),
            "trades": {k: [asdict(t) for t in v] for k, v in trades.items()},
            "verification": {"status": self.v_status, "message": self.v_message,
                             "excluded_positions": sorted(self.excluded_positions)},
            "warnings": warnings,
            "data_ok": self.v_status in ("OK", "MISSING"),
        }


def export_csv(report: Dict[str, object], path: str) -> int:
    """প্রতিটা গোনা ট্রেড এক লাইনে — MT5 History-র position নম্বরের সাথে মিলিয়ে দেখার জন্য।"""
    rows = [t for k in ("claude", "gpt") for t in report["trades"][k]]
    cols = ["strategy", "position_id", "symbol", "side", "open_time", "close_time", "volume",
            "entry_price", "initial_sl", "net", "risk_money", "r_multiple", "result", "exit_reason", "deals"]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for t in sorted(rows, key=lambda x: x["close_time"]):
            t = dict(t)
            for k in ("open_time", "close_time"):
                t[k] = datetime.fromtimestamp(t[k], tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S") + " (server)"
            w.writerow({c: t.get(c) for c in cols})
    return len(rows)
