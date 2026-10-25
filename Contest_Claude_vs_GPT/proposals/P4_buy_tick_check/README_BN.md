# P4 — BUY setup-এ tick None (GPT ৪-খ)

> **প্রস্তাব — চালু নয়।** চালু প্যাকেজের ফাইল বদলানো হয়নি। লিখিত অনুমোদন ছাড়া প্রতিযোগিতায় ব্যবহার করা যাবে না।
> সব পরীক্ষা নকল broker-এ চালানো হয়েছে; আসল MT5-এ একটাও নয়।

* ফাইল: `gpt_liquidity_fibonacci_scalper_v1.py` · SHA-256 `65bfcc49602799b5a6a0cc0628d800244c5f920aefaef30efb339771c6256828`
* বদলের জায়গা: `_setup()` (BUY শাখা, এক লাইন)
* diff: `diff_vs_v1_0.diff`

v1.0-এর BUY শাখায় `float(mt5.symbol_info_tick(symbol).ask)` আছে। tick `None` হলে এখানে exception ওঠে
(adapter তা ধরে রাখে, তবে মূল ফাইলে এটা crash)।
P4: tick `None` হলে `{"signal": "NO_TRADE", "reason": "SKIP_NO_TICK"}` ফেরত দেয় (SELL শাখা যেভাবে করে)। কোনো order যায় না।
শুধু error handling বদলেছে; entry, SL ও TP-এর গণনা একই আছে।
