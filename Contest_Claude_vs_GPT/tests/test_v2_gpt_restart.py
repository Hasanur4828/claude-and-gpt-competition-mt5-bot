"""
v2 প্রস্তাব G2 — restart পরীক্ষা: অজানা order-এর block প্রোগ্রাম restart-এর পরে কী হয়। নকল broker।
*** সব নকল। আসল MT5 নয়, কোনো আসল order নয়। চালু ফাইল বদলানো হয় না (শুধু মেমরিতে আলাদা নামে load)। ***
বিষয়: [H] position state unknown · [P1r] order_send None / অনিশ্চিত retcode → reconcile + block ·
       [P3r] fill volume reconcile · [P4r] tick None / invalid / stale · আচরণগত সমতা।
usage: python test_v2_gpt.py <package_dir> <out_json>
"""
import sys, os, types, json, hashlib, importlib.util
from datetime import datetime
from types import SimpleNamespace as NS

PKG, OUT = sys.argv[1], sys.argv[2]
TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TESTS)
import sim_mt5 as S
import sim_faults as SF

V2 = os.path.join(PKG, "proposals", "v2")
FILES = {
    "v1.0": os.path.join(PKG, "gpt_liquidity_fibonacci_scalper_v1.py"),
    "G2": os.path.join(V2, "G2_gpt_core_combined", "gpt_liquidity_fibonacci_scalper_v1.py"),
    "adapter_active": os.path.join(PKG, "gpt_contest_adapter.py"),
    "A1": os.path.join(V2, "A1_adapter_position_state", "gpt_contest_adapter.py"),
}
sha = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()
H0 = {k: sha(v) for k, v in FILES.items()}

MT5 = types.ModuleType("MetaTrader5")
S.install(S.Broker(n_bars=600), MT5)
sys.modules["MetaTrader5"] = MT5
CUR = {"b": None}


class SimDT(datetime):
    @classmethod
    def now(cls, tz=None):
        return CUR["b"].now_utc()


def load(path, name, core=None):
    if core is not None:
        sys.modules["gpt_liquidity_fibonacci_scalper_v1"] = core
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    if hasattr(m, "datetime"):
        m.datetime = SimDT
    return m


CORE = {"v1.0": load(FILES["v1.0"], "core_v10"), "G2": load(FILES["G2"], "core_g2")}
ADP = {("active", "v1.0"): load(FILES["adapter_active"], "adp_act_v10", CORE["v1.0"]),
       ("active", "G2"): load(FILES["adapter_active"], "adp_act_g2", CORE["G2"]),
       ("A1", "v1.0"): load(FILES["A1"], "adp_a1_v10", CORE["v1.0"]),
       ("A1", "G2"): load(FILES["A1"], "adp_a1_g2", CORE["G2"])}
GP, CL = 26102402, 26102401


class B(SF.FaultyBroker):
    """অতিরিক্ত fault: pos_none, deals_none, tick_age/tick_bad (symbol ভিত্তিক), open_retcode, none_no_open, delayed_open"""
    def __init__(self, **kw):
        super().__init__(**kw)
        self.pos_none = False
        self.deals_none = False
        self.tick_age = {}
        self.tick_bad = {}
        self.open_retcode = None          # (retcode, execute: bool)
        self.none_no_open = False
        self.delayed = []                 # None ফেরত দিয়ে পরে খুলবে এমন request

    def positions_get(self, symbol=None, ticket=None):
        return None if self.pos_none else super().positions_get(symbol=symbol, ticket=ticket)

    def history_deals_get(self, *a, **k):
        return None if self.deals_none else super().history_deals_get(*a, **k)

    def symbol_info_tick(self, s):
        t = super().symbol_info_tick(s)
        if t is None:
            return None
        if s in self.tick_bad:
            return NS(**{**vars(t), **self.tick_bad[s]})
        if s in self.tick_age:
            return NS(bid=t.bid, ask=t.ask, time=t.time - self.tick_age[s])
        return t

    def order_send(self, req):
        is_open = req.get("action") == S.TRADE_ACTION_DEAL and not req.get("position")
        if is_open and self.none_no_open:
            self.requests.append({"req": dict(req), "time": 0, "target_magic": None, "dropped": "none_no_open"})
            self.sends += 1
            return None
        if is_open and self.delayed is not None and getattr(self, "delay_next", False):
            self.delay_next = False
            self.requests.append({"req": dict(req), "time": 0, "target_magic": None, "dropped": "delayed"})
            self.sends += 1
            self.delayed.append(dict(req))
            return None
        if is_open and self.open_retcode:
            code, execute = self.open_retcode
            r = super().order_send(req) if execute else None
            if not execute:
                self.requests.append({"req": dict(req), "time": 0, "target_magic": None, "rejected": code})
                self.sends += 1
            return NS(retcode=code, order=getattr(r, "order", 0), deal=getattr(r, "deal", 0), comment="injected")
        return super().order_send(req)

    def execute_delayed(self):
        for r in self.delayed:
            S.Broker.order_send(self, r)
        self.delayed = []


