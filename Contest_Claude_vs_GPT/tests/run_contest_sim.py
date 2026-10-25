"""
End-to-end সিমুলেশন: Claude Pullback v1 + GPT Fibonacci & Liquidity Sweep
একই নকল hedging অ্যাকাউন্টে, একই সময়ের একই বাজার ডেটায়। সব ফলাফল নকল ডেটার — আসল লাভ নয়।
usage: python run_contest_sim.py <contest_dir> <work_dir>
"""
import sys, os, types, json, hashlib, copy
from datetime import datetime, timezone, timedelta

CONTEST, WORK = sys.argv[1], sys.argv[2]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, CONTEST)
os.makedirs(WORK, exist_ok=True)
import sim_mt5 as S

GPT_SRC = os.path.join(CONTEST, "gpt_liquidity_fibonacci_scalper_v1.py")
hash_before = hashlib.sha256(open(GPT_SRC, "rb").read()).hexdigest()

broker = S.Broker(server_offset_h=3, n_bars=7000)
mod = types.ModuleType("MetaTrader5")
S.install(broker, mod)
sys.modules["MetaTrader5"] = mod

import gpt_liquidity_fibonacci_scalper_v1 as G
import gpt_contest_adapter as A
import claude_pullback_v1 as C
import contest_counter as K
import contest_preflight as P


class SimDT(datetime):                          # GPT-এর ফাইল না বদলে শুধু টেস্টে সময় নকল করা
    @classmethod
    def now(cls, tz=None):
        return broker.now_utc()


G.datetime = SimDT

CL, GP = C.MAGIC, G.MAGIC
STATE = os.path.join(WORK, "claude_state.json")
for f in (STATE, os.path.join(WORK, "news.json")):
    if os.path.exists(f):
        os.remove(f)

# নিউজ: প্রতি বুধ ও শুক্র UTC 12:30-এ নকল USD high-impact ইভেন্ট
def news_events():
    out, d = [], datetime(2026, 3, 1, tzinfo=timezone.utc)
    while d < datetime(2026, 6, 1, tzinfo=timezone.utc):
        if d.weekday() in (2, 4):
            out.append({"country": "USD", "impact": "High", "date": (d + timedelta(hours=12, minutes=30)).isoformat()})
        d += timedelta(days=1)
    return out

logs = []
violations = []
claude_blocked_by_gpt = []
gpt_block_checks = {"calls": 0, "claude_only_present": 0, "blocked_when_claude_only": 0}


def make_claude():
    return C.ClaudePullbackV1(state_file=STATE, log=lambda s: on_claude_log(s), notify=lambda s: None,
                              clock=broker.now_utc,
                              news=C.NewsFilter(cache_file=os.path.join(WORK, "news.json"), fetcher=news_events))


def on_claude_log(s):
    logs.append(s)
    if "SKIP_POSITION_EXISTS" in s:
        sym = s.split("|")[1].strip()
        mags = {p.magic for p in broker.positions.values() if p.symbol == sym}
        if mags and mags <= {GP}:
            claude_blocked_by_gpt.append(s)


def make_gpt():
    g = A.GPTContestAdapter()
    orig = g._has_position

    def spy(symbol):
        r = orig(symbol)
        mags = {p.magic for p in broker.positions.values() if p.symbol == symbol}
        gpt_block_checks["calls"] += 1
        if mags and mags <= {CL}:
            gpt_block_checks["claude_only_present"] += 1
            if r:
                gpt_block_checks["blocked_when_claude_only"] += 1
        return r
    g._has_position = spy
    return g


claude, gpt = make_claude(), make_gpt()
START, END = 2700, len(broker.m15["BTCUSDm"]) - 2
RESTART_AT = START + (END - START) // 2
seen_pos = {}
gpt_outputs = []
snap_before_restart = None
restart_info = {}

