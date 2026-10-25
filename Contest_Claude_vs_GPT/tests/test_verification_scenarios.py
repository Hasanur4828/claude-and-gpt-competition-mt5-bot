"""
demo_verification v2 — GPT-এর ১৫টা পরিস্থিতি (+ baseline), নকল fault-injection broker-এ।
*** সব নকল। আসল MT5 নয়। ***
প্রতিটা পরিস্থিতি: আলাদা নতুন broker, প্যাকেজের আলাদা কপি (নিজস্ব খাতা), নতুন import।
usage: python test_verification_scenarios.py <package_dir> <out_json>
"""
import sys, os, types, shutil, tempfile, json, importlib
PKG, OUT = sys.argv[1], sys.argv[2]
TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TESTS)
import sim_mt5 as S
import sim_faults as SF

MODS = ("demo_verification", "contest_preflight", "contest_counter", "claude_pullback_v1", "gpt_contest_adapter",
        "gpt_liquidity_fibonacci_scalper_v1", "verification_journal")
CL, GP = 26102401, 26102402


class Env:
    def __init__(self, faults=None, **bk):
        from datetime import datetime, timezone, timedelta
        # নকল broker-এর "এখন" = আসল এখনের কাছাকাছি, যাতে স্ক্রিপ্টের সময়-জানালা বাস্তবের মতো কাজ করে
        start = datetime.now(timezone.utc).replace(second=0, microsecond=0) - timedelta(minutes=15 * 2800)
        self.b = SF.FaultyBroker(faults=faults, n_bars=3000, start_utc=start, **bk)
        self.b.pos_idx = 2800
        self.mod = types.ModuleType("MetaTrader5")
        SF.install(self.b, self.mod)
        sys.modules["MetaTrader5"] = self.mod
        self.D = os.path.join(tempfile.mkdtemp(), "pkg")
        shutil.copytree(PKG, self.D, ignore=shutil.ignore_patterns("tests", "proposals", "gpt_original_unchanged",
                                                                   "verification_positions.json", "demo_verification_*"))
        self.V = None

    def fresh_import(self):
        for k in [k for k in list(sys.modules) if k in MODS]:
            del sys.modules[k]
        while self.D in sys.path:
            sys.path.remove(self.D)
        sys.path.insert(0, self.D)
        SF.install(self.b, self.mod)
        sys.modules["MetaTrader5"] = self.mod
        self.V = importlib.import_module("demo_verification")
        self.V.SLEEP = lambda s: None
        return self.V

    def open_raw(self, magic, symbol="BTCUSDm", side=0, vol=0.01):
        t = self.b.symbol_info_tick(symbol)
        return S.Broker.order_send(self.b, {"action": 1, "symbol": symbol, "volume": vol, "type": side,
                                            "sl": 0.0, "tp": 0.0, "magic": magic})

    def run(self, patch=None):
        V = self.fresh_import()
        if patch:
            patch(self, V)
        n0 = len(self.b.requests)
        ok = V.main(assume_yes=True)
        import verification_journal as VJ
        jst, jmsg, _ = VJ.load(os.path.join(self.D, "verification_positions.json"))
        res = V.ST["results"]
        return {
            "ok": ok,
            "failed": [r["check"] for r in res if "ok" in r and not r["ok"]],
            "urgent": len(V.ST["urgent"]), "urgent_msgs": V.ST["urgent"][:4],
            "leftovers": V.ST["leftovers"],
            "requests": len(self.b.requests) - n0,
            "contest_positions_open": sorted(t for t, p in self.b.positions.items() if p.magic in (CL, GP)),
            "all_positions": {t: p.magic for t, p in self.b.positions.items()},
            "journal": jst, "journal_msg": jmsg,
            "shutdown": getattr(self.b, "shutdown_called", False),
            "report": os.path.exists(os.path.join(self.D, "demo_verification_report.json")),
            "log": open(os.path.join(self.D, "demo_verification_log.txt"), encoding="utf-8").read()
            if os.path.exists(os.path.join(self.D, "demo_verification_log.txt")) else "",
        }


ROWS = []


def scen(sid, title, expected, fn):
    try:
        actual, ok = fn()
    except Exception as e:
        import traceback
        actual, ok = f"TEST HARNESS ERROR {type(e).__name__}: {e}\n{traceback.format_exc()}", False
    ROWS.append({"id": sid, "scenario": title, "expected": expected, "actual": actual, "pass": bool(ok)})
    print(f"{'PASS' if ok else 'FAIL'}  [{sid}] {title}\n      expected: {expected}\n      actual:   {actual}\n")


