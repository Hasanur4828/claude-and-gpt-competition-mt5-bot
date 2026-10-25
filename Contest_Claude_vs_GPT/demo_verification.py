"""
Demo Verification v2 — আসল MT5 Hedging DEMO অ্যাকাউন্টে স্বয়ংক্রিয় যাচাই
==========================================================================
GPT-এর অনুমোদিত A–E শর্ত অনুযায়ী (২৫ অক্টোবর ২০২৬)। চালানো:  python demo_verification.py
(terminal অন্য জায়গায় থাকলে:  python demo_verification.py "C:\\path\\terminal64.exe")
*** GPT-এর অনুমতি ছাড়া আসল ডেমোতেও চালাবেন না। ***

নিরাপত্তার নিয়ম
  গার্ড (কোনো order-এর আগে): DEMO, HEDGING, magic ঠিক ও আলাদা, symbol আছে, tick আছে,
      SL/TP broker-এর stop level মানে, খাতা (verification_positions.json) নষ্ট নয়,
      আগের orphan নেই, প্রতিযোগিতার পজিশন খোলা নেই, তারপর YES।
  A  order-এর আগে ও পরে position snapshot। order ticket কখনো position ticket ধরা হয় না —
      deal → position_id দিয়ে খোঁজা, তারপর symbol, দিক, magic, volume মিলিয়ে তবেই "নিশ্চিত"।
      নিশ্চিত না হলে আর কোনো order যায় না, জরুরি সতর্কবার্তা।
  B  cleanup শুধু "নিশ্চিত-সম্পর্কিত" পজিশন বন্ধ করে (খাতার position_id / order / deal মেলে)।
      পরীক্ষার সময় নতুন-দেখা কিন্তু সম্পর্ক অনিশ্চিত পজিশন → বন্ধ নয়, ticket-সহ জরুরি সতর্কবার্তা।
  C  বাইরের try/finally: স্বাভাবিক শেষ, exception, Ctrl+C — সবক্ষেত্রে cleanup, রিপোর্ট, shutdown-এর চেষ্টা।
      প্রতিটা order পাঠানোর আগেই খাতায় লেখা — process মরে গেলেও পরের বার orphan ধরা পড়ে।
  D  খাতায় প্রতিটা পরীক্ষার position_id, order, deal ও সব deal_ids — counter এগুলো সবসময় বাদ দেয়।
  E  আংশিক বন্ধের আগে বন্ধ-অংশ ও বাকি-অংশ দুটোই volume_min / volume_max / volume_step মানে কি না।

ফলাফল: demo_verification_report.txt / .json, demo_verification_log.txt, verification_positions.json
"""
from __future__ import annotations

import ast
import json
import os
import sys
import tempfile
import time
import traceback
from datetime import datetime, timezone, timedelta

import MetaTrader5 as mt5

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import verification_journal as VJ                                 # noqa: E402
from contest_preflight import run_preflight                       # noqa: E402
from contest_counter import ContestCounter, latest_deal_ticket     # noqa: E402
import claude_pullback_v1 as CLM                                  # noqa: E402
import gpt_contest_adapter as GA                                  # noqa: E402

TEST_SYMBOL = "BTCUSDm"
SLTP_PCT = 0.03
CLAUDE_MAGIC, GPT_MAGIC = 26102401, 26102402
OK_RET = (10008, 10009, 10010)
POLL_TRIES, POLL_DELAY = 10, 0.5
LOG_PATH = os.path.join(HERE, "demo_verification_log.txt")
REPORT_TXT = os.path.join(HERE, "demo_verification_report.txt")
REPORT_JSON = os.path.join(HERE, "demo_verification_report.json")
GPT_FILE = os.path.join(HERE, "gpt_liquidity_fibonacci_scalper_v1.py")
SLEEP = time.sleep                     # পরীক্ষায় বদলানো যায়

UNKNOWN = object()                     # MT5 উত্তর দেয়নি — "নেই" নয়
ST = {"results": [], "leftovers": [], "urgent": [], "journal": None, "run": None,
      "pre_snapshot": None, "orders_attempted": False, "stop_orders": False}