broker.pos_idx, broker.tick_i = START, 0
while broker.pos_idx < END:
    claude.run_once("contest")
    gpt_outputs += gpt.run_contest_once("contest")
    # নতুন পজিশনে ঝুঁকি যাচাই
    for t, p in broker.positions.items():
        if t not in seen_pos:
            risk = abs(broker.order_calc_profit(p.type, p.symbol, p.volume, p.price_open, p.sl)) if p.sl else None
            seen_pos[t] = {"magic": p.magic, "symbol": p.symbol, "type": p.type, "entry": p.price_open, "sl": p.sl,
                           "tp": p.tp, "vol": p.volume, "risk": risk, "bal": broker.balance}
    # প্রতি সময়ে নিয়ম: প্রতি bot প্রতি symbol-এ ≤1, Claude-এর BTC+ETH একসাথে নয়
    for mg in (CL, GP):
        for sym in S.SPEC:
            n = sum(1 for p in broker.positions.values() if p.magic == mg and p.symbol == sym)
            if n > 1:
                violations.append(f"{mg} has {n} positions on {sym}")
    if any(p.magic == CL and p.symbol == "BTCUSDm" for p in broker.positions.values()) and \
       any(p.magic == CL and p.symbol == "ETHUSDm" for p in broker.positions.values()):
        violations.append("Claude BTC+ETH together")
    if broker.pos_idx >= RESTART_AT and broker.tick_i == 0 and not restart_info and \
       any(p.magic == CL for p in broker.positions.values()) and any(p.magic == GP for p in broker.positions.values()) or \
       (broker.pos_idx >= END - 200 and broker.tick_i == 0 and not restart_info):
        snap_before_restart = K.ContestCounter(0).report()
        open_claude = sorted(t for t, p in broker.positions.items() if p.magic == CL)
        claude, gpt = make_claude(), make_gpt()          # ---- সফটওয়্যার "বন্ধ করে আবার চালু" ----
        restart_info = {"bar": broker.pos_idx, "gpt_open_at_restart": sorted(t for t, p in broker.positions.items() if p.magic == GP), "claude_open_at_restart": open_claude,
                        "claude_trades_reloaded": sorted(int(k) for k in claude.trades)}
        snap_after_restart = K.ContestCounter(0).report()
        restart_info["counter_same_after_restart"] = (
            json.dumps(snap_before_restart["claude"], sort_keys=True) == json.dumps(snap_after_restart["claude"], sort_keys=True)
            and json.dumps(snap_before_restart["gpt"], sort_keys=True) == json.dumps(snap_after_restart["gpt"], sort_keys=True))
    broker.advance_tick()

# শেষে খোলা ট্রেড ম্যানেজমেন্টে ধরা পড়ুক
claude.run_once("contest")

# ================= যাচাই =================
R = {}
# ১. মালিকানা: কেউ অন্যের পজিশন বন্ধ/বদল করেছে?
own_viol = [r for r in broker.requests if r["target_magic"] is not None and r["target_magic"] != r["req"].get("magic")]
bad_magic = [r for r in broker.requests if r["req"].get("magic") not in (CL, GP)]
R["requests_total"] = len(broker.requests)
R["close_or_modify_requests"] = sum(1 for r in broker.requests if r["target_magic"] is not None)
R["ownership_violations"] = len(own_viol)
R["unknown_magic_requests"] = len(bad_magic)
R["per_symbol_or_lock_violations"] = len(violations)

# ২. স্বাধীনতা
R["claude_blocked_by_gpt_only"] = len(claude_blocked_by_gpt)
R["gpt_position_checks"] = gpt_block_checks

# ৩. ঝুঁকি ও SL/TP
risk_bad, sltp_bad, gpt_tp_bad = [], [], []
for t, v in seen_pos.items():
    if v["risk"] is None or v["risk"] > 0.01 * v["bal"] * 1.02:
        risk_bad.append((t, v))
    buy = v["type"] == 0
    if (buy and not (v["sl"] < v["entry"] < v["tp"])) or (not buy and not (v["tp"] < v["entry"] < v["sl"])):
        sltp_bad.append((t, v))
    if v["magic"] == GP:
        rr = abs(v["tp"] - v["entry"]) / abs(v["entry"] - v["sl"])
        if abs(rr - 2.0) > 0.01:
            gpt_tp_bad.append((t, rr))
R["positions_opened"] = {"claude": sum(1 for v in seen_pos.values() if v["magic"] == CL),
                         "gpt": sum(1 for v in seen_pos.values() if v["magic"] == GP)}
R["risk_over_1pct"] = len(risk_bad)
R["sl_tp_wrong_side"] = len(sltp_bad)
R["gpt_tp_not_2R"] = len(gpt_tp_bad)

# ৪. Claude ম্যানেজমেন্ট
cl_deals = {}
for d in broker.deals:
    if broker.truth.get(d.position_id, {}).get("magic") == CL and d.entry == 1:
        cl_deals.setdefault(d.position_id, []).append(d)
R["claude_partial_tp1_trades"] = sum(1 for v in cl_deals.values() if len(v) >= 2)
R["claude_breakeven_moves"] = sum(1 for r in broker.requests if r["req"]["action"] == S.TRADE_ACTION_SLTP)
R["claude_time_stops"] = sum(1 for s in logs if "EXIT_TIME" in s)
R["claude_maxhold_stops"] = sum(1 for s in logs if "EXIT_MAXHOLD" in s)
codes = {}
for s in logs:
    if " | " in s and "UTC" in s:
        parts = s.split(" | "); c = parts[4].split(" ")[0] if len(parts) > 4 else "?"
        codes[c] = codes.get(c, 0) + 1