import tempfile
STATE_DIR = tempfile.mkdtemp(prefix="g2_exec_state_")


def broker(pos=2800, n_bars=7000, offset=0, balance=10000.0, faults=None, keep_state=False):
    if not keep_state:                    # প্রতিটা পরীক্ষার নিজস্ব exec-state ফাইল (প্রস্তাব ফোল্ডারে কিছু লেখা হয় না)
        CORE["G2"].EXEC_STATE_FILE = tempfile.mktemp(dir=STATE_DIR, suffix=".json")
    b = B(faults=faults, n_bars=n_bars, server_offset_h=offset, balance=balance)
    b.pos_idx = pos
    SF.install(b, MT5)
    CUR["b"] = b
    return b


def gpt_pos(b, sym=None):
    return [p for p in S.Broker.positions_get(b) if p.magic == GP and (sym is None or p.symbol == sym)]


def opens(b):
    return [r for r in b.requests if r["req"].get("action") == S.TRADE_ACTION_DEAL and not r["req"].get("position")]


def signal(b, symbol="BTCUSDm", side="BUY", risk_frac=0.005):
    t = S.Broker.symbol_info_tick(b, symbol)
    e = t.ask if side == "BUY" else t.bid
    d = e * risk_frac
    sl, tp = (e - d, e + 2 * d) if side == "BUY" else (e + d, e - 2 * d)
    return {"symbol": symbol, "signal": side, "entry": e, "stop_loss": sl, "take_profit": tp}


ROWS = []


def row(group, test, expected, actual, ok):
    ROWS.append({"group": group, "test": test, "expected": expected, "actual": actual, "pass": bool(ok)})


