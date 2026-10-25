"""
v2: P6c — Claude বট: বন্ধ-যাচাই + TP1 অবস্থা + BE retry + restart/অজানা order-এর পরে state মেলানো (orphan adoption)।
v5 (চালু) বনাম P6 / P6b / P6c (প্রস্তাব), নকল fault-injection broker-এ।
*** সব নকল। আসল MT5 নয়। কোনো ফাইল বদলানো হয় না। ***
usage: python test_p6_close_verification.py <package_dir> <out_json>
"""
import sys, os, types, json, tempfile, hashlib, importlib.util
PKG, OUT = sys.argv[1], sys.argv[2]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sim_mt5 as S
import sim_faults as SF

F = {"v5": os.path.join(PKG, "claude_pullback_v1.py"),
     "P6": os.path.join(PKG, "proposals", "P6_claude_close_verification", "claude_pullback_v1.py"),
     "P6b": os.path.join(PKG, "proposals", "P6b_claude_close_verification_plus_tp1_state", "claude_pullback_v1.py"),
     "P6c": os.path.join(PKG, "proposals", "v2", "P6c_claude_close_tp1_be_reconcile", "claude_pullback_v1.py")}
sha = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()
H0 = {k: sha(v) for k, v in F.items()}

mod = types.ModuleType("MetaTrader5")
b0 = SF.FaultyBroker(n_bars=3000); b0.pos_idx = 2800
SF.install(b0, mod)
sys.modules["MetaTrader5"] = mod


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


C = {k: load(p, "claude_" + k) for k, p in F.items()}
C["P6"].CLOSE_CONFIRM_DELAY = C["P6b"].CLOSE_CONFIRM_DELAY = C["P6c"].CLOSE_CONFIRM_DELAY = 0.0
ROWS = []


def rec(test, expected, actual, ok):
    ROWS.append({"test": test, "expected": expected, "actual": actual, "pass": bool(ok)})


def setup(ver, faults=None, vol=0.04, tp1_hit=True, bars_ago=0):
    b = SF.FaultyBroker(n_bars=3000, faults=faults); b.pos_idx = 2800
    SF.install(b, mod)
    logs, notes, sleeps = [], [], []
    M = C[ver]
    bot = M.ClaudePullbackV1(state_file=os.path.join(tempfile.mkdtemp(), "st.json"),
                             log=logs.append, notify=notes.append, clock=b.now_utc)
    if ver in ("P6", "P6b", "P6c"):
        bot.sleep = sleeps.append
    tick = b.symbol_info_tick("BTCUSDm")
    r = S.Broker.order_send(b, {"action": 1, "symbol": "BTCUSDm", "volume": vol, "type": 0,
                                "sl": tick.ask * 0.97, "tp": tick.ask * 1.06, "magic": M.MAGIC})
    pos = b.positions[r.order]
    tp1 = tick.bid * (0.999 if tp1_hit else 1.05)
    ebt = int(b.copy_rates_from_pos("BTCUSDm", 15, 1, 1)[-1]["time"]) - bars_ago * 900
    bot.trades[str(r.order)] = {"symbol": "BTCUSDm", "side": "BUY", "entry": pos.price_open, "sl": pos.sl,
                                "tp1": tp1, "tp2": pos.tp, "lot": vol, "risk_money": 50.0,
                                "entry_bar_time": ebt, "tp1_done": False, "open_utc": "x"}
    bot.state["BTCUSDm"]["phase"] = M.IN_TRADE
    return b, bot, r.order, logs, notes, sleeps


def be(p):
    return p is not None and abs(p.sl - round(p.price_open, 2)) < 1e-6


