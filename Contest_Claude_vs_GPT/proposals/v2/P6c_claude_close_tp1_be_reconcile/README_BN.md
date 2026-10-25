# P6c — Claude বট: বন্ধ-যাচাই + TP1 অবস্থা + BE retry + state মেলানো

> **প্রস্তাব — চালু নয়।** চালু ফাইল বদলানো হয়নি। লিখিত অনুমোদন ছাড়া প্রতিযোগিতায় ব্যবহার করা যাবে না।
> সব পরীক্ষা নকল broker-এ হয়েছে; আসল MT5 বা ডেমোতে একটাও নয়।

* ফাইল: `claude_pullback_v1.py` · SHA-256 `d10f490a9609694fb5c9a6174bd5bb43ac543beb2caba2e9e3174c3976ef1c24`
* diff: `diff_vs_active_v5.diff` (চালু v5-এর সাথে), `diff_vs_P6b.diff` (আগের প্রস্তাবের সাথে)

P6b-এর সব অংশ আছে: বন্ধের পরে আবার যাচাই, TP1 অবস্থা আগেই লেখা, SL→BE ব্যর্থ হলে সর্বোচ্চ ৫ বার আবার চেষ্টা। এর সাথে যোগ হয়েছে:
* **TP1 মেলানো:** state-এ `tp1_partial = unconfirmed` থাকলেও যদি পজিশনের volume মূল lot-এর চেয়ে কম দেখা যায়, তাহলে ধরা হয় আংশিক বন্ধ হয়েছিল → `ok (reconciled)`। এটা restart-এর পরেও কাজ করে।
* **নিজের অজানা পজিশন গ্রহণ (adoption):**
  * কখন লাগে: entry-তে `order_send` None দিয়েছিল অথচ order খুলেছে, অথবা order-এর পরে state লেখার আগেই প্রোগ্রাম বন্ধ হয়েছিল।
  * কী করে: broker-এ Claude-এর (magic 26102401, Claude-এর symbol) এমন পজিশন যা state-এ নেই, সেটা state-এ নেওয়া হয়।
    entry ও SL আসে broker থেকে, তা থেকে 1R ও TP1 হিসাব হয়। SL আগেই BE-তে থাকলে `tp1_done` ধরা হয়।
    phase হয় IN_TRADE, সাথে WARNING log ও notify।
  * কী করে না: কোনো order পাঠায় না। GPT বা অন্য magic-এর পজিশন কখনো নেয় না। MT5 None দিলে কিছুই বদলায় না।

কৌশল (entry, SL, TP, lot) বদলায়নি।
