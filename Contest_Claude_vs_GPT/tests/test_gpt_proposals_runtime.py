"""
GPT প্রস্তাব P1, P3, P4 (আর COMBINED) — runtime পরীক্ষা, নকল fault-injection broker-এ।
*** সব নকল। আসল MT5 নয়, কোনো আসল order নয়। ***
কোনো ফাইল বদলানো হয় না: প্রতিটা সংস্করণ আলাদা নামে মেমরিতে load হয়, সবাই একই নকল MetaTrader5 ব্যবহার করে।
usage: python test_gpt_proposals_runtime.py <package_dir> <out_json>
"""
import sys, os, types, json, hashlib, importlib.util
from datetime import datetime

PKG, OUT = sys.argv[1], sys.argv[2]
TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TESTS)
import sim_mt5 as S
import sim_faults as SF

PROP = os.path.join(PKG, "proposals")
FILES = {
    "v1.0": os.path.join(PKG, "gpt_liquidity_fibonacci_scalper_v1.py"),
    "P1": os.path.join(PROP, "P1_order_send_none", "gpt_liquidity_fibonacci_scalper_v1.py"),
    "P2": os.path.join(PROP, "P2_daily_loss_server_time", "gpt_liquidity_fibonacci_scalper_v1.py"),
    "P3": os.path.join(PROP, "P3_partial_fill_volume", "gpt_liquidity_fibonacci_scalper_v1.py"),
    "P4": os.path.join(PROP, "P4_buy_tick_check", "gpt_liquidity_fibonacci_scalper_v1.py"),
    "COMBINED": os.path.join(PROP, "COMBINED_v1_1_all_four", "gpt_liquidity_fibonacci_scalper_v1.py"),
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


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    m.datetime = SimDT
    return m


M = {k: load(p, "gpt_" + k.replace(".", "_")) for k, p in FILES.items()}
GP = M["v1.0"].MAGIC


def broker(faults=None, offset=0, pos=2800, n_bars=3000, balance=10000.0):
    b = SF.FaultyBroker(faults=faults, n_bars=n_bars, server_offset_h=offset, balance=balance)
    b.pos_idx = pos
    SF.install(b, MT5)
    CUR["b"] = b
    return b


def gpt_positions(b):
    return [p for p in S.Broker.positions_get(b) if p.magic == GP]


def opens(b):
    return [r for r in b.requests if r["req"].get("action") == S.TRADE_ACTION_DEAL and not r["req"].get("position")]


def signal(b, symbol="BTCUSDm", side="BUY", risk_frac=0.005):
    t = S.Broker.symbol_info_tick(b, symbol)
    e = t.ask if side == "BUY" else t.bid
    d = e * risk_frac
    sl, tp = (e - d, e + 2 * d) if side == "BUY" else (e + d, e - 2 * d)
    return {"symbol": symbol, "signal": side, "entry": e, "stop_loss": sl, "take_profit": tp}


ROWS = []


def row(pid, test, expected, actual, ok):
    ROWS.append({"proposal": pid, "test": test, "expected": expected, "actual": actual, "pass": bool(ok)})


def send_case(ver, faults, side="BUY", symbol="BTCUSDm", balance=10000.0):
    b = broker(faults, balance=balance)
    bot = M[ver].GPTLiquidityFibonacciScalper()
    r = bot._send_order(signal(b, symbol, side))
    return b, r


# =====================================================================================
# P1 — order_send None: duplicate হয় কি না (বিশেষ গুরুত্ব)
# =====================================================================================
for ver in ("v1.0", "P1", "COMBINED"):
    for side in ("BUY", "SELL"):
        b, r = send_case(ver, {"open_returns_none": True}, side)
        n_send, n_pos = len(opens(b)), len(gpt_positions(b))
        if ver == "v1.0":
            row("P1", f"[{ver}] order_send None (order আসলে খোলে) {side}",
                "আগের অবস্থা দেখানো: v1.0 অন্য filling mode-এ আবার পাঠায় → একাধিক পজিশন (ঝুঁকি প্রমাণ)",
                f"sends={n_send}, GPT positions={n_pos}, status={r.get('status')}", n_send >= 2 and n_pos >= 2)
        else:
            ok = (n_send == 1 and n_pos == 1 and r.get("status") == "UNKNOWN" and r.get("reason") == "ORDER_SEND_NONE"
                  and "last_error" in r and r.get("requested_volume", 0) > 0 and r.get("type_filling") == S.ORDER_FILLING_FOK)
            row("P1", f"[{ver}] order_send None (order আসলে খোলে) {side}",
                "ঠিক ১টা send, সর্বোচ্চ ১টা পজিশন, status UNKNOWN, reason ORDER_SEND_NONE, last_error আছে",
                f"sends={n_send}, GPT positions={n_pos}, status={r.get('status')}, reason={r.get('reason')}, "
                f"last_error={r.get('last_error')!r}, filling={r.get('type_filling')}", ok)

# None + কিছুই খোলেনি (সংযোগ বিচ্ছিন্ন)
for ver in ("v1.0", "P1"):
    b, r = send_case(ver, {"disconnect_after_n": 0})
    tried = len([x for x in b.requests if x.get("dropped") == "disconnected"])
    exp_ok = (tried == 3) if ver == "v1.0" else (tried == 1 and r.get("status") == "UNKNOWN")
    # v1.0-তে আসলে symbol_info None হয়ে আগেই FAILED হয় কি না দেখো
    row("P1", f"[{ver}] সংযোগ বিচ্ছিন্ন → order_send None, কিছু খোলেনি",
        "v1.0: আগেই SKIP_SYMBOL_INFO (সংযোগ নেই বলে) অথবা ৩ চেষ্টা · P1: আগেই SKIP_SYMBOL_INFO অথবা ১ চেষ্টা + UNKNOWN",
        f"order_send attempts={tried}, status={r.get('status')}, reason={r.get('reason')}",
        r.get("reason") == "SKIP_SYMBOL_INFO" or exp_ok)

# সংযোগ আছে কিন্তু order_send-এর মুহূর্তে None, কিছু খোলে না → P1 পুনরায় পাঠায় না
class NoneNoOpen(SF.FaultyBroker):
    def order_send(self, req):
        self.requests.append({"req": dict(req), "time": 0, "target_magic": None, "dropped": "none_no_open"})
        return None

for ver in ("v1.0", "P1"):
    b = NoneNoOpen(n_bars=3000, server_offset_h=0); b.pos_idx = 2800; SF.install(b, MT5); CUR["b"] = b
    r = M[ver].GPTLiquidityFibonacciScalper()._send_order(signal(b))
    n = len(b.requests)
    row("P1", f"[{ver}] order_send None, কিছুই খোলেনি (সংযোগ query ঠিক আছে)",
        "v1.0: ৩ বার পাঠায়, FAILED · P1: ১ বার, UNKNOWN (ফল অজানা — তাই আবার নয়)",
        f"attempts={n}, status={r.get('status')}",
        (n == 3 and r.get("status") == "FAILED") if ver == "v1.0" else (n == 1 and r.get("status") == "UNKNOWN"))

# পরের চক্র: পজিশন দেখা গেলে GPT নতুন order দেয় না
for ver in ("P1", "COMBINED"):
    b, r = send_case(ver, {"open_returns_none": True})
    bot = M[ver].GPTLiquidityFibonacciScalper()
    hp = bot._has_position("BTCUSDm")
    row("P1", f"[{ver}] UNKNOWN-এর পরের চক্র",
        "খোলা পজিশন দেখা যায় → _has_position True → নতুন order নয়",
        f"_has_position={hp}, GPT positions={len(gpt_positions(b))}", hp is True and len(gpt_positions(b)) == 1)

# স্বাভাবিক পথ ও filling fallback হুবহু এক (P1, COMBINED বনাম v1.0)
def norm(r):
    return json.dumps({k: v for k, v in r.items() if k not in ("requested_volume", "filled_volume", "fill_status")},
                      sort_keys=True, default=str)

for faults, label in (({}, "স্বাভাবিক (FOK গ্রহণ)"),
                      ({"allowed_filling": {S.ORDER_FILLING_RETURN}}, "শুধু RETURN গ্রহণ (FOK, IOC → 10030)"),
                      ({"allowed_filling": set()}, "কোনো filling গ্রহণ নয়")):
    for side in ("BUY", "SELL"):
        b0, r0 = send_case("v1.0", faults, side)
        req0 = [x["req"] for x in b0.requests]
        for ver in ("P1", "P3", "COMBINED"):
            b1, r1 = send_case(ver, faults, side)
            req1 = [x["req"] for x in b1.requests]
            same = norm(r0) == norm(r1) and req0 == req1
            row("P1" if ver == "P1" else ("P3" if ver == "P3" else "COMBINED"),
                f"[{ver}] {label} {side}: v1.0-এর সাথে তুলনা",
                "একই request ক্রম (একই filling mode ক্রম), একই ফল (P3-এর নতুন তিনটা key বাদে)",
                f"v1.0 sends={len(req0)} status={r0.get('status')} · {ver} sends={len(req1)} status={r1.get('status')} · same={same}",
                same)

# =====================================================================================
# P3 — আংশিক fill: অনুরোধ বনাম আসল volume
# =====================================================================================
for ver in ("v1.0", "P3", "COMBINED"):
    b, r = send_case(ver, {"partial_fill": 0.5})
    real = sum(p.volume for p in gpt_positions(b))
    if ver == "v1.0":
        row("P3", "[v1.0] broker অর্ধেক পূরণ করে (DONE_PARTIAL)",
            "আগের অবস্থা দেখানো: v1.0 'volume' = অনুরোধ, আসল পূরণ জানায় না",
            f"reported volume={r.get('volume')}, broker-এ আসল={real:.2f}", abs(r.get("volume", 0) - real) > 1e-9)
    else:
        ok = (r.get("fill_status") == "PARTIAL" and abs((r.get("filled_volume") or -1) - real) < 1e-9
              and r.get("requested_volume") == r.get("volume") and r["requested_volume"] > real)
        row("P3", f"[{ver}] broker অর্ধেক পূরণ করে (DONE_PARTIAL)",
            "requested_volume = অনুরোধ, filled_volume = broker-এর আসল, fill_status PARTIAL",
            f"requested={r.get('requested_volume')}, filled={r.get('filled_volume')}, broker-এ আসল={real:.2f}, "
            f"fill_status={r.get('fill_status')}", ok)
    for faults, lab, exp_status in (({"result_no_volume": True}, "result-এ volume নেই", "UNKNOWN_FILL"),
                                    ({"result_no_volume": True, "partial_fill": 0.5}, "আংশিক + result-এ volume নেই", "UNKNOWN_FILL"),
                                    ({}, "স্বাভাবিক পূর্ণ fill", "FULL")):
        if ver == "v1.0":
            continue
        b, r = send_case(ver, faults)
        real = sum(p.volume for p in gpt_positions(b))
        if exp_status == "UNKNOWN_FILL":
            ok = r.get("fill_status") == "UNKNOWN_FILL" and r.get("filled_volume") is None
            exp = "filled_volume None (অনুরোধকে পূরণ ধরে নেয় না), fill_status UNKNOWN_FILL"
        else:
            ok = r.get("fill_status") == "FULL" and abs(r.get("filled_volume") - real) < 1e-9 and real == r["requested_volume"]
            exp = "filled = requested = broker-এর আসল, fill_status FULL"
        row("P3", f"[{ver}] {lab}", exp,
            f"requested={r.get('requested_volume')}, filled={r.get('filled_volume')}, broker-এ আসল={real:.2f}, "
            f"fill_status={r.get('fill_status')}", ok)

# volume = 0 ফেরত (আসল MT5-এ field সবসময় থাকে, তথ্য না থাকলে 0)
class ZeroVol(SF.FaultyBroker):
    def order_send(self, req):
        from types import SimpleNamespace as NS
        r = super().order_send(req)
        return NS(retcode=r.retcode, order=r.order, deal=r.deal, comment=r.comment, volume=0.0) if r is not None else r

for ver in ("P3", "COMBINED"):
    b = ZeroVol(n_bars=3000, server_offset_h=0); b.pos_idx = 2800; SF.install(b, MT5); CUR["b"] = b
    r = M[ver].GPTLiquidityFibonacciScalper()._send_order(signal(b))
    row("P3", f"[{ver}] result.volume = 0 (আসল MT5-এ 'তথ্য নেই'-এর রূপ)", "UNKNOWN_FILL, filled_volume None",
        f"filled={r.get('filled_volume')}, fill_status={r.get('fill_status')}",
        r.get("fill_status") == "UNKNOWN_FILL" and r.get("filled_volume") is None)

# =====================================================================================
# P4 — BUY setup-এর মুহূর্তে tick None
# =====================================================================================
def find_setup_bars(ver, direction, want=3):
    found = []
    b = broker(None, pos=400, n_bars=7000)
    bot = M[ver].GPTLiquidityFibonacciScalper()
    for sym in ("BTCUSDm", "XAUUSDm"):
        for pos in range(400, 6900, 1):
            b.pos_idx, b.tick_i = pos, 0
            r = bot._setup(sym, direction)
            if r.get("signal") == direction:
                found.append((sym, pos))
                if len([f for f in found if f[0] == sym]) >= want:
                    break
    return found

buy_bars = find_setup_bars("v1.0", "BUY")
for sym, pos in buy_bars:
    for ver in ("v1.0", "P4", "COMBINED"):
        b = broker({"no_tick": {sym}}, pos=pos, n_bars=7000)
        bot = M[ver].GPTLiquidityFibonacciScalper()
        try:
            r = bot._setup(sym, "BUY"); err = None
        except Exception as e:
            r, err = None, f"{type(e).__name__}: {e}"
        n_orders = len(b.requests)
        if ver == "v1.0":
            row("P4", f"[v1.0] {sym} bar {pos}: BUY setup, tick None",
                "আগের অবস্থা দেখানো: v1.0 crash করে (exception)", f"exception={err}", err is not None and n_orders == 0)
        else:
            ok = err is None and r == {"signal": "NO_TRADE", "reason": "SKIP_NO_TICK"} and n_orders == 0
            row("P4", f"[{ver}] {sym} bar {pos}: BUY setup, tick None",
                "exception নয়; NO_TRADE / SKIP_NO_TICK; ০ order", f"result={r}, exception={err}, orders={n_orders}", ok)
        # একই bar-এ tick থাকলে P4 আর v1.0 হুবহু এক
        b = broker(None, pos=pos, n_bars=7000)
        r_tick = M[ver].GPTLiquidityFibonacciScalper()._setup(sym, "BUY")
        b = broker(None, pos=pos, n_bars=7000)
        r_ref = M["v1.0"].GPTLiquidityFibonacciScalper()._setup(sym, "BUY")
        if ver != "v1.0":
            row("P4", f"[{ver}] {sym} bar {pos}: tick থাকলে", "v1.0-এর সাথে হুবহু এক signal (entry, SL, TP)",
                f"signal={r_tick.get('signal')} entry={r_tick.get('entry')} sl={r_tick.get('stop_loss')} same={r_tick == r_ref}",
                r_tick == r_ref)
if not buy_bars:
    row("P4", "BUY setup খুঁজে পাওয়া", "নকল ডেটায় অন্তত ১টা BUY setup", "পাওয়া যায়নি", False)

# =====================================================================================
# আচরণগত সমতা: প্রতিটা প্রস্তাব বনাম v1.0 — tick থাকা অবস্থায় _setup() ও evaluate_symbol() হুবহু এক কি না
# (offset 0, যাতে P2-এর দৈনিক-লস পরিবর্তন প্রভাব না ফেলে; P2-এর offset আচরণ আলাদা পরীক্ষায়)
# =====================================================================================
EQ = {}
b = broker(None, offset=0, pos=400, n_bars=7000)
bots = {k: M[k].GPTLiquidityFibonacciScalper() for k in M}
checked, diffs, sig_count = 0, {k: 0 for k in M}, 0
for pos in range(400, 6990, 3):
    b.pos_idx, b.tick_i = pos, 0
    for sym in ("BTCUSDm", "XAUUSDm"):
        for direction in ("BUY", "SELL"):
            ref = json.dumps(bots["v1.0"]._setup(sym, direction), sort_keys=True, default=str)
            if '"signal": "BUY"' in ref or '"signal": "SELL"' in ref:
                sig_count += 1
            for k in M:
                if k != "v1.0" and json.dumps(bots[k]._setup(sym, direction), sort_keys=True, default=str) != ref:
                    diffs[k] += 1
            checked += 1
        ref = json.dumps(bots["v1.0"].evaluate_symbol(sym), sort_keys=True, default=str)
        for k in M:
            if k != "v1.0" and json.dumps(bots[k].evaluate_symbol(sym), sort_keys=True, default=str) != ref:
                diffs[k] += 1
        checked += 1
for k in M:
    if k == "v1.0":
        continue
    row(k, f"[{k}] আচরণগত সমতা: {checked}টা _setup/evaluate_symbol কল (নকল ২,১৯৭ bar × ২ symbol)",
        "v1.0-এর সাথে ০ পার্থক্য (tick আছে, offset 0)", f"পার্থক্য={diffs[k]}, এর মধ্যে v1.0 signal={sig_count}", diffs[k] == 0)

# =====================================================================================
H1 = {k: sha(v) for k, v in FILES.items()}
row("ALL", "পরীক্ষার আগে-পরে সব ফাইলের SHA-256", "অপরিবর্তিত",
    f"v1.0 {H1['v1.0'][:16]}… unchanged={H0 == H1}", H0 == H1 and H1["v1.0"].startswith("4d41a0ea7e751760"))

summary = {"total": len(ROWS), "passed": sum(r["pass"] for r in ROWS),
           "per_proposal": {}, "sha256": H1, "SIMULATED_ONLY": True}
for r in ROWS:
    d = summary["per_proposal"].setdefault(r["proposal"], [0, 0])
    d[0] += r["pass"]; d[1] += 1
json.dump({"summary": summary, "rows": ROWS}, open(OUT, "w"), indent=1, ensure_ascii=False, default=str)
for r in ROWS:
    print(("PASS " if r["pass"] else "FAIL ") + f"{r['proposal']:<9} {r['test']}\n      expected: {r['expected']}\n      actual:   {r['actual']}")
print(json.dumps(summary, indent=1, ensure_ascii=False))