# ---------- T1: স্বাভাবিক TP1 আংশিক বন্ধ ----------
out = {}
for ver in ("v5", "P6", "P6b", "P6c"):
    b, bot, tk, logs, notes, sl = setup(ver)
    bot.manage_open_trades()
    p = b.positions.get(tk)
    out[ver] = (getattr(p, "volume", None), be(p), bot.trades[str(tk)].get("tp1_done"), len(b.requests))
    if ver in ("P6", "P6b", "P6c"):
        rec(f"T1 [{ver}] স্বাভাবিক TP1 (lot 0.04)",
            "বাকি 0.02, SL→BE, tp1_partial 'ok', log 'confirmed (remaining 0.02)', সতর্কবার্তা নেই, v5-এর সাথে broker-এ একই ফল",
            f"volume {out[ver][0]}, BE {out[ver][1]}, tp1_partial {bot.trades[str(tk)].get('tp1_partial')}, "
            f"confirmed-log {any('confirmed (remaining 0.02)' in l for l in logs)}, warnings {sum('WARNING' in l for l in logs)}, "
            f"v5 {out['v5']} vs {ver} {out[ver]}",
            abs(out[ver][0] - 0.02) < 1e-9 and out[ver][1] and bot.trades[str(tk)].get("tp1_partial") == "ok"
            and any("confirmed (remaining 0.02)" in l for l in logs) and not any("WARNING" in l for l in logs)
            and out["v5"] == out[ver])

# ---------- T2: TP1-এ broker নকল "done" (কিছু বন্ধ করে না) ----------
for ver in ("v5", "P6", "P6b", "P6c"):
    b, bot, tk, logs, notes, sl = setup(ver, {"fake_close_ok_n": 1})
    bot.manage_open_trades()
    p = b.positions.get(tk)
    t = bot.trades[str(tk)]
    if ver == "v5":
        rec("T2 [v5] TP1-এ নকল 'done'", "আগের অবস্থা দেখানো: v5 সফল ধরে নেয় (কোনো সতর্কবার্তা নেই), volume আসলে 0.04-ই",
            f"volume {p.volume}, warnings {sum('WARNING' in l for l in logs)}, log '{[l for l in logs if 'EXIT_TP1' in l][:1]}'",
            abs(p.volume - 0.04) < 1e-9 and not any("WARNING" in l for l in logs))
    else:
        rec(f"T2 [{ver}] TP1-এ নকল 'done'",
            "নিশ্চিত হয় না → WARNING log + notify, tp1_partial 'unconfirmed'; SL তবুও BE-তে; ৫ বার যাচাই (৪ বিরতি); নতুন close order নয়",
            f"volume {p.volume}, BE {be(p)}, tp1_partial {t.get('tp1_partial')}, tp1_done {t.get('tp1_done')}, "
            f"warning {any('NOT confirmed' in l for l in logs)}, notify {any('নিশ্চিত হয়নি' in n for n in notes)}, "
            f"sleeps {len(sl)}, close requests {sum(1 for r in b.requests if r['req'].get('position') and r['req'].get('action') == 1)}",
            abs(p.volume - 0.04) < 1e-9 and be(p) and t.get("tp1_partial") == "unconfirmed" and t.get("tp1_done")
            and any("NOT confirmed" in l for l in logs) and any("নিশ্চিত হয়নি" in n for n in notes) and len(sl) == 4
            and sum(1 for r in b.requests if r["req"].get("position") and r["req"].get("action") == 1) == 1)

# ---------- T3: time-stop-এ নকল "done" → পরের চক্রে আবার চেষ্টা ----------
for ver in ("v5", "P6", "P6b", "P6c"):
    b, bot, tk, logs, notes, sl = setup(ver, {"fake_close_ok_n": 1}, tp1_hit=False, bars_ago=20)
    bot.manage_open_trades()
    still1 = tk in b.positions
    hint1 = bot.trades.get(str(tk), {}).get("exit_hint")
    bot.manage_open_trades()                    # পরের চক্র: নকল শেষ, আসল বন্ধ
    still2 = tk in b.positions
    bot.manage_open_trades()                    # তার পরের চক্র: বন্ধ লেখা হয়
    recorded = any(c["ticket"] == tk for c in bot.closed)
    if ver == "v5":
        rec("T3 [v5] time-stop-এ নকল 'done'",
            "আগের অবস্থা দেখানো: প্রথম চক্রে 'EXIT_TIME' সফল ধরে নেয় (exit_hint বসে) অথচ পজিশন খোলা; পরের চক্রে শর্ত থাকায় আবার বন্ধ",
            f"after cycle1 open={still1} exit_hint={hint1}; after cycle2 open={still2}; recorded={recorded}",
            still1 and hint1 == "EXIT_TIME" and not still2 and recorded)
    else:
        rec(f"T3 [{ver}] time-stop-এ নকল 'done'",
            "প্রথম চক্রে নিশ্চিত হয় না → False, exit_hint বসে না, WARNING; পরের চক্রে আবার বন্ধ → confirmed; তারপর বন্ধ লেখা",
            f"after cycle1 open={still1} exit_hint={hint1} warning={any('NOT confirmed' in l for l in logs)}; "
            f"after cycle2 open={still2} confirmed-log={any('EXIT_TIME' in l and 'confirmed (closed)' in l for l in logs)}; recorded={recorded}",
            still1 and hint1 is None and any("NOT confirmed" in l for l in logs) and not still2
            and any("EXIT_TIME" in l and "confirmed (closed)" in l for l in logs) and recorded)

