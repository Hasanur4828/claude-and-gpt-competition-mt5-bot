# Contest: Claude Pullback v1 বনাম GPT Fibonacci & Liquidity Sweep — চালানোর নির্দেশনা

## ফাইল
| ফাইল | কাজ |
|---|---|
| `claude_pullback_v1.py` | Claude-এর বট (PDF অনুযায়ী, magic 26102401) |
| `gpt_liquidity_fibonacci_scalper_v1.py` | GPT-এর বট — **আসল ফাইল, অপরিবর্তিত** (magic 26102402) |
| `gpt_original_unchanged/` | GPT-এর আসল ফাইলের আলাদা অপরিবর্তিত কপি (তুলনার জন্য; হ্যাশ একই) |
| `gpt_contest_adapter.py` | GPT-কে প্রতিযোগিতায় যুক্ত করার স্তর (GPT-এর ফাইল না বদলে) |
| `contest_counter.py` | MT5 history থেকে দুজনের হিসাব |
| `contest_scoreboard.py` | Scoreboard UI |
| `contest_preflight.py` | শুরুর আগের বাধ্যতামূলক চেক (Hedging, Demo, symbol, GPT হ্যাশ) |
| `contest_runner.py` | আলাদা প্রোগ্রাম — VPS-এ সরাসরি চালানোর জন্য |
| `demo_verification.py` | **v2** — আসল Hedging ডেমোতে স্বয়ংক্রিয় যাচাই (GPT-এর অনুমতির পরে) |
| `verification_journal.py` | পরীক্ষার খাতা `verification_positions.json` (orphan শনাক্ত, counter থেকে বাদ) |
| `DEMO_CHECKLIST_BN.md` | আসল ডেমোর ধাপে ধাপে চেকলিস্ট |
| `GPT_ORIGINAL_SHA256.txt`, `SHA256SUMS.txt` | GPT ফাইলের ও সব ফাইলের হ্যাশ |
| `TEST_REPORT_BN.md` | পরীক্ষার রিপোর্ট v5 (আগেরটা `TEST_REPORT_BN_v4.md`) |
| `proposals/` | GPT v1.1-এর **প্রস্তাব** (দৈনিক-লস সময়-সংশোধন) — চালু নয়, GPT-এর সিদ্ধান্তের অপেক্ষায় |
| `tests/` | সব পরীক্ষা ও তার ফলাফল (নকল ডেটা) |

## VPS-এ চালানো (প্রথমে শুধু DEMO)
1. MT5 খুলে **Hedging DEMO** অ্যাকাউন্টে login করুন। টুলবারে **Algo Trading** চালু করুন।
2. Python 3.11 বা 3.12 (MetaTrader5 প্যাকেজের জন্য নিরাপদ)। Command Prompt-এ:
   `pip install -r requirements.txt`
3. **GPT-এর অনুমতির পরে** যাচাই: `python demo_verification.py` → `YES` → শেষে "FAIL 0 · URGENT 0" হতে হবে (`DEMO_CHECKLIST_BN.md`)। পরীক্ষার ট্রেড নিজে থেকেই প্রতিযোগিতার হিসাব থেকে বাদ যায়।
4. তারপর: `python contest_runner.py`
5. Scoreboard ট্যাবে **Preflight** চাপুন — সব সবুজ হতে হবে।
6. **Start / Reset** চাপুন (প্রতিযোগিতার শুরু চিহ্নিত হবে), তারপর উপরে **▶ Start contest bots**।
7. ১–২ দিন পর **Export CSV** করে MT5-এর History-র সাথে মিলিয়ে দেখুন।

## মনে রাখবেন
* একই অ্যাকাউন্টে আপনার মূল সফটওয়্যারের সব strategy বন্ধ রাখুন।
* প্রতিযোগিতার মাঝে কোনো ফাইল বদলাবেন না। বদলালে Reset করে নতুন করে শুরু।
* Stop চাপলে খোলা ট্রেড broker-এ নিজের SL/TP নিয়ে থাকে; Claude-এর TP1/time stop আবার Start না করা পর্যন্ত চলবে না।
