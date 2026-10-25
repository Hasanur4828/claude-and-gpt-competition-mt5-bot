# পরীক্ষার রিপোর্ট — Claude Pullback v1 বনাম GPT Fibonacci & Liquidity Sweep

তারিখ: ২৫ অক্টোবর ২০২৬ · প্রস্তুত করেছে: Claude · **ZIP v4**

> **সবচেয়ে গুরুত্বপূর্ণ:** এখানকার সব পরীক্ষা **নকল (simulated) broker ও নকল ডেটায়**।
> **আসল MT5 / Hedging ডেমোতে একটাও পরীক্ষা হয়নি** (আমার কাজের কম্পিউটার Linux, MetaTrader5 প্যাকেজ শুধু
> Windows-এ চলে, আপনার অ্যাকাউন্টে আমার প্রবেশাধিকার নেই)।
> **কোনো বটকে বিজয়ী, বা সফটওয়্যারকে বাস্তব ব্যবহারের জন্য সম্পূর্ণ প্রস্তুত — ঘোষণা করা হচ্ছে না।**
> নকল ডেটার লাভ-লস আসল লাভ নয়।

---

## ১. GPT-এর সিদ্ধান্ত অনুযায়ী অবস্থা

| GPT-এর শর্ত | অবস্থা |
|---|---|
| Adapter: শুধু Claude-এর 26102401 উপেক্ষা; নিজের/অন্য strategy-র পজিশনে মূল নিয়ম | ✅ `gpt_contest_adapter.py` |
| GPT শুধু নিজের 26102402 পরিচালনা করবে, Claude-এর ট্রেডে হাত দেবে না | ✅ GPT কোনো পজিশন নিজে বন্ধ/বদল করে না; নকল broker-এ সব request পরীক্ষা — লঙ্ঘন ০ |
| মূল ফাইল এক অক্ষরও বদলাবে না; আলাদা অপরিবর্তিত সংস্করণ রাখবে | ✅ চালু ফাইল ও `gpt_original_unchanged/`-এর কপি — দুটোই SHA-256 `4d41a0ea…bd81160`, পাঠানো ফাইলের সাথে byte-by-byte এক |
| Adapter ও অন্য integration আলাদা ফাইলে | ✅ adapter, counter, scoreboard, preflight, runner, verification — সব আলাদা |
| SHA-256 যাচাই চালু | ✅ preflight প্রতিবার; v1.1 বসালে প্রতিযোগিতা আটকে দেয় (পরীক্ষিত) |
| v1.1: বদল শুধু `_daily_loss_count()` + server-time helper; entry/SL/TP/risk/strategy অপরিবর্তিত | ✅ AST দিয়ে প্রমাণিত (অংশ ৪); import-ও বদলায়নি |
| v1.1 এখনই অনুমোদিত নয় | ✅ শুধু `proposals/`-এ; চালু নয় |
| v1.0 ও v1.1-এর আচরণ, সীমাবদ্ধতা, সব পরীক্ষার ফল নথিভুক্ত | ✅ অংশ ৪ ও `proposals/README_PROPOSAL_BN.md` |
| ZIP-এ diff, demo_verification.py, TEST_REPORT সম্পূর্ণ | ✅ |
| demo_verification: বন্ধ ব্যর্থ হলে স্পষ্ট সতর্কতা ও log; শুধু Demo Hedging | ✅ অংশ ৫ |
| নিউজ ফিল্টার যোগ হবে না | ✅ |
| প্রতিযোগিতা শুরুর পর কৌশল বদল নয় | ✅ নিয়ম হিসেবে নথিভুক্ত; preflight হ্যাশ এটা কার্যকর করে |

---

## ২. সব পরীক্ষা (সব নকল)

| # | পরীক্ষা | ফাইল | ফল |
|---|---|---|---|
| ১ | Counter unit test | `tests/test_counter.py` | **৪০/৪০** |
| ২ | দুই বট একসাথে, একই নকল Hedging অ্যাকাউন্ট ও ডেটা (৪,২৯৮ M15 ≈ ৪৫ দিন, server UTC+3) — GPT v1.0 | `tests/run_contest_sim.py` | নিচে ২ক |
| ২খ | একই সিমুলেশন GPT v1.1 দিয়ে | একই | GPT ও Claude-এর ট্রেড v1.0-এর সাথে হুবহু এক; লঙ্ঘন ০ |
| ৩ | GPT দৈনিক-লস সময়-পরীক্ষা v1.0 বনাম v1.1 | `tests/test_gpt_daily_loss_timing.py` | অংশ ৪ |
| ৪ | v1.1 পরিসর-প্রমাণ (AST) | `tests/verify_v11_scope.py` | শুধু অনুমোদিত দুই ফাংশন ✅ |
| ৫ | `demo_verification.py` ৭টা নকল পরিস্থিতিতে | `tests/test_demo_verification_on_sim.py` | ৭/৭ প্রত্যাশিত আচরণ (অংশ ৫) |
| ৬ | Contest Runner চালু | `tests/smoke_runner.py` | preflight ১১/১১, loop error ০ |
| ৭ | Scoreboard UI | `tests/ui_from_sim.py` | ছবি `results/ui_sim_*.png` |
| ৮ | সব Python ফাইল compile | — | পাস |