# ---------- T4: close প্রত্যাখ্যান — v5-এর মতোই (send ব্যর্থ, যাচাই ডাকা হয় না) ----------
for ver in ("v5", "P6", "P6b", "P6c"):
    b, bot, tk, logs, notes, sl = setup(ver, {"refuse_close": True}, tp1_hit=False, bars_ago=20)
    bot.manage_open_trades()
    rec(f"T4 [{ver}] time-stop close broker প্রত্যাখ্যান করে (10018)",
        "পজিশন খোলা, exit_hint নেই, যাচাই-বিরতি ০ (send-ই ব্যর্থ)",
        f"open={tk in b.positions} exit_hint={bot.trades[str(tk)].get('exit_hint')} sleeps={len(sl)}",
        tk in b.positions and bot.trades[str(tk)].get("exit_hint") is None and len(sl) == 0)

# ---------- T5: স্বাভাবিক time-stop ও max-hold পুরো বন্ধ ----------
for bars, reason in ((20, "EXIT_TIME"), (60, "EXIT_MAXHOLD")):
    res = {}
    for ver in ("v5", "P6", "P6b", "P6c"):
        b, bot, tk, logs, notes, sl = setup(ver, None, tp1_hit=False, bars_ago=bars)
        if reason == "EXIT_MAXHOLD":
            bot.trades[str(tk)]["tp1_done"] = True
        bot.manage_open_trades()
        res[ver] = (tk in b.positions, bot.trades[str(tk)].get("exit_hint"), len(b.requests))
        if ver in ("P6", "P6b", "P6c"):
            rec(f"T5 [{ver}] স্বাভাবিক {reason}", "বন্ধ, exit_hint বসে, log 'confirmed (closed)', v5-এর সাথে একই",
                f"v5 {res['v5']} vs {ver} {res[ver]}, confirmed {any('confirmed (closed)' in l for l in logs)}",
                res["v5"] == res[ver] and res[ver][0] is False and res[ver][1] == reason
                and any("confirmed (closed)" in l for l in logs))

# ---------- T6: আংশিক বন্ধের পরে বাকি volume ভুল (broker কম/বেশি বন্ধ করেছে) ----------
class WrongPartial(SF.FaultyBroker):
    def order_send(self, req):
        if req.get("position") and req.get("action") == S.TRADE_ACTION_DEAL:
            req = dict(req); req["volume"] = round(float(req["volume"]) / 2, 2)   # অনুরোধের অর্ধেক বন্ধ করে, "done" বলে
        return super().order_send(req)

