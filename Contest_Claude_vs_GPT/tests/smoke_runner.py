import sys, os, types, time, shutil
CON, WORK = sys.argv[1], sys.argv[2]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sim_mt5 as S
b = S.Broker(n_bars=3200); b.pos_idx = 2900
m = types.ModuleType("MetaTrader5"); S.install(b, m)
m.initialize = lambda *a, **k: True; m.shutdown = lambda: None
sys.modules["MetaTrader5"] = m
# runner-টা কপি ফোল্ডারে চালাই যাতে config/state ফাইল আসল ফোল্ডারে না পড়ে
import tempfile; D = os.path.join(tempfile.mkdtemp(), "runner_copy"); shutil.copytree(CON, D, ignore=shutil.ignore_patterns("tests"))
sys.path.insert(0, D)
import contest_runner as RR
import claude_pullback_v1 as C
C.NewsFilter.status = lambda self, now: "OK"
import customtkinter as ctk
ctk.set_appearance_mode("dark")
app = RR.RunnerApp()
def adv():
    for _ in range(40): b.advance_tick()
    app.after(300, adv)
def go():
    app.toggle(); adv(); app.after(6000, done)
def done():
    app.update(); os.system(f"import -window root {WORK}/runner_smoke.png")
    txt = app.logbox.get("0.0", "end")
    print("PREFLIGHT lines:", txt.count("PREFLIGHT"), "| FAIL lines:", txt.count("PREFLIGHT FAIL"),
          "| LOOP ERROR:", txt.count("LOOP ERROR"), "| running:", app.running)
    print("requests sent:", len(b.requests), "positions:", len(b.positions))
    app._quit()
app.after(1500, go); app.mainloop()
