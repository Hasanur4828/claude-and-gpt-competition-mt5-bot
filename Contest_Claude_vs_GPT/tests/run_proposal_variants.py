"""
প্রস্তাব "চালু করলে কী হবে" — শুধু অস্থায়ী কপিতে (আসল প্যাকেজ বদলায় না)।
প্রতিটা variant: প্যাকেজ কপি → প্রস্তাবের ফাইল বসানো → (GPT ফাইল বদলালে) কপির preflight GPT_SHA256 নতুন hash-এ →
তারপর পুরো test suite: e2e দুই-বট সিমুলেশন, Claude regression, ৩২ verification পরিস্থিতি, counter unit test।
শেষে v5 (চালু) বনাম variant-এর ট্রেড তালিকা তুলনা। *** সব নকল broker, আসল MT5 নয়। ***
usage: python run_proposal_variants.py <package_dir> <out_dir>
"""
import sys, os, shutil, subprocess, json, hashlib, tempfile, re, csv

PKG, OUTD = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
TESTS = os.path.join(PKG, "tests")
P = os.path.join(PKG, "proposals")
os.makedirs(OUTD, exist_ok=True)
sha = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()
GPTF, CLF = "gpt_liquidity_fibonacci_scalper_v1.py", "claude_pullback_v1.py"
G = lambda d: os.path.join(P, d, GPTF)
CF = lambda d: os.path.join(P, d, CLF)
VARIANTS = {
    "v5_active": {},
    "P6": {CLF: CF("P6_claude_close_verification")},
    "P6b": {CLF: CF("P6b_claude_close_verification_plus_tp1_state")},
    "GPT_COMBINED": {GPTF: G("COMBINED_v1_1_all_four")},
    "GPT_COMBINED+P6b": {GPTF: G("COMBINED_v1_1_all_four"), CLF: CF("P6b_claude_close_verification_plus_tp1_state")},
}
ADF = "gpt_contest_adapter.py"
V2 = os.path.join(P, "v2")
if os.environ.get("VARIANT_SET") == "v2":          # v2 প্রস্তাব (G2 core + A1 adapter + P6c)
    VARIANTS = {
        "v5_active": {},
        "P6c": {CLF: os.path.join(V2, "P6c_claude_close_tp1_be_reconcile", CLF)},
        "G2+A1": {GPTF: os.path.join(V2, "G2_gpt_core_combined", GPTF), ADF: os.path.join(V2, "A1_adapter_position_state", ADF)},
        "G2+A1+P6c": {GPTF: os.path.join(V2, "G2_gpt_core_combined", GPTF), ADF: os.path.join(V2, "A1_adapter_position_state", ADF),
                      CLF: os.path.join(V2, "P6c_claude_close_tp1_be_reconcile", CLF)},
    }
H_BEFORE = {f: sha(os.path.join(PKG, f)) for f in (GPTF, CLF, "contest_preflight.py", "gpt_contest_adapter.py")}


def build(name, repl):
    d = os.path.join(tempfile.mkdtemp(prefix=f"var_{name}_"), "pkg")
    shutil.copytree(PKG, d, ignore=shutil.ignore_patterns("proposals", "__pycache__", "results", "verification_positions.json"))
    for dst, src in repl.items():
        shutil.copy2(src, os.path.join(d, dst))
    if GPTF in repl:                                   # "অনুমোদনের পরে" যা করতে হবে: preflight hash হালনাগাদ
        pf = os.path.join(d, "contest_preflight.py")
        s = open(pf, encoding="utf-8").read()
        new = sha(os.path.join(d, GPTF))
        s2 = re.sub(r'GPT_SHA256 = "[0-9a-f]{64}"', f'GPT_SHA256 = "{new}"', s)
        assert s2 != s
        open(pf, "w", encoding="utf-8").write(s2)
    return d


def run(cmd, log):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=3000)
    open(log, "w", encoding="utf-8").write(r.stdout + "\n--- stderr ---\n" + r.stderr)
    return r.returncode


