"""
Contest Preflight — প্রতিযোগিতা শুরুর আগে বাধ্যতামূলক চেক
==========================================================
কোনো একটা চেক ব্যর্থ হলে প্রতিযোগিতা মোড চালু হবে না।

    from contest_preflight import run_preflight
    ok, results = run_preflight()
    for name, passed, detail in results: print(name, passed, detail)
"""
from __future__ import annotations

import hashlib
import os
from typing import List, Tuple

import MetaTrader5 as mt5

import verification_journal as VJ

# GPT-এর আসল ফাইলের SHA-256 (ব্যবহারকারীর পাঠানো ফাইল থেকে নেওয়া, ২৫ অক্টোবর ২০২৬)
GPT_FILE = "gpt_liquidity_fibonacci_scalper_v1.py"
GPT_SHA256 = "4d41a0ea7e75176002f1fc90a1530f77893c47e964f1420f91c1ba58bdd81160"
SYMBOLS = ("BTCUSDm", "ETHUSDm", "XAUUSDm")
MAGICS = {"claude": 26102401, "gpt": 26102402}

HEDGING = getattr(mt5, "ACCOUNT_MARGIN_MODE_RETAIL_HEDGING", 2)
DEMO = getattr(mt5, "ACCOUNT_TRADE_MODE_DEMO", 0)


def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def run_preflight(folder: str = ".", allow_real_account: bool = False) -> Tuple[bool, List[Tuple[str, bool, str]]]:
    res: List[Tuple[str, bool, str]] = []

    ti = mt5.terminal_info()
    res.append(("MT5 terminal connected", bool(ti and getattr(ti, "connected", True)),
                "" if ti else f"terminal_info() = None, {mt5.last_error()}"))
    res.append(("Algo trading allowed in terminal", bool(ti and getattr(ti, "trade_allowed", False)),
                "MT5-এ 'Algo Trading' বোতাম চালু করুন" if not (ti and getattr(ti, "trade_allowed", False)) else ""))

    ai = mt5.account_info()
    if ai is None:
        res.append(("Account info", False, "account_info() = None — login হয়নি"))
    else:
        res.append(("Account allows trading", bool(getattr(ai, "trade_allowed", True)), ""))
        hedging = ai.margin_mode == HEDGING
        res.append(("Account is HEDGING", hedging,
                    "" if hedging else "Netting অ্যাকাউন্ট — দুই বট একই symbol-এ আলাদা পজিশন রাখতে পারবে না। "
                                       "Broker-এ নতুন Hedging ডেমো অ্যাকাউন্ট খুলুন।"))
        demo = ai.trade_mode == DEMO
        res.append(("Account is DEMO", demo or allow_real_account,
                    "" if demo else ("আসল অ্যাকাউন্ট — প্রতিযোগিতা শুধু ডেমোতে" if not allow_real_account
                                     else "সতর্কতা: আসল অ্যাকাউন্ট (allow_real_account=True)")))

    for s in SYMBOLS:
        ok = bool(mt5.symbol_select(s, True)) and mt5.symbol_info(s) is not None
        res.append((f"Symbol {s} available", ok, "" if ok else "Market Watch-এ নাম মিলিয়ে দেখুন"))

    path = os.path.join(folder, GPT_FILE)
    if not os.path.exists(path):
        res.append(("GPT original file present", False, path))
    else:
        h = file_sha256(path)
        res.append(("GPT original file unchanged (SHA-256)", h == GPT_SHA256,
                    "" if h == GPT_SHA256 else f"hash মেলেনি: {h}"))

    res.append(("Magic numbers distinct", len(set(MAGICS.values())) == len(MAGICS), str(MAGICS)))

    # demo_verification-এর খাতা: নষ্ট বা অসম্পূর্ণ (orphan সম্ভব) হলে প্রতিযোগিতা নয়
    vst, vmsg, _ = VJ.load(os.path.join(folder, "verification_positions.json"))
    res.append(("Verification journal OK (no orphaned test positions)", vst in ("OK", "MISSING"),
                vmsg if vst != "OK" else ""))

    # শুরুর আগে অন্য strategy-র পুরনো পজিশন থাকলে সতর্কতা (ব্যর্থ নয়, কারণ নিজের নিয়মে শেষ হবে)
    others = [p for p in (mt5.positions_get() or ()) if p.magic not in MAGICS.values()]
    res.append(("No leftover positions from other strategies", True,
                "" if not others else f"সতর্কতা: অন্য strategy-র {len(others)}টা পজিশন খোলা — ঐ symbol-এ "
                                      f"দুই বটই অপেক্ষা করবে যতক্ষণ না সেগুলো বন্ধ হয়"))
    return all(ok for _, ok, _ in res), res
