# P3 — আসল fill volume (GPT ৩-খ)

> **প্রস্তাব — চালু নয়।** চালু প্যাকেজের ফাইল বদলানো হয়নি। লিখিত অনুমোদন ছাড়া প্রতিযোগিতায় ব্যবহার করা যাবে না।
> সব পরীক্ষা নকল broker-এ চালানো হয়েছে; আসল MT5-এ একটাও নয়।

* ফাইল: `gpt_liquidity_fibonacci_scalper_v1.py` · SHA-256 `3c7df70edec920807d5591dbf15caece8a13487a3037c995eddc12097b07c451`
* বদলের জায়গা: `_send_order()` (সফল-ফলের dict)
* diff: `diff_vs_v1_0.diff`

v1.0 সফল হলে `"volume"` হিসেবে অনুরোধ করা volume দেখায়, broker আংশিক পূরণ করলেও (DONE_PARTIAL)।
P3 তিনটা নতুন key যোগ করে:
* `requested_volume` — যা অনুরোধ করা হয়েছিল।
* `filled_volume` — broker result-এর `volume`। result-এ volume না থাকলে বা 0 হলে এর মান `None` হয়; অনুরোধ করা volume-কে কখনো পূরণ ধরে নেওয়া হয় না।
* `fill_status` — `FULL`, `PARTIAL` বা `UNKNOWN_FILL`।

পুরনো `"volume"` key বদলানো হয়নি (অনুরোধ করা volume), যাতে বাকি কোড না ভাঙে।
প্রতিযোগিতার counter আগের মতোই broker-এর deal থেকে আসল volume নেয়।