R["claude_log_codes"] = dict(sorted(codes.items(), key=lambda x: -x[1]))
gcodes = {}
for o in gpt_outputs:
    k = o.get("signal") if o.get("signal") in ("BUY", "SELL") else o.get("reason")
    gcodes[k] = gcodes.get(k, 0) + 1
R["gpt_eval_codes"] = dict(sorted(gcodes.items(), key=lambda x: -x[1]))

# ৫. Counter বনাম broker-এর আসল হিসাব
rep = K.ContestCounter(0).report()
truth_closed = {k: {pid for pid, v in broker.truth.items() if v["closed"] and v["magic"] == m}
                for k, m in (("claude", CL), ("gpt", GP))}
cmp_ok = {}
for k in ("claude", "gpt"):
    ids = {t["position_id"] for t in rep["trades"][k]}
    net_truth = round(sum(broker.truth[p]["net"] for p in truth_closed[k]), 2)
    sym_truth = {}
    for p in truth_closed[k]:
        sym_truth[broker.truth[p]["symbol"]] = round(sym_truth.get(broker.truth[p]["symbol"], 0) + broker.truth[p]["net"], 2)
    cmp_ok[k] = {"ids_match": ids == truth_closed[k], "count": len(ids), "truth_count": len(truth_closed[k]),
                 "net": round(rep[k]["net_profit"], 2), "truth_net": net_truth,
                 "net_match": abs(rep[k]["net_profit"] - net_truth) < 0.05,
                 "symbol_net_match": all(abs(rep[k]["by_symbol"].get(s, {}).get("net_profit", 0) - v) < 0.05
                                         for s, v in sym_truth.items()),
                 "no_duplicate_ids": len(ids) == len(rep["trades"][k])}
R["counter_vs_broker"] = cmp_ok
R["open_positions_at_end"] = {"claude": rep["claude"]["open_positions"], "gpt": rep["gpt"]["open_positions"]}

# ৬. দ্বিগুণ গণনা: সব deal দুবার করে দিলে কি বদলায়?
orig_deals = broker.deals
broker.deals = orig_deals + [copy.copy(d) for d in orig_deals]
rep_dup = K.ContestCounter(0).report()
broker.deals = orig_deals
R["duplicate_deals_same_result"] = all(rep_dup[k]["trades"] == rep[k]["trades"] and
                                       abs(rep_dup[k]["net_profit"] - rep[k]["net_profit"]) < 1e-6 for k in ("claude", "gpt"))
R["report_twice_same"] = json.dumps(K.ContestCounter(0).report()["claude"], sort_keys=True) == json.dumps(rep["claude"], sort_keys=True)

# ৭. Server time offset (+3h): শেষ ৩ ঘণ্টায় বন্ধ ট্রেড
now_utc = broker.now_utc_ts()
recent = [d for d in broker.deals if d.entry == 1 and d.time > now_utc]   # server সময় UTC-র "ভবিষ্যতে"
naive = broker.history_deals_get(datetime.fromtimestamp(0, tz=timezone.utc), datetime.fromtimestamp(now_utc, tz=timezone.utc))
R["server_offset_hours"] = broker.offset / 3600
R["closing_deals_in_last_3h"] = len(recent)
R["naive_utc_window_would_miss"] = len([d for d in recent if d not in naive])
counted = {t["position_id"] for k in ("claude", "gpt") for t in rep["trades"][k]}
R["recent_closed_positions_counted"] = all(d.position_id in counted or d.position_id in broker.positions for d in recent)

# ৭খ. নির্দিষ্ট পরীক্ষা: শেষ বন্ধ ট্রেডের deal-গুলোকে "এখন (আসল UTC) + ২.৫ ঘণ্টা" server সময়ে সরিয়ে দেখা
import time as _time
last_pid = max((t["position_id"], t["close_time"]) for t in rep["trades"]["claude"])[0] if rep["trades"]["claude"] else None
if last_pid:
    saved = [(d, d.time, d.time_msc) for d in broker.deals if d.position_id == last_pid]
    future = int(_time.time()) + int(2.5 * 3600)
    for d, _, _ in saved:
        d.time, d.time_msc = future, future * 1000 + d.ticket % 1000
    rep_off = K.ContestCounter(0).report()
    naive2 = broker.history_deals_get(datetime(2026, 1, 1, tzinfo=timezone.utc), datetime.now(timezone.utc))
    R["server_ahead_2_5h_test"] = {
        "trade_counted_by_counter": any(t["position_id"] == last_pid for t in rep_off["trades"]["claude"]),
        "naive_window_to_utc_now_would_count_it": any(d.position_id == last_pid and d.entry == 1 for d in naive2)}
    for d, t0, tm in saved:
        d.time, d.time_msc = t0, tm

