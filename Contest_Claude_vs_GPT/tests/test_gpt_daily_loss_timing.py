"""
GPT-এর দৈনিক ২-লস গণনা: আসল v1.0 বনাম প্রস্তাবিত v1.1 — server time ভিন্ন হলে কী হয়।
নকল MT5 (শুধু এই পরীক্ষার জন্য)। কোনো ফাইল বদলানো হয় না; GPT module-এর ঘড়ি শুধু মেমরিতে নকল করা হয়।
usage: python test_gpt_daily_loss_timing.py <package_dir> <out_json>
"""
import sys, os, types, json, hashlib, importlib.util
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace as NS

PKG, OUT = sys.argv[1], sys.argv[2]
ORIG = os.path.join(PKG, "gpt_liquidity_fibonacci_scalper_v1.py")
PROP = os.path.join(PKG, "proposals", "P2_daily_loss_server_time", "gpt_liquidity_fibonacci_scalper_v1.py")
h0 = hashlib.sha256(open(ORIG, "rb").read()).hexdigest()

W = {"now": None, "offset": 0, "deals": [], "tick_age": 5}
mt5 = types.ModuleType("MetaTrader5")
mt5.TIMEFRAME_H1, mt5.TIMEFRAME_M15 = 16385, 15
mt5.history_deals_get = lambda a, b: tuple(d for d in W["deals"] if a.timestamp() <= d.time <= b.timestamp())
mt5.account_info = lambda: NS(balance=10000.0)
mt5.symbol_info_tick = lambda s: NS(time=int(W["now"].timestamp()) + W["offset"] - W["tick_age"], bid=1, ask=1)
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


V10 = load(ORIG, "gpt_v10")
V11 = load(PROP, "gpt_v11")
MAGIC = V10.MAGIC

DAY = datetime(2026, 5, 13, tzinfo=timezone.utc)          # বুধবার


def build(events, offset):
    """events: [(utc_close_time, pnl)] — প্রতিটা আলাদা GPT position; deal-এর সময় = UTC + offset (server time)"""
    deals, pid = [], 1000
    for when, pnl in events:
        pid += 1
        open_t = int((when - timedelta(hours=1)).timestamp()) + offset
        close_t = int(when.timestamp()) + offset
        deals.append(NS(magic=MAGIC, symbol="BTCUSDm", position_id=pid, profit=0.0, commission=0.0, swap=0.0, time=open_t))
        deals.append(NS(magic=MAGIC, symbol="BTCUSDm", position_id=pid, profit=pnl, commission=0.0, swap=0.0, time=close_t))
    return deals


CASES = [
    # (নাম, এখন (UTC), ঘটনা, আজকের প্রত্যাশিত লস সংখ্যা)
    ("09:40 UTC, losses yday 22:30 + today 00:20, 09:00, 09:20, win 05:00",
     DAY + timedelta(hours=9, minutes=40),
     [(DAY - timedelta(hours=1, minutes=30), -30), (DAY + timedelta(minutes=20), -30),
      (DAY + timedelta(hours=9), -30), (DAY + timedelta(hours=9, minutes=20), -30), (DAY + timedelta(hours=5), 40)], 3),
    ("00:30 UTC, losses yday 22:30 + today 00:20",
     DAY + timedelta(minutes=30),
     [(DAY - timedelta(hours=1, minutes=30), -30), (DAY + timedelta(minutes=20), -30)], 1),
    ("23:50 UTC, losses today 21:00 + 23:40",
     DAY + timedelta(hours=23, minutes=50),
     [(DAY + timedelta(hours=21), -30), (DAY + timedelta(hours=23, minutes=40), -30)], 2),
    ("14:10 UTC, two losses in last 30 min (13:45, 14:05)",
     DAY + timedelta(hours=14, minutes=10),
     [(DAY + timedelta(hours=13, minutes=45), -30), (DAY + timedelta(hours=14, minutes=5), -30)], 2),
]
OFFSETS_H = [-5, 0, 2, 3, 5.5, 10]
FRESH_AGES = [5, 180]            # tick ৫ সেকেন্ড ও ৩ মিনিট পুরনো — দুটোই "তাজা"

rows, summary = [], {"v1.0_correct": 0, "v1.1_correct": 0, "total": 0, "v1.1_never_undercounts": True}
for name, now, ev, exp in CASES:
    for oh in OFFSETS_H:
        off = int(oh * 3600)
        for age in FRESH_AGES:
            W.update(now=now, offset=off, deals=build(ev, off), tick_age=age)
            a = V10.GPTLiquidityFibonacciScalper._daily_loss_count(("BTCUSDm", "XAUUSDm"))
            b = V11.GPTLiquidityFibonacciScalper._daily_loss_count(("BTCUSDm", "XAUUSDm"))
            rows.append({"case": name, "server_offset_h": oh, "tick_age_s": age, "expected": exp, "v1.0": a, "v1.1": b,
                         "v1.0_ok": a == exp, "v1.1_ok": b == exp})
            summary["total"] += 1
            summary["v1.0_correct"] += a == exp
            summary["v1.1_correct"] += b == exp

# offset জানা না গেলে (সব tick ২০ মিনিটের বেশি পুরনো) — v1.1 রক্ষণশীল হওয়ার কথা: কখনো কম গুনবে না
stale = []
for name, now, ev, exp in CASES:
    for oh in OFFSETS_H:
        off = int(oh * 3600)
        W.update(now=now, offset=off, deals=build(ev, off), tick_age=1200)   # ২০ মিনিট পুরনো = অজানা
        b = V11.GPTLiquidityFibonacciScalper._daily_loss_count(("BTCUSDm", "XAUUSDm"))
        stale.append({"case": name, "server_offset_h": oh, "expected": exp, "v1.1_stale_tick": b, "not_under": b >= exp})
        if b < exp:
            summary["v1.1_never_undercounts"] = False
summary["stale_tick_cases"] = len(stale)
summary["stale_tick_overcount_cases"] = sum(1 for s in stale if s["v1.1_stale_tick"] > s["expected"])

h1 = hashlib.sha256(open(ORIG, "rb").read()).hexdigest()
summary["original_sha256_before"] = h0
summary["original_sha256_after"] = h1
summary["original_unchanged"] = h0 == h1
summary["proposed_sha256"] = hashlib.sha256(open(PROP, "rb").read()).hexdigest()

json.dump({"summary": summary, "rows": rows, "stale_tick": stale}, open(OUT, "w"), indent=1)
print(f"{'case':<60} {'off':>5} {'age':>4} {'exp':>3} {'v1.0':>4} {'v1.1':>4}")
for r in rows:
    print(f"{r['case'][:60]:<60} {r['server_offset_h']:>5} {r['tick_age_s']:>4} {r['expected']:>3} {r['v1.0']:>4}{'' if r['v1.0_ok'] else '✗'} {r['v1.1']:>4}{'' if r['v1.1_ok'] else '✗'}")
print("\nstale tick (offset unknown -> conservative):")
for s_ in stale:
    print(f"  {s_['case'][:60]:<60} off {s_['server_offset_h']:>5} exp {s_['expected']} got {s_['v1.1_stale_tick']} {'OK (not under)' if s_['not_under'] else 'UNDER!'}")
print(json.dumps(summary, indent=1))