def short(r):
    return (f"ok={r['ok']} failed={r['failed']} urgent={r['urgent']} requests={r['requests']} "
            f"contest_open={r['contest_positions_open']} journal={r['journal']} shutdown={r['shutdown']}")


# ---------------- S0 baseline ----------------
def s0():
    r = Env().run()
    return short(r), r["ok"] and not r["urgent"] and not r["contest_positions_open"] and r["journal"] == "OK" and r["shutdown"]
scen("S0", "Baseline: normal Hedging demo", "all checks pass, 0 test positions left, journal OK, shutdown called", s0)

# ---------------- 1 ----------------
def s1a():
    e = Env({"open_returns_none": True}); r = e.run()
    gpt_open = [t for t, m in r["all_positions"].items() if m == GP]
    ok = (not r["ok"]) and r["urgent"] >= 1 and gpt_open and not any(m == CL for m in r["all_positions"].values()) \
        and r["journal"] == "INCOMPLETE" and r["shutdown"]
    return short(r) + f" | GPT positions left (unlinked, not auto-closed): {gpt_open}", ok
scen("1a", "Broker returns None for the open (but the order executed)",
     "position cannot be linked → NOT auto-closed, urgent warning with tickets, Claude order never sent, journal INCOMPLETE "
     "(note: GPT's own _send_order retries other filling modes on None, so >1 GPT position can appear)", s1a)

def s1b():
    r = Env({"wrong_order_ticket": True}).run()
    return short(r), r["ok"] and not r["contest_positions_open"]
scen("1b", "Broker returns a wrong order ticket (deal ticket correct)", "resolved via deal → position_id; all pass; nothing left", s1b)

def s1c():
    r = Env({"wrong_deal_ticket": True}).run()
    return short(r), r["ok"] and not r["contest_positions_open"]
scen("1c", "Broker returns a wrong deal ticket (order ticket correct)", "resolved via order → deal history; all pass; nothing left", s1c)

def s1d():
    r = Env({"wrong_order_ticket": True, "wrong_deal_ticket": True}).run()
    ok = (not r["ok"]) and r["urgent"] >= 1 and len(r["contest_positions_open"]) == 1 and r["journal"] == "INCOMPLETE"
    return short(r), ok
scen("1d", "Both order and deal tickets wrong", "cannot confirm → stop further orders, urgent, the 1 GPT position NOT auto-closed, journal INCOMPLETE", s1d)

# ---------------- 2 ----------------
def s2():
    r = Env({"hide_new_positions_n": 3}).run()
    return short(r), r["ok"] and not r["contest_positions_open"]
scen("2", "Order succeeds but position not visible for the first 3 queries", "polling finds it; all pass; nothing left", s2)

# ---------------- 3 ----------------
def s3():
    r = Env({"partial_fill": 0.5}).run()
    return short(r) + (" | partial-fill logged" if "partial fill" in r["log"] else ""), \
        r["ok"] and not r["contest_positions_open"] and "partial fill" in r["log"]
scen("3", "Orders only partially filled (50%)", "accepted with actual volume (logged), partial-close plan uses actual volume; all pass; nothing left", s3)

# ---------------- 4 / 5 ----------------
def s4():
    e = Env(); m = e.open_raw(0); r = e.run()
    return short(r), r["ok"] and m.order in r["all_positions"] and not r["contest_positions_open"]
scen("4", "A manual position (magic 0) already open on BTCUSDm", "manual position untouched; all pass", s4)

def s5():
    e = Env(); o = e.open_raw(777)
    def patch(env, V):                                   # পরীক্ষার মাঝখানে আরেকটা manual পজিশন খোলা হয়
        orig = V.new_entry
        def ne(*a, **k):
            if a[0].startswith("Claude"):
                env.open_raw(0, side=1)
            return orig(*a, **k)
        V.new_entry = ne
    r = e.run(patch)
    others = [t for t, m in r["all_positions"].items() if m in (0, 777)]
    return short(r) + f" | other positions still open: {others}", r["ok"] and o.order in r["all_positions"] and len(others) == 2 \
        and not r["contest_positions_open"]
