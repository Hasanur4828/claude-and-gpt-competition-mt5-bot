# G2 — GPT core v2: H + P1r + P2r + P3r + P4r একসাথে

> **প্রস্তাব — চালু নয়।** চালু ফাইল বদলানো হয়নি। লিখিত অনুমোদন ছাড়া প্রতিযোগিতায় ব্যবহার করা যাবে না।
> সব পরীক্ষা নকল broker-এ হয়েছে; আসল MT5 বা ডেমোতে একটাও নয়।

* ফাইল: `gpt_liquidity_fibonacci_scalper_v1.py` · SHA-256 `64308ee75bd727de0ffcc7ecc12e07a8f92809c78c6f643513a6fea544d7064a`
* diff: `diff_vs_active_v1_0.diff` (চালু v1.0-এর সাথে), `diff_vs_COMBINED_v1.diff` (আগের প্রস্তাবের সাথে)

চালু v1.0-এর মাত্র ১১টা লাইন বাদ গেছে বা বদলেছে। বাকি সব যোগ করা লাইন। কৌশলের কোনো parameter (entry, SL, TP, lot, session, ২-লস নিয়ম) বদলায়নি।

* **[H] `_has_position()`** — `True` মানে পজিশন আছে, `False` মানে query ঠিকঠাক চলেছে কিন্তু পজিশন নেই, `None` মানে query ব্যর্থ (অবস্থা অজানা)।
  `None` হলে `evaluate_symbol` ফেরত দেয় `SKIP_POSITION_STATE_UNKNOWN`, সাথে `last_error`। সেই চক্রে কোনো order যায় না।
* **[P1r] `order_send` None বা অনিশ্চিত retcode (10012 timeout, 10031 connection)**
  * অন্য filling mode দিয়ে আর পাঠানো হয় না।
  * পাঠানোর আগে একটা snapshot নেওয়া হয়: নিজের পজিশন আর সবচেয়ে বড় deal ticket। এই query ব্যর্থ হলে order পাঠানোই হয় না।
  * অনিশ্চিত ফল এলে পজিশন ও deal history মিলিয়ে দেখা হয় (reconcile):
    * পাওয়া গেলে status `OPENED_RECONCILED`, সাথে আসল পূরণ হওয়া volume।
    * না পেলে status `UNKNOWN`, আর ওই symbol-এ নতুন order বন্ধ (block)।
  * পরের প্রতিটা চক্রে আবার মেলানো হয়:
    * পাওয়া গেলে `RESOLVED_OPENED`।
    * সব query ঠিক থাকলে, ≥৬০ সেকেন্ড পরেও কিছু না পেলে `RESOLVED_NOT_EXECUTED`।
    * query ব্যর্থ হলে block থেকেই যায়।
  * block ফাইলে (`gpt_exec_unknown_state.json`, module-এর পাশে) atomic ভাবে লেখা হয়, তাই **restart-এর পরেও থাকে**।
    ফাইল নষ্ট হলে `SKIP_EXEC_STATE_UNREADABLE` — ফাইল পরীক্ষা না করা পর্যন্ত কোনো order নয়।
* **[P2r] দৈনিক লস**
  * server offset নেওয়া হয় শুধু তাজা tick (≤ ৫ মিনিট) থেকে।
  * কোনো তাজা tick নেই বা tick-গুলো আলাদা offset দেখায় → `None`। offset কখনো অনুমান করা হয় না।
  * deal history বা account পাওয়া না গেলেও `None`।
  * `None` হলে `SKIP_DAILY_LOSS_UNKNOWN`, নতুন entry বন্ধ।
* **[P3r] fill volume** — broker-এর deal record (`history_deals_get(ticket=deal)`) থেকে নেওয়া হয়। না পেলে result-এর volume। তাও না পেলে `UNKNOWN_FILL`।
  ফলে আছে `fill_source` ও `position_id`। পুরনো `"volume"` key আগের মতোই অনুরোধ করা volume।
* **[P4r] tick**
  * BUY setup-এ tick None → `SKIP_NO_TICK` (আগের P4)।
  * `_send_order`-এ: bid ≤ 0, ask ≤ 0 বা ask < bid → `SKIP_INVALID_TICK`।
  * tick ১২০ সেকেন্ডের বেশি পুরনো → `SKIP_STALE_TICK`।
  * offset অজানা বলে tick-এর বয়স মাপা যায় না → `SKIP_TICK_AGE_UNKNOWN`।

**A1 adapter-এর সাথে একসাথেই চালু করতে হবে।** চালু adapter MT5 None পেলে "পজিশন নেই" বলে দেয়, তাই G2 সেটা দেখতেই পায় না।
