"""
প্রতিটা প্রস্তাবের পরিসর-প্রমাণ (AST)। দুই ফাইলের Python AST (line number ও comment বাদে) অংশ ধরে তুলনা:
  ১) কোন ফাংশন/অংশ বদলেছে, যোগ হয়েছে, বাদ পড়েছে — অনুমোদিত তালিকার বাইরে কিছু থাকলে FAIL।
  ২) বদলানো ফাংশনের ভেতরে statement-স্তরের diff (ast.unparse করা কোডে) — ঠিক কোন statement যোগ/বদল হয়েছে।
usage: python verify_proposal_scope.py <package_dir> <out_json>
"""
import ast, sys, os, json, hashlib, difflib

PKG, OUT = sys.argv[1], sys.argv[2]
P = os.path.join(PKG, "proposals")
G10 = os.path.join(PKG, "gpt_liquidity_fibonacci_scalper_v1.py")
C5 = os.path.join(PKG, "claude_pullback_v1.py")
K = "GPTLiquidityFibonacciScalper."
CK = "ClaudePullbackV1."
SPEC = [
    ("P1", G10, os.path.join(P, "P1_order_send_none", "gpt_liquidity_fibonacci_scalper_v1.py"),
     {K + "_send_order"}, set()),
    ("P2", G10, os.path.join(P, "P2_daily_loss_server_time", "gpt_liquidity_fibonacci_scalper_v1.py"),
     {K + "_daily_loss_count"}, {K + "_server_offset_seconds"}),
    ("P3", G10, os.path.join(P, "P3_partial_fill_volume", "gpt_liquidity_fibonacci_scalper_v1.py"),
     {K + "_send_order"}, set()),
    ("P4", G10, os.path.join(P, "P4_buy_tick_check", "gpt_liquidity_fibonacci_scalper_v1.py"),
     {K + "_setup"}, set()),
    ("COMBINED", G10, os.path.join(P, "COMBINED_v1_1_all_four", "gpt_liquidity_fibonacci_scalper_v1.py"),
     {K + "_send_order", K + "_daily_loss_count", K + "_setup"}, {K + "_server_offset_seconds"}),
    ("P6", C5, os.path.join(P, "P6_claude_close_verification", "claude_pullback_v1.py"),
     {CK + "__init__", CK + "_close", CK + "_manage_open_trades"},
     {CK + "_confirm_close", "import import time", "assign (CLOSE_CONFIRM_TRIES, CLOSE_CONFIRM_DELAY)"}),
    ("P6b", C5, os.path.join(P, "P6b_claude_close_verification_plus_tp1_state", "claude_pullback_v1.py"),
     {CK + "__init__", CK + "_close", CK + "_manage_open_trades"},
     {CK + "_confirm_close", "import import time", "assign (CLOSE_CONFIRM_TRIES, CLOSE_CONFIRM_DELAY)", "assign BE_MAX_TRIES"}),
    ("P5", os.path.join(PKG, "demo_verification.py"), os.path.join(P, "P5_demo_volume_spec_report", "demo_verification.py"),
     {"run_checks"}, set()),
]

if os.environ.get("VARIANT_SET") == "v2":
    V2 = os.path.join(P, "v2")
    SPEC = [
        ("G2", G10, os.path.join(V2, "G2_gpt_core_combined", "gpt_liquidity_fibonacci_scalper_v1.py"),
         {K + "__init__", K + "_setup", K + "_daily_loss_count", K + "_has_position", K + "_send_order", K + "evaluate_symbol"},
         {K + "_server_offset_seconds", K + "_deal_window", K + "_exec_snapshot", K + "_reconcile", K + "_execution_unknown",
          K + "_check_exec_unknown", K + "_fill_info", "assign UNCERTAIN_RETCODES", "assign UNKNOWN_RESOLVE_SEC",
          "assign MAX_TICK_AGE_SEC", "assign OFFSET_SYMBOLS", "assign EXEC_STATE_FILE", "import import json",
          "import import os", K + "_load_exec_state", K + "_save_exec_state"}),
        ("A1", os.path.join(PKG, "gpt_contest_adapter.py"), os.path.join(V2, "A1_adapter_position_state", "gpt_contest_adapter.py"),
         {"GPTContestAdapter._has_position", "module docstring"},
         {"import from typing import Any, Dict, List, Optional"}, {"import from typing import Any, Dict, List"}),
        ("P6c", C5, os.path.join(V2, "P6c_claude_close_tp1_be_reconcile", "claude_pullback_v1.py"),
         {CK + "__init__", CK + "_close", CK + "_manage_open_trades", CK + "manage_open_trades"},
         {CK + "_confirm_close", CK + "_adopt_orphans", "import import time",
          "assign (CLOSE_CONFIRM_TRIES, CLOSE_CONFIRM_DELAY)", "assign BE_MAX_TRIES"}),
    ]


