"""
Fault-injection নকল broker — শুধু পরীক্ষার জন্য। আসল MT5 নয়।
sim_mt5.Broker-এর উপর ইচ্ছাকৃত ত্রুটি যোগ করে GPT-এর ১৫টা পরিস্থিতি তৈরি করা হয়।

faults (dict) — যেকোনোটা চালু করা যায়:
  open_returns_none     : নতুন পজিশন খোলে, কিন্তু order_send None ফেরত দেয়
  wrong_order_ticket    : result.order ভুল (অস্তিত্বহীন) নম্বর
  wrong_deal_ticket     : result.deal ভুল নম্বর
  hide_new_positions_n  : নতুন পজিশন প্রথম N বার positions_get-এ দেখা যায় না
  partial_fill          : খোলার সময় অনুরোধের এই অনুপাত পূরণ (যেমন 0.5)
  refuse_close          : position বন্ধের সব request প্রত্যাখ্যান (10018)
  fake_close_ok_n       : প্রথম N টা বন্ধ request DONE দেখায় কিন্তু কিছু বন্ধ করে না
  fake_close_comment    : (ঐচ্ছিক) শুধু এই comment-এর বন্ধ request-এ নকল DONE
  disconnect_after_n    : N টা order_send-এর পর সংযোগ বিচ্ছিন্ন (সব query → None)
  allowed_filling       : শুধু এই filling mode-গুলো গ্রহণ (অন্যগুলো 10030)
  vol_rules             : {symbol: (vmin, step, vmax)}
  stops_level           : {symbol: points}
  no_tick               : {symbols} — tick None
  missing_symbols       : {symbols} — symbol_info None
  raise_on              : {"order_send_n": N, "exc": ExceptionClass} — N-তম order_send-এ exception
  result_no_volume      : খোলার result-এ volume field থাকে না
"""
from types import SimpleNamespace as NS
import sim_mt5 as S


class FaultyBroker(S.Broker):
    def __init__(self, faults=None, **kw):
        super().__init__(**kw)
        self.faults = dict(faults or {})
        self.sends = 0
        self.connected = True
        self.hidden = {}            # ticket -> বাকি কতবার লুকানো
        self.fake_close_left = int(self.faults.get("fake_close_ok_n", 0))

    # ---------- সংযোগ ----------
    def _down(self):
        n = self.faults.get("disconnect_after_n")
        return (not self.connected) or (n is not None and self.sends >= n)

    def last_error(self):
        return (-10004, "No IPC connection") if self._down() else (1, "Success")

    def terminal_info(self):
        return None if self._down() else super().terminal_info()

    def account_info(self):
        return None if self._down() else super().account_info()

    def symbol_info(self, s):
        if self._down() or s in self.faults.get("missing_symbols", ()):
            return None
        si = super().symbol_info(s)
        if si is None:
            return None
        vr = self.faults.get("vol_rules", {}).get(s)
        if vr:
            si.volume_min, si.volume_step, si.volume_max = vr
        sl = self.faults.get("stops_level", {}).get(s)
        if sl is not None:
            si.trade_stops_level = sl
        return si

    def symbol_select(self, s, enable=True):
        return (not self._down()) and s in S.SPEC and s not in self.faults.get("missing_symbols", ())

    def symbol_info_tick(self, s):
        if self._down() or s in self.faults.get("no_tick", ()):
            return None
        return super().symbol_info_tick(s)

    def positions_get(self, symbol=None, ticket=None):
        if self._down():
            return None
        out = []
        for p in super().positions_get(symbol=symbol, ticket=ticket):
            left = self.hidden.get(p.ticket, 0)
            if left > 0:
                self.hidden[p.ticket] = left - 1
                continue
            out.append(p)
        return tuple(out)

    def history_deals_get(self, *a, **k):
        return None if self._down() else super().history_deals_get(*a, **k)

    def history_orders_get(self, *a, **k):
        return None if self._down() else super().history_orders_get(*a, **k)

    # ---------- order ----------
    def order_send(self, req):
        if self._down():
            self.requests.append({"req": dict(req), "time": 0, "target_magic": None, "dropped": "disconnected"})
            return None
        self.sends += 1
        ro = self.faults.get("raise_on")
        if ro and self.sends == ro["order_send_n"]:
            raise ro["exc"]("injected fault")
        allowed = self.faults.get("allowed_filling")
        if allowed is not None and req.get("type_filling") not in allowed and req.get("action") == S.TRADE_ACTION_DEAL:
            self.requests.append({"req": dict(req), "time": 0, "target_magic": None, "rejected": 10030})
            return NS(retcode=10030, order=0, deal=0, comment="Unsupported filling mode")
        is_close = req.get("action") == S.TRADE_ACTION_DEAL and req.get("position")
        if is_close:
            tgt = self.positions.get(req["position"])
            if self.faults.get("refuse_close"):
                self.requests.append({"req": dict(req), "time": 0, "target_magic": getattr(tgt, "magic", None),
                                      "rejected": 10018})
                return NS(retcode=10018, order=0, deal=0, comment="Market closed (injected)")
            only = self.faults.get("fake_close_comment")
            if self.fake_close_left > 0 and (only is None or req.get("comment") == only):
                self.fake_close_left -= 1
                self.requests.append({"req": dict(req), "time": 0, "target_magic": getattr(tgt, "magic", None),
                                      "faked": True})
                return NS(retcode=S.TRADE_RETCODE_DONE, order=self._nt(), deal=self._nt(), comment="done (fake)")
            return super().order_send(req)
        is_open = req.get("action") == S.TRADE_ACTION_DEAL and not req.get("position")
        if is_open and self.faults.get("partial_fill"):
            req = dict(req)
            step = 0.01
            req["volume"] = max(step, round(int(req["volume"] * self.faults["partial_fill"] / step) * step, 8))
        before = set(self.positions)
        r = super().order_send(req)
        if is_open:
            new = [t for t in self.positions if t not in before]
            for t in new:
                if self.faults.get("hide_new_positions_n"):
                    self.hidden[t] = int(self.faults["hide_new_positions_n"])
            if r is not None and self.faults.get("partial_fill") and r.retcode == S.TRADE_RETCODE_DONE:
                r = NS(retcode=S.TRADE_RETCODE_DONE_PARTIAL, order=r.order, deal=r.deal, comment="partial",
                       volume=getattr(r, "volume", None))
            if self.faults.get("result_no_volume") and r is not None:
                r = NS(retcode=r.retcode, order=r.order, deal=r.deal, comment=r.comment)
            if self.faults.get("open_returns_none"):
                return None
            if self.faults.get("wrong_order_ticket") and r is not None:
                r = NS(retcode=r.retcode, order=r.order + 777777, deal=r.deal, comment=r.comment, volume=getattr(r, "volume", None))
            if self.faults.get("wrong_deal_ticket") and r is not None:
                r = NS(retcode=r.retcode, order=r.order, deal=r.deal + 888888, comment=r.comment, volume=getattr(r, "volume", None))
        return r


def install(broker, module):
    S.install(broker, module)
    module.initialize = lambda *a, **k: True
    module.shutdown = lambda: setattr(broker, "shutdown_called", True)
