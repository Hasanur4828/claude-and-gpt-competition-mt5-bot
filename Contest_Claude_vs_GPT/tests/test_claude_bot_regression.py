"""
Claude বটের পরিবর্তনের regression test (নকল broker — আসল MT5 নয়)
  R1  plan_partial_close(): volume নিয়মের সব ধরনের ক্ষেত্র
  R2  TP1: অদ্ভুত volume নিয়মে আংশিক বন্ধ বাদ, কিন্তু SL→breakeven হয়; স্বাভাবিক নিয়মে অর্ধেক বন্ধ
  R3  MT5 সংযোগ বিচ্ছিন্ন: খোলা ট্রেডকে "বন্ধ" ধরে না, হিসাব থেকে মোছে না; সংযোগ ফিরলে ঠিকমতো বন্ধ লেখে
  R4  positions_get None হলে _own_positions MT5Unavailable তোলে (entry SKIP_TERMINAL-এর ভিত্তি)
  R5  order_send None (ফল অজানা) হলে Claude আর পাঠায় না — দ্বিগুণ পজিশনের ঝুঁকি নেই
usage: python test_claude_bot_regression.py <package_dir> <out_json>
"""
import sys, os, types, json, tempfile
from types import SimpleNamespace as NS
PKG, OUT = sys.argv[1], sys.argv[2]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sim_mt5 as S
import sim_faults as SF

mod = types.ModuleType("MetaTrader5")
b0 = SF.FaultyBroker(n_bars=3000); b0.pos_idx = 2800
SF.install(b0, mod)
sys.modules["MetaTrader5"] = mod
sys.path.insert(0, PKG)
import claude_pullback_v1 as C

rows = []
def rec(test, expected, actual, ok):
    rows.append({"test": test, "expected": expected, "actual": actual, "pass": bool(ok)})
    print(("PASS " if ok else "FAIL ") + test + f" | expected: {expected} | actual: {actual}")

# নোট: নকল broker দাম symbol-এর digits-এ round করে না; বট SL বসায় round(entry, digits)-এ, তাই তুলনাও সেভাবে।
# ---------- R1 ----------
cases = [
    ((0.02, 0.01, 0.01, 100), (0.01, 0.01)),
    ((0.03, 0.01, 0.01, 100), (0.01, 0.02)),
    ((0.01, 0.01, 0.01, 100), None),
    ((0.10, 0.10, 0.10, 100), None),
    ((0.30, 0.10, 0.10, 100), (0.1, 0.2)),
    ((0.25, 0.10, 0.05, 100), (0.1, 0.15)),
    ((0.15, 0.10, 0.05, 100), None),
    ((5.00, 0.01, 0.01, 2.0), None),
    ((0.02, 0.01, 0.0, 100), None),
]
for (vol, vmin, step, vmax), exp in cases:
    plan, why = C.plan_partial_close(vol, NS(volume_min=vmin, volume_step=step, volume_max=vmax))
    got = None if plan is None else tuple(round(x, 8) for x in plan)
    rec(f"R1 plan_partial_close(vol={vol}, min={vmin}, step={step}, max={vmax})",
        exp, f"{got} {why}".strip(), got == exp)


def bot_with_trade(broker, vol, tp1_hit=True):
    SF.install(broker, mod)
    logs = []
    bot = C.ClaudePullbackV1(state_file=os.path.join(tempfile.mkdtemp(), "st.json"),
                             log=logs.append, notify=lambda s: None, clock=broker.now_utc)
    tick = broker.symbol_info_tick("BTCUSDm")
    r = broker.order_send({"action": 1, "symbol": "BTCUSDm", "volume": vol, "type": 0,
                           "sl": tick.ask * 0.97, "tp": tick.ask * 1.06, "magic": C.MAGIC})
    pos = broker.positions[r.order]
    tp1 = tick.bid * (0.999 if tp1_hit else 1.05)
    bot.trades[str(r.order)] = {"symbol": "BTCUSDm", "side": "BUY", "entry": pos.price_open, "sl": pos.sl,
                                "tp1": tp1, "tp2": pos.tp, "lot": vol, "risk_money": 50.0,
                                "entry_bar_time": int(broker.copy_rates_from_pos("BTCUSDm", 15, 1, 1)[-1]["time"]),
                                "tp1_done": False, "open_utc": "x"}
    bot.state["BTCUSDm"]["phase"] = C.IN_TRADE
    return bot, r.order, logs

# ---------- R2 ----------
b = SF.FaultyBroker(n_bars=3000, faults={"vol_rules": {"BTCUSDm": (0.1, 0.1, 100.0)}}); b.pos_idx = 2800
bot, tk, logs = bot_with_trade(b, 0.1)
bot.manage_open_trades()
p = b.positions.get(tk)
rec("R2a TP1 with min 0.1 / step 0.1, lot 0.1 → partial skipped, SL moved to entry",
    "volume 0.1, sl == entry, tp1_done, log says skipped",
    f"volume {getattr(p,'volume',None)}, sl==entry {p is not None and abs(p.sl - round(p.price_open, 2)) < 1e-6}, "
    f"tp1_done {bot.trades[str(tk)]['tp1_done']}, logged {any('partial close skipped' in l for l in logs)}",
    p is not None and abs(p.volume - 0.1) < 1e-9 and abs(p.sl - round(p.price_open, 2)) < 1e-6
    and bot.trades[str(tk)]["tp1_done"] and any("partial close skipped" in l for l in logs))