for ver in ("v5", "P6", "P6b", "P6c"):
    b = WrongPartial(n_bars=3000); b.pos_idx = 2800
    SF.install(b, mod)
    logs, notes, sl = [], [], []
    M = C[ver]
    bot = M.ClaudePullbackV1(state_file=os.path.join(tempfile.mkdtemp(), "st.json"), log=logs.append,
                             notify=notes.append, clock=b.now_utc)
    if ver in ("P6", "P6b", "P6c"):
        bot.sleep = sl.append
    tick = b.symbol_info_tick("BTCUSDm")
    r = S.Broker.order_send(b, {"action": 1, "symbol": "BTCUSDm", "volume": 0.08, "type": 0, "sl": tick.ask * 0.97,
                                "tp": tick.ask * 1.06, "magic": M.MAGIC})
    bot.trades[str(r.order)] = {"symbol": "BTCUSDm", "side": "BUY", "entry": b.positions[r.order].price_open,
                                "sl": tick.ask * 0.97, "tp1": tick.bid * 0.999, "tp2": tick.ask * 1.06, "lot": 0.08,
                                "risk_money": 50.0, "entry_bar_time": int(b.copy_rates_from_pos("BTCUSDm", 15, 1, 1)[-1]["time"]),
                                "tp1_done": False, "open_utc": "x"}
    bot.state["BTCUSDm"]["phase"] = M.IN_TRADE
    bot.manage_open_trades()
    p = b.positions.get(r.order)
    t = bot.trades[str(r.order)]
    if ver == "v5":
        rec("T6 [v5] TP1: broker 0.04-এর বদলে 0.02 বন্ধ করে 'done' বলে", "আগের অবস্থা: v5 ধরতে পারে না (সতর্কবার্তা নেই)",
            f"remaining {p.volume} (expected 0.04), warnings {sum('WARNING' in l for l in logs)}", not any("WARNING" in l for l in logs))
    else:
        rec(f"T6 [{ver}] TP1: broker 0.04-এর বদলে 0.02 বন্ধ করে 'done' বলে",
            "বাকি volume মেলে না (0.06 ≠ 0.04) → WARNING, tp1_partial 'unconfirmed', state-এ আসল বাকি volume দেখায়",
            f"remaining {p.volume}, tp1_partial {t.get('tp1_partial')}, warning {[l for l in logs if 'NOT confirmed' in l][:1]}",
            abs(p.volume - 0.06) < 1e-9 and t.get("tp1_partial") == "unconfirmed" and any("expected 0.04" in l for l in logs))

# ---------- T7: বন্ধ পাঠানোর ঠিক পরে সংযোগ বিচ্ছিন্ন (TP1) ----------
for ver in ("v5", "P6", "P6b", "P6c"):
    b, bot, tk, logs, notes, sl = setup(ver)
    _orig = b.order_send
    once = {"left": 1}
    def _send_then_drop(req, _o=_orig, _b=b, _once=once):
        r = _o(req)
        if req.get("position") and _once["left"] > 0:
            _once["left"] -= 1
            _b.connected = False                                  # প্রথম TP1 close চলে গেছে, তারপর সব None
        return r
    b.order_send = _send_then_drop
    SF.install(b, mod)
    bot.manage_open_trades()
    v_after = S.Broker.positions_get(b, ticket=tk)[0].volume
    t1 = dict(bot.trades[str(tk)])
    b.connected = True                                            # সংযোগ ফিরে আসে
    bot.manage_open_trades()
    v_after2 = S.Broker.positions_get(b, ticket=tk)[0].volume if S.Broker.positions_get(b, ticket=tk) else None
    p_now = b.positions.get(tk)
    exp7 = ("জানা দুর্বলতা দেখানো: সংযোগ ফেরার পরে দ্বিতীয়বার আংশিক বন্ধ (0.04 → 0.02 → 0.01), তারপর BE" if ver not in ("P6b", "P6c") else
            "দ্বিতীয়বার আংশিক বন্ধ নয় (0.02-ই থাকে); tp1_done আগেই লেখা; সংযোগ ফেরার পরে SL→BE বসে")
    ok7 = (v_after2 is not None and abs(v_after2 - 0.01) < 1e-9) if ver not in ("P6b", "P6c") else \
          (abs(v_after2 - 0.02) < 1e-9 and t1.get("tp1_done") is True and be(p_now) and not bot.trades[str(tk)].get("be_pending"))
    rec(f"T7 [{ver}] TP1 close যাওয়ার পরেই সংযোগ বিচ্ছিন্ন, তারপর সংযোগ ফেরা", exp7,
        f"after close {v_after}, tp1_done {t1.get('tp1_done')}, tp1_partial {t1.get('tp1_partial')}; after reconnect cycle volume {v_after2}"
        + f", BE now {be(p_now)}" + (f", warnings {[l for l in logs if 'NOT confirmed' in l][:1]}" if ver != "v5" else ""),
        ok7)

