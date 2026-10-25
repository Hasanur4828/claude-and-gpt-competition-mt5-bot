"""
P2 (দৈনিক লস, server time) — boundary time, broker offset ও tick-age সীমা পরীক্ষা। v1.0 বনাম P2 বনাম COMBINED।
নকল MT5 (শুধু মেমরিতে)। কোনো ফাইল বদলানো হয় না। আসল MT5 নয়।
প্রত্যাশিত মান আলাদা "oracle" দিয়ে গোনা: আজকের (UTC) [00:00:00, এখন] সময়ে বন্ধ হওয়া GPT পজিশন যার নিট ≤ −0.2R।
usage: python test_p2_boundaries.py <package_dir> <out_json>
"""
import sys, os, types, json, hashlib, importlib.util
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace as NS

PKG, OUT = sys.argv[1], sys.argv[2]
FILES = {
    "v1.0": os.path.join(PKG, "gpt_liquidity_fibonacci_scalper_v1.py"),
    "P2": os.path.join(PKG, "proposals", "P2_daily_loss_server_time", "gpt_liquidity_fibonacci_scalper_v1.py"),
    "COMBINED": os.path.join(PKG, "proposals", "COMBINED_v1_1_all_four", "gpt_liquidity_fibonacci_scalper_v1.py"),
}
sha = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()
H0 = {k: sha(v) for k, v in FILES.items()}

W = {"now": None, "offset": 0, "deals": [], "tick_age": 5, "no_ticks": False}
mt5 = types.ModuleType("MetaTrader5")
mt5.TIMEFRAME_H1, mt5.TIMEFRAME_M15 = 16385, 15
mt5.history_deals_get = lambda a, b: tuple(d for d in W["deals"] if a.timestamp() <= d.time <= b.timestamp())
mt5.account_info = lambda: NS(balance=10000.0)
mt5.symbol_info_tick = lambda s: None if W["no_ticks"] else NS(
    time=int(W["now"].timestamp()) + W["offset"] - W["tick_age"], bid=1, ask=1)
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


M = {k: load(p, "p2b_" + k.replace(".", "_")) for k, p in FILES.items()}
MAGIC = M["v1.0"].MAGIC
D = datetime(2026, 5, 13, tzinfo=timezone.utc)
S1 = timedelta(seconds=1)


def build(events, offset):
    deals, pid = [], 5000
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


L = -30
CASES = [
    ("এখন ঠিক 00:00:00; লস গতকাল 23:59:59 ও আজ 00:00:00", D,
     [(D - S1, L), (D, L)]),
    ("এখন 00:00:30 (মধ্যরাতের ঠিক পরে); লস গতকাল 23:50, 23:59:59", D + timedelta(seconds=30),
     [(D - timedelta(minutes=10), L), (D - S1, L)]),
    ("এখন 00:00:30; লস গতকাল 23:59:59 ও আজ 00:00:10", D + timedelta(seconds=30),
     [(D - S1, L), (D + timedelta(seconds=10), L)]),
    ("এখন 23:59:59; লস আজ 00:00:00, 23:59:30 আর গতকাল 23:59:59", D + timedelta(days=1) - S1,
     [(D, L), (D + timedelta(days=1) - timedelta(seconds=30), L), (D - S1, L)]),
    ("এখন 12:00; লস আজ 11:59:59 ও জয় 11:00, ছোট লস −10 (−0.1R, গোনা হবে না)", D + timedelta(hours=12),
     [(D + timedelta(hours=12) - S1, L), (D + timedelta(hours=11), 40), (D + timedelta(hours=10), -10)]),
    ("এখন 18:00; আজ ৩টা লস (02:00, 09:00, 17:59)", D + timedelta(hours=18),
     [(D + timedelta(hours=2), L), (D + timedelta(hours=9), L), (D + timedelta(hours=18) - S1, L)]),
]
OFFS = [-12, -5, -3.5, 0, 2, 3, 3.5, 5.5, 10, 14]

rows, sm = [], {"total": 0, "correct": {k: 0 for k in M}}
for name, now, ev in CASES:
    exp = oracle(now, ev)
    for oh in OFFS:
        off = int(oh * 3600)
        W.update(now=now, offset=off, deals=build(ev, off), tick_age=5, no_ticks=False)
        got = {k: M[k].GPTLiquidityFibonacciScalper._daily_loss_count(("BTCUSDm", "XAUUSDm")) for k in M}
        rows.append({"group": "boundary×offset", "case": name, "offset_h": oh, "expected": exp, **got})
        sm["total"] += 1
        for k in M:
            sm["correct"][k] += got[k] == exp

