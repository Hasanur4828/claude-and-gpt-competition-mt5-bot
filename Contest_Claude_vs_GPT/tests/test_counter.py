import sys, json
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, sys.argv[2])
from datetime import datetime, timezone, timedelta
import fake_mt5 as F
import contest_counter as C
C.mt5 = F

now = datetime.now(timezone.utc)
start = now - timedelta(days=5)
T = lambda h: int((start + timedelta(hours=h)).timestamp())
CL, GP = C.CLAUDE_MAGIC, C.GPT_MAGIC

# শুরুর আগের ট্রেড — গোনা যাবে না
F.add_trade(CL, "BTCUSDm", "BUY", [50.0], int((start - timedelta(hours=3)).timestamp()),
            int((start - timedelta(hours=2)).timestamp()))
START_TICKET = max(d.ticket for d in F.DEALS)          # প্রতিযোগিতা শুরু = এই মুহূর্তের শেষ deal
# Claude
F.add_trade(CL, "BTCUSDm", "BUY", [-10.0], T(1), T(2), reason=4)                    # SL  −1R
F.add_trade(CL, "BTCUSDm", "BUY", [5.0, -0.3], T(3), T(5), reason=0)                # TP1 + BE  +0.47R
F.add_trade(CL, "XAUUSDm", "SELL", [5.0, 12.5], T(6), T(9), reason=5)               # TP1 + TP2 +1.75R
F.add_trade(CL, "ETHUSDm", "BUY", [-3.0], T(10), T(14), reason=0)                   # time stop −0.3R
F.add_trade(CL, "BTCUSDm", "SELL", [5.0, -5.5], T(15), T(18), reason=4, close_magic=0)  # −0.05R = BE; SL deal magic 0
# GPT
F.add_trade(GP, "BTCUSDm", "BUY", [20.0], T(1), T(4), reason=5)
F.add_trade(GP, "XAUUSDm", "SELL", [-10.0], T(5), T(6), reason=4)
F.add_trade(GP, "XAUUSDm", "SELL", [-10.0], T(7), T(8), reason=4)
F.add_trade(GP, "BTCUSDm", "BUY", [20.0], T(9), T(12), reason=5)
# Personal (অন্য magic) — উপেক্ষিত
F.add_trade(12345, "BTCUSDm", "BUY", [99.0], T(2), T(3))
# খোলা ট্রেড
F.add_open(GP, "BTCUSDm", 3.0)
F.add_open(12345, "XAUUSDm", 7.0)

rep = C.ContestCounter(START_TICKET).report()
c, g = rep["claude"], rep["gpt"]
fails = []
def check(name, got, exp, tol=1e-6):
    ok = (got == exp) or (isinstance(exp, float) and got is not None and abs(got - exp) < tol)
    print(("OK  " if ok else "FAIL"), name, got, "expected", exp)
    if not ok: fails.append(name)

check("claude trades", c["trades"], 5)
check("claude wins", c["wins"], 2)
check("claude losses", c["losses"], 2)
check("claude BE", c["breakeven"], 1)
check("claude net", round(c["net_profit"], 2), 8.7)
check("claude PF", c["profit_factor"], 22.2 / 13.5, 1e-3)
check("claude totalR", round(c["total_r"], 4), 0.87)
check("claude avgR", c["avg_r"], 0.174, 1e-4)
check("claude maxDD", round(c["max_drawdown"], 2), 10.0)
check("claude consec L", c["max_consec_losses"], 1)
check("claude streak", c["current_streak"], "1L")
check("claude win_rate", c["win_rate"], 40.0)
check("claude ETH symbol trades", c["by_symbol"]["ETHUSDm"]["trades"], 1)
check("gpt trades", g["trades"], 4)
check("gpt wins", g["wins"], 2)
check("gpt losses", g["losses"], 2)
check("gpt net", round(g["net_profit"], 2), 20.0)
check("gpt PF", g["profit_factor"], 2.0)
check("gpt avgR", g["avg_r"], 0.5)
check("gpt maxDD", round(g["max_drawdown"], 2), 20.0)
check("gpt consec L", g["max_consec_losses"], 2)
check("gpt streak", g["current_streak"], "1W")
check("gpt open", g["open_positions"], 1)
check("gpt floating", g["floating"], 3.0)
check("claude open", c["open_positions"], 0)
check("verdict waits (<50)", rep["compare"]["verdict"], "WAIT")
check("lead net", rep["compare"]["net_profit"], "gpt")
check("lead DD (lower better)", rep["compare"]["max_drawdown"], "claude")
check("exit reasons GPT", sorted(t["exit_reason"] for t in rep["trades"]["gpt"]), ["SL", "SL", "TP", "TP"])
check("claude per-symbol BTC trades", c["by_symbol"]["BTCUSDm"]["trades"], 3)
check("claude per-symbol BTC net", round(c["by_symbol"]["BTCUSDm"]["net_profit"], 2), -5.8)
check("claude per-symbol GOLD PF", c["by_symbol"]["XAUUSDm"]["profit_factor"], float("inf"))
check("gpt per-symbol GOLD losses", g["by_symbol"]["XAUUSDm"]["losses"], 2)
check("gpt per-symbol BTC win_rate", g["by_symbol"]["BTCUSDm"]["win_rate"], 100.0)
check("claude gross profit", round(c["gross_profit"], 2), 22.2)
check("claude gross loss", round(c["gross_loss"], 2), 13.5)
check("pre-start trade excluded (no +50)", all(t["net"] != 50.0 for t in rep["trades"]["claude"]), True)
F.DEALS.extend(list(F.DEALS))                                   # সব deal দুবার
rep2 = C.ContestCounter(START_TICKET).report()
check("duplicate deals -> same claude trades", rep2["claude"]["trades"], 5)
check("duplicate deals -> same gpt net", round(rep2["gpt"]["net_profit"], 2), 20.0)

common = C.ContestCounter(START_TICKET, symbols_filter={"BTCUSDm", "XAUUSDm"}).report()
check("common-only claude trades (no ETH)", common["claude"]["trades"], 4)

print("\nRESULT:", "ALL PASS" if not fails else f"{len(fails)} FAILED: {fails}")
json.dump(rep, open(sys.argv[3], "w"), ensure_ascii=False, indent=1, default=str)