# ---------- T8 (P6b): SL→BE broker প্রত্যাখ্যান করলে পরের চক্রে আবার, সর্বোচ্চ ৫ বার ----------
for ver, n_reject in (("P6b", 2), ("P6b", 99), ("P6c", 2), ("P6c", 99), ("v5", 2)):
    b, bot, tk, logs, notes, sl = setup(ver)
    left = {"n": n_reject}
    _o = b.order_send
    def _rej(req, _o=_o, _left=left):
        from types import SimpleNamespace as NS
        if req.get("action") == S.TRADE_ACTION_SLTP and _left["n"] > 0:
            _left["n"] -= 1
            return NS(retcode=10016, order=0, deal=0, comment="Invalid stops (injected)")
        return _o(req)
    b.order_send = _rej
    SF.install(b, mod)
    for _ in range(7):
        bot.manage_open_trades()
    p = b.positions.get(tk)
    sltp = sum(1 for r in b.requests if r["req"].get("action") == S.TRADE_ACTION_SLTP)
    t = bot.trades[str(tk)]
    if ver == "v5":
        rec("T8 [v5] SL→BE প্রথম ২ বার প্রত্যাখ্যাত", "আগের অবস্থা: v5 একবারই চেষ্টা করে, আর করে না — SL BE-তে যায় না",
            f"BE {be(p)}, accepted SLTP requests {sltp}, rejected {n_reject - left['n']}", not be(p))
    elif n_reject == 2:
        rec(f"T8 [{ver}] SL→BE প্রথম ২ বার প্রত্যাখ্যাত", "পরের চক্রগুলোতে আবার চেষ্টা → তৃতীয়বারে BE বসে, be_pending False, ২টা WARNING",
            f"BE {be(p)}, be_pending {t.get('be_pending')}, be_tries {t.get('be_tries')}, warnings {sum('SL→BE failed' in l for l in logs)}",
            be(p) and not t.get("be_pending") and sum("SL→BE failed" in l for l in logs) == 2)
    else:
        rec(f"T8 [{ver}] SL→BE সবসময় প্রত্যাখ্যাত", "৫ বার চেষ্টা, তারপর থামে + notify 'হাতে দেখুন' (প্রতি সেকেন্ডে অসীম request নয়)",
            f"BE {be(p)}, tries {t.get('be_tries')}, rejected {n_reject - left['n']}, notify {any('হাতে দেখুন' in n for n in notes)}",
            not be(p) and t.get("be_tries") == 5 and n_reject - left["n"] == 5 and any("হাতে দেখুন" in n for n in notes))


# =====================================================================================
# v2 নতুন: restart ও অজানা order-এর পরে state মেলানো (P6c)
# =====================================================================================
def new_bot(ver, b, state_file, logs, notes):
    SF.install(b, mod)
    bot = C[ver].ClaudePullbackV1(state_file=state_file, log=logs.append, notify=notes.append, clock=b.now_utc)
    if ver != "v5":
        bot.sleep = lambda s: None
    return bot

# T9: T7-এর পরিস্থিতি, তারপর প্রোগ্রাম restart (নতুন instance, একই state ফাইল)
for ver in ("v5", "P6b", "P6c"):
    b, bot, tk, logs, notes, sl = setup(ver)
    sf = bot.state_file
    once = {"left": 1}
    _orig = b.order_send
    def _drop(req, _o=_orig, _b=b, _once=once):
        r = _o(req)
        if req.get("position") and _once["left"] > 0:
            _once["left"] -= 1
            _b.connected = False
        return r
    b.order_send = _drop; SF.install(b, mod)
    bot.manage_open_trades()                       # TP1 close যায়, তারপর সংযোগ বিচ্ছিন্ন
    if ver == "v5":
        bot._save()                                # v5 এই অবস্থায় নিজে save করে না; restart-এর আগে শেষ save ধরে নিই
    b.connected = True
    logs2, notes2 = [], []
    bot2 = new_bot(ver, b, sf, logs2, notes2)       # restart
    bot2.manage_open_trades()
    bot2.manage_open_trades()
    p = b.positions.get(tk)
    t = bot2.trades.get(str(tk), {})
    if ver == "v5":
        rec("T9 [v5] TP1 close-এর পরে সংযোগ বিচ্ছিন্ন → restart", "আগের অবস্থা: restart-এর পরে দ্বিতীয়বার আংশিক বন্ধ",
            f"volume {getattr(p, 'volume', None)}, tp1_done {t.get('tp1_done')}", p is not None and abs(p.volume - 0.01) < 1e-9)
    else:
        exp_partial = "ok (reconciled)" if ver == "P6c" else "unconfirmed"
        rec(f"T9 [{ver}] TP1 close-এর পরে সংযোগ বিচ্ছিন্ন → restart",
            "দ্বিতীয় আংশিক বন্ধ নয় (0.02), BE বসে, be_pending False; " +
            ("tp1_partial 'ok (reconciled)' (বাকি volume দেখে মেলানো)" if ver == "P6c" else "tp1_partial 'unconfirmed' থেকে যায় (P6b মেলায় না)"),
            f"volume {getattr(p, 'volume', None)}, BE {be(p)}, tp1_partial {t.get('tp1_partial')}, be_pending {t.get('be_pending')}",
            p is not None and abs(p.volume - 0.02) < 1e-9 and be(p) and t.get("tp1_partial") == exp_partial and not t.get("be_pending"))

