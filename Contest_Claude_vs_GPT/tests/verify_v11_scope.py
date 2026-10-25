"""
প্রমাণ: GPT v1.1 প্রস্তাবে শুধু _daily_loss_count() বদলেছে আর _server_offset_seconds() যোগ হয়েছে।
বাকি সব — import, constant, StrategyConfig, entry/setup, SL/TP, risk, order — হুবহু এক।
পদ্ধতি: দুই ফাইলের Python AST (কোডের গঠন, line number বাদে) প্রতিটা অংশ ধরে তুলনা।
usage: python verify_v11_scope.py <v1.0 file> <v1.1 file> <out_json>
"""
import ast, sys, json, hashlib

A, B, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
ALLOWED_CHANGED = {"GPTLiquidityFibonacciScalper._daily_loss_count"}
ALLOWED_NEW = {"GPTLiquidityFibonacciScalper._server_offset_seconds"}


def parts(path):
    tree = ast.parse(open(path, encoding="utf-8").read())
    out = {}
    for i, node in enumerate(tree.body):
        if isinstance(node, ast.ClassDef):
            body_other = []
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    out[f"{node.name}.{sub.name}"] = ast.dump(sub, include_attributes=False)
                else:
                    body_other.append(ast.dump(sub, include_attributes=False))
            head = ast.ClassDef(name=node.name, bases=node.bases, keywords=node.keywords, body=[],
                                decorator_list=node.decorator_list, type_params=getattr(node, "type_params", []))
            out[f"class {node.name} (header + non-method body)"] = ast.dump(head, include_attributes=False) + "|".join(body_other)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out[node.name] = ast.dump(node, include_attributes=False)
        else:
            key = f"top-level #{i} {type(node).__name__}"
            if isinstance(node, ast.Expr) and isinstance(getattr(node, "value", None), ast.Constant) and i == 0:
                key = "module docstring"
            if isinstance(node, ast.Assign):
                key = "assign " + ",".join(ast.unparse(t) for t in node.targets)
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                key = "import " + ast.unparse(node)
            out[key] = ast.dump(node, include_attributes=False)
    return out


pa, pb = parts(A), parts(B)
same, changed, added, removed = [], [], [], []
for k in sorted(set(pa) | set(pb)):
    if k in pa and k in pb:
        (same if pa[k] == pb[k] else changed).append(k)
    elif k in pb:
        added.append(k)
    else:
        removed.append(k)

ok = set(changed) <= ALLOWED_CHANGED and set(added) <= ALLOWED_NEW and not removed
res = {
    "v1_0_sha256": hashlib.sha256(open(A, "rb").read()).hexdigest(),
    "v1_1_sha256": hashlib.sha256(open(B, "rb").read()).hexdigest(),
    "identical_parts_count": len(same), "identical_parts": same,
    "changed": changed, "added": added, "removed": removed,
    "scope_ok": ok,
}
json.dump(res, open(OUT, "w"), indent=1)
print(f"identical parts: {len(same)}")
for k in same:
    print("  =", k)
print("changed:", changed)
print("added:  ", added)
print("removed:", removed)
print("SCOPE OK (only allowed changes):", ok)