### ২ক. দুই-বট সিমুলেশনের বিস্তারিত (GPT v1.0)
| যাচাই | ফল |
|---|---|
| order request / বন্ধ-বা-বদল request | ৫২ / ২৩ |
| **অন্যের পজিশন বন্ধ/বদল** | **০** ✅ |
| অচেনা magic · প্রতি বট প্রতি symbol >১ · Claude-এর BTC+ETH একসাথে | ০ · ০ · ০ ✅ |
| **Claude আটকেছে শুধু GPT-এর পজিশনে** | **০** ✅ |
| **GPT আটকেছে শুধু Claude-এর পজিশনে** | **০** (এমন অবস্থা ১১৯ বার; মূল কোড একা থাকলে প্রতিবার আটকাত) ✅ |
| পজিশন: Claude / GPT | ১৮ / ১১ |
| ঝুঁকি >১% · SL/TP ভুল দিকে · GPT TP ≠ 2R | ০ · ০ · ০ ✅ |
| Claude: TP1 আংশিক / breakeven / time stop / max-hold | ১০ / ১০ / ২ / ১ ✅ |
| **Counter বনাম broker-এর আসল হিসাব** | **হুবহু মিল** (position, সংখ্যা, নিট, symbol অনুযায়ী) ✅ |
| সব deal দুবার দিলে | একই ফল — দ্বিগুণ গণনা নেই ✅ |
| Server UTC-র ২.৫ ঘণ্টা আগে | সাম্প্রতিক ট্রেড গোনা হয় ✅ |
| Restart (দুই বটের ট্রেড খোলা অবস্থায়) | Claude-এর ট্রেড ফেরত, পরে নতুন বট বন্ধ ও হিসাব করেছে; counter অপরিবর্তিত ✅ |
| Preflight: Hedging ডেমো / Netting / আসল | পাস / ব্যর্থ ✅ / ব্যর্থ ✅ |
| Netting প্রদর্শনী | GPT-এর SELL Claude-এর BUY বন্ধ করে → Netting-এ নিরাপত্তা অসম্ভব |

---

## ৩. আসল MT5 বনাম নকল

| বিষয় | আসল MT5 ডেমো | নকল |
|---|---|---|
| উপরের সব পরীক্ষা | ❌ | ✅ |
| আসল broker-এর order গ্রহণ, filling, requote, slippage | ❌ | নকল broker সব গ্রহণ করে |
| আসল server time offset | ❌ | নকল offset |
| ForexFactory নিউজ (Claude-এর Gold) | ❌ | নকল নিউজ |

**আসল MT5-এ পরীক্ষা: ০টা।**

---

## ৪. GPT v1.0 বনাম প্রস্তাবিত v1.1 (দৈনিক ২-লস গণনা)

**পরিসর (AST):** ২৯টা অংশ হুবহু এক — সব import, `StrategyConfig`, `MAGIC`, `_setup` (entry), `_calc_lot` (risk),
`_send_order` (SL/TP/order), `_trend`, `_session_allowed`, `_has_position`, `evaluate_symbol`, `run_once` ইত্যাদি।
বদল: শুধু `_daily_loss_count`; যোগ: শুধু `_server_offset_seconds`।

| পরীক্ষা | v1.0 (চালু) | v1.1 (প্রস্তাব) |
|---|---|---|
| ৪৮টা পরিস্থিতি (offset −৫…+১০h) | **১৪/৪৮** | **৪৮/৪৮** |
| offset ০-তে | ৮/৮ | ৮/৮, হুবহু এক |
| offset ≠ ০ | ৬/৪০ | ৪০/৪০ |
| offset অজানা (২৪টা) | — | কখনো কম নয়; ১২টায় বেশি (আগে থামে) |
| পূর্ণ সিমুলেশনে ট্রেড | ১১টা | একই ১১টা (এই সময়ে সীমা লাগেনি — সংশোধনের প্রমাণ নয়) |

হ্যাশ: v1.0 `4d41a0ea7e75176002f1fc90a1530f77893c47e964f1420f91c1ba58bdd81160` ·
v1.1 (প্রস্তাব) `3556dd076812f5293d5b127ccecf5686dda6e7f692af0b07c4a2df6f285efd17`
সীমাবদ্ধতা ও সম্পূর্ণ বিবরণ: `proposals/README_PROPOSAL_BN.md`, পার্থক্য: `proposals/gpt_v1_to_v1_1.diff`।

