"""
v2 প্রস্তাব P2r (G2-এর ভেতরে) — দৈনিক লস ও server offset: offset জানা না গেলে বা অসংগত হলে UNKNOWN (None),
কখনো অনুমান নয়। v1.0 বনাম আগের P2 (v1) বনাম G2। নকল MT5 (শুধু মেমরিতে)। আসল MT5 নয়।
প্রত্যাশিত মান আলাদা oracle দিয়ে গোনা: আজকের (UTC) [00:00:00, এখন]-এ বন্ধ GPT পজিশন যার নিট ≤ −0.2R।
usage: python test_v2_p2.py <package_dir> <out_json>
"""
import sys, os, types, json, hashlib, importlib.util
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace as NS

PKG, OUT = sys.argv[1], sys.argv[2]
FILES = {
    "v1.0": os.path.join(PKG, "gpt_liquidity_fibonacci_scalper_v1.py"),
    "P2_v1": os.path.join(PKG, "proposals", "P2_daily_loss_server_time", "gpt_liquidity_fibonacci_scalper_v1.py"),
    "G2": os.path.join(PKG, "proposals", "v2", "G2_gpt_core_combined", "gpt_liquidity_fibonacci_scalper_v1.py"),
}
sha = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()
H0 = {k: sha(v) for k, v in FILES.items()}
SYMS = ("BTCUSDm", "XAUUSDm", "ETHUSDm")
# ticks: {symbol: None (নেই) | (offset_sec, age_sec)}
W = {"now": None, "offset": 0, "deals": [], "ticks": {}, "deals_none": False, "acc_none": False}
mt5 = types.ModuleType("MetaTrader5")
mt5.TIMEFRAME_H1, mt5.TIMEFRAME_M15 = 16385, 15
mt5.history_deals_get = lambda a, b: None if W["deals_none"] else tuple(d for d in W["deals"] if a.timestamp() <= d.time <= b.timestamp())
mt5.account_info = lambda: None if W["acc_none"] else NS(balance=10000.0)
mt5.last_error = lambda: (1, "Success")


def _tick(s):
    t = W["ticks"].get(s, "default")
    if t == "default":
        t = (W["offset"], 5)
    if t is None:
        return None
    off, age = t
    return NS(time=int(W["now"].timestamp()) + off - age, bid=1, ask=1)


mt5.symbol_info_tick = _tick
sys.modules["MetaTrader5"] = mt5


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)

    class DT(datetime):
        @classmethod
        def now(cls, tz=None):
            return W["now"]
    m.datetime = DT
    return m


M = {k: load(p, "v2p2_" + k.replace(".", "_")) for k, p in FILES.items()}
import tempfile
M["G2"].EXEC_STATE_FILE = os.path.join(tempfile.mkdtemp(), "exec.json")   # প্রস্তাব ফোল্ডারে কিছু লেখা হয় না
MAGIC = M["v1.0"].MAGIC
D = datetime(2026, 5, 13, tzinfo=timezone.utc)
S1 = timedelta(seconds=1)
L = -30


def build(events, offset):
    deals, pid = [], 7000
    for when, pnl in events:
        pid += 1
        o = int((when - timedelta(hours=1)).timestamp()) + offset
        c = int(when.timestamp()) + offset
        deals.append(NS(magic=MAGIC, symbol="BTCUSDm", position_id=pid, profit=0.0, commission=0.0, swap=0.0, time=o))
        deals.append(NS(magic=MAGIC, symbol="BTCUSDm", position_id=pid, profit=pnl, commission=0.0, swap=0.0, time=c))
    return deals


def oracle(now, events):
    start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    return sum(1 for w, p in events if start <= w <= now and p <= -20)


def count(k):
    return M[k].GPTLiquidityFibonacciScalper._daily_loss_count(("BTCUSDm", "XAUUSDm"))


CASES = [
    ("এখন ঠিক 00:00:00; লস গতকাল 23:59:59 ও আজ 00:00:00", D, [(D - S1, L), (D, L)]),
    ("এখন 00:00:30; লস গতকাল 23:50, 23:59:59", D + timedelta(seconds=30), [(D - timedelta(minutes=10), L), (D - S1, L)]),
    ("এখন 00:00:30; লস গতকাল 23:59:59 ও আজ 00:00:10", D + timedelta(seconds=30), [(D - S1, L), (D + timedelta(seconds=10), L)]),
    ("এখন 23:59:59; লস আজ 00:00:00, 23:59:30, গতকাল 23:59:59", D + timedelta(days=1) - S1,
     [(D, L), (D + timedelta(days=1) - timedelta(seconds=30), L), (D - S1, L)]),
    ("এখন 12:00; লস 11:59:59, জয় 11:00, ছোট লস −0.1R", D + timedelta(hours=12),
     [(D + timedelta(hours=12) - S1, L), (D + timedelta(hours=11), 40), (D + timedelta(hours=10), -10)]),
    ("এখন 18:00; আজ ৩টা লস", D + timedelta(hours=18),
     [(D + timedelta(hours=2), L), (D + timedelta(hours=9), L), (D + timedelta(hours=18) - S1, L)]),
]
OFFS = [-12, -5, -3.5, 0, 2, 3, 3.5, 5.5, 10, 14]
ROWS = []


