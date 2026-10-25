# আসল Hedging DEMO-তে যাচাইয়ের চেকলিস্ট (প্রতিযোগিতা শুরুর আগে)

প্রতিটা ধাপ শেষে টিক দিন। কোনোটা ব্যর্থ হলে প্রতিযোগিতা শুরু করবেন না — ফলাফল Claude-কে পাঠান।

## ক. প্রস্তুতি
- [ ] VPS-এ MT5 খোলা, **Hedging DEMO** অ্যাকাউন্টে login, টুলবারে **Algo Trading** সবুজ
- [ ] Python 3.11/3.12, `pip install -r requirements.txt`
- [ ] Market Watch-এ `BTCUSDm`, `ETHUSDm`, `XAUUSDm` দেখা যায়
- [ ] আপনার মূল সফটওয়্যার এই অ্যাকাউন্টে বন্ধ (বা তার সব strategy বন্ধ)

## খ. স্বয়ংক্রিয় যাচাই (শুধু GPT-এর অনুমতির পরে)
- [ ] `python demo_verification.py` → `YES` লিখুন
- [ ] শেষে **"FAIL 0 · URGENT 0"** এসেছে
- [ ] `verification_positions.json` তৈরি হয়েছে (মুছবেন না — counter এটা দিয়ে পরীক্ষা-ট্রেড বাদ দেয়)
- [ ] `demo_verification_report.txt`, `demo_verification_log.txt` ও `verification_positions.json` Claude/GPT-কে পাঠিয়েছেন (server offset, symbol তথ্য, সব PASS/FAIL এতে আছে)
- [ ] MT5-এ কোনো পরীক্ষা-পজিশন খোলা নেই (Trade ট্যাব খালি)

## গ. প্রতিযোগিতা শুরু
- [ ] `python contest_runner.py`
- [ ] Scoreboard → **Preflight** সবুজ
- [ ] **Start / Reset** (এতে পরীক্ষা-ট্রেড বাদ পড়ে)
- [ ] **▶ Start contest bots**

## ঘ. প্রথম ১–২ দিনে
- [ ] Log ট্যাবে প্রতি ১৫ মিনিটে Claude-এর প্রতি symbol-এ এক লাইন আসছে
- [ ] GPT-এর লাইন আসছে (NO_RECENT_BOS, WAIT_FIB_SWEEP_CONFIRM ইত্যাদি স্বাভাবিক)
- [ ] কোনো `LOOP ERROR` বা `order failed` নেই (থাকলে লাইনটা পাঠান)
- [ ] Gold-এর জন্য `SKIP_NEWS_UNAVAILABLE` বারবার আসছে কি না দেখুন (এলে নিউজ ফিড VPS থেকে আসছে না)

## ঙ. Restart পরীক্ষা (হাতে)
- [ ] Claude-এর একটা ট্রেড খোলা থাকা অবস্থায় Runner বন্ধ করুন, ১ মিনিট পরে আবার চালু করে Start চাপুন
- [ ] Scoreboard-এর সংখ্যা আগের মতোই
- [ ] সেই ট্রেড পরে TP1 / time stop / SL-এ ঠিকমতো শেষ হয়েছে, Log-এ "closed #…" এসেছে

## চ. হিসাব মেলানো
- [ ] ১–২ দিন পর **Export CSV**
- [ ] MT5 → History ট্যাব → প্রতিটা Position নম্বর CSV-তে আছে, লাভ-লস মেলে, কোনোটা দুবার নেই
- [ ] Personal বা পরীক্ষা-ট্রেড CSV-তে নেই

সব টিক হলে তবেই বলা যাবে: "আসল ডেমোতে যাচাই সম্পন্ন"।