# tick-age সীমা: ২৯৯ সেকেন্ড = offset জানা, ৩০১ = অজানা (রক্ষণশীল)
age_rows = []
case_name, now, ev = CASES[3]
exp = oracle(now, ev)
for oh in (-5, 0, 3, 5.5):
    off = int(oh * 3600)
    for age in (0, 120, 299, 301, 900, -120):
        W.update(now=now, offset=off, deals=build(ev, off), tick_age=age, no_ticks=False)
        known = M["P2"].GPTLiquidityFibonacciScalper._server_offset_seconds()
        got = M["P2"].GPTLiquidityFibonacciScalper._daily_loss_count(("BTCUSDm", "XAUUSDm"))
        exp_known = off if abs(age) <= 300 else None
        age_rows.append({"offset_h": oh, "tick_age_s": age, "offset_detected": known, "expected_detected": exp_known,
                         "count": got, "expected": exp,
                         "pass": known == exp_known and (got == exp if exp_known is not None else got >= exp)})

# offset অজানা (কোনো tick নেই, বা ৫:৪৫-এর মতো অ-আধা-ঘণ্টা offset) → কখনো কম গোনে না
cons = []
for name, now, ev in CASES:
    exp = oracle(now, ev)
    for oh in OFFS + [5.75]:
        off = int(oh * 3600)
        for mode in ("no_ticks", "stale_1200s", "odd_offset") if oh == 5.75 else ("no_ticks", "stale_1200s"):
            W.update(now=now, offset=off, deals=build(ev, off), tick_age=1200 if mode == "stale_1200s" else 5,
                     no_ticks=(mode == "no_ticks"))
            got = M["P2"].GPTLiquidityFibonacciScalper._daily_loss_count(("BTCUSDm", "XAUUSDm"))
            cons.append({"case": name, "offset_h": oh, "mode": mode, "expected": exp, "P2": got, "not_under": got >= exp})

# server offset হঠাৎ বদলালে (DST: +2 → +3) — প্রতি কলে tick থেকে নতুন করে পড়ে
dst = []
name, now, ev = CASES[5]
exp = oracle(now, ev)
for oh in (2, 3):
    off = oh * 3600
    W.update(now=now, offset=off, deals=build(ev, off), tick_age=5, no_ticks=False)
    dst.append({"offset_h": oh, "expected": exp, "P2": M["P2"].GPTLiquidityFibonacciScalper._daily_loss_count(("BTCUSDm",))})

H1 = {k: sha(v) for k, v in FILES.items()}
summary = {
    "boundary_offset_cases": sm["total"],
    "correct": sm["correct"],
    "tick_age_cases": len(age_rows), "tick_age_pass": sum(r["pass"] for r in age_rows),
    "unknown_offset_cases": len(cons), "unknown_offset_never_under": all(c["not_under"] for c in cons),
    "unknown_offset_overcount_cases": sum(1 for c in cons if c["P2"] > c["expected"]),
    "dst_switch_ok": all(d["P2"] == d["expected"] for d in dst),
    "P2_equals_COMBINED_everywhere": all(r["P2"] == r["COMBINED"] for r in rows),
    "files_unchanged": H0 == H1, "sha256": H1, "SIMULATED_ONLY": True,
}
json.dump({"summary": summary, "rows": rows, "tick_age": age_rows, "unknown_offset": cons, "dst": dst},
          open(OUT, "w"), indent=1, ensure_ascii=False)
print(f"{'case':<62} {'off':>5} {'exp':>3} {'v1.0':>5} {'P2':>4} {'COMB':>4}")
for r in rows:
    mk = lambda k: f"{r[k]}{'' if r[k] == r['expected'] else '✗'}"
    print(f"{r['case'][:62]:<62} {r['offset_h']:>5} {r['expected']:>3} {mk('v1.0'):>5} {mk('P2'):>4} {mk('COMBINED'):>4}")
print("\ntick age:")
for r in age_rows:
    print(f"  off {r['offset_h']:>5} age {r['tick_age_s']:>5}s detected={r['offset_detected']} (exp {r['expected_detected']}) "
          f"count={r['count']} exp={r['expected']} {'PASS' if r['pass'] else 'FAIL'}")
print("\nunknown offset (conservative):")
for c in cons:
    print(f"  {c['case'][:50]:<50} off {c['offset_h']:>5} {c['mode']:<12} exp {c['expected']} P2 {c['P2']} "
          f"{'OK' if c['not_under'] else 'UNDER!'}")
print("\nDST:", dst)
print(json.dumps(summary, indent=1, ensure_ascii=False))
