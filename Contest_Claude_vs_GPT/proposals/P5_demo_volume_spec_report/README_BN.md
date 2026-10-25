# P5 — demo verification-এ volume spec রিপোর্ট (GPT ৫-গ)

> **প্রস্তাব — চালু নয়।** চালু প্যাকেজের ফাইল বদলানো হয়নি। লিখিত অনুমোদন ছাড়া প্রতিযোগিতায় ব্যবহার করা যাবে না।
> সব পরীক্ষা নকল broker-এ চালানো হয়েছে; আসল MT5-এ একটাও নয়।

* ফাইল: `demo_verification.py` · SHA-256 `bed38da8690320cb5fe1b9aaab12f7d25956684cdfaebcd16cc9d882b7e47335`
* বদলের জায়গা: `run_checks()` (শুধু তথ্য-লাইন)
* diff: `diff_vs_v5.diff`

GPT-এর lot নিয়ম বদলানো হয়নি (৫-গ)। ডেমো যাচাইয়ে BTCUSDm ও XAUUSDm-এর জন্য দুটো জিনিস দেখানো হয়:
* broker-এর আসল volume spec: min, step, max, contract।
* ৫টা SL দূরত্বে (0.25%, 0.5%, 1%, 2%, আর এই পরীক্ষার নিজের 3%) min lot-এর ঝুঁকি, সেটা ১%-এর মধ্যে আনতে কত balance লাগে, এবং বর্তমান balance-এ তা আঁটে কি না (✓ বা ✗)।

এই অংশ কোনো order পাঠায় না। চালু `demo_verification.py` (v2) বদলানো হয়নি।
