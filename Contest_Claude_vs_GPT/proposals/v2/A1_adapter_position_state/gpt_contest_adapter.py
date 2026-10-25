"""
GPT Fibonacci & Liquidity Sweep — প্রতিযোগিতা মোডের adapter
==============================================================
GPT-এর আসল ফাইল (gpt_liquidity_fibonacci_scalper_v1.py) এক অক্ষরও বদলানো হয়নি।
এই adapter শুধু দুটো integration-নিয়ম যোগ করে, GPT-এর ট্রেডিং লজিকে হাত দেয় না:

1. পজিশন চেক: GPT-এর মূল কোড ওই symbol-এ *যেকোনো* পজিশন থাকলে ট্রেড আটকায়।
   প্রতিযোগিতায় তাতে Claude-এর পজিশন GPT-কে আটকে দিত (আর উল্টোটাও) — অন্যায্য।
   এখানে: নিজের (GPT) পজিশন থাকলে আটকাবে, Claude-এর পজিশন উপেক্ষা করবে,
   অন্য যেকোনো strategy-র (Personal ইত্যাদি) পুরনো পজিশন থাকলে আটকাবে।
2. নিরাপত্তা: কোনো symbol-এ অপ্রত্যাশিত error হলে পুরো সফটওয়্যার crash না করে
   সেটা log-এ ফেরত দেয় (মূল কোডে BUY-এর সময় tick None হলে crash হতে পারত)।
3. [A1 প্রস্তাব] MT5 positions_get() None দিলে (API/সংযোগ error) "পজিশন নেই" ধরা হয় না:
   _has_position() None ফেরত দেয় = অবস্থা অজানা। GPT core v2 (G2) তখন এই চক্রে order দেয় না
   (SKIP_POSITION_STATE_UNKNOWN)। এই adapter শুধু G2-এর সাথে একসাথে চালু করতে হবে।
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import MetaTrader5 as mt5

from gpt_liquidity_fibonacci_scalper_v1 import GPTLiquidityFibonacciScalper, MAGIC as GPT_MAGIC

CLAUDE_MAGIC = 26102401
DISPLAY_NAME = "GPT Fibonacci & Liquidity Sweep"


class GPTContestAdapter(GPTLiquidityFibonacciScalper):
    def _has_position(self, symbol: str) -> Optional[bool]:
        positions = mt5.positions_get(symbol=symbol)
        if positions is None:
            return None                     # [A1] query ব্যর্থ = অবস্থা অজানা, "পজিশন নেই" নয়
        for p in positions:
            if p.magic == CLAUDE_MAGIC:
                continue                    # প্রতিযোগীর পজিশন — উপেক্ষা
            return True                     # নিজের বা অন্য কোনো strategy-র পজিশন — আটকাও
        return False

    def evaluate_symbol(self, symbol: str) -> Dict[str, Any]:
        try:
            return super().evaluate_symbol(symbol)
        except Exception as e:              # crash নয়, log-এ কারণ
            return {"signal": "NO_TRADE", "reason": f"ERROR_{type(e).__name__}", "detail": str(e),
                    "symbol": symbol}

    def run_contest_once(self, active_strategy: str) -> List[Dict[str, Any]]:
        """সফটওয়্যারের loop থেকে প্রতি সেকেন্ডে ডাকুন।
        শুধু active_strategy == 'contest' হলেই আসল order যাবে।"""
        if active_strategy != "contest":
            return []
        outs = self.run_once(execute=True)
        for o in outs:
            o.setdefault("engine", "GPT_LIQUIDITY_FIBONACCI")
        return outs