def trades(work):
    rows = list(csv.DictReader(open(os.path.join(work, "sim_trades.csv"), encoding="utf-8")))
    keep = ("strategy", "position_id", "symbol", "side", "open_time", "close_time", "volume", "net", "exit_reason")
    return [{k.lstrip("\ufeff"): v for k, v in r.items() if k.lstrip("\ufeff") in keep} for r in rows]


SUM = {}
for name, repl in VARIANTS.items():
    d = build(name, repl)
    od = os.path.join(OUTD, name)
    os.makedirs(od, exist_ok=True)
    res = {"files": {f: sha(os.path.join(d, f)) for f in (GPTF, CLF, "gpt_contest_adapter.py")}}
    work = os.path.join(od, "sim")
    rc = run([sys.executable, os.path.join(TESTS, "run_contest_sim.py"), d, work], os.path.join(od, "e2e_output.txt"))
    R = json.load(open(os.path.join(work, "sim_report.json"), encoding="utf-8")) if rc == 0 else {}
    res["e2e_rc"] = rc
    for k in ("ownership_violations", "unknown_magic_requests"):
        res[k] = R.get(k)
    res["preflight_hedging_demo"] = R.get("preflight_hedging_demo")
    res["counter_vs_broker"] = R.get("counter_vs_broker")
    res["restart_ok"] = (R.get("restart") or {}).get("claude_open_trades_reloaded_ok")
    res["sim_results"] = R.get("SIMULATED_RESULTS_NOT_REAL")
    res["trades"] = trades(work) if rc == 0 else None
    rc = run([sys.executable, os.path.join(TESTS, "test_claude_bot_regression.py"), d, os.path.join(od, "reg.json")],
             os.path.join(od, "regression_output.txt"))
    reg = json.load(open(os.path.join(od, "reg.json"), encoding="utf-8"))
    res["claude_regression"] = f"{sum(r['pass'] for r in reg['rows'])}/{len(reg['rows'])}" if isinstance(reg, dict) and "rows" in reg \
        else f"{sum(r['pass'] for r in reg)}/{len(reg)}"
    rc = run([sys.executable, os.path.join(TESTS, "test_verification_scenarios.py"), d, os.path.join(od, "scen.json")],
             os.path.join(od, "scenarios_output.txt"))
    sc = json.load(open(os.path.join(od, "scen.json"), encoding="utf-8"))
    rows = sc.get("rows", sc.get("scenarios", sc)) if isinstance(sc, dict) else sc
    res["verification_scenarios"] = f"{sum(1 for r in rows if r.get('pass'))}/{len(rows)}"
    rc = run([sys.executable, os.path.join(TESTS, "test_counter.py"), TESTS, d, os.path.join(od, "counter.json")],
             os.path.join(od, "counter_output.txt"))
    res["counter_unit_rc"] = rc
    res["counter_unit_tail"] = open(os.path.join(od, "counter_output.txt"), encoding="utf-8").read().strip().splitlines()[-3:]
    SUM[name] = res
    shutil.rmtree(os.path.dirname(d), ignore_errors=True)

base = SUM["v5_active"]["trades"]
for name, r in SUM.items():
    r["trades_identical_to_v5"] = r["trades"] == base
    r["n_trades"] = len(r["trades"] or [])
H_AFTER = {f: sha(os.path.join(PKG, f)) for f in H_BEFORE}
out = {"package_files_unchanged": H_BEFORE == H_AFTER, "hashes": H_AFTER, "SIMULATED_ONLY": True,
       "variants": {k: {kk: vv for kk, vv in v.items() if kk != "trades"} for k, v in SUM.items()}}
json.dump(out, open(os.path.join(OUTD, "variants_summary.json"), "w"), indent=1, ensure_ascii=False, default=str)
json.dump({k: v["trades"] for k, v in SUM.items()}, open(os.path.join(OUTD, "variants_trades.json"), "w"), indent=1,
          ensure_ascii=False)
print(json.dumps(out, indent=1, ensure_ascii=False, default=str))