# T10: Claude-এর entry-তে order_send None অথচ পজিশন খোলে (orphan) → পরের চক্রে কী হয়
def orphan_case(ver, sl_mult=0.97, tp_mult=1.06, extra=None):
    b = SF.FaultyBroker(n_bars=3000); b.pos_idx = 2800
    logs, notes = [], []
    sf = os.path.join(tempfile.mkdtemp(), "st.json")
    bot = new_bot(ver, b, sf, logs, notes)
    tick = b.symbol_info_tick("BTCUSDm")
    r = S.Broker.order_send(b, {"action": 1, "symbol": "BTCUSDm", "volume": 0.04, "type": 0,
                                "sl": round(tick.ask * sl_mult, 2), "tp": round(tick.ask * tp_mult, 2), "magic": C[ver].MAGIC})
    if extra:
        extra(b)
    return b, bot, r.order, logs, notes, sf

for ver in ("v5", "P6c"):
    b, bot, tk, logs, notes, sf = orphan_case(ver)
    n0 = len(b.requests)
    bot.manage_open_trades()
    t = bot.trades.get(str(tk))
    if ver == "v5":
        rec("T10 [v5] entry-তে order_send None, পজিশন আসলে খোলা (state-এ নেই)", "আগের অবস্থা: পজিশন ব্যবস্থাপনার বাইরে (orphan)",
            f"tracked {t is not None}", t is None)
    else:
        rec("T10 [P6c] entry-তে order_send None, পজিশন আসলে খোলা (state-এ নেই)",
            "পরের চক্রে adopt: state-এ আসে, phase IN_TRADE, TP1 = entry + 1R, tp1_done False, WARNING + notify, নতুন order নয়",
            f"tracked {t is not None}, tp1 {t and t['tp1']}, tp1_done {t and t['tp1_done']}, phase {bot.state['BTCUSDm']['phase']}, "
            f"new requests {len(b.requests) - n0}, warning {any('adopted' in l for l in logs)}",
            t is not None and not t["tp1_done"] and bot.state["BTCUSDm"]["phase"] == C[ver].IN_TRADE
            and abs(t["tp1"] - round(t["entry"] + (t["entry"] - t["sl"]), 2)) < 0.011 and len(b.requests) == n0
            and any("adopted" in l for l in logs) and any("পজিশন পাওয়া গেছে" in n for n in notes))

# T11: adopt-এর পরে TP1 ছুঁলে আংশিক বন্ধ ও BE স্বাভাবিকভাবে চলে
b, bot, tk, logs, notes, sf = orphan_case("P6c")
bot.manage_open_trades()
bot.trades[str(tk)]["tp1"] = b.symbol_info_tick("BTCUSDm").bid * 0.999      # TP1 ছোঁয়ানো
bot.manage_open_trades()
p = b.positions.get(tk)
t = bot.trades[str(tk)]
rec("T11 [P6c] adopt করা পজিশনে TP1", "অর্ধেক বন্ধ (0.02 বাকি), tp1_partial ok, SL→BE",
    f"volume {getattr(p, 'volume', None)}, tp1_partial {t.get('tp1_partial')}, BE {be(p)}",
    p is not None and abs(p.volume - 0.02) < 1e-9 and t.get("tp1_partial") == "ok" and be(p))

# T12: state ফাইল হারিয়ে গেছে (crash before save) → restart
for ver in ("v5", "P6c"):
    b, bot, tk, logs, notes, sl = setup(ver)
    os.path.exists(bot.state_file) and os.remove(bot.state_file)
    logs2, notes2 = [], []
    bot2 = new_bot(ver, b, os.path.join(tempfile.mkdtemp(), "fresh.json"), logs2, notes2)
    bot2.manage_open_trades()
    rec(f"T12 [{ver}] state ফাইল নেই, broker-এ নিজের পজিশন খোলা → restart",
        "আগের অবস্থা: ব্যবস্থাপনার বাইরে" if ver == "v5" else "adopt করে ব্যবস্থাপনায় নেয়",
        f"tracked {str(tk) in bot2.trades}", (str(tk) in bot2.trades) == (ver == "P6c"))

