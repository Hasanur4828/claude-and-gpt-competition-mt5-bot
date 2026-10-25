"""
P5 — demo_verification-এ BTCUSDm/XAUUSDm volume spec রিপোর্ট (শুধু তথ্য, order নয়)। নকল broker-এ।
১) P5 বসানো অস্থায়ী কপিতে পুরো ৩২-পরিস্থিতির পরীক্ষা (আচরণ অপরিবর্তিত কি না)
২) রিপোর্টে নতুন তথ্য-লাইন আছে কি না, আর বড় min lot + ছোট balance-এ ✗ দেখায় কি না
৩) P5 অংশ নিজে কোনো order পাঠায় না
usage: python test_p5_volume_spec.py <package_dir> <out_json>
"""
import sys, os, shutil, tempfile, subprocess, json, types, importlib, hashlib
PKG, OUT = os.path.abspath(sys.argv[1]), sys.argv[2]
TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TESTS)
import sim_faults as SF

P5 = os.path.join(PKG, "proposals", "P5_demo_volume_spec_report", "demo_verification.py")
H0 = hashlib.sha256(open(os.path.join(PKG, "demo_verification.py"), "rb").read()).hexdigest()
d = os.path.join(tempfile.mkdtemp(), "pkg")
shutil.copytree(PKG, d, ignore=shutil.ignore_patterns("proposals", "__pycache__", "results", "verification_positions.json"))
shutil.copy2(P5, os.path.join(d, "demo_verification.py"))
ROWS = []

r = subprocess.run([sys.executable, os.path.join(TESTS, "test_verification_scenarios.py"), d, os.path.join(d, "scen.json")],
                   capture_output=True, text=True, timeout=3000)
sc = json.load(open(os.path.join(d, "scen.json"), encoding="utf-8"))
ROWS.append({"test": "P5 বসানো কপিতে ৩২-পরিস্থিতির পরীক্ষা", "expected": "৩২/৩২ (v5-এর মতোই)",
             "actual": f"{sum(x['pass'] for x in sc)}/{len(sc)}", "pass": all(x["pass"] for x in sc) and len(sc) == 32})


def run_once(faults, balance):
    from datetime import datetime, timezone, timedelta
    start = datetime.now(timezone.utc).replace(second=0, microsecond=0) - timedelta(minutes=15 * 2800)
    b = SF.FaultyBroker(faults=faults, n_bars=3000, start_utc=start, balance=balance)
    b.pos_idx = 2800
    mod = types.ModuleType("MetaTrader5")
    SF.install(b, mod)
    sys.modules["MetaTrader5"] = mod
    dd = os.path.join(tempfile.mkdtemp(), "pkg")
    shutil.copytree(d, dd, ignore=shutil.ignore_patterns("verification_positions.json", "demo_verification_*", "scen.json"))
    for k in [k for k in list(sys.modules) if k in ("demo_verification", "contest_preflight", "contest_counter",
                                                      "claude_pullback_v1", "gpt_contest_adapter",
                                                      "gpt_liquidity_fibonacci_scalper_v1", "verification_journal")]:
        del sys.modules[k]
    sys.path.insert(0, dd)
    V = importlib.import_module("demo_verification")
    V.SLEEP = lambda s: None
    # শুধু P5 অংশ পর্যন্ত কত order গেছে তা মাপতে: info "volume spec XAUUSDm" লেখার মুহূর্তে request সংখ্যা
    marks = {}
    _info = V.info
    def info(name, value):
        if name.startswith("volume spec"):
            marks[name] = len(b.requests)
        return _info(name, value)
    V.info = info
    V.main(assume_yes=True)
    sys.path.remove(dd)
    lines = {x["info"]: x["value"] for x in V.ST["results"] if "info" in x and x["info"].startswith("volume spec")}
    return lines, marks


lines, marks = run_once({}, 10000.0)
ok = set(lines) == {"volume spec BTCUSDm", "volume spec XAUUSDm"} and all(v.count("balance ≥") == 5 for v in lines.values()) \
     and all(v == 0 for v in marks.values())
ROWS.append({"test": "স্বাভাবিক (min 0.01, balance 10,000)", "expected": "দুই symbol-এর তথ্য-লাইন, প্রতিটায় ৫ SL দূরত্ব (0.25%, 0.5%, 1%, 2%, এই পরীক্ষার 3%); P5 অংশে ০ order",
             "actual": json.dumps({**lines, "orders_before_P5_lines": marks}, ensure_ascii=False), "pass": ok})

lines, marks = run_once({"vol_rules": {"BTCUSDm": (0.1, 0.1, 100.0)}}, 10000.0)
btc = lines.get("volume spec BTCUSDm", "")
seg = {p.split(":")[0].strip(): p for p in btc.split(" | ")[1:]}
ok = "min 0.1" in btc and "✗" in seg.get("SL 3.00% (এই পরীক্ষার SL)", "") and "✓" in seg.get("SL 0.25%", "")
ROWS.append({"test": "BTC min 0.1, balance 10,000 (13a2-এর মতো)",
             "expected": "এই পরীক্ষার ৩% SL-এ ✗ (তাই 13a2-এ GPT order দেয়নি — ব্যাখ্যা মেলে), ছোট SL দূরত্বে ✓",
             "actual": btc, "pass": ok})

H1 = hashlib.sha256(open(os.path.join(PKG, "demo_verification.py"), "rb").read()).hexdigest()
ROWS.append({"test": "চালু demo_verification.py অপরিবর্তিত", "expected": "SHA আগে = পরে", "actual": H1[:16], "pass": H0 == H1})
summary = {"total": len(ROWS), "passed": sum(x["pass"] for x in ROWS),
           "P5_sha256": hashlib.sha256(open(P5, "rb").read()).hexdigest(), "SIMULATED_ONLY": True}
json.dump({"summary": summary, "rows": ROWS}, open(OUT, "w"), indent=1, ensure_ascii=False)
for x in ROWS:
    print(("PASS " if x["pass"] else "FAIL ") + x["test"] + f"\n      expected: {x['expected']}\n      actual:   {x['actual']}")
print(json.dumps(summary, indent=1, ensure_ascii=False))
