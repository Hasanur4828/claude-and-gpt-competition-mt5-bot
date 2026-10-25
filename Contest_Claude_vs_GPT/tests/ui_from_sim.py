import sys, os, json, types
sys.path.insert(0, sys.argv[1])
sys.modules["MetaTrader5"] = types.ModuleType("MetaTrader5")
data = json.load(open(sys.argv[2]))
import customtkinter as ctk
from contest_scoreboard import ContestScoreboard
ctk.set_appearance_mode("dark")
app = ctk.CTk(); app.geometry("1040x1180")
prov = lambda start, flt: data["common" if flt else "all"]
b = ContestScoreboard(app, {"contest_start_deal": 0, "contest_start_utc": "2026-03-30 (simulated)"},
                      report_provider=prov, start_ticket_provider=lambda: 0,
                      banner="SIMULATION — FAKE MARKET DATA, NOT REAL RESULTS")
b.pack(fill="both", expand=True)
def shot(n): app.update(); os.system(f"import -window root {sys.argv[3]}/{n}")
def s1(): shot("ui_sim_common.png"); b.scope.set("All symbols"); b.refresh(); app.after(800, s2)
def s2(): shot("ui_sim_all.png"); app.destroy()
app.after(1500, s1); app.mainloop()