# ৮. Contest start (deal ticket) — শুরুর আগের ট্রেড বাদ
mid_ticket = sorted(d.ticket for d in broker.deals)[len(broker.deals) // 2]
rep_mid = K.ContestCounter(mid_ticket).report()
after_ids = {d.position_id for d in broker.deals if d.entry == 0 and d.ticket > mid_ticket}
R["start_ticket_filter_ok"] = all(t["position_id"] in after_ids for k in ("claude", "gpt") for t in rep_mid["trades"][k])

# ৯. Restart
R["restart"] = restart_info
reloaded_ok = set(restart_info.get("claude_open_at_restart", [])) == set(restart_info.get("claude_trades_reloaded", []))
R["restart"]["claude_open_trades_reloaded_ok"] = reloaded_ok
managed_after = [t for t in restart_info.get("claude_open_at_restart", []) if broker.truth[t]["closed"]]
R["restart"]["pre_restart_trades_closed_after_restart"] = len(managed_after)
R["restart"]["their_results_recorded_by_new_bot"] = all(any(c["ticket"] == t for c in claude.closed) or
                                                         any(c["ticket"] == t for c in getattr(claude, "closed", []))
                                                         for t in managed_after)

# ১০. GPT ফাইল অপরিবর্তিত
hash_after = hashlib.sha256(open(GPT_SRC, "rb").read()).hexdigest()
R["gpt_sha256_before"] = hash_before
R["gpt_sha256_after"] = hash_after
R["gpt_sha256_expected"] = P.GPT_SHA256
R["gpt_unchanged"] = hash_before == hash_after == P.GPT_SHA256

# ১১. Preflight: hedging demo পাস, netting ও real ব্যর্থ
ok_h, res_h = P.run_preflight(folder=CONTEST)
R["preflight_hedging_demo"] = {"ok": ok_h, "failed": [n for n, o, _ in res_h if not o]}
broker.margin_mode = S.ACCOUNT_MARGIN_MODE_RETAIL_NETTING
ok_n, res_n = P.run_preflight(folder=CONTEST)
R["preflight_netting"] = {"ok": ok_n, "failed": [n for n, o, _ in res_n if not o]}
broker.margin_mode = S.ACCOUNT_MARGIN_MODE_RETAIL_HEDGING
broker.trade_mode = S.ACCOUNT_TRADE_MODE_REAL
ok_r, res_r = P.run_preflight(folder=CONTEST)
R["preflight_real_account"] = {"ok": ok_r, "failed": [n for n, o, _ in res_r if not o]}
broker.trade_mode = S.ACCOUNT_TRADE_MODE_DEMO

# ১২. GPT-এর নিজের daily-loss window-এ server offset-এর প্রভাব (GPT কোড না বদলে পর্যবেক্ষণ)
R["note_gpt_daily_loss_window_uses_utc_vs_server_time"] = True

# সিমুলেশনের (নকল) ফল — শুধু কাজ করে কি না বোঝার জন্য
R["SIMULATED_RESULTS_NOT_REAL"] = {k: {x: rep[k][x] for x in ("trades", "wins", "losses", "breakeven", "net_profit",
                                                              "gross_profit", "gross_loss", "win_rate", "profit_factor",
                                                              "avg_r", "max_drawdown")} for k in ("claude", "gpt")}
R["sim_period"] = {"from_utc": datetime.fromtimestamp(broker.t0 + START * 900, tz=timezone.utc).isoformat(),
                   "to_utc": broker.now_utc().isoformat(), "m15_bars": END - START}

json.dump(R, open(os.path.join(WORK, "sim_report.json"), "w"), indent=1, ensure_ascii=False, default=str)
K.export_csv(rep, os.path.join(WORK, "sim_trades.csv"))
json.dump({"all": rep, "common": K.ContestCounter(0, {"BTCUSDm", "XAUUSDm"}).report()},
          open(os.path.join(WORK, "sim_counter_report.json"), "w"), default=str)
open(os.path.join(WORK, "claude_sim_log.txt"), "w", encoding="utf-8").write("\n".join(logs))
print(json.dumps(R, indent=1, ensure_ascii=False, default=str))

# ---------------- Netting demo: কেন hedging লাগবে ----------------
nb = S.Broker(margin_mode=S.ACCOUNT_MARGIN_MODE_RETAIL_NETTING, n_bars=3000)
S.install(nb, mod)
nb.pos_idx = 2800
r1 = mod.order_send({"action": 1, "symbol": "BTCUSDm", "volume": 0.05, "type": 0, "sl": 1.0, "tp": 999999.0, "magic": CL})
r2 = mod.order_send({"action": 1, "symbol": "BTCUSDm", "volume": 0.05, "type": 1, "sl": 999999.0, "tp": 1.0, "magic": GP})
print("\nNETTING DEMO: Claude BUY then GPT SELL on BTC ->", r2.comment, "| Claude position still open:",
      any(p.magic == CL for p in nb.positions.values()), "| GPT order touched magic:",
      nb.requests[-1]["target_magic"])