def row(group, test, expected, actual, ok):
    ROWS.append({"group": group, "test": test, "expected": expected, "actual": actual, "pass": bool(ok)})


# ---- ১. boundary × offset, সব tick তাজা ----
corr = {k: 0 for k in M}
n = 0
for name, now, ev in CASES:
    exp = oracle(now, ev)
    for oh in OFFS:
        off = int(oh * 3600)
        W.update(now=now, offset=off, deals=build(ev, off), ticks={}, deals_none=False, acc_none=False)
        got = {k: count(k) for k in M}
        n += 1
        for k in M:
            corr[k] += got[k] == exp
row("boundary", f"boundary × offset ({n}টা: ৬ সময় × ১০ offset, সব tick তাজা)", "G2 সব সঠিক (P2 v1-এর মতোই)",
    f"সঠিক: v1.0 {corr['v1.0']}/{n} · P2 v1 {corr['P2_v1']}/{n} · G2 {corr['G2']}/{n}", corr["G2"] == n)

# ---- ২. tick-age সীমা (সব symbol একই বয়স) ----
name, now, ev = CASES[3]
exp = oracle(now, ev)
ok_all, detail = True, []
for oh in (-5, 0, 3, 5.5):
    off = int(oh * 3600)
    for age in (0, 120, 299, 301, 900, -120):
        W.update(now=now, offset=off, deals=build(ev, off), ticks={s: (off, age) for s in SYMS})
        got = count("G2")
        want = exp if abs(age) <= 300 else None
        ok_all &= got == want
        detail.append(f"{oh}h/{age}s→{got}")
row("tick_age", "tick বয়স 0/120/299/−120 সেকেন্ড = জানা; 301/900 = অজানা (৪ offset × ৬)",
    "জানা হলে সঠিক সংখ্যা, অজানা হলে None (UNKNOWN) — কোনো অনুমান নয়", " ".join(detail), ok_all)

# ---- ৩. অজানা / অসংগত offset → None ----
name, now, ev = CASES[5]
exp = oracle(now, ev)
off3 = 3 * 3600
specials = [
    ("কোনো tick নেই", {s: None for s in SYMS}, None),
    ("সব tick ২০ মিনিট পুরনো", {s: (off3, 1200) for s in SYMS}, None),
    ("৫:৪৫ ঘণ্টার offset (আধা-ঘণ্টা নয়)", {s: (int(5.75 * 3600), 5) for s in SYMS}, None),
    ("অসংগত: BTC তাজা +3h, XAU তাজা +2h", {"BTCUSDm": (off3, 5), "XAUUSDm": (2 * 3600, 5), "ETHUSDm": None}, None),
    ("অসংগত: BTC +3h, ETH +3.5h", {"BTCUSDm": (off3, 5), "XAUUSDm": None, "ETHUSDm": (int(3.5 * 3600), 5)}, None),
    ("XAU ও ETH নেই, শুধু BTC তাজা", {"BTCUSDm": (off3, 5), "XAUUSDm": None, "ETHUSDm": None}, exp),
    ("XAU পুরনো (সপ্তাহান্তের মতো), BTC তাজা", {"BTCUSDm": (off3, 5), "XAUUSDm": (off3, 50000), "ETHUSDm": (off3, 10)}, exp),
    # সীমাবদ্ধতা দেখানো: ঠিক ~২ ঘণ্টা পুরনো XAU tick দেখতে "+1h offset-এর তাজা tick"-এর মতো — আলাদা করা যায় না।
    # G2 তখন অসংগত ধরে UNKNOWN দেয় (entry বন্ধ = নিরাপদ দিক), কখনো ভুল offset নেয় না।
    ("XAU ঠিক ২ ঘণ্টা ৭ সেকেন্ড পুরনো (তাজা +1h-এর মতো দেখায়), BTC তাজা +3h", {"BTCUSDm": (off3, 5), "XAUUSDm": (off3, 2 * 3600 + 7), "ETHUSDm": None}, None),
]
for label, ticks, want in specials:
    W.update(now=now, offset=off3, deals=build(ev, off3), ticks=ticks, deals_none=False, acc_none=False)
    got = {k: count(k) for k in M}
    row("unknown", f"[G2] {label}", "None (UNKNOWN)" if want is None else f"সঠিক {want}",
        f"G2={got['G2']} · (তুলনা: v1.0={got['v1.0']}, P2 v1={got['P2_v1']})", got["G2"] == want)

