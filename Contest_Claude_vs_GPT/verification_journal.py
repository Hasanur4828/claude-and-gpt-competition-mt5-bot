"""
Verification Journal — verification_positions.json
==================================================
demo_verification.py যত পরীক্ষা-order পাঠায়, প্রতিটা পাঠানোর *আগে* ও *পরে* এখানে লেখা হয়।
এর তিনটা কাজ:
  1. Counter এই position/deal/order নম্বরগুলো প্রতিযোগিতার হিসাব থেকে বাদ দেয়।
  2. পরের বার চালুর সময় orphan (খোলা রয়ে যাওয়া) পরীক্ষা-পজিশন খুঁজে বের করা।
  3. Preflight — অসম্পূর্ণ/নষ্ট খাতা থাকলে প্রতিযোগিতা শুরু হতে দেয় না।

নিরাপত্তা: atomic write (tmp + os.replace) — অর্ধেক লেখা ফাইল কখনো আসল নাম পায় না;
payload-এর SHA-256 checksum — নষ্ট/হাতে বদলানো ফাইল ধরা পড়ে।
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Dict, Set, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PATH = os.path.join(HERE, "verification_positions.json")
FORMAT = "verification_positions/v1"
DONE_STATUSES = ("complete", "resolved")


def _checksum(runs) -> str:
    return hashlib.sha256(json.dumps(runs, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def load(path: str = DEFAULT_PATH) -> Tuple[str, str, Dict[str, Any]]:
    """ফেরত: (status, message, data). status = OK | MISSING | CORRUPT | INCOMPLETE"""
    if not os.path.exists(path):
        return "MISSING", "verification_positions.json নেই — demo_verification এখনো চালানো হয়নি (বা ফাইল সরানো হয়েছে)", {"runs": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("format") != FORMAT or not isinstance(data.get("runs"), list):
            return "CORRUPT", "verification_positions.json-এর গঠন অচেনা", {"runs": []}
        if data.get("checksum") != _checksum(data["runs"]):
            return "CORRUPT", "verification_positions.json-এর checksum মেলেনি (নষ্ট বা হাতে বদলানো)", data
    except Exception as e:
        return "CORRUPT", f"verification_positions.json পড়া যায়নি: {type(e).__name__}: {e}", {"runs": []}
    bad = []
    for r in data["runs"]:
        if r.get("status") not in DONE_STATUSES:
            bad.append(f"run {r.get('run_id')} status={r.get('status')}")
        for p in r.get("positions", []):
            if p.get("state") not in ("closed", "none_opened"):
                bad.append(f"run {r.get('run_id')} position {p.get('position_id')} state={p.get('state')}")
    if bad:
        return "INCOMPLETE", "অসম্পূর্ণ পরীক্ষা: " + "; ".join(bad[:5]), data
    return "OK", f"{len(data['runs'])}টা পরীক্ষা-run নথিভুক্ত", data


def save(data: Dict[str, Any], path: str = DEFAULT_PATH) -> None:
    data = dict(data)
    data["format"] = FORMAT
    data["checksum"] = _checksum(data["runs"])
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def exclusions(data: Dict[str, Any]) -> Tuple[Set[int], Set[int], Set[int]]:
    """সব run-এর (position_ids, deal_ids, order_tickets) — counter এগুলো বাদ দেয়।"""
    pos, deals, orders = set(), set(), set()
    for r in data.get("runs", []):
        for p in r.get("positions", []):
            for k, s in (("position_id", pos), ("order_ticket", orders), ("deal_ticket", deals)):
                v = p.get(k)
                if v:
                    s.add(int(v))
            for d in p.get("deal_ids", []) or []:
                deals.add(int(d))
    return pos, deals, orders