def advance(b, seconds):
    n = int(seconds // 225) + (1 if seconds % 225 else 0)
    for _ in range(n):
        b.advance_tick()


# ---------- signal bar খোঁজা (evaluate_symbol BUY/SELL, BTC, offset 0) ----------
def find_eval_signals(want=2):
    b = broker()
    bot = CORE["v1.0"].GPTLiquidityFibonacciScalper()
    out = []
    for pos in range(400, 6990):
        b.pos_idx, b.tick_i = pos, 0
        r = bot.evaluate_symbol("BTCUSDm")
        if r.get("signal") in ("BUY", "SELL"):
            out.append((pos, r["signal"]))
            if len(out) >= want:
                break
    return out



SIG = find_eval_signals(1)
SPOS, SSIDE = SIG[0]

# R1: None অথচ খোলে → restart → নতুন instance
b = broker(pos=SPOS, faults={"open_returns_none": True})
bot = CORE["G2"].GPTLiquidityFibonacciScalper()
r = bot._send_order(signal(b, side=SSIDE))
bot2 = CORE["G2"].GPTLiquidityFibonacciScalper()            # restart: মেমরি খালি
e = bot2.evaluate_symbol("BTCUSDm")
row("restart", "[G2] None অথচ খোলে → restart → evaluate", "নিরাপদ: SKIP_POSITION_EXISTS (broker-এ পজিশন দেখা যায়)",
    f"first={r.get('status')} after restart={e.get('reason')} positions={len(gpt_pos(b))}",
    e.get("reason") == "SKIP_POSITION_EXISTS" and len(gpt_pos(b)) == 1)

# R2: None, order এখনো দেখা যাচ্ছে না (দেরিতে খুলবে) → restart → block ফাইল থেকে ফেরে
b = broker(pos=SPOS)
bot = CORE["G2"].GPTLiquidityFibonacciScalper()
b.delay_next = True
r = bot._send_order(signal(b, side=SSIDE))
f_exists = os.path.exists(CORE["G2"].EXEC_STATE_FILE)
bot2 = CORE["G2"].GPTLiquidityFibonacciScalper()            # restart (একই ফাইল)
e1 = bot2.evaluate_symbol("BTCUSDm")
s1 = bot2._send_order(signal(b, side=SSIDE))
b.execute_delayed()                                         # broker দেরিতে order খোলে
e2 = bot2.evaluate_symbol("BTCUSDm")
e3 = bot2.evaluate_symbol("BTCUSDm")
row("restart", "[G2] None, order তখনো দেখা যায় না → restart → পরে order খোলে",
    "block ফাইলে থাকে → restart-এর পরেও SKIP_EXECUTION_UNKNOWN, নতুন send নয়; খোলার পরে RESOLVED_OPENED → SKIP_POSITION_EXISTS; মোট ১ পজিশন; ফাইল মুছে যায়",
    f"first={r.get('status')} file={f_exists} → {e1.get('reason')} / send={s1.get('reason')} → {e2.get('reason')} → {e3.get('reason')} "
    f"positions={len(gpt_pos(b))} file_after={os.path.exists(CORE['G2'].EXEC_STATE_FILE)}",
    r.get("status") == "UNKNOWN" and f_exists and e1.get("reason") == "SKIP_EXECUTION_UNKNOWN" and s1.get("reason") == "SKIP_EXECUTION_UNKNOWN"
    and e2.get("reason") == "EXECUTION_UNKNOWN_RESOLVED_OPENED" and e3.get("reason") == "SKIP_POSITION_EXISTS"
    and len(gpt_pos(b)) == 1 and not os.path.exists(CORE["G2"].EXEC_STATE_FILE))

# R3: None, কিছুই খোলে না → restart → ৬০ সেকেন্ড পরে মীমাংসা, ফাইল মুছে যায়
b = broker(pos=SPOS)
bot = CORE["G2"].GPTLiquidityFibonacciScalper()
b.none_no_open = True
r = bot._send_order(signal(b, side=SSIDE))
b.none_no_open = False
bot2 = CORE["G2"].GPTLiquidityFibonacciScalper()
e1 = bot2.evaluate_symbol("BTCUSDm")
advance(b, 225)
e2 = bot2.evaluate_symbol("BTCUSDm")
row("restart", "[G2] None, কিছুই খোলেনি → restart → সময় পেরোনো", "restart-এর পরে SKIP_EXECUTION_UNKNOWN; ≥৬০ সেকেন্ডে RESOLVED_NOT_EXECUTED; ফাইল মুছে যায়",
    f"{e1.get('reason')} → {e2.get('reason')} file_after={os.path.exists(CORE['G2'].EXEC_STATE_FILE)}",
    e1.get("reason") == "SKIP_EXECUTION_UNKNOWN" and e2.get("reason") == "EXECUTION_UNKNOWN_RESOLVED_NOT_EXECUTED"
    and not os.path.exists(CORE["G2"].EXEC_STATE_FILE))

# R4: state ফাইল নষ্ট → সব symbol-এ order বন্ধ, কারণ পরিষ্কার
b = broker(pos=SPOS)
open(CORE["G2"].EXEC_STATE_FILE, "w").write("{ নষ্ট json")
bot = CORE["G2"].GPTLiquidityFibonacciScalper()
e = bot.evaluate_symbol("BTCUSDm")
s_ = bot._send_order(signal(b, side=SSIDE))
row("restart", "[G2] exec-state ফাইল নষ্ট (অর্ধেক লেখা/ভুল JSON)", "evaluate ও send দুটোই SKIP_EXEC_STATE_UNREADABLE, ০ order",
    f"evaluate={e.get('reason')} send={s_.get('reason')} orders={len(opens(b))}",
    e.get("reason") == "SKIP_EXEC_STATE_UNREADABLE" and s_.get("reason") == "SKIP_EXEC_STATE_UNREADABLE" and not opens(b))

# R5: ফাইল নেই → স্বাভাবিক; সফল order-এ ফাইল তৈরি হয় না
b = broker(pos=SPOS)
bot = CORE["G2"].GPTLiquidityFibonacciScalper()
r = bot._send_order(signal(b, side=SSIDE))
row("restart", "[G2] ফাইল নেই, স্বাভাবিক order", "OPENED, কোনো ফাইল লেখা হয় না",
    f"status={r.get('status')} file={os.path.exists(CORE['G2'].EXEC_STATE_FILE)}",
    r.get("status") == "OPENED" and not os.path.exists(CORE["G2"].EXEC_STATE_FILE))

summary = {"total": len(ROWS), "passed": sum(r["pass"] for r in ROWS), "SIMULATED_ONLY": True}
json.dump({"summary": summary, "rows": ROWS}, open(OUT, "w"), indent=1, ensure_ascii=False, default=str)
for r in ROWS:
    print(("PASS " if r["pass"] else "FAIL ") + f"{r['group']:<8} {r['test']}\n      expected: {r['expected']}\n      actual:   {r['actual']}")
print(json.dumps(summary, indent=1, ensure_ascii=False))