for label, key in (("history_deals_get None", "deals_none"), ("account_info None", "acc_none")):
    W.update(now=now, offset=off3, deals=build(ev, off3), ticks={}, deals_none=False, acc_none=False)
    W[key] = True
    got = {k: count(k) for k in M}
    row("unknown", f"[G2] {label}", "None (UNKNOWN); v1.0 ও P2 v1 ০ দেয় (= লস নেই ধরে ট্রেড চালিয়ে যায়)",
        f"G2={got['G2']} · v1.0={got['v1.0']} · P2 v1={got['P2_v1']}", got["G2"] is None and got["v1.0"] == 0)
W.update(deals_none=False, acc_none=False)

# ---- ৪. DST: একই দিনে offset +2 → +3 ----
name, now, ev = CASES[5]
exp = oracle(now, ev)
res = []
for oh in (2, 3):
    W.update(now=now, offset=oh * 3600, deals=build(ev, oh * 3600), ticks={})
    res.append(count("G2"))
row("dst", "[G2] DST: offset +2 তারপর +3", f"দুটোতেই {exp}", f"{res}", res == [exp, exp])

# ---- ৫. evaluate_symbol-স্তরে: UNKNOWN হলে নতুন entry বন্ধ (নকল broker) ----
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sim_mt5 as S
import sim_faults as SF
MT5S = types.ModuleType("MetaTrader5")


class TB(SF.FaultyBroker):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.age = 0
        self.deals_none = False

    def symbol_info_tick(self, s):
        t = super().symbol_info_tick(s)
        return None if t is None else NS(bid=t.bid, ask=t.ask, time=t.time - self.age)

    def history_deals_get(self, *a, **k):
        return None if self.deals_none else super().history_deals_get(*a, **k)


tb = TB(n_bars=7000, server_offset_h=3); tb.pos_idx = 2800
SF.install(tb, MT5S)
sys.modules["MetaTrader5"] = MT5S


class SDT(datetime):
    @classmethod
    def now(cls, tz=None):
        return tb.now_utc()


G2s = load(FILES["G2"], "v2p2_g2_sim"); G2s.datetime = SDT
G2s.EXEC_STATE_FILE = os.path.join(tempfile.mkdtemp(), "exec.json")
V10s = load(FILES["v1.0"], "v2p2_v10_sim"); V10s.datetime = SDT
for label, setup in (("সব tick ২০ মিনিট পুরনো (offset অজানা)", lambda: setattr(tb, "age", 1200)),
                     ("deal history None", lambda: setattr(tb, "deals_none", True))):
    tb.age, tb.deals_none = 0, False
    setup()
    g = G2s.GPTLiquidityFibonacciScalper().evaluate_symbol("BTCUSDm")
    v = V10s.GPTLiquidityFibonacciScalper().evaluate_symbol("BTCUSDm")
    row("evaluate", f"[G2] evaluate_symbol: {label}", "NO_TRADE / SKIP_DAILY_LOSS_UNKNOWN (v1.0 এগিয়ে যায়)",
        f"G2={g.get('reason')} · v1.0={v.get('reason')}", g.get("reason") == "SKIP_DAILY_LOSS_UNKNOWN"
        and v.get("reason") != "SKIP_DAILY_LOSS_UNKNOWN")
tb.age, tb.deals_none = 0, False
g = G2s.GPTLiquidityFibonacciScalper().evaluate_symbol("BTCUSDm")
row("evaluate", "[G2] evaluate_symbol: সব ঠিক (offset +3 জানা)", "SKIP_DAILY_LOSS_UNKNOWN নয়", f"G2={g.get('reason')}",
    g.get("reason") != "SKIP_DAILY_LOSS_UNKNOWN")

H1 = {k: sha(v) for k, v in FILES.items()}
row("ALL", "পরীক্ষার আগে-পরে ফাইল SHA-256", "অপরিবর্তিত", f"same={H0 == H1}", H0 == H1)
summary = {"total": len(ROWS), "passed": sum(r["pass"] for r in ROWS), "sha256": H1, "SIMULATED_ONLY": True}
json.dump({"summary": summary, "rows": ROWS}, open(OUT, "w"), indent=1, ensure_ascii=False, default=str)
for r in ROWS:
    print(("PASS " if r["pass"] else "FAIL ") + f"{r['group']:<9} {r['test']}\n      expected: {r['expected']}\n      actual:   {r['actual']}")
print(json.dumps(summary, indent=1, ensure_ascii=False))