**সুপারিশ:** আগে `demo_verification.py` দিয়ে আসল broker-এর offset জানুন। offset ০ হলে v1.0-ই সঠিক।

---

## ৫. `demo_verification.py`-এর নিরাপত্তা (GPT কোড দেখে নেবে)

* **কঠোর গার্ড, কোনো order-এর আগে:** DEMO না হলে থামে · HEDGING না হলে থামে · প্রতিযোগিতার পজিশন খোলা থাকলে থামে · তারপর `YES` লেখা ছাড়া চলে না।
* শুধু **নিজের খোলা** পরীক্ষা-পজিশন (ticket তালিকা) বন্ধ করে, **তার নিজের magic দিয়ে**; অন্য কারো পজিশনে হাত দেয় না।
* **`try/finally`:** error হলেও শেষে cleanup সবসময় চলে; প্রতি পজিশনে ৩ বার চেষ্টা × ৩ filling mode, প্রতিটা চেষ্টার retcode ও `last_error` log-এ।
* **বন্ধ ব্যর্থ হলে:** console, log ও report-এ বড় `!!` সতর্কবার্তা — ticket, symbol, দিক, lot, magic, হাতে বন্ধের নির্দেশ, "প্রতিযোগিতা শুরু করবেন না"।
* প্রতিটা কাজ সময়সহ `demo_verification_log.txt`-এ।

**৭টা নকল পরিস্থিতির ফল:**
| পরিস্থিতি | ফল |
|---|---|
| ১ স্বাভাবিক Hedging ডেমো | সব পাস, শেষে ০ পজিশন খোলা ✅ |
| ২ Netting | গার্ডে থামে, **০টা order** ✅ |
| ৩ আসল অ্যাকাউন্ট | গার্ডে থামে, **০টা order** ✅ |
| ৪ প্রতিযোগিতার পজিশন আগে থেকে খোলা | গার্ডে থামে, ০টা order, সেই পজিশন অক্ষত ✅ |
| ৫ broker সব close প্রত্যাখ্যান করে | ব্যর্থ ঘোষণা, ২টা ticket-সহ বড় সতর্কবার্তা, সব চেষ্টা log-এ ✅ |
| ৬ মাঝপথে crash | error রেকর্ড, cleanup দুটো পজিশনই বন্ধ করেছে ✅ |
| ৭ একই symbol-এ Personal-এর পজিশন | সেটা অক্ষত, পরীক্ষা পাস ✅ |

---

## ৬. GPT-এর মূল কোড অপরিবর্তিত — যাচাই
* পাঠানো ফাইল বনাম চালু ফাইল বনাম `gpt_original_unchanged/` কপি: `cmp` এক, `diff` পার্থক্য নেই।
* SHA-256 `4d41a0ea…bd81160` — সব পরীক্ষার আগে ও পরে এক; `SHA256SUMS.txt`।
* পরীক্ষায় নকল ঘড়ির জন্য GPT module-এর `datetime` নাম শুধু **মেমরিতে** বদলানো — ফাইলে কিছু লেখা হয়নি।

---

## ৭. আসল ডেমোতে যা বাকি
| বিষয় | কীভাবে | অবস্থা |
|---|---|---|
| Preflight, অ্যাকাউন্টের ধরন, symbol | `demo_verification.py` | ⏳ (GPT কোড দেখার পর) |
| SL/TP, ট্রেড-স্বাধীনতা, মালিকানা, counter বনাম History | `demo_verification.py` | ⏳ |
| আসল server offset (v1.1 সিদ্ধান্তের জন্য) | `demo_verification.py` | ⏳ |
| Restart | `DEMO_CHECKLIST_BN.md` (হাতে) | ⏳ |
| দৈনিক লসের সীমা | প্রতিযোগিতা চলাকালে log দেখে | ⏳ |

---

## ৮. জানা সীমাবদ্ধতা
1. আসল MT5-এ ০টা পরীক্ষা।
2. GPT v1.0-এর দৈনিক-লস সময়-সমস্যা — server time ≠ UTC হলে; GPT-এর সিদ্ধান্তের অপেক্ষায়।
3. দৈনিক লসের সীমা আসল broker-এ স্বয়ংক্রিয়ভাবে পরীক্ষা হয় না।
4. ForexFactory ফিড আসল ইন্টারনেটে পরীক্ষিত নয়; না পেলে Claude Gold-এ ট্রেড করবে না।
5. নকল broker-এ requote/slippage/partial fill নেই।
6. Symbol নাম Exness "m" ধরে নেওয়া।
7. Restart নকলে একবার, TP1-এর আগে।
8. Runner-এ Stop চাপলে Claude-এর TP1/time-stop ম্যানেজমেন্টও থামে।
9. নকল লাভ-লস (Claude +$773.80, GPT +$389.64) কোনো প্রমাণ নয়।
10. GPT কম ট্রেড নেয় — ৫০ ট্রেডের রায়ে কয়েক মাস লাগতে পারে।