# ======================= ছোট সাহায্যকারী =======================
def log(msg):
    line = f"[{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} UTC] {msg}"
    print(line)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def check(name, ok, detail=""):
    ST["results"].append({"check": name, "ok": bool(ok), "detail": str(detail)})
    log(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")
    return ok


def info(name, value):
    ST["results"].append({"info": name, "value": value})
    log(f"INFO  {name} = {value}")


def urgent(msg):
    ST["urgent"].append(msg)
    log("!!! URGENT: " + msg)


def get_pos(ticket):
    """position বা None (সত্যিই নেই) বা UNKNOWN (MT5 উত্তর দেয়নি)।"""
    if not ticket:
        return None
    ps = mt5.positions_get(ticket=int(ticket))
    if ps is None:
        return UNKNOWN
    return ps[0] if ps else None


def snapshot():
    ps = mt5.positions_get()
    if ps is None:
        return UNKNOWN
    return {int(p.ticket): {"magic": p.magic, "symbol": p.symbol, "type": p.type, "volume": p.volume} for p in ps}


def jsave():
    try:
        VJ.save(ST["journal"])
    except Exception as e:
        urgent(f"verification_positions.json লেখা যায়নি: {type(e).__name__}: {e}")


def side_type(side):
    return getattr(mt5, "POSITION_TYPE_BUY", 0) if side == "BUY" else getattr(mt5, "POSITION_TYPE_SELL", 1)


# ======================= A: position শনাক্ত ও যাচাই =======================
def new_entry(label, magic, side, volume_req):
    e = {"label": label, "magic": magic, "symbol": TEST_SYMBOL, "side": side, "volume_requested": volume_req,
         "order_ticket": None, "deal_ticket": None, "position_id": None, "deal_ids": [], "state": "sending",
         "time_utc": datetime.now(timezone.utc).isoformat()}
    ST["run"]["positions"].append(e)
    jsave()                                            # পাঠানোর *আগে* খাতায় — process মরলেও চিহ্ন থাকে
    return e


def _position_id_from_deal(deal_ticket, e):
    if not deal_ticket:
        return None
    dl = mt5.history_deals_get(ticket=int(deal_ticket))
    if not dl:
        return None
    d = dl[0]
    if d.entry == 0 and d.magic == e["magic"] and d.symbol == e["symbol"]:
        return int(d.position_id)
    return None


def _position_id_from_order(order_ticket, e):
    if not order_ticket:
        return None
    now = datetime.now(timezone.utc)
    ds = mt5.history_deals_get(now - timedelta(days=1), now + timedelta(days=2))
    for d in ds or ():
        if int(getattr(d, "order", 0) or 0) == int(order_ticket) and d.entry == 0 \
                and d.magic == e["magic"] and d.symbol == e["symbol"]:
            return int(d.position_id)
    return None


def resolve(e, order_ok):
    """order-এর পরে আসল position খুঁজে যাচাই। সফল হলে position object, না হলে None।"""
    pre = ST["pre_snapshot"]
    for i in range(POLL_TRIES):
        pid = _position_id_from_deal(e["deal_ticket"], e) or _position_id_from_order(e["order_ticket"], e)
        if pid:
            p = get_pos(pid)
            if p is UNKNOWN:
                log(f"resolve {e['label']}: MT5 unavailable (poll {i + 1})")
            elif p is not None:
                problems = []
                if int(pid) in pre:
                    problems.append("position পরীক্ষার আগেই ছিল")
                if p.symbol != e["symbol"]:
                    problems.append(f"symbol {p.symbol}")
                if p.magic != e["magic"]:
                    problems.append(f"magic {p.magic}")
                if p.type != side_type(e["side"]):
                    problems.append(f"type {p.type}")
                if not (0 < p.volume <= e["volume_requested"] + 1e-9):
                    problems.append(f"volume {p.volume} vs requested {e['volume_requested']}")
                e["position_id"] = int(pid)
                if problems:
                    e["state"] = "unresolved"
                    jsave()
                    urgent(f"{e['label']}: position #{pid} যাচাই ব্যর্থ ({'; '.join(problems)}) — আর কোনো order নয়")
                    ST["stop_orders"] = True
                    return None
                e["state"], e["volume_actual"] = "open", float(p.volume)
                if p.volume < e["volume_requested"] - 1e-9:
                    log(f"{e['label']}: partial fill {p.volume} / {e['volume_requested']} — গ্রহণযোগ্য, প্রকৃত volume ধরা হলো")
                jsave()
                return p
        SLEEP(POLL_DELAY)
    # নিশ্চিত হয়নি
    post = snapshot()
    suspects = []
    if post is not UNKNOWN:
        suspects = [t for t, v in post.items() if t not in ST["pre_snapshot"] and v["magic"] == e["magic"]
                    and v["symbol"] == e["symbol"]]
    if not order_ok and not suspects and post is not UNKNOWN:
        e["state"] = "none_opened"
        jsave()
        log(f"{e['label']}: order ব্যর্থ, কোনো নতুন পজিশন দেখা যায়নি")
        return None
    e["state"] = "unresolved"
    e["suspect_tickets"] = suspects
    jsave()
    ST["stop_orders"] = True
    urgent(f"{e['label']}: position নিশ্চিতভাবে শনাক্ত হয়নি (order {e['order_ticket']}, deal {e['deal_ticket']}, "
           f"সন্দেহভাজন নতুন পজিশন {suspects or 'নেই/অজানা'}) — আর কোনো order পাঠানো হবে না; MT5-এ নিজে দেখুন")
    return None


# ======================= B: শুধু নিশ্চিত-সম্পর্কিত পজিশন বন্ধ =======================
def linked_entry(ticket):
    for e in ST["run"]["positions"] if ST["run"] else ():
        if e.get("position_id") == int(ticket):
            return e
    return None


def close_linked(e, attempts=3, quiet=False):
    """খাতায় নিশ্চিত এই entry-র পজিশন, তার নিজের magic দিয়ে বন্ধ। 'সফল' বললেও আবার দেখে নেয়।"""
    pid = e.get("position_id")
    for i in range(1, attempts + 1):
        p = get_pos(pid)
        if p is None:
            return True
        if p is UNKNOWN:
            log(f"cleanup #{pid} attempt {i}: MT5 unavailable")
            SLEEP(POLL_DELAY)
            continue
        if p.magic != e["magic"] or p.symbol != e["symbol"]:
            msg = f"#{pid}: magic/symbol খাতার সাথে মেলে না ({p.magic}/{p.symbol} বনাম {e['magic']}/{e['symbol']}) — বন্ধ করা হলো না"
            log("REFUSE " + msg) if quiet else urgent(msg)
            return False
        t = mt5.symbol_info_tick(p.symbol)
        if t is None:
            log(f"cleanup #{pid} attempt {i}: no tick {mt5.last_error()}")
            SLEEP(POLL_DELAY)
            continue
        buy = p.type == getattr(mt5, "POSITION_TYPE_BUY", 0)
        for f in (mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_RETURN):
            r = mt5.order_send({"action": mt5.TRADE_ACTION_DEAL, "symbol": p.symbol, "volume": p.volume,
                                "type": mt5.ORDER_TYPE_SELL if buy else mt5.ORDER_TYPE_BUY,
                                "position": int(p.ticket), "price": t.bid if buy else t.ask, "deviation": 50,
                                "magic": e["magic"], "comment": "VERIFY_CLEANUP",
                                "type_time": mt5.ORDER_TIME_GTC, "type_filling": f})
            log(f"cleanup #{pid} attempt {i} filling {f}: retcode {getattr(r, 'retcode', None)} "
                f"{getattr(r, 'comment', '')} last_error {mt5.last_error()}")
            if r is not None and r.retcode in OK_RET:
                break
        for _ in range(POLL_TRIES):                    # "সফল" বললেও সত্যিই বন্ধ হয়েছে কি না
            SLEEP(POLL_DELAY)
            q = get_pos(pid)
            if q is None:
                return True
            if q is not UNKNOWN and r is not None and r.retcode in OK_RET:
                log(f"cleanup #{pid}: broker 'done' বললেও পজিশন এখনো খোলা — আবার চেষ্টা")
                break
    return get_pos(pid) is None


def finalize_entry(e):
    """বন্ধ entry-র সব deal_id খাতায় (D)।"""
    pid = e.get("position_id")
    if not pid:
        return
    p = get_pos(pid)
    if p is None:
        ds = mt5.history_deals_get(position=int(pid))
        if ds is None:
            e["state"] = "closed_deals_unknown"
            urgent(f"#{pid}: বন্ধ, কিন্তু deal history পাওয়া যায়নি — খাতা অসম্পূর্ণ")
        else:
            e["deal_ids"] = sorted({int(d.ticket) for d in ds})
            e["state"] = "closed"
    elif p is UNKNOWN:
        e["state"] = "unknown"
    else:
        e["state"] = "open"


def cleanup():
    log("---- CLEANUP ----")
    run = ST["run"]
    # ১. নিশ্চিত entry-গুলো বন্ধ
    for e in list(run["positions"]):
        if e.get("position_id") and e.get("state") in ("open", "unresolved"):
            try:
                if e["state"] == "open":
                    close_linked(e)
            except Exception as ex:
                urgent(f"{e['label']} বন্ধের সময় error: {type(ex).__name__}: {ex}")
    # ২. ঝাড়ু: পরীক্ষার সময় নতুন-দেখা প্রতিযোগিতা-magic পজিশন
    try:
        post = snapshot()
        if post is UNKNOWN:
            urgent("cleanup-এর সময় MT5 উত্তর দিচ্ছে না — পজিশনের অবস্থা অজানা")
        else:
            for t, v in post.items():
                if t in ST["pre_snapshot"] or v["magic"] not in (CLAUDE_MAGIC, GPT_MAGIC):
                    continue
                e = linked_entry(t)
                if e is not None and e.get("state") in ("open",):
                    close_linked(e)
                elif e is None:
                    run.setdefault("unlinked_new_positions", [])
                    if t not in run["unlinked_new_positions"]:
                        run["unlinked_new_positions"].append(t)
                    urgent(f"নতুন পজিশন #{t} ({v['symbol']} magic {v['magic']} {v['volume']} lot) পরীক্ষার সময় দেখা গেছে, "
                           f"কিন্তু পরীক্ষার order-এর সাথে নিশ্চিত সম্পর্ক নেই — স্বয়ংক্রিয়ভাবে বন্ধ করা হলো না")
    except Exception as ex:
        urgent(f"ঝাড়ু ধাপে error: {type(ex).__name__}: {ex}")
    # ৩. চূড়ান্ত অবস্থা, deal_ids, leftovers
    ST["leftovers"] = []
    for e in run["positions"]:
        try:
            finalize_entry(e)
        except Exception as ex:
            e["state"] = "unknown"
            urgent(f"{e['label']} finalize error: {type(ex).__name__}: {ex}")
        if e["state"] in ("open", "unknown", "unresolved", "closed_deals_unknown"):
            ST["leftovers"].append({k: e.get(k) for k in ("label", "position_id", "order_ticket", "deal_ticket",
                                                           "magic", "symbol", "side", "state", "suspect_tickets")})
    for t in run.get("unlinked_new_positions", []):
        if get_pos(t) not in (None,):
            ST["leftovers"].append({"label": "UNLINKED new position", "position_id": t, "state": "unlinked"})
    run["status"] = "complete" if not ST["leftovers"] else "incomplete"
    run["finished_utc"] = datetime.now(timezone.utc).isoformat()
    jsave()
    check("Cleanup: no test or unlinked positions left, journal complete", not ST["leftovers"],
          ST["leftovers"] if ST["leftovers"] else "")
    if ST["leftovers"]:
        b = "!" * 78
        log(b)
        log("!!  সতর্কতা: নিচের পজিশন খোলা / অজানা / অনিশ্চিত — MT5-এ নিজে দেখে হাতে বন্ধ করুন  !!")
        for l in ST["leftovers"]:
            log(f"!!  {l}")
        log("!!  MT5 → Trade ট্যাব → ডান-ক্লিক → Close Position।  প্রতিযোগিতা শুরু করবেন না।")
        log("!!  সমাধানের পর demo_verification আবার চালালে orphan পরীক্ষা খাতা হালনাগাদ করবে।")
        log(b)


def cleanup_guarded():
    """C: cleanup চলার সময় Ctrl+C এলেও আরেকবার চেষ্টা।"""
    for attempt in (1, 2):
        try:
            cleanup()
            return
        except KeyboardInterrupt:
            urgent(f"cleanup চলার সময় Ctrl+C (চেষ্টা {attempt}) — cleanup আবার চালানো হচ্ছে")
        except Exception as ex:
            urgent(f"cleanup error: {type(ex).__name__}: {ex}")
            log(traceback.format_exc())
    urgent("cleanup সম্পূর্ণ হয়নি — MT5-এ নিজে দেখুন; পরের বার চালালে orphan পরীক্ষা হবে")


# ======================= C: আগের run-এর orphan =======================
def handle_orphans():
    """ফেরত True = নতুন পরীক্ষা চালানো যাবে।"""
    status, msg, data = VJ.load()
    ST["journal"] = data if status != "CORRUPT" else None
    if status == "CORRUPT":
        check("GUARD: verification journal readable", False,
              msg + " — ফাইলটা অন্য নামে সরিয়ে MT5-এ magic 26102401/26102402-এর পজিশন হাতে দেখুন, তারপর আবার চালান")
        return False
    check("GUARD: verification journal readable", True, msg)
    if status != "INCOMPLETE":
        return True
    log("আগের অসম্পূর্ণ পরীক্ষা পাওয়া গেছে — orphan পরীক্ষা চলছে")
    all_ok = True
    for run in data["runs"]:
        if run.get("status") in VJ.DONE_STATUSES:
            continue
        ST["run"] = run
        for e in run.get("positions", []):
            if e.get("state") in ("closed", "none_opened"):
                continue
            if not e.get("position_id"):
                all_ok = False
                urgent(f"orphan? {e['label']} ({e['time_utc']}): position শনাক্ত হয়নি, সন্দেহভাজন {e.get('suspect_tickets')} — হাতে দেখুন")
                continue
            p = get_pos(e["position_id"])
            if p is UNKNOWN:
                all_ok = False
                urgent("MT5 উত্তর দিচ্ছে না — orphan পরীক্ষা করা গেল না")
                continue
            if p is not None:
                log(f"orphan #{e['position_id']} ({e['label']}) খোলা — খাতায় নিশ্চিত, বন্ধ করা হচ্ছে")
                close_linked(e)
            finalize_entry(e)
            if e["state"] != "closed":
                all_ok = False
                urgent(f"orphan #{e['position_id']} এখনো {e['state']}")
        for t in run.get("unlinked_new_positions", []):
            if get_pos(t) is not None:
                all_ok = False
                urgent(f"আগের পরীক্ষার অনিশ্চিত নতুন পজিশন #{t} এখনো খোলা — হাতে দেখুন")
        if all_ok:
            run["status"] = "resolved"
    jsave()
    ST["run"] = None
    check("GUARD: no orphaned test positions from earlier runs", all_ok,
          "orphan সমাধান হয়েছে — নিরাপত্তার জন্য এই run এখানে থামছে, আবার চালান" if all_ok else "উপরের সতর্কবার্তা দেখুন")
    return False                                       # orphan পাওয়া গেলে এই run-এ নতুন পরীক্ষা নয়


# ======================= main =======================
def main(terminal_path=None, assume_yes=False):
    try:
        _main_body(terminal_path, assume_yes)
    except KeyboardInterrupt:
        check("Interrupted by Ctrl+C", False, "ব্যবহারকারী থামিয়েছেন")
    except Exception as ex:
        check("Unexpected error", False, f"{type(ex).__name__}: {ex}")
        log(traceback.format_exc())
    finally:
        try:
            if ST["orders_attempted"]:
                cleanup_guarded()
        finally:
            try:
                write_report()
            except BaseException as ex:                # Ctrl+C রিপোর্ট লেখার সময়ও
                log(f"REPORT ERROR: {type(ex).__name__}: {ex}")
            finally:
                try:
                    mt5.shutdown()
                    log("mt5.shutdown() called")
                except BaseException:
                    pass
    return not [r for r in ST["results"] if "ok" in r and not r["ok"]]


def _main_body(terminal_path, assume_yes):
    ok = mt5.initialize(terminal_path) if terminal_path else mt5.initialize()
    if not check("MT5 initialize", ok, mt5.last_error() if not ok else ""):
        return
    ai = mt5.account_info()
    if not check("Account info", ai is not None, "" if ai else mt5.last_error()):
        return
    log(f"Account {ai.login} · server {getattr(ai, 'server', '?')} · balance {ai.balance}")

    # ---- গার্ড ----
    is_demo = ai.trade_mode == getattr(mt5, "ACCOUNT_TRADE_MODE_DEMO", 0)
    is_hedge = ai.margin_mode == getattr(mt5, "ACCOUNT_MARGIN_MODE_RETAIL_HEDGING", 2)
    if not check("GUARD: account is DEMO", is_demo, "" if is_demo else "আসল অ্যাকাউন্ট — কোনো order নয়"):
        return
    if not check("GUARD: account is HEDGING", is_hedge, "" if is_hedge else "Netting — কোনো order নয়"):
        return
    magics_ok = (CLM.MAGIC == CLAUDE_MAGIC and GA.GPT_MAGIC == GPT_MAGIC and GA.CLAUDE_MAGIC == CLM.MAGIC
                 and CLAUDE_MAGIC != GPT_MAGIC)
    if not check("GUARD: magic numbers correct and distinct", magics_ok,
                 f"Claude {CLM.MAGIC} · GPT {GA.GPT_MAGIC} · adapter's Claude {GA.CLAUDE_MAGIC}"):
        return
    if not handle_orphans():
        return
    snap = snapshot()
    if not check("GUARD: positions readable", snap is not UNKNOWN, "" if snap is not UNKNOWN else mt5.last_error()):
        return
    contest_open = [t for t, v in snap.items() if v["magic"] in (CLAUDE_MAGIC, GPT_MAGIC)]
    if not check("GUARD: no contest positions already open", not contest_open,
                 f"{contest_open} — প্রতিযোগিতা চলাকালে চালাবেন না" if contest_open else ""):
        return
    si = mt5.symbol_info(TEST_SYMBOL) if mt5.symbol_select(TEST_SYMBOL, True) else None
    if not check(f"GUARD: symbol {TEST_SYMBOL} available", si is not None, "" if si else "Market Watch-এ নাম দেখুন"):
        return
    t = mt5.symbol_info_tick(TEST_SYMBOL)
    if not check(f"GUARD: {TEST_SYMBOL} has a tick", t is not None and t.bid > 0, "" if t else mt5.last_error()):
        return
    min_dist = float(si.trade_stops_level) * float(si.point)
    sl_dist = t.bid * SLTP_PCT
    if not check("GUARD: test SL/TP respect broker stop level", sl_dist > 1.5 * min_dist,
                 f"SL distance {sl_dist:.2f} vs stops_level {min_dist:.2f}"):
        return
    gpt_src = open(GPT_FILE, encoding="utf-8").read()
    gpt_sends_close = any(isinstance(n, ast.Constant) and n.value in ("position",) for n in ast.walk(ast.parse(gpt_src))) \
        or "TRADE_ACTION_SLTP" in gpt_src
    check("Static: GPT code never sends close/modify requests (no 'position' key, no SLTP)", not gpt_sends_close)

    if not assume_yes:
        a = input(f"\nডেমো অ্যাকাউন্টে {TEST_SYMBOL}-এ ছোট পরীক্ষা-ট্রেড খোলা ও বন্ধ হবে। চালাতে YES লিখুন: ")
        if a.strip() != "YES":
            log("ব্যবহারকারী বাতিল করেছেন।")
            return
    run_checks()


def run_checks():
    pf_ok, pf = run_preflight(HERE)
    for n, o, d in pf:
        check(f"Preflight: {n}", o, d)
    if not pf_ok:
        log("Preflight ব্যর্থ — order পরীক্ষা চালানো হলো না।")
        return

    now = time.time()
    offs = {}
    for s in ("BTCUSDm", "ETHUSDm", "XAUUSDm"):
        tk = mt5.symbol_info_tick(s)
        if tk:
            offs[s] = round((tk.time - now) / 60.0, 1)
    best = max(offs.values()) if offs else None
    info("server_offset_minutes_by_symbol", offs)
    info("server_offset_hours_estimate", round(best / 30) * 0.5 if best is not None else None)

    for s in ("BTCUSDm", "ETHUSDm", "XAUUSDm"):
        s_i, tk = mt5.symbol_info(s), mt5.symbol_info_tick(s)
        if s_i and tk:
            info(f"symbol {s}", f"digits {s_i.digits}, contract {getattr(s_i, 'trade_contract_size', '?')}, "
                                f"min {s_i.volume_min}, step {s_i.volume_step}, max {s_i.volume_max}, "
                                f"stops_level {s_i.trade_stops_level}, filling_mode {getattr(s_i, 'filling_mode', '?')}, "
                                f"spread {round(tk.ask - tk.bid, s_i.digits)}")

    si = mt5.symbol_info(TEST_SYMBOL)
    vmin, step, vmax = float(si.volume_min), float(si.volume_step), float(si.volume_max)
    claude_vol, plan = None, None
    for k in range(0, 20):                             # E: আংশিক বন্ধ বৈধ হয় এমন সবচেয়ে ছোট volume
        v = round(vmin * 2 + k * step, 8)
        if v > vmax:
            break
        pl, why = CLM.plan_partial_close(v, si)
        if pl:
            claude_vol, plan = v, pl
            break
    if claude_vol is None:
        claude_vol = vmin
        log(f"E: এই symbol-এ বৈধ আংশিক বন্ধ সম্ভব নয় (min {vmin}, step {step}, max {vmax}) — partial পরীক্ষা বাদ")
    start_ticket = latest_deal_ticket()

    ST["journal"] = ST["journal"] or {"runs": []}
    ST["run"] = {"run_id": "V" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S"),
                 "started_utc": datetime.now(timezone.utc).isoformat(), "status": "running", "positions": []}
    ST["journal"]["runs"].append(ST["run"])
    snap = snapshot()
    if snap is UNKNOWN:
        check("Pre-order snapshot", False, "MT5 উত্তর দিচ্ছে না")
        ST["run"]["status"] = "complete"
        jsave()
        return
    ST["pre_snapshot"] = snap
    ST["run"]["pre_snapshot"] = sorted(snap)
    jsave()

    claude = CLM.ClaudePullbackV1(state_file=os.path.join(tempfile.mkdtemp(), "claude_verify_state.json"),
                                  log=log, notify=lambda s: None)
    gpt = GA.GPTContestAdapter()

    # ---- GPT-এর order (নিজের অপরিবর্তিত _send_order) ----
    tk = mt5.symbol_info_tick(TEST_SYMBOL)
    g_sig = {"symbol": TEST_SYMBOL, "signal": "SELL", "entry": tk.bid,
             "stop_loss": round(tk.bid * (1 + SLTP_PCT), si.digits), "take_profit": round(tk.bid * (1 - SLTP_PCT), si.digits)}
    g_vol = gpt._calc_lot(TEST_SYMBOL, "SELL", tk.bid, g_sig["stop_loss"])
    ge = new_entry("GPT test SELL", GPT_MAGIC, "SELL", g_vol)
    ST["orders_attempted"] = True
    g_res = gpt._send_order(g_sig)
    log(f"GPT _send_order result: {g_res}")
    ge["order_ticket"], ge["deal_ticket"] = g_res.get("ticket"), g_res.get("deal")
    if g_res.get("volume"):
        ge["volume_requested"] = float(g_res["volume"])
    jsave()
    gp = resolve(ge, g_res.get("status") == "OPENED")
    check("A: GPT position confirmed (deal→position, symbol, side, magic, volume)", gp is not None,
          f"position {ge.get('position_id')} state {ge['state']}")
    if ST["stop_orders"] or gp is None:
        log("GPT-এর পজিশন নিশ্চিত হয়নি — আর কোনো order পাঠানো হবে না")
        return

    # ---- Claude-এর order (নিজের _send) ----
    tk = mt5.symbol_info_tick(TEST_SYMBOL)
    c_sl, c_tp = round(tk.ask * (1 - SLTP_PCT), si.digits), round(tk.ask * (1 + SLTP_PCT), si.digits)
    ce = new_entry("Claude test BUY", CLAUDE_MAGIC, "BUY", claude_vol)
    c_res = claude._send({"action": mt5.TRADE_ACTION_DEAL, "symbol": TEST_SYMBOL, "volume": claude_vol,
                          "type": mt5.ORDER_TYPE_BUY, "sl": c_sl, "tp": c_tp}, TEST_SYMBOL, 1)
    log(f"Claude _send result: retcode {getattr(c_res, 'retcode', None)} order {getattr(c_res, 'order', None)} "
        f"deal {getattr(c_res, 'deal', None)}")
    ce["order_ticket"], ce["deal_ticket"] = getattr(c_res, "order", None), getattr(c_res, "deal", None)
    jsave()
    cp = resolve(ce, c_res is not None)
    check("A: Claude position confirmed (deal→position, symbol, side, magic, volume)", cp is not None,
          f"position {ce.get('position_id')} state {ce['state']}")
    if ST["stop_orders"] or cp is None:
        return

    gp, cp = get_pos(ge["position_id"]), get_pos(ce["position_id"])
    if gp in (None, UNKNOWN) or cp in (None, UNKNOWN):
        check("Both positions open together (hedging)", False, "একটা পজিশন দেখা যাচ্ছে না")
        return
    check("Both positions open together on same symbol (hedging)", True,
          f"GPT #{gp.ticket} {gp.volume} · Claude #{cp.ticket} {cp.volume}")
    check("GPT SL/TP set at broker", gp.sl > gp.price_open > gp.tp > 0, f"sl {gp.sl} tp {gp.tp}")
    check("Claude SL/TP set at broker", 0 < cp.sl < cp.price_open < cp.tp, f"sl {cp.sl} tp {cp.tp}")
    g_before = (gp.sl, gp.tp, gp.volume)

    new_sl = round(cp.price_open * (1 - SLTP_PCT / 2), si.digits)
    mod_ok = claude._modify_sl(cp, new_sl, cp.tp)
    cp2, gp2 = get_pos(ce["position_id"]), get_pos(ge["position_id"])
    check("Claude modified its own SL", mod_ok and cp2 not in (None, UNKNOWN) and abs(cp2.sl - new_sl) < 10 ** -si.digits * 2,
          f"new sl {getattr(cp2, 'sl', None)}")
    check("GPT position unchanged after Claude's modify",
          gp2 not in (None, UNKNOWN) and (gp2.sl, gp2.tp, gp2.volume) == g_before)

    refused = claude._close(gp2, gp2.volume, "VERIFY_FOREIGN") is False and claude._modify_sl(gp2, gp2.sl, gp2.tp) is False
    wrong_label = dict(ce, magic=GPT_MAGIC)            # উল্টো দিক: GPT-লেবেলে Claude-এর পজিশন বন্ধের চেষ্টা
    refused_rev = close_linked(wrong_label, attempts=1, quiet=True) is False and get_pos(ce["position_id"]) not in (None, UNKNOWN)
    gp3 = get_pos(ge["position_id"])
    check("Claude code refuses GPT position; GPT-magic cleanup refuses Claude position",
          refused and refused_rev and gp3 not in (None, UNKNOWN) and (gp3.sl, gp3.tp, gp3.volume) == g_before)

    cp_now = get_pos(ce["position_id"])
    pl, why = CLM.plan_partial_close(float(cp_now.volume), si)
    if pl:
        pc = claude._close(cp_now, pl[0], "VERIFY_PARTIAL")
        SLEEP(POLL_DELAY)
        cp4 = get_pos(ce["position_id"])
        check("E: Claude partial close (close & remaining both valid)",
              pc and cp4 not in (None, UNKNOWN) and abs(cp4.volume - pl[1]) < 1e-9,
              f"{cp_now.volume} → close {pl[0]}, remaining {getattr(cp4, 'volume', None)} (expected {pl[1]})")
    else:
        check("E: partial close skipped — volumes would violate broker rules", True, why)
    cp5 = get_pos(ce["position_id"])
    if cp5 not in (None, UNKNOWN):
        claude._close(cp5, cp5.volume, "VERIFY_CLOSE")
    for _ in range(POLL_TRIES):
        if get_pos(ce["position_id"]) is None:
            break
        SLEEP(POLL_DELAY)
    gp4 = get_pos(ge["position_id"])
    check("Claude fully closed its position", get_pos(ce["position_id"]) is None)
    check("GPT position still open & unchanged after Claude closed",
          gp4 not in (None, UNKNOWN) and (gp4.sl, gp4.tp, gp4.volume) == g_before)
    check("GPT test position closed with GPT magic", close_linked(ge))
    finalize_entry(ge)
    finalize_entry(ce)
    jsave()

    # ---- D: counter ----
    rep = ContestCounter(start_ticket).report()
    all_ids = [x["position_id"] for k in ("claude", "gpt") for x in rep["trades"][k]]
    check("D: counter EXCLUDES both verification trades",
          ge["position_id"] not in all_ids and ce["position_id"] not in all_ids
          and {ge["position_id"], ce["position_id"]} <= set(rep["verification"]["excluded_positions"]),
          f"excluded {rep['verification']['excluded_positions']}")
    raw = ContestCounter(start_ticket, verification_path=os.path.join(tempfile.mkdtemp(), "none.json")).report()
    for key, e in (("claude", ce), ("gpt", ge)):
        hist = mt5.history_deals_get(position=int(e["position_id"])) or ()
        net = round(sum(d.profit + d.commission + d.swap + getattr(d, "fee", 0.0) for d in hist), 2)
        rows = [x for x in raw["trades"][key] if x["position_id"] == e["position_id"]]
        check(f"Counter accuracy without exclusion ({key}): counted once, net = MT5 history",
              len(rows) == 1 and abs(rows[0]["net"] - net) < 0.011,
              f"rows {len(rows)} counter {rows[0]['net'] if rows else None} history {net} deals {len(hist)}")
        check(f"D: journal has all deal IDs ({key})", sorted(e["deal_ids"]) == sorted({int(d.ticket) for d in hist}),
              e["deal_ids"])


def write_report():
    res = ST["results"]
    passed = sum(1 for r in res if r.get("ok"))
    failed = [r for r in res if "ok" in r and not r["ok"]]
    stamp = datetime.now(timezone.utc).isoformat()
    payload = {"utc": stamp, "passed": passed, "failed": len(failed), "results": res,
               "urgent": ST["urgent"], "leftover_positions": ST["leftovers"],
               "run_id": (ST["run"] or {}).get("run_id")}
    tmp = REPORT_JSON + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1, ensure_ascii=False, default=str)
    os.replace(tmp, REPORT_JSON)
    lines = [f"Demo verification v2 {stamp}", f"PASS {passed} · FAIL {len(failed)}", ""]
    if ST["urgent"] or ST["leftovers"]:
        lines.append("!!! জরুরি সতর্কতা — MT5-এ নিজে দেখুন, প্রতিযোগিতা শুরু করবেন না !!!")
        lines += [f"!!! {u}" for u in ST["urgent"]]
        lines += [f"!!! leftover: {l}" for l in ST["leftovers"]]
        lines.append("")
    for r in res:
        lines.append(f"{'PASS' if r['ok'] else 'FAIL'}  {r['check']}  {r['detail']}" if "ok" in r
                     else f"INFO  {r['info']} = {r['value']}")
    tmp = REPORT_TXT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, REPORT_TXT)
    log(f"==== PASS {passed} · FAIL {len(failed)} · URGENT {len(ST['urgent'])} ====  {REPORT_TXT}")
    if failed or ST["urgent"]:
        log("কিছু চেক ব্যর্থ / জরুরি সতর্কতা — প্রতিযোগিতা শুরু করবেন না। রিপোর্ট ও log পাঠান।")
    else:
        log("সব পাস।")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--yes"]
    ok = main(args[0] if args else None, assume_yes="--yes" in sys.argv)
    sys.exit(0 if ok else 1)