b = SF.FaultyBroker(n_bars=3000, faults={"vol_rules": {"BTCUSDm": (0.1, 0.1, 100.0)}}); b.pos_idx = 2800
bot, tk, logs = bot_with_trade(b, 0.3)
bot.manage_open_trades()
p = b.positions.get(tk)
rec("R2b TP1 with min 0.1 / step 0.1, lot 0.3 → close 0.1, keep 0.2, SL→entry",
    "volume 0.2, sl == entry", f"volume {getattr(p,'volume',None)}, sl==entry {p is not None and abs(p.sl - round(p.price_open, 2)) < 1e-6}",
    p is not None and abs(p.volume - 0.2) < 1e-9 and abs(p.sl - round(p.price_open, 2)) < 1e-6)

b = SF.FaultyBroker(n_bars=3000); b.pos_idx = 2800
bot, tk, logs = bot_with_trade(b, 0.04)
bot.manage_open_trades()
p = b.positions.get(tk)
rec("R2c TP1 normal rules (min 0.01 / step 0.01), lot 0.04 → half closed (same as v4)",
    "volume 0.02, sl == entry", f"volume {getattr(p,'volume',None)}, sl==entry {p is not None and abs(p.sl - round(p.price_open, 2)) < 1e-6}",
    p is not None and abs(p.volume - 0.02) < 1e-9 and abs(p.sl - round(p.price_open, 2)) < 1e-6)

b = SF.FaultyBroker(n_bars=3000); b.pos_idx = 2800
bot, tk, logs = bot_with_trade(b, 0.04, tp1_hit=False)
bot.manage_open_trades()
p = b.positions.get(tk)
rec("R2d TP1 not reached → nothing changes", "volume 0.04, sl unchanged, tp1_done False",
    f"volume {getattr(p,'volume',None)}, tp1_done {bot.trades[str(tk)]['tp1_done']}",
    p is not None and abs(p.volume - 0.04) < 1e-9 and not bot.trades[str(tk)]["tp1_done"])

# ---------- R3 ----------
b = SF.FaultyBroker(n_bars=3000); b.pos_idx = 2800
bot, tk, logs = bot_with_trade(b, 0.04, tp1_hit=False)
b.connected = False
bot.manage_open_trades()
rec("R3a MT5 disconnected → open trade NOT recorded as closed, kept in management",
    "trade still tracked, 0 closed records, log 'MT5 unavailable'",
    f"tracked {str(tk) in bot.trades}, closed {len(bot.closed)}, logged {any('MT5 unavailable' in l for l in logs)}",
    str(tk) in bot.trades and len(bot.closed) == 0 and any("MT5 unavailable" in l for l in logs))
b.connected = True
p = b.positions[tk]
b._close(p, p.volume, b._price("BTCUSDm") - 50, S.DEAL_REASON_SL, p.magic)      # broker-এ SL লাগল
bot.manage_open_trades()
net_truth = round(b.truth[tk]["net"], 2)
rec("R3b connection back, position closed by SL → recorded once with correct net",
    f"1 closed record, net {net_truth}", f"{len(bot.closed)} record(s), net {bot.closed[-1]['net'] if bot.closed else None}",
    len(bot.closed) == 1 and abs(bot.closed[-1]["net"] - net_truth) < 0.011 and str(tk) not in bot.trades)

# ---------- R4 ----------
b = SF.FaultyBroker(n_bars=3000); b.pos_idx = 2800
SF.install(b, mod)
mod.positions_get = lambda symbol=None, ticket=None: None
bot = C.ClaudePullbackV1(state_file=os.path.join(tempfile.mkdtemp(), "st.json"), log=lambda s: None,
                         notify=lambda s: None, clock=b.now_utc)
try:
    bot._own_positions("ETHUSDm"); raised = False
except C.MT5Unavailable:
    raised = True
rec("R4 positions_get → None raises MT5Unavailable (never treated as 'no positions')", "MT5Unavailable", raised, raised)

# ---------- R5 ----------
b = SF.FaultyBroker(n_bars=3000, faults={"open_returns_none": True}); b.pos_idx = 2800
SF.install(b, mod)
logs = []
bot = C.ClaudePullbackV1(state_file=os.path.join(tempfile.mkdtemp(), "st.json"), log=logs.append,
                         notify=lambda s: None, clock=b.now_utc)
r = bot._send({"action": 1, "symbol": "BTCUSDm", "volume": 0.02, "type": 0, "sl": 1.0, "tp": 10 ** 7}, "BTCUSDm", 1)
opened = sum(1 for p in b.positions.values() if p.magic == C.MAGIC)
rec("R5 order_send returns None (outcome unknown) → Claude does NOT resend with other filling modes",
    "1 send, result None, 1 position at most", f"sends {b.sends}, result {r}, positions {opened}",
    b.sends == 1 and r is None and opened <= 1)

json.dump(rows, open(OUT, "w"), indent=1, ensure_ascii=False)
print("\nREGRESSION:", f"{sum(r['pass'] for r in rows)}/{len(rows)} PASS")