scen("5", "Another strategy's position (magic 777) pre-exists + a manual one is opened DURING the test",
     "both untouched (not contest magic, not linked), no urgent; all pass", s5)

# ---------------- 6 ----------------
def s6a():
    e = Env()
    def patch(env, V):
        V.GA.CLAUDE_MAGIC = 26102402
    r = e.run(patch)
    return short(r), (not r["ok"]) and r["requests"] == 0 and "GUARD: magic numbers correct and distinct" in r["failed"]
scen("6a", "Adapter's Claude magic wrongly equals GPT's", "guard fails, 0 orders sent", s6a)

def s6b():
    e = Env()
    def patch(env, V):
        V.CLM.MAGIC = 26102402
    r = e.run(patch)
    return short(r), (not r["ok"]) and r["requests"] == 0
scen("6b", "Claude bot magic wrongly set to GPT's number", "guard fails, 0 orders sent", s6b)

# ---------------- 7 ----------------
def s7():
    e = Env()
    def patch(env, V):
        def boom(self, *a, **k):                          # দুই পজিশন খোলা থাকতেই checks থামে
            raise RuntimeError("stop checks early")
        V.CLM.ClaudePullbackV1._modify_sl = boom
        orig = V.cleanup
        def c():
            env.b.connected = False                       # cleanup শুরুর মুহূর্তে সংযোগ বিচ্ছিন্ন
            orig()
        V.cleanup = c
    r1 = e.run(patch)
    first = (not r1["ok"]) and r1["urgent"] >= 1 and len(r1["contest_positions_open"]) == 2 and r1["journal"] == "INCOMPLETE"
    e.b.connected = True
    r2 = e.run()                                          # সংযোগ ফিরল, আবার চালানো → orphan সমাধান
    second = not r2["contest_positions_open"] and r2["journal"] == "OK" and r2["requests"] >= 2 \
        and "GUARD: no orphaned test positions from earlier runs" not in r2["failed"]
    return f"RUN1 {short(r1)} || RUN2 {short(r2)}", first and second
scen("7", "Connection lost during cleanup with BOTH test positions still open, then restored and re-run",
     "run1: states unknown → urgent, 2 test positions left open, journal INCOMPLETE; run2: orphans found via journal, "
     "both closed with their own magic, journal resolved, run stops safely", s7)

# ---------------- 8 ----------------
def s8a():
    r = Env({"fake_close_ok_n": 2, "fake_close_comment": "VERIFY_CLEANUP"}).run()
    return short(r) + (" | 'still open' retry logged" if "এখনো খোলা" in r["log"] else ""), \
        r["ok"] and not r["contest_positions_open"] and "এখনো খোলা" in r["log"]
scen("8a", "Cleanup close returns DONE but position stays open (first 2 times)",
     "cleanup re-checks, sees still open, retries, finally closed; all pass", s8a)

def s8b():
    r = Env({"fake_close_ok_n": 2, "fake_close_comment": "CLAUDE_PB_v1"}).run()
    ok = (not r["ok"]) and "Claude fully closed its position" in r["failed"] and not r["contest_positions_open"] \
        and r["journal"] == "OK"
    return short(r), ok
scen("8b", "Claude BOT's own close returns DONE but position stays open",
     "verification detects it (FAIL 'Claude fully closed'), cleanup still closes everything, journal OK. "
     "FINDING: Claude bot trusts retcode, no re-check", s8b)

# ---------------- 9 ----------------
def s9a():
    e = Env()
    def patch(env, V):
        def boom(self, *a, **k):
            raise KeyboardInterrupt()
        V.CLM.ClaudePullbackV1._modify_sl = boom
    r = e.run(patch)
    return short(r), "Interrupted by Ctrl+C" in r["failed"] and not r["contest_positions_open"] and r["report"] and r["shutdown"] \
        and r["journal"] == "OK"
scen("9a", "Ctrl+C in the middle of the checks (before cleanup)", "cleanup runs, both test positions closed, report written, shutdown called, journal complete", s9a)

