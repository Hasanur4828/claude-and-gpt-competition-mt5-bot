"""
Contest Scoreboard — customtkinter UI
=====================================
Claude Pullback v1  বনাম  GPT Fibonacci & Liquidity Sweep — পাশাপাশি ট্রেড কাউন্টার।

সফটওয়্যারে বসানো:
    from contest_scoreboard import ContestScoreboard
    board = ContestScoreboard(contest_tab, config=app_config, save_config=save_fn)
    board.pack(fill="both", expand=True)

config-এ রাখা হয়:
    "contest_start_deal" : শুরুর মুহূর্তের শেষ MT5 deal ticket (এর পরের ট্রেডই গোনা হয়)
    "contest_start_utc"  : শুধু দেখানোর জন্য শুরুর সময়
প্রতি ৩০ সেকেন্ডে MT5 history থেকে নতুন হিসাব। লেবেল ইংরেজিতে, যাতে সব Windows-এ ঠিক দেখায়।
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Callable, Optional

import customtkinter as ctk

from contest_counter import ContestCounter, MIN_TRADES_FOR_VERDICT, export_csv, latest_deal_ticket

CLAUDE_COLOR = "#4F8EF7"
GPT_COLOR = "#10B981"
MUTED = "#9AA3B2"
GOOD = "#22C55E"
BAD = "#EF4444"
COMMON_SYMBOLS = {"BTCUSDm", "XAUUSDm"}
SYMBOL_LABELS = {"BTCUSDm": "BTC", "XAUUSDm": "GOLD", "ETHUSDm": "ETH"}


def money(v: float, sign: bool = True) -> str:
    if v < 0:
        return f"−${abs(v):,.2f}"
    return f"{'+' if sign and v > 0 else ''}${v:,.2f}"


def pf_txt(v):
    return "-" if v is None else ("∞" if v == float("inf") else f"{v:.2f}")


def r_txt(v):
    return "-" if v is None else f"{v:+.2f}R"


ROWS = [
    ("Completed trades", "trades", lambda v: f"{v}", None),
    ("Wins", "wins", lambda v: f"{v}", None),
    ("Losses", "losses", lambda v: f"{v}", None),
    ("Breakeven", "breakeven", lambda v: f"{v}", None),
    ("Win rate", "win_rate", lambda v: f"{v:.1f}%", "win_rate"),
    ("Gross profit", "gross_profit", lambda v: money(v, sign=False), None),
    ("Gross loss", "gross_loss", lambda v: money(-v) if v else "$0.00", None),
    ("Net profit", "net_profit", money, "net_profit"),
    ("Profit factor", "profit_factor", pf_txt, "profit_factor"),
    ("Average R", "avg_r", r_txt, "avg_r"),
    ("Total R", "total_r", lambda v: f"{v:+.2f}R", None),
    ("Max drawdown", "max_drawdown", lambda v: money(v, sign=False), "max_drawdown"),
    ("Max losing streak", "max_consec_losses", lambda v: f"{v}", None),
    ("Current streak", "current_streak", lambda v: f"{v}", None),
    ("Best / worst trade", None, None, None),
    ("Today (server day)", None, None, None),
    ("Open now", None, None, None),
]


class _Column(ctk.CTkFrame):
    def __init__(self, master, title, subtitle, color):
        super().__init__(master, corner_radius=10, border_width=2, border_color=color)
        ctk.CTkLabel(self, text=title, font=("Arial", 17, "bold"), text_color=color).pack(pady=(10, 0))
        ctk.CTkLabel(self, text=subtitle, font=("Arial", 11), text_color=MUTED).pack()
        self.big = ctk.CTkLabel(self, text="$0.00", font=("Arial", 30, "bold"))
        self.big.pack(pady=(8, 0))
        self.wl = ctk.CTkLabel(self, text="0 W  ·  0 L  ·  0 BE", font=("Arial", 13))
        self.wl.pack()
        self.progress = ctk.CTkProgressBar(self, progress_color=color, height=8)
        self.progress.set(0)
        self.progress.pack(fill="x", padx=18, pady=(10, 2))
        self.progress_lbl = ctk.CTkLabel(self, text="", font=("Arial", 10), text_color=MUTED)
        self.progress_lbl.pack(pady=(0, 10))

    def update_stats(self, s):
        net = s["net_profit"]
        self.big.configure(text=money(net), text_color=GOOD if net >= 0 else BAD)
        self.wl.configure(text=f"{s['wins']} W  ·  {s['losses']} L  ·  {s['breakeven']} BE")
        self.progress.set(min(1.0, s["trades"] / MIN_TRADES_FOR_VERDICT))
        self.progress_lbl.configure(text=f"{s['trades']} / {MIN_TRADES_FOR_VERDICT} trades for verdict")


class ContestScoreboard(ctk.CTkFrame):
    def __init__(self, master, config: dict, save_config: Optional[Callable[[dict], None]] = None,
                 report_provider: Optional[Callable[[int, Optional[set]], dict]] = None,
                 start_ticket_provider: Optional[Callable[[], int]] = None,
                 preflight: Optional[Callable[[], tuple]] = None,
                 export_dir: str = ".", refresh_ms: int = 30000, banner: Optional[str] = None):
        super().__init__(master, fg_color="transparent")
        self.config_ref = config
        self.save_config = save_config or (lambda c: None)
        self.provider = report_provider or (lambda start, f: ContestCounter(start, f).report())
        self.start_ticket = start_ticket_provider or latest_deal_ticket
        self.preflight = preflight
        self.export_dir = export_dir
        self.refresh_ms = refresh_ms
        self.scope = ctk.StringVar(value="Common only (BTC + GOLD)")
        self.last_report = None

        if banner:   # যেমন: "DEMO — FAKE TEST DATA"
            ctk.CTkLabel(self, text=banner, fg_color="#B45309", text_color="white",
                         font=("Arial", 13, "bold")).pack(fill="x")

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=10, pady=(6, 2))
        ctk.CTkLabel(top, text="Strategy Contest — Claude vs GPT", font=("Arial", 18, "bold")).pack(side="left")
        ctk.CTkButton(top, text="Start / Reset", width=110, fg_color="#7C3AED",
                      command=self._reset_contest).pack(side="right", padx=3)
        ctk.CTkButton(top, text="Export CSV", width=100, command=self._export).pack(side="right", padx=3)
        if preflight:
            ctk.CTkButton(top, text="Preflight", width=90, fg_color="#475569",
                          command=self._run_preflight).pack(side="right", padx=3)
        ctk.CTkSegmentedButton(top, values=["All symbols", "Common only (BTC + GOLD)"],
                               variable=self.scope, command=lambda _v: self.refresh()).pack(side="right", padx=8)
        self.info = ctk.CTkLabel(self, text="", font=("Arial", 11), text_color=MUTED)
        self.info.pack(fill="x", padx=12)

        cols = ctk.CTkFrame(self, fg_color="transparent")
        cols.pack(fill="x", padx=10, pady=6)
        self.claude_col = _Column(cols, "Claude Pullback v1", "Trend pullback · H1 + M15 · magic 26102401", CLAUDE_COLOR)
        self.claude_col.pack(side="left", fill="both", expand=True, padx=(0, 6))
        self.gpt_col = _Column(cols, "GPT Fibonacci & Liquidity Sweep", "BOS + Fib 50–61.8% + sweep · magic 26102402", GPT_COLOR)
        self.gpt_col.pack(side="left", fill="both", expand=True, padx=(6, 0))

        body = ctk.CTkScrollableFrame(self, corner_radius=10)
        body.pack(fill="both", expand=True, padx=10, pady=6)

        # ---- মোট তুলনা ----
        heads = [("Metric", 170), ("Claude", 170), ("GPT", 170), ("Leader", 110)]
        for c, (txt, w) in enumerate(heads):
            ctk.CTkLabel(body, text=txt, font=("Arial", 12, "bold"), width=w, anchor="w",
                         text_color={1: CLAUDE_COLOR, 2: GPT_COLOR}.get(c, MUTED)).grid(row=0, column=c, padx=8, pady=(8, 4), sticky="w")
        self.cells = {}
        r = 1
        for label, key, fmt, cmp_key in ROWS:
            ctk.CTkLabel(body, text=label, anchor="w", font=("Arial", 12)).grid(row=r, column=0, padx=8, pady=1, sticky="w")
            cells = []
            for col in (1, 2, 3):
                lb = ctk.CTkLabel(body, text="-", anchor="w", font=("Arial", 12, "bold" if col == 3 else "normal"))
                lb.grid(row=r, column=col, padx=8, sticky="w")
                cells.append(lb)
            self.cells[label] = cells
            r += 1

        # ---- symbol অনুযায়ী ----
        ctk.CTkLabel(body, text="Results by symbol", font=("Arial", 14, "bold")).grid(row=r, column=0, columnspan=4, padx=8, pady=(14, 4), sticky="w")
        r += 1
        self.sym_cells = {}
        for sym in ("BTCUSDm", "XAUUSDm", "ETHUSDm"):
            ctk.CTkLabel(body, text=SYMBOL_LABELS[sym], anchor="w", font=("Arial", 12, "bold")).grid(row=r, column=0, padx=8, sticky="nw")
            a = ctk.CTkLabel(body, text="-", anchor="w", justify="left", font=("Arial", 11))
            b = ctk.CTkLabel(body, text="-", anchor="w", justify="left", font=("Arial", 11))
            a.grid(row=r, column=1, padx=8, pady=2, sticky="w")
            b.grid(row=r, column=2, padx=8, pady=2, sticky="w")
            self.sym_cells[sym] = (a, b)
            r += 1

        self.verdict = ctk.CTkLabel(self, text="", font=("Arial", 14, "bold"))
        self.verdict.pack(pady=(2, 8))

        if "contest_start_deal" not in self.config_ref:
            self._reset_contest(initial=True)
        self.after(200, self._loop)

    # ---------- কাজ ----------
    def _reset_contest(self, initial=False):
        try:
            ticket = int(self.start_ticket())
        except Exception as e:
            self.info.configure(text=f"Could not read MT5 history: {e}", text_color=BAD)
            return
        self.config_ref["contest_start_deal"] = ticket
        self.config_ref["contest_start_utc"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        self.save_config(self.config_ref)
        if not initial:
            self.refresh()

    def _export(self):
        if not self.last_report:
            return
        name = f"contest_trades_{datetime.now():%Y%m%d_%H%M%S}.csv"
        n = export_csv(self.last_report, os.path.join(self.export_dir, name))
        self.info.configure(text=f"Exported {n} trades → {name}  (MT5 History-র Position নম্বরের সাথে মিলিয়ে দেখুন)",
                            text_color=GOOD)

    def _run_preflight(self):
        ok, res = self.preflight()
        bad = [f"{n}: {d}" for n, o, d in res if not o]
        self.info.configure(text="Preflight OK — contest can run" if ok else "Preflight FAILED — " + " | ".join(bad),
                            text_color=GOOD if ok else BAD)

    def _loop(self):
        self.refresh()
        self.after(self.refresh_ms, self._loop)

    @staticmethod
    def _sym_text(d):
        if not d:
            return "no trades"
        return (f"{d['trades']} trades · {d['wins']}W/{d['losses']}L/{d['breakeven']}BE · WR {d['win_rate']:.0f}%\n"
                f"Gross {money(d['gross_profit'], sign=False)} / {money(-d['gross_loss']) if d['gross_loss'] else '$0.00'}"
                f" · Net {money(d['net_profit'])}\nPF {pf_txt(d['profit_factor'])} · Avg {r_txt(d['avg_r'])}"
                f" · DD {money(d['max_drawdown'], sign=False)}")

    def refresh(self):
        try:
            flt = COMMON_SYMBOLS if self.scope.get().startswith("Common") else None
            rep = self.provider(int(self.config_ref["contest_start_deal"]), flt)
        except Exception as e:
            self.info.configure(text=f"Could not read MT5 history: {e}", text_color=BAD)
            return
        self.last_report = rep
        c, g, cmp = rep["claude"], rep["gpt"], rep["compare"]
        upd = datetime.fromisoformat(rep["updated"]).strftime("%H:%M:%S")
        self.info.configure(text=f"Contest started {self.config_ref.get('contest_start_utc', '?')} (after deal "
                                 f"#{self.config_ref['contest_start_deal']})  ·  {self.scope.get()}  ·  updated {upd}",
                            text_color=MUTED)
        if rep.get("warnings"):                       # verification খাতা নিয়ে সতর্কতা — লাল
            self.info.configure(text=" | ".join(rep["warnings"]),
                                text_color=BAD if not rep.get("data_ok", True) else "#F59E0B")
        self.claude_col.update_stats(c)
        self.gpt_col.update_stats(g)
        for label, key, fmt, cmp_key in ROWS:
            a, b, l = self.cells[label]
            if key:
                a.configure(text=fmt(c[key]))
                b.configure(text=fmt(g[key]))
            elif label.startswith("Best"):
                a.configure(text=f"{money(c['best_trade'])} / {money(c['worst_trade'])}")
                b.configure(text=f"{money(g['best_trade'])} / {money(g['worst_trade'])}")
            elif label.startswith("Today"):
                a.configure(text=f"{c['today_trades']} trades, {money(c['today_net'])}")
                b.configure(text=f"{g['today_trades']} trades, {money(g['today_net'])}")
            elif label == "Open now":
                a.configure(text=f"{c['open_positions']} open, {money(c['floating'])}")
                b.configure(text=f"{g['open_positions']} open, {money(g['floating'])}")
            if cmp_key:
                who = cmp.get(cmp_key, "=")
                l.configure(text={"claude": "◀ Claude", "gpt": "GPT ▶"}.get(who, "="),
                            text_color={"claude": CLAUDE_COLOR, "gpt": GPT_COLOR}.get(who, MUTED))
            else:
                l.configure(text="")
        for sym, (a, b) in self.sym_cells.items():
            a.configure(text=self._sym_text(c["by_symbol"].get(sym)))
            b.configure(text="(GPT does not trade ETH)" if sym == "ETHUSDm" else self._sym_text(g["by_symbol"].get(sym)))
        if cmp["verdict"] == "WAIT":
            need = max(0, MIN_TRADES_FOR_VERDICT - min(c["trades"], g["trades"]))
            self.verdict.configure(text=f"No verdict yet — both need {MIN_TRADES_FOR_VERDICT} trades (at least {need} more)",
                                   text_color=MUTED)
        else:
            name = "Claude Pullback v1" if cmp["verdict"] == "claude" else "GPT Fibonacci & Liquidity Sweep"
            self.verdict.configure(text=f"Leader after {MIN_TRADES_FOR_VERDICT}+ trades each: {name}",
                                   text_color=CLAUDE_COLOR if cmp["verdict"] == "claude" else GPT_COLOR)
