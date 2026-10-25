"""
Contest Runner — Claude Pullback v1 বনাম GPT Fibonacci & Liquidity Sweep
========================================================================
আলাদা একটা ছোট প্রোগ্রাম: আপনার মূল সফটওয়্যারে হাত না দিয়েই VPS-এ প্রতিযোগিতা চালায়।

চালানোর আগে:
  1. VPS-এ MT5 খুলে Hedging DEMO অ্যাকাউন্টে login করুন, "Algo Trading" চালু করুন।
  2. pip install MetaTrader5 customtkinter pandas numpy requests
  3. এই ফোল্ডারে:  python contest_runner.py
     (terminal64.exe অন্য জায়গায় থাকলে:  python contest_runner.py "C:\\path\\terminal64.exe")

Password চাওয়া হয় না — চলমান, আগে থেকেই login করা MT5-এর সাথে যুক্ত হয়।
প্রতিযোগিতার সময় আপনার মূল সফটওয়্যারের সব strategy বন্ধ রাখুন (একই অ্যাকাউন্ট হলে)।
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from datetime import datetime

import MetaTrader5 as mt5
import customtkinter as ctk

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from contest_preflight import run_preflight                     # noqa: E402
from contest_scoreboard import ContestScoreboard                # noqa: E402
from claude_pullback_v1 import ClaudePullbackV1                 # noqa: E402
from gpt_contest_adapter import GPTContestAdapter               # noqa: E402

CONFIG_FILE = os.path.join(HERE, "contest_config.json")
LOG_FILE = os.path.join(HERE, "contest_log.txt")


def load_cfg():
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_cfg(c):
    tmp = CONFIG_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(c, f, indent=1)
    os.replace(tmp, CONFIG_FILE)


class RunnerApp(ctk.CTk):
    def __init__(self, terminal_path=None):
        super().__init__()
        self.title("Contest Runner — Claude vs GPT (DEMO)")
        self.geometry("1100x900")
        self.cfg = load_cfg()
        self.running = False
        self.lock = threading.Lock()          # MT5 call একসাথে একটাই thread থেকে

        ok = mt5.initialize(terminal_path) if terminal_path else mt5.initialize()
        if not ok:
            ctk.CTkLabel(self, text=f"MT5 initialize failed: {mt5.last_error()}\n"
                                    f"MT5 খোলা ও login করা আছে কি না দেখুন।", text_color="#EF4444",
                         font=("Arial", 16)).pack(pady=40)
            return

        bar = ctk.CTkFrame(self)
        bar.pack(fill="x", padx=10, pady=8)
        self.btn = ctk.CTkButton(bar, text="▶ Start contest bots", fg_color="green", command=self.toggle)
        self.btn.pack(side="left", padx=6)
        self.status = ctk.CTkLabel(bar, text="Stopped", text_color="orange", font=("Arial", 13, "bold"))
        self.status.pack(side="left", padx=12)
        acc = mt5.account_info()
        ctk.CTkLabel(bar, text=f"Account {acc.login if acc else '?'} · {acc.server if acc and hasattr(acc, 'server') else ''}",
                     text_color="#9AA3B2").pack(side="right", padx=8)

        tabs = ctk.CTkTabview(self)
        tabs.pack(fill="both", expand=True, padx=10, pady=4)
        tabs.add("Scoreboard")
        tabs.add("Log")
        self.board = ContestScoreboard(tabs.tab("Scoreboard"), config=self.cfg, save_config=save_cfg,
                                       preflight=lambda: self._locked(run_preflight, HERE), export_dir=HERE,
                                       report_provider=self._report)
        self.board.pack(fill="both", expand=True)
        self.logbox = ctk.CTkTextbox(tabs.tab("Log"))
        self.logbox.pack(fill="both", expand=True)

        self.claude = ClaudePullbackV1(state_file=os.path.join(HERE, "claude_pb_v1_state.json"),
                                       log=self.log, notify=self.log)
        self.gpt = GPTContestAdapter()
        self._pending = []
        self.after(500, self._flush_log)
        self.protocol("WM_DELETE_WINDOW", self._quit)

    def _locked(self, fn, *a):
        with self.lock:
            return fn(*a)

    def _report(self, start, flt):
        from contest_counter import ContestCounter
        return self._locked(lambda: ContestCounter(start, flt).report())

    def log(self, msg):
        line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
        self._pending.append(line)
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

    def _flush_log(self):                     # UI শুধু মূল thread থেকে বদলানো হয়
        while self._pending:
            self.logbox.insert("end", self._pending.pop(0) + "\n")
        self.logbox.see("end")
        self.after(500, self._flush_log)

    def toggle(self):
        if self.running:
            self.running = False
            self.btn.configure(text="▶ Start contest bots", fg_color="green")
            self.status.configure(text="Stopped (open trades keep their SL/TP at broker)", text_color="orange")
            return
        ok, res = self._locked(run_preflight, HERE)
        for n, o, d in res:
            self.log(f"PREFLIGHT {'OK  ' if o else 'FAIL'} {n} {d}")
        if not ok:
            self.status.configure(text="Preflight FAILED — see Log tab", text_color="#EF4444")
            return
        self.running = True
        self.btn.configure(text="■ Stop", fg_color="red")
        self.status.configure(text="Running: Claude + GPT (contest)", text_color="#22C55E")
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while self.running:
            try:
                with self.lock:
                    self.claude.run_once("contest")
                    for o in self.gpt.run_contest_once("contest"):
                        ex = o.get("execution")
                        self.log(f"GPT {o.get('symbol', '')} {o.get('signal')} {o.get('reason', '')}"
                                 f"{' → ' + str(ex) if ex else ''}")
            except Exception as e:
                self.log(f"LOOP ERROR {type(e).__name__}: {e}")
            time.sleep(1)

    def _quit(self):
        self.running = False
        time.sleep(1.2)
        mt5.shutdown()
        self.destroy()


if __name__ == "__main__":
    ctk.set_appearance_mode("dark")
    RunnerApp(sys.argv[1] if len(sys.argv) > 1 else None).mainloop()