def s9b():
    e = Env()
    def patch(env, V):
        orig = V.close_linked
        state = {"armed": False, "fired": False}
        oc = V.cleanup
        def c():
            state["armed"] = True
            oc()
        def cl(*a, **k):
            if state["armed"] and not state["fired"]:
                state["fired"] = True
                raise KeyboardInterrupt()
            return orig(*a, **k)
        V.cleanup, V.close_linked = c, cl
        def boom(self, *a, **k):
            raise RuntimeError("stop checks early")
        V.CLM.ClaudePullbackV1._modify_sl = boom
    r = e.run(patch)
    return short(r) + (" | 'Ctrl+C during cleanup' logged" if "cleanup চলার সময় Ctrl+C" in r["log"] else ""), \
        not r["contest_positions_open"] and r["report"] and r["shutdown"] and "cleanup চলার সময় Ctrl+C" in r["log"]
scen("9b", "Ctrl+C while cleanup is running", "cleanup restarts once and finishes, positions closed, report written, shutdown called", s9b)

def s9c():
    e = Env()
    def patch(env, V):
        class J:
            def __getattr__(self, n):
                import json as _j
                return getattr(_j, n)
            def dump(self, *a, **k):
                raise KeyboardInterrupt()
        V.json = J()
    r = e.run(patch)
    return short(r) + (" | REPORT ERROR logged" if "REPORT ERROR" in r["log"] else ""), \
        r["shutdown"] and not r["contest_positions_open"] and r["journal"] == "OK" and "REPORT ERROR" in r["log"]
scen("9c", "Ctrl+C while the report is being written", "shutdown still called, positions already closed, journal complete (separate file), error logged", s9c)

# ---------------- 10 ----------------
def corrupt(content):
    def fn():
        e = Env()
        with open(os.path.join(e.D, "verification_positions.json"), "w", encoding="utf-8") as f:
            f.write(content)
        r = e.run()
        e.fresh_import()
        import contest_counter as K, contest_preflight as PF
        rep = K.ContestCounter(0).report()
        pf_ok, pf = PF.run_preflight(e.D)
        ok = (not r["ok"]) and r["requests"] == 0 and rep["data_ok"] is False and rep["warnings"] and not pf_ok
        return short(r) + f" | counter data_ok={rep['data_ok']} warning='{rep['warnings'][0][:60]}…' preflight_ok={pf_ok}", ok
    return fn
scen("10a", "verification_positions.json is garbage", "guard fails (0 orders); counter: data_ok False + ERROR warning; preflight fails", corrupt("{{{ not json"))
valid_but_tampered = json.dumps({"format": "verification_positions/v1", "runs": [{"run_id": "X", "status": "complete", "positions": []}],
                                 "checksum": "0" * 64})
scen("10b", "verification_positions.json valid JSON but checksum wrong (tampered)", "same as 10a", corrupt(valid_but_tampered))
scen("10c", "verification_positions.json truncated (partially written)", "same as 10a", corrupt('{"format": "verification_positions/v1", "runs": [{"run_id": "X", '))

def s10d():
    e = Env(); e.fresh_import()
    import contest_counter as K
    rep = K.ContestCounter(0).report()
    return f"status={rep['verification']['status']} warnings={rep['warnings']}", \
        rep["verification"]["status"] == "MISSING" and rep["warnings"] and rep["warnings"][0].startswith("NOTE")
scen("10d", "verification_positions.json missing", "counter not silent: NOTE warning shown", s10d)

# ---------------- 11 + D both directions ----------------
def s11():
    e = Env()
    before = e.open_raw(CL); S.Broker._close(e.b, e.b.positions[before.order], 0.01, e.b._price("BTCUSDm") + 10, 5, CL)
    r = e.run()
    after = e.open_raw(GP, side=1); S.Broker._close(e.b, e.b.positions[after.order], 0.01, e.b._price("BTCUSDm") - 10, 5, GP)
    e.fresh_import()
    import contest_counter as K
    r1 = K.ContestCounter(0).report(); r2 = K.ContestCounter(0).report()
    ids = sorted(t["position_id"] for k in ("claude", "gpt") for t in r1["trades"][k])
    same = json.dumps(r1["claude"], sort_keys=True) == json.dumps(r2["claude"], sort_keys=True) and \
        json.dumps(r1["gpt"], sort_keys=True) == json.dumps(r2["gpt"], sort_keys=True)
    ok = r["ok"] and ids == sorted([before.order, after.order]) and len(r1["verification"]["excluded_positions"]) == 2 and same
    return f"counted {ids} (contest trades before={before.order}, after={after.order}); excluded verification " \
           f"{r1['verification']['excluded_positions']}; second counter instance identical={same}", ok
scen("11", "Counter after restart + D both directions (contest trades before AND after verification)",
     "both real contest trades counted exactly once, both verification trades excluded, new counter instance gives identical result", s11)

