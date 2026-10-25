"""
v2 প্রস্তাব — GPT core G2 (+ adapter A1): runtime পরীক্ষা, নকল fault-injection broker-এ।
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


SIG = find_eval_signals()
row("setup", "evaluate_symbol signal bar খোঁজা (v1.0, BTC)", "অন্তত ১টা", f"{SIG}", len(SIG) >= 1)
SPOS, SSIDE = SIG[0]

# =====================================================================================
# [H] / [A1] — positions_get None
# =====================================================================================
def eval_with(bot_factory, pos_none, existing):
    b = broker(pos=SPOS)
    if existing:
        S.Broker.order_send(b, {"action": 1, "symbol": "BTCUSDm", "volume": 0.01, "type": 0, "sl": 0, "tp": 0, "magic": GP})
    bot = bot_factory()
    b.pos_none = pos_none
    r = bot.evaluate_symbol("BTCUSDm")
    return b, r

for label, fac in (("core v1.0", lambda: CORE["v1.0"].GPTLiquidityFibonacciScalper()),
                   ("core G2", lambda: CORE["G2"].GPTLiquidityFibonacciScalper()),
                   ("adapter active + v1.0", lambda: ADP[("active", "v1.0")].GPTContestAdapter()),
                   ("adapter active + G2", lambda: ADP[("active", "G2")].GPTContestAdapter()),
                   ("adapter A1 + v1.0", lambda: ADP[("A1", "v1.0")].GPTContestAdapter()),
                   ("adapter A1 + G2", lambda: ADP[("A1", "G2")].GPTContestAdapter())):
    b, r = eval_with(fac, True, True)
    safe = r.get("reason") in ("SKIP_POSITION_STATE_UNKNOWN",) or (r.get("signal") not in ("BUY", "SELL")
                                                                    and r.get("reason") == "SKIP_POSITION_STATE_UNKNOWN")
    exp_safe = label in ("core G2", "adapter A1 + G2")
    row("H", f"[{label}] GPT পজিশন খোলা আছে, positions_get None, signal bar",
        "নিরাপদ: SKIP_POSITION_STATE_UNKNOWN, signal নয়" if exp_safe else
        "আগের/অসম্পূর্ণ অবস্থা দেখানো: 'পজিশন নেই' ধরে signal দেয় (run_once-এ দ্বিতীয় order যেত)",
        f"signal={r.get('signal')} reason={r.get('reason')}",
        (r.get("reason") == "SKIP_POSITION_STATE_UNKNOWN") if exp_safe else (r.get("signal") in ("BUY", "SELL")))

# query ঠিক আছে, পজিশন নেই / আছে — তিন অবস্থা আলাদা
for label, fac in (("core G2", lambda: CORE["G2"].GPTLiquidityFibonacciScalper()),
                   ("adapter A1 + G2", lambda: ADP[("A1", "G2")].GPTContestAdapter())):
    b, r1 = eval_with(fac, False, True)
    b, r2 = eval_with(fac, False, False)
    bot = fac(); b = broker(pos=SPOS)
    s3 = bot._has_position("BTCUSDm"); b.pos_none = True; s4 = bot._has_position("BTCUSDm")
    row("H", f"[{label}] তিন অবস্থা: পজিশন আছে / query ঠিক কিন্তু নেই / query ব্যর্থ",
        "SKIP_POSITION_EXISTS · signal দেয় · _has_position: False তারপর None",
        f"{r1.get('reason')} · {r2.get('signal')} · {s3} / {s4}",
        r1.get("reason") == "SKIP_POSITION_EXISTS" and r2.get("signal") in ("BUY", "SELL") and s3 is False and s4 is None)

# adapter: Claude-এর পজিশন উপেক্ষা আগের মতোই
b = broker(pos=SPOS)
S.Broker.order_send(b, {"action": 1, "symbol": "BTCUSDm", "volume": 0.01, "type": 0, "sl": 0, "tp": 0, "magic": CL})
r = ADP[("A1", "G2")].GPTContestAdapter().evaluate_symbol("BTCUSDm")
row("H", "[adapter A1 + G2] শুধু Claude-এর পজিশন আছে", "উপেক্ষা করে signal দেয় (আগের মতো)", f"signal={r.get('signal')}",
    r.get("signal") in ("BUY", "SELL"))

# _send_order-এর snapshot query ব্যর্থ → order নয়
b = broker()
bot = CORE["G2"].GPTLiquidityFibonacciScalper()
sig = signal(b)
b.pos_none = True
r = bot._send_order(sig)
row("H", "[G2] _send_order: pre-send snapshot-এ positions_get None", "SKIPPED SKIP_PRECHECK_QUERY_FAILED, ০ order",
    f"status={r.get('status')} reason={r.get('reason')} orders={len(opens(b))}",
    r.get("reason") == "SKIP_PRECHECK_QUERY_FAILED" and len(opens(b)) == 0)
b = broker(); bot = CORE["G2"].GPTLiquidityFibonacciScalper(); sig = signal(b); b.deals_none = True
r = bot._send_order(sig)
row("H", "[G2] _send_order: pre-send snapshot-এ history_deals_get None", "SKIPPED SKIP_PRECHECK_QUERY_FAILED, ০ order",
    f"status={r.get('status')} reason={r.get('reason')} orders={len(opens(b))}",
    r.get("reason") == "SKIP_PRECHECK_QUERY_FAILED" and len(opens(b)) == 0)

# =====================================================================================
# [P1r] order_send None / অনিশ্চিত retcode
# =====================================================================================
for side in ("BUY", "SELL"):
    for ver in ("v1.0", "G2"):
        b = broker(faults={"open_returns_none": True})
        bot = CORE[ver].GPTLiquidityFibonacciScalper()
        r = bot._send_order(signal(b, side=side))
        n_s, n_p = len(opens(b)), len(gpt_pos(b))
        if ver == "v1.0":
            row("P1r", f"[v1.0] None অথচ খোলে ({side})", "আগের অবস্থা: ৩ send, ৩ পজিশন", f"sends={n_s} positions={n_p} status={r.get('status')}",
                n_s == 3 and n_p == 3)
        else:
            real = sum(p.volume for p in gpt_pos(b))
            rec = r.get("reconcile", {})
            row("P1r", f"[G2] None অথচ খোলে ({side})",
                "১ send, ১ পজিশন, reconcile করে OPENED_RECONCILED, filled = broker-এর আসল, block নেই",
                f"sends={n_s} positions={n_p} status={r.get('status')} filled={r.get('filled_volume')} real={real} "
                f"pos_ids={rec.get('position_ids')} block={'BTCUSDm' in bot._exec_unknown}",
                n_s == 1 and n_p == 1 and r.get("status") == "OPENED_RECONCILED" and abs(r.get("filled_volume") - real) < 1e-9
                and rec.get("position_ids") == [gpt_pos(b)[0].ticket] and "BTCUSDm" not in bot._exec_unknown)

# None, কিছুই খোলেনি → UNKNOWN + block → সময়ের আগে খোলে না → ৬০ সেকেন্ড পরে মীমাংসা
b = broker(pos=SPOS)
bot = CORE["G2"].GPTLiquidityFibonacciScalper()
b.none_no_open = True
r = bot._send_order(signal(b, side=SSIDE))
row("P1r", "[G2] None, কিছুই খোলেনি", "status UNKNOWN, ১ send, block বসে, last_error আছে",
    f"status={r.get('status')} sends={len(opens(b))} block={'BTCUSDm' in bot._exec_unknown} reconcile={r.get('reconcile', {}).get('state')}",
    r.get("status") == "UNKNOWN" and len(opens(b)) == 1 and "BTCUSDm" in bot._exec_unknown and "last_error" in r)
b.none_no_open = False
r2 = bot._send_order(signal(b, side=SSIDE))
e1 = bot.evaluate_symbol("BTCUSDm")
row("P1r", "[G2] block থাকা অবস্থায় (০ সেকেন্ড) আবার order / evaluate", "SKIPPED SKIP_EXECUTION_UNKNOWN, নতুন send নয়; evaluate NO_TRADE",
    f"send2={r2.get('status')}/{r2.get('reason')} sends={len(opens(b))} evaluate={e1.get('signal')}/{e1.get('reason')}",
    r2.get("reason") == "SKIP_EXECUTION_UNKNOWN" and len(opens(b)) == 1 and e1.get("reason") == "SKIP_EXECUTION_UNKNOWN")
advance(b, 225)          # ২২৫ সেকেন্ড পরে (≥ ৬০)
e2 = bot.evaluate_symbol("BTCUSDm")
e3 = bot.evaluate_symbol("BTCUSDm")
row("P1r", "[G2] ≥৬০ সেকেন্ড পরে, query ঠিক, কিছু পাওয়া যায়নি", "একবার EXECUTION_UNKNOWN_RESOLVED_NOT_EXECUTED (NO_TRADE), তারপর block নেই",
    f"eval={e2.get('reason')} block={'BTCUSDm' in bot._exec_unknown} next={e3.get('signal')}/{e3.get('reason')}",
    e2.get("reason") == "EXECUTION_UNKNOWN_RESOLVED_NOT_EXECUTED" and "BTCUSDm" not in bot._exec_unknown
    and e3.get("reason") != "SKIP_EXECUTION_UNKNOWN")

# None, পরে broker-এ দেরিতে খোলে
b = broker(pos=SPOS)
bot = CORE["G2"].GPTLiquidityFibonacciScalper()
b.delay_next = True
r = bot._send_order(signal(b, side=SSIDE))
b.execute_delayed()
e1 = bot.evaluate_symbol("BTCUSDm")
e2 = bot.evaluate_symbol("BTCUSDm")
row("P1r", "[G2] None, order পরে দেরিতে খোলে (৬০ সেকেন্ডের মধ্যে)",
    "প্রথমে UNKNOWN; পরের evaluate-এ EXECUTION_UNKNOWN_RESOLVED_OPENED; তারপর SKIP_POSITION_EXISTS; মোট ১ পজিশন",
    f"{r.get('status')} → {e1.get('reason')} → {e2.get('reason')} · positions={len(gpt_pos(b))} "
    f"bot sends={len([x for x in b.requests if x.get('dropped') == 'delayed'])} (broker পরে নিজে ১টা execute করেছে)",
    r.get("status") == "UNKNOWN" and e1.get("reason") == "EXECUTION_UNKNOWN_RESOLVED_OPENED"
    and e2.get("reason") == "SKIP_POSITION_EXISTS" and len(gpt_pos(b)) == 1)

# None, তারপর query-ও ব্যর্থ → সময় পেরোলেও block থাকে; সংযোগ ফিরলে মীমাংসা
b = broker(pos=SPOS)
bot = CORE["G2"].GPTLiquidityFibonacciScalper()
b.none_no_open = True
r = bot._send_order(signal(b, side=SSIDE))
b.pos_none = b.deals_none = True
advance(b, 450)
blk = bot._check_exec_unknown("BTCUSDm")
b.pos_none = b.deals_none = False
b.none_no_open = False
blk2 = bot._check_exec_unknown("BTCUSDm")
row("P1r", "[G2] UNKNOWN-এর পরে reconcile query-ও ব্যর্থ (৪৫০ সেকেন্ড)",
    "block থাকে (SKIP_EXECUTION_UNKNOWN, reconcile UNKNOWN); query ঠিক হলে তবেই মীমাংসা",
    f"while failing: {blk.get('reason')}/{blk.get('reconcile', {}).get('state')} · after: {blk2.get('reason') if blk2 else None}",
    blk.get("reason") == "SKIP_EXECUTION_UNKNOWN" and blk["reconcile"]["state"] == "UNKNOWN"
    and blk2 and blk2.get("reason") == "EXECUTION_UNKNOWN_RESOLVED_NOT_EXECUTED")

# None, আর order খুলে সাথে সাথে বন্ধও হয়ে গেছে (শুধু deal history-তে আছে)
b = broker(faults={"open_returns_none": True})
bot = CORE["G2"].GPTLiquidityFibonacciScalper()
sig = signal(b)
orig = b.order_send
def send_and_close(req, _o=orig, _b=b):
    r = _o(req)
    for p in list(_b.positions.values()):
        if p.magic == GP:
            S.Broker._close(_b, p, p.volume, S.Broker.symbol_info_tick(_b, p.symbol).bid, S.DEAL_REASON_SL, GP)
    return r
b.order_send = send_and_close; SF.install(b, MT5)
r = bot._send_order(sig)
rec = r.get("reconcile", {})
row("P1r", "[G2] None, order খুলে সাথে সাথে SL-এ বন্ধ (পজিশন নেই, শুধু deal)",
    "deal history থেকে OPENED_RECONCILED, still_open False, block নেই",
    f"status={r.get('status')} still_open={rec.get('still_open')} deals={rec.get('deal_tickets')} block={'BTCUSDm' in bot._exec_unknown}",
    r.get("status") == "OPENED_RECONCILED" and rec.get("still_open") is False and rec.get("deal_tickets")
    and "BTCUSDm" not in bot._exec_unknown)

# অনিশ্চিত retcode 10031 / 10012
for code in (10031, 10012):
    for execute in (True, False):
        for ver in ("v1.0", "G2"):
            b = broker()
            b.open_retcode = (code, execute)
            bot = CORE[ver].GPTLiquidityFibonacciScalper()
            r = bot._send_order(signal(b))
            n_s, n_p = len(opens(b)), len(gpt_pos(b))
            tag = f"retcode {code}, broker-এ {'আসলে খোলে' if execute else 'খোলে না'}"
            if ver == "v1.0":
                row("P1r", f"[v1.0] {tag}", "আগের অবস্থা: পরের filling-এ আবার পাঠায় (৩ send)" + (" → ৩ পজিশন" if execute else ""),
                    f"sends={n_s} positions={n_p} status={r.get('status')}", n_s == 3)
            else:
                exp_status = "OPENED_RECONCILED" if execute else "UNKNOWN"
                row("P1r", f"[G2] {tag}", f"১ send, {exp_status}, পজিশন {'১' if execute else '০'}",
                    f"sends={n_s} positions={n_p} status={r.get('status')} reason={r.get('reason')}",
                    n_s == 1 and r.get("status") == exp_status and n_p == (1 if execute else 0))

# স্বাভাবিক পথ ও 10030 fallback — request ক্রম v1.0-এর মতো
def norm(r):
    drop = ("requested_volume", "filled_volume", "fill_status", "fill_source", "position_id")
    return json.dumps({k: v for k, v in r.items() if k not in drop}, sort_keys=True, default=str)

for faults, label in (({}, "স্বাভাবিক FOK"), ({"allowed_filling": {S.ORDER_FILLING_RETURN}}, "শুধু RETURN (FOK, IOC → 10030)"),
                      ({"allowed_filling": set()}, "কোনো filling গ্রহণ নয়")):
    for side in ("BUY", "SELL"):
        b0 = broker(faults=faults); r0 = CORE["v1.0"].GPTLiquidityFibonacciScalper()._send_order(signal(b0, side=side))
        b1 = broker(faults=faults); r1 = CORE["G2"].GPTLiquidityFibonacciScalper()._send_order(signal(b1, side=side))
        same = norm(r0) == norm(r1) and [x["req"] for x in b0.requests] == [x["req"] for x in b1.requests]
        row("P1r", f"[G2] {label} {side}: v1.0-এর সাথে তুলনা", "একই request ক্রম ও ফল (নতুন fill key বাদে)",
            f"v1.0 {r0.get('status')} sends={len(b0.requests)} · G2 {r1.get('status')} sends={len(b1.requests)} · same={same}", same)

# =====================================================================================
# [P3r] fill volume
# =====================================================================================
cases = [({"partial_fill": 0.5}, "আংশিক fill (DONE_PARTIAL)", "PARTIAL", "deal_history"),
         ({"result_no_volume": True}, "result-এ volume নেই (deal আছে)", "FULL", "deal_history"),
         ({"result_no_volume": True, "partial_fill": 0.5}, "আংশিক + result-এ volume নেই", "PARTIAL", "deal_history"),
         ({"wrong_deal_ticket": True}, "result-এ ভুল deal নম্বর, volume আছে", "FULL", "order_result"),
         ({"wrong_deal_ticket": True, "result_no_volume": True}, "ভুল deal নম্বর + volume নেই", "UNKNOWN_FILL", None),
         ({}, "স্বাভাবিক", "FULL", "deal_history")]
for faults, label, exp_status, exp_src in cases:
    b = broker(faults=faults)
    r = CORE["G2"].GPTLiquidityFibonacciScalper()._send_order(signal(b))
    real = sum(p.volume for p in gpt_pos(b))
    ok = r.get("fill_status") == exp_status and r.get("fill_source") == exp_src and \
        (r.get("filled_volume") is None if exp_status == "UNKNOWN_FILL" else abs(r.get("filled_volume") - real) < 1e-9) and \
        r.get("requested_volume") == r.get("volume")
    row("P3r", f"[G2] {label}", f"fill_status {exp_status}, source {exp_src}, filled = broker-এর আসল (অজানা হলে None)",
        f"requested={r.get('requested_volume')} filled={r.get('filled_volume')} real={real:.2f} status={r.get('fill_status')} "
        f"source={r.get('fill_source')} position_id={r.get('position_id')}", ok)
b = broker(faults={"allowed_filling": set()})
r = CORE["G2"].GPTLiquidityFibonacciScalper()._send_order(signal(b))
row("P3r", "[G2] broker সব filling প্রত্যাখ্যান করে", "FAILED, কোনো filled_volume দাবি নেই, ০ পজিশন",
    f"status={r.get('status')} retcode={r.get('retcode')} filled={'filled_volume' in r} positions={len(gpt_pos(b))}",
    r.get("status") == "FAILED" and "filled_volume" not in r and not gpt_pos(b))

# =====================================================================================
# [P4r] tick
# =====================================================================================
def find_setup_bars(direction, want=3):
    found = []
    b = broker()
    bot = CORE["v1.0"].GPTLiquidityFibonacciScalper()
    for sym in ("BTCUSDm", "XAUUSDm"):
        for pos in range(400, 6900):
            b.pos_idx, b.tick_i = pos, 0
            if bot._setup(sym, direction).get("signal") == direction:
                found.append((sym, pos))
                if len([f for f in found if f[0] == sym]) >= want:
                    break
    return found

for sym, pos in find_setup_bars("BUY"):
    b = broker(pos=pos, faults={"no_tick": {sym}})
    try:
        r = CORE["G2"].GPTLiquidityFibonacciScalper()._setup(sym, "BUY"); err = None
    except Exception as e:
        r, err = None, repr(e)
    row("P4r", f"[G2] {sym} bar {pos}: BUY setup-এ tick None", "NO_TRADE / SKIP_NO_TICK, exception নয়, ০ order",
        f"result={r} err={err} orders={len(b.requests)}", r == {"signal": "NO_TRADE", "reason": "SKIP_NO_TICK"} and not b.requests)

for label, mod, exp in ((("ask = 0"), {"tick_bad": {"BTCUSDm": {"ask": 0.0}}}, "SKIP_INVALID_TICK"),
                        (("bid < 0"), {"tick_bad": {"BTCUSDm": {"bid": -1.0}}}, "SKIP_INVALID_TICK"),
                        (("ask < bid"), {"tick_bad": {"BTCUSDm": {"ask": 1.0}}}, "SKIP_INVALID_TICK"),
                        (("BTC tick ৩০০ সেকেন্ড পুরনো"), {"tick_age": {"BTCUSDm": 300}}, "SKIP_STALE_TICK"),
                        (("BTC tick ১২১ সেকেন্ড পুরনো"), {"tick_age": {"BTCUSDm": 121}}, "SKIP_STALE_TICK"),
                        (("সব tick ২০ মিনিট পুরনো (offset অজানা)"), {"tick_age": {"BTCUSDm": 1200, "XAUUSDm": 1200, "ETHUSDm": 1200}}, "SKIP_TICK_AGE_UNKNOWN"),
                        (("BTC tick ৬০ সেকেন্ড পুরনো"), {"tick_age": {"BTCUSDm": 60}}, "OPENED"),
                        (("BTC tick ১২০ সেকেন্ড পুরনো"), {"tick_age": {"BTCUSDm": 120}}, "OPENED")):
    b = broker()
    sig = signal(b)
    for k, v in mod.items():
        setattr(b, k, v)
    r = CORE["G2"].GPTLiquidityFibonacciScalper()._send_order(sig)
    got = r.get("status") if exp == "OPENED" else r.get("reason")
    row("P4r", f"[G2] _send_order: {label}", f"{exp}" + ("" if exp == "OPENED" else ", ০ order"),
        f"status={r.get('status')} reason={r.get('reason')} orders={len(opens(b))}",
        got == exp and (len(opens(b)) == (1 if exp == "OPENED" else 0)))

# =====================================================================================
# আচরণগত সমতা (offset 0, সব query ঠিক): v1.0 বনাম G2
# =====================================================================================
b = broker()
bots = {k: CORE[k].GPTLiquidityFibonacciScalper() for k in CORE}
checked, diffs, sigs = 0, 0, 0
for pos in range(400, 6990, 5 if not os.environ.get("QUICK") else 500):
    b.pos_idx, b.tick_i = pos, 0
    for sym in ("BTCUSDm", "XAUUSDm"):
        for direction in ("BUY", "SELL"):
            a = json.dumps(bots["v1.0"]._setup(sym, direction), sort_keys=True, default=str)
            g = json.dumps(bots["G2"]._setup(sym, direction), sort_keys=True, default=str)
            diffs += a != g; checked += 1
        a = bots["v1.0"].evaluate_symbol(sym); g = bots["G2"].evaluate_symbol(sym)
        sigs += a.get("signal") in ("BUY", "SELL")
        diffs += json.dumps(a, sort_keys=True, default=str) != json.dumps(g, sort_keys=True, default=str); checked += 1
row("EQ", f"[G2] আচরণগত সমতা: {checked}টা _setup/evaluate_symbol কল", "v1.0-এর সাথে ০ পার্থক্য",
    f"পার্থক্য={diffs}, v1.0 signal={sigs}", diffs == 0)

H1 = {k: sha(v) for k, v in FILES.items()}
row("ALL", "পরীক্ষার আগে-পরে ফাইল SHA-256", "অপরিবর্তিত", f"{ {k: v[:16] for k, v in H1.items()} } same={H0 == H1}", H0 == H1)
summary = {"total": len(ROWS), "passed": sum(r["pass"] for r in ROWS), "per_group": {}, "sha256": H1, "SIMULATED_ONLY": True}
for r in ROWS:
    g = summary["per_group"].setdefault(r["group"], [0, 0]); g[0] += r["pass"]; g[1] += 1
json.dump({"summary": summary, "rows": ROWS}, open(OUT, "w"), indent=1, ensure_ascii=False, default=str)
for r in ROWS:
    print(("PASS " if r["pass"] else "FAIL ") + f"{r['group']:<4} {r['test']}\n      expected: {r['expected']}\n      actual:   {r['actual']}")
print(json.dumps(summary, indent=1, ensure_ascii=False))