# T13: SL আগেই BE-তে থাকা পজিশন adopt → tp1_done True (আবার আংশিক বন্ধ নয়)
def to_be(b):
    for p in b.positions.values():
        p.sl = p.price_open
b, bot, tk, logs, notes, sf = orphan_case("P6c", extra=to_be)
bot.manage_open_trades()
n0 = len(b.requests)
bot.trades[str(tk)]["tp1"] = b.symbol_info_tick("BTCUSDm").bid * 0.999
bot.manage_open_trades()
t = bot.trades[str(tk)]
rec("T13 [P6c] SL আগেই entry-তে (BE) এমন পজিশন adopt", "tp1_done True, TP1 ছুঁলেও নতুন আংশিক বন্ধ নয়",
    f"tp1_done {t['tp1_done']}, close requests {sum(1 for r in b.requests[n0:] if r['req'].get('position'))}, volume {b.positions[tk].volume}",
    t["tp1_done"] and abs(b.positions[tk].volume - 0.04) < 1e-9)

# T14: GPT-এর পজিশন, অন্য symbol-এর পজিশন কখনো adopt নয়; positions_get None হলে কিছু বদলায় না
b = SF.FaultyBroker(n_bars=3000); b.pos_idx = 2800
logs, notes = [], []
bot = new_bot("P6c", b, os.path.join(tempfile.mkdtemp(), "st.json"), logs, notes)
S.Broker.order_send(b, {"action": 1, "symbol": "BTCUSDm", "volume": 0.01, "type": 0, "sl": 0, "tp": 0, "magic": 26102402})
S.Broker.order_send(b, {"action": 1, "symbol": "BTCUSDm", "volume": 0.01, "type": 0, "sl": 0, "tp": 0, "magic": 999})
bot.manage_open_trades()
a1 = len(bot.trades)
S.Broker.order_send(b, {"action": 1, "symbol": "BTCUSDm", "volume": 0.02, "type": 0, "sl": 1.0, "tp": 0, "magic": C["P6c"].MAGIC})
b.connected = False
bot.manage_open_trades()
a2 = len(bot.trades)
b.connected = True
rec("T14 [P6c] GPT (26102402) ও অজানা magic-এর পজিশন; তারপর positions_get None",
    "অন্যের পজিশন adopt নয় (০); MT5 None হলে কিছু বদলায় না (০), 'MT5 unavailable' log",
    f"after others {a1}, during None {a2}, log {any('MT5 unavailable' in l for l in logs)}",
    a1 == 0 and a2 == 0 and any("MT5 unavailable" in l for l in logs))

# T15: orphan নেই → স্বাভাবিক পথে কোনো অতিরিক্ত order request নয় (T1/T5 ইতিমধ্যে v5-এর সাথে broker-ফল মেলায়)
b, bot, tk, logs, notes, sl = setup("P6c", tp1_hit=False)
n0 = len(b.requests)
for _ in range(5):
    bot.manage_open_trades()
rec("T15 [P6c] tracked পজিশন, কিছু ঘটছে না, ৫ চক্র", "০টা order request, adopt নেই", f"requests {len(b.requests) - n0}, trades {len(bot.trades)}",
    len(b.requests) == n0 and len(bot.trades) == 1)

H1 = {k: sha(v) for k, v in F.items()}
rec("ALL পরীক্ষার আগে-পরে ফাইল SHA-256", "অপরিবর্তিত", f"{ {k: v[:16] for k, v in H1.items()} } unchanged={H0 == H1}", H0 == H1)
summary = {"total": len(ROWS), "passed": sum(r["pass"] for r in ROWS), "sha256": H1, "SIMULATED_ONLY": True}
json.dump({"summary": summary, "rows": ROWS}, open(OUT, "w"), indent=1, ensure_ascii=False)
for r in ROWS:
    print(("PASS " if r["pass"] else "FAIL ") + r["test"] + f"\n      expected: {r['expected']}\n      actual:   {r['actual']}")
print(json.dumps(summary, indent=1, ensure_ascii=False))