# ---------------- 12 ----------------
def s12a():
    r = Env(margin_mode=S.ACCOUNT_MARGIN_MODE_RETAIL_NETTING).run()
    return short(r), (not r["ok"]) and r["requests"] == 0
scen("12a", "Netting account", "stops before any order (0 requests)", s12a)

def s12b():
    r = Env(trade_mode=S.ACCOUNT_TRADE_MODE_REAL).run()
    return short(r), (not r["ok"]) and r["requests"] == 0
scen("12b", "Real account", "stops before any order (0 requests)", s12b)

# ---------------- 13 ----------------
def s13a():
    r = Env({"vol_rules": {"BTCUSDm": (0.1, 0.1, 100.0)}}, balance=100000.0).run()
    part = "E: Claude partial close (close & remaining both valid)" not in r["failed"] and "close 0.1" in r["log"]
    return short(r), r["ok"] and not r["contest_positions_open"] and part
scen("13a", "Unusual volume rules: min 0.1, step 0.1 (balance 100,000)",
     "Claude test volume 0.2 → close 0.1 / remain 0.1 (both valid); all pass", s13a)

def s13a2():
    r = Env({"vol_rules": {"BTCUSDm": (0.1, 0.1, 100.0)}}).run()
    return short(r) + (" | GPT SKIPPED (lot too small) logged" if "SKIP_LOT_TOO_SMALL" in r["log"] else ""), \
        (not r["ok"]) and r["requests"] == 0 and not r["contest_positions_open"] and "SKIP_LOT_TOO_SMALL" in r["log"]
scen("13a2", "min lot 0.1 with balance 10,000: GPT's 1%-risk lot < min lot",
     "GPT's own rule refuses the order (SKIP_LOT_TOO_SMALL), verification reports it, 0 orders, nothing left. "
     "FINDING: on such accounts GPT would never trade", s13a2)

def s13b():
    r = Env({"vol_rules": {"BTCUSDm": (0.01, 0.01, 0.01)}}).run()
    return short(r) + (" | partial skipped & logged" if "partial close skipped" in r["log"] else ""), \
        r["ok"] and not r["contest_positions_open"] and "partial close skipped" in r["log"]
scen("13b", "volume_max 0.01 (no valid partial close possible)", "partial close skipped with reason; full close works; all pass", s13b)

def s13c():
    r = Env({"allowed_filling": {S.ORDER_FILLING_RETURN}}).run()
    return short(r), r["ok"] and not r["contest_positions_open"]
scen("13c", "Broker accepts only RETURN filling mode", "both bots fall back FOK→IOC→RETURN; all pass", s13c)

# ---------------- 14 ----------------
def s14():
    r = Env().run()
    a = "Claude code refuses GPT position; GPT-magic cleanup refuses Claude position" not in r["failed"]
    b = "Static: GPT code never sends close/modify requests (no 'position' key, no SLTP)" not in r["failed"]
    return short(r) + f" | refusal-both-ways PASS={a} static-GPT PASS={b}", r["ok"] and a and b
scen("14", "Claude's close/modify on GPT position refused, and the reverse", "both refusal checks PASS; GPT code has no close/modify path (static check)", s14)

# ---------------- 15 ----------------
def s15(faults, title, guard):
    def fn():
        r = Env(faults).run()
        return short(r), (not r["ok"]) and r["requests"] == 0 and any(guard in f for f in r["failed"])
    return fn
scen("15a", "Symbol name not found", "guard fails, 0 orders", s15({"missing_symbols": {"BTCUSDm"}}, "", "GUARD: symbol"))
scen("15b", "No tick for the symbol", "guard fails, 0 orders", s15({"no_tick": {"BTCUSDm"}}, "", "has a tick"))
scen("15c", "SL/TP would break broker stop level", "guard fails, 0 orders",
     s15({"stops_level": {"BTCUSDm": 10 ** 9}}, "", "stop level"))

json.dump(ROWS, open(OUT, "w"), indent=1, ensure_ascii=False, default=str)
print("=" * 70)
print(f"SCENARIOS (SIMULATED): {sum(r['pass'] for r in ROWS)}/{len(ROWS)} behaved as expected")
for r in ROWS:
    if not r["pass"]:
        print("  NOT AS EXPECTED:", r["id"], r["scenario"])
