# P1 — order_send None হলে আর পাঠানো নয় (GPT ১-খ)

> **প্রস্তাব — চালু নয়।** চালু প্যাকেজের ফাইল বদলানো হয়নি। লিখিত অনুমোদন ছাড়া প্রতিযোগিতায় ব্যবহার করা যাবে না।
> সব পরীক্ষা নকল broker-এ চালানো হয়েছে; আসল MT5-এ একটাও নয়।

* ফাইল: `gpt_liquidity_fibonacci_scalper_v1.py` · SHA-256 `52050515055a9758ab3a5ce4f802b65721680bb80813a3754fbc1952af9a71bd`
* বদলের জায়গা: `_send_order()`
* diff: `diff_vs_v1_0.diff`

`mt5.order_send()` `None` দিলে order broker-এ পৌঁছেছে কি না জানা যায় না। v1.0 তখন পরের filling mode (IOC, তারপর RETURN) দিয়ে
একই order আবার পাঠায়, তাই একই সংকেতে ২–৩টা পজিশন খুলে যেতে পারে।
P1: প্রথম `None`-এই থামে। আর পাঠায় না, এবং ফেরত দেয়
`{"status": "UNKNOWN", "reason": "ORDER_SEND_NONE", symbol, side, requested_volume, type_filling, magic, last_error, note}`।
এই dict-টাই adapter-এর log-এ যায় (GPT-এর ফাইলে আলাদা logger নেই)।
retcode-ভিত্তিক filling fallback (10030 পেলে পরের mode) আগের মতোই আছে।