def parts(path):
    tree = ast.parse(open(path, encoding="utf-8").read())
    out, src = {}, {}
    for i, node in enumerate(tree.body):
        if isinstance(node, ast.ClassDef):
            other = []
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    out[f"{node.name}.{sub.name}"] = ast.dump(sub, include_attributes=False)
                    src[f"{node.name}.{sub.name}"] = ast.unparse(sub)
                else:
                    other.append(ast.dump(sub, include_attributes=False))
            head = ast.ClassDef(name=node.name, bases=node.bases, keywords=node.keywords, body=[],
                                decorator_list=node.decorator_list, type_params=getattr(node, "type_params", []))
            out[f"class {node.name} (header + non-method body)"] = ast.dump(head, include_attributes=False) + "|".join(other)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out[node.name] = ast.dump(node, include_attributes=False)
            src[node.name] = ast.unparse(node)
        else:
            key = f"top-level #{i} {type(node).__name__}"
            if isinstance(node, ast.Expr) and isinstance(getattr(node, "value", None), ast.Constant) and i == 0:
                key = "module docstring"
            elif isinstance(node, ast.Assign):
                key = "assign " + ",".join(ast.unparse(t) for t in node.targets)
            elif isinstance(node, ast.AnnAssign):
                key = "assign " + ast.unparse(node.target)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                key = "import " + ast.unparse(node)
            elif isinstance(node, ast.If):
                key = "if " + ast.unparse(node.test)          # যেমন: if __name__ == '__main__' (অবস্থান নয়, বিষয়বস্তু দিয়ে চেনা)
            out[key] = ast.dump(node, include_attributes=False)
    return out, src


RES, ALL_OK = {}, True
for spec in SPEC:
    pid, a, b, allowed_changed, allowed_new = spec[:5]
    allowed_removed = spec[5] if len(spec) > 5 else set()
    pa, sa = parts(a)
    pb, sb = parts(b)
    same, changed, added, removed = [], [], [], []
    for k in sorted(set(pa) | set(pb)):
        if k in pa and k in pb:
            (same if pa[k] == pb[k] else changed).append(k)
        elif k in pb:
            added.append(k)
        else:
            removed.append(k)
    stmt = {}
    for k in changed:
        if k in sa:
            d = [l for l in difflib.unified_diff(sa[k].splitlines(), sb[k].splitlines(), lineterm="", n=0)
                 if not l.startswith(("---", "+++", "@@"))]
            stmt[k] = {"added_or_changed": [l[1:].strip() for l in d if l.startswith("+")],
                       "removed_or_changed": [l[1:].strip() for l in d if l.startswith("-")]}
    ok = set(changed) <= allowed_changed and set(added) <= allowed_new and set(removed) <= allowed_removed
    ALL_OK &= ok
    RES[pid] = {"base": os.path.basename(a), "base_sha256": hashlib.sha256(open(a, "rb").read()).hexdigest(),
                "proposal_sha256": hashlib.sha256(open(b, "rb").read()).hexdigest(),
                "identical_parts": len(same), "changed": changed, "added": added, "removed": removed,
                "allowed_changed": sorted(allowed_changed), "allowed_new": sorted(allowed_new),
                "statement_diff": stmt, "scope_ok": ok}

json.dump({"all_scope_ok": ALL_OK, "proposals": RES}, open(OUT, "w"), indent=1, ensure_ascii=False)
for pid, r in RES.items():
    print(f"\n=== {pid}  sha {r['proposal_sha256'][:16]}…  base {r['base']} {r['base_sha256'][:16]}…")
    print(f"identical parts: {r['identical_parts']} | changed: {r['changed']} | added: {r['added']} | removed: {r['removed']}")
    for k, d in r["statement_diff"].items():
        print(f"  [{k}] statement diff:")
        for l in d["removed_or_changed"]:
            print("     - " + l)
        for l in d["added_or_changed"]:
            print("     + " + l)
    print("SCOPE OK:", r["scope_ok"])
print("\nALL SCOPE OK:", ALL_OK)
