"""নকল MetaTrader5 — শুধু counter আর UI পরীক্ষার জন্য।"""
from types import SimpleNamespace as NS
from datetime import datetime, timezone

ORDER_TYPE_BUY, ORDER_TYPE_SELL = 0, 1
DEALS, ORDERS, POSITIONS = [], [], []
BALANCE = 1000.0
_tk = [1000]


def _t():
    _tk[0] += 1
    return _tk[0]


def add_trade(magic, symbol, side, net_parts, open_ts, close_ts, reason=4, price=100.0, vol=10.0,
              sl_dist=1.0, close_magic=None):
    """একটা সম্পূর্ণ ট্রেড যোগ করে। net_parts = প্রতিটা বন্ধ deal-এর লাভ (partial close হলে একাধিক)।"""
    pid = _t()
    typ = 0 if side == "BUY" else 1
    sl = price - sl_dist if side == "BUY" else price + sl_dist
    ORDERS.append(NS(position_id=pid, time_setup_msc=open_ts * 1000, sl=sl))
    DEALS.append(NS(ticket=_t(), position_id=pid, magic=magic, symbol=symbol, entry=0, type=typ,
                    volume=vol, price=price, profit=0.0, commission=0.0, swap=0.0, fee=0.0,
                    time=open_ts, time_msc=open_ts * 1000, reason=0))
    for i, p in enumerate(net_parts):
        ts = close_ts - (len(net_parts) - 1 - i) * 60
        DEALS.append(NS(ticket=_t(), position_id=pid, magic=magic if close_magic is None else close_magic,
                        symbol=symbol, entry=1, type=1 - typ, volume=vol / len(net_parts), price=price,
                        profit=p, commission=0.0, swap=0.0, fee=0.0, time=ts, time_msc=ts * 1000,
                        reason=reason if i == len(net_parts) - 1 else 3))
    return pid


def add_open(magic, symbol, profit):
    POSITIONS.append(NS(identifier=_t(), magic=magic, symbol=symbol, profit=profit, swap=0.0))


def history_deals_get(a, b):
    lo, hi = a.timestamp(), b.timestamp()
    return tuple(d for d in DEALS if lo <= d.time <= hi)


def history_orders_get(position=None):
    return tuple(o for o in ORDERS if o.position_id == position)


def positions_get(symbol=None):
    return tuple(POSITIONS)


def account_info():
    return NS(balance=BALANCE)


def order_calc_profit(otype, symbol, volume, price, sl):
    diff = (sl - price) if otype == ORDER_TYPE_BUY else (price - sl)
    return diff * volume          # contract size 1


def symbol_info_tick(s):
    return None
