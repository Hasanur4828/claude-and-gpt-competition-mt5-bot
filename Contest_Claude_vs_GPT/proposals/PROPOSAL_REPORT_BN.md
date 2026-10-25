# প্রস্তাব রিপোর্ট v6: GPT-এর সিদ্ধান্ত ১-খ, ২-খ, ৩-খ, ৪-খ, ৫-গ, 8b-রাজি

তারিখ: ২৫ অক্টোবর ২০২৬ · প্রস্তুত করেছে: Claude · **ZIP v6**

> **সব পরীক্ষা নকল (simulated) broker-এ হয়েছে। আসল MT5 বা ডেমো অ্যাকাউন্টে একটাও পরীক্ষা হয়নি। কোনো আসল order পাঠানো হয়নি।**
> **কোনো প্রস্তাব চালু করা হয়নি।** চালু প্যাকেজের ফাইল (GPT-এর মূল ফাইল, adapter, Claude বট, demo_verification, preflight) আগের মতোই আছে।
> লিখিত অনুমোদনের আগে কোনো নতুন সংস্করণ প্রতিযোগিতায় ব্যবহার করা যাবে না। demo_verification ডেমোতেও চালানো যাবে না।

---

## ১. প্রস্তাবের তালিকা

| ID | GPT-এর সিদ্ধান্ত | ফাইল | বদল | SHA-256 |
|---|---|---|---|---|
| P1 | ১-খ | gpt_…_v1.py | `_send_order`: None এলে UNKNOWN, আর পাঠানো হয় না | `52050515055a9758ab3a5ce4f802b65721680bb80813a3754fbc1952af9a71bd` |
| P2 | ২-খ | gpt_…_v1.py | `_daily_loss_count` + নতুন `_server_offset_seconds` | `3556dd076812f5293d5b127ccecf5686dda6e7f692af0b07c4a2df6f285efd17` |
| P3 | ৩-খ | gpt_…_v1.py | `_send_order`: requested_volume / filled_volume / fill_status | `3c7df70edec920807d5591dbf15caece8a13487a3037c995eddc12097b07c451` |
| P4 | ৪-খ | gpt_…_v1.py | `_setup` BUY: tick None হলে SKIP_NO_TICK | `65bfcc49602799b5a6a0cc0628d800244c5f920aefaef30efb339771c6256828` |
| COMBINED | P1–P4 একসাথে | gpt_…_v1.py | উপরের চারটা | `f49bdc0da25bb75cd446953a64b2a6552e8166060e4377614f11afc2b73e393e` |
| P5 | ৫-গ | demo_verification.py | শুধু তথ্য-লাইন: BTC/Gold-এর volume spec | `bed38da8690320cb5fe1b9aaab12f7d25956684cdfaebcd16cc9d882b7e47335` |
| P6 | 8b-রাজি | claude_pullback_v1.py | বন্ধের পরে আবার যাচাই | `0d3dc29da2b11e67f5ab478b2f94cfa0b6d0ab05da9c45b2b69716c8b51307ae` |
| P6b | ঐচ্ছিক বিকল্প | claude_pullback_v1.py | P6 + TP1 অবস্থা আগে লেখা + BE পুনরায় চেষ্টা | `b390bf3195d7aedbff13a81e3b98bd23b76287217aae76ee8108994a0b0758be` |

তুলনার ভিত্তি (চালু ফাইল): GPT v1.0 `4d41a0ea…bd81160` · Claude v5 `0516a96f…65bb96` · demo_verification v2 `c708da0c…`।
প্রতিটা ফোল্ডারে আছে: ফাইল, সম্পূর্ণ diff, `SHA256.txt` আর `README_BN.md`।

---

## ২. AST পরিসর-প্রমাণ (`tests/verify_proposal_scope.py`)

দুই ফাইলের AST (line number ও comment বাদ দিয়ে) প্রতিটা অংশ ধরে তুলনা করা হয়েছে। যে ফাংশন বদলেছে, তার ভেতরে statement-স্তরের diff-ও দেখা হয়েছে।

| ID | অপরিবর্তিত অংশ | বদলেছে | যোগ হয়েছে | ফল |
|---|---|---|---|---|
| P1 | ২৯ | `_send_order` | — | SCOPE OK |
| P2 | ২৯ | `_daily_loss_count` | `_server_offset_seconds` | SCOPE OK |
| P3 | ২৯ | `_send_order` | — | SCOPE OK |
| P4 | ২৯ | `_setup` (১ statement → ৪) | — | SCOPE OK |
| COMBINED | ২৭ | ওপরের তিনটা | `_server_offset_seconds` | SCOPE OK |
| P5 | ৫২ | `run_checks` | — | SCOPE OK |
| P6 | ৮২ | `__init__`, `_close`, `_manage_open_trades` | `_confirm_close`, `import time`, ২টা constant | SCOPE OK |
| P6b | ৮২ | ওপরের তিনটা | ওপরের সব + `BE_MAX_TRIES` | SCOPE OK |

statement-স্তরের পূর্ণ তালিকা আছে `tests/results/proposals/ast_scope_output.txt`-এ।

---

## ৩. Runtime পরীক্ষা: প্রত্যাশিত বনাম আসল

### P1: order_send None (duplicate হয় কি না বিশেষভাবে দেখা হয়েছে) · ১৯/১৯
| পরিস্থিতি | প্রত্যাশিত | আসল |
|---|---|---|
| None, অথচ order আসলে খোলে (v1.0, BUY/SELL) | আগের ঝুঁকিটা দেখা যাবে | ৩ বার পাঠায় → **৩টা পজিশন**, status FAILED |
| একই পরিস্থিতি (P1 ও COMBINED, BUY/SELL) | ১ বার পাঠাবে, ≤ ১ পজিশন, UNKNOWN, last_error থাকবে | ১ বার পাঠায় → **১টা পজিশন**, UNKNOWN, ORDER_SEND_NONE, last_error আছে, filling FOK |
| None, কিছুই খোলেনি | v1.0: ৩ চেষ্টা · P1: ১ চেষ্টা | v1.0: ৩, FAILED · P1: ১, UNKNOWN |
| সংযোগ বিচ্ছিন্ন | order পর্যন্ত পৌঁছাবে না | দুটোই আগেই SKIP_SYMBOL_INFO দেয়, ০ চেষ্টা |
| UNKNOWN-এর পরের চক্র | পজিশন দেখা যাবে → নতুন order নয় | `_has_position` = True |
| স্বাভাবিক FOK / শুধু RETURN (10030 fallback) / কোনো filling গ্রহণ নয় | v1.0-এর মতোই request ক্রম ও ফল | তিন ধরনেই হুবহু এক (P1, P3, COMBINED) |

### P2: দৈনিক লস, server time
| পরীক্ষা | v1.0 | P2 | COMBINED |
|---|---|---|---|
| আগের ৪৮টা (৪ ঘটনা × ৬ offset × ২ tick-age), আবার চালানো | ১৪/৪৮ | **৪৮/৪৮** | — |
| নতুন boundary: এখন 00:00:00, 00:00:30, 23:59:59, 12:00, 18:00; লস ঠিক মধ্যরাতে, 23:59:59-এ; −0.1R লস (গোনা হবে না) × offset −12, −5, −3.5, 0, 2, 3, 3.5, 5.5, 10, 14 | ২৩/৬০ | **৬০/৬০** | ৬০/৬০ |
| tick-age সীমা: 0, 120, 299 সেকেন্ড = offset জানা; 301, 900 সেকেন্ড = অজানা; −120 সেকেন্ড (ঘড়ি একটু আগে) | — | **২৪/২৪** | — |
| DST: offset +2 থেকে +3 | — | দুটোতেই সঠিক | — |
| offset অজানা (tick নেই / tick ২০ মিনিট পুরনো / ৫:৪৫-এর মতো অ-আধা-ঘণ্টা offset) | — | ১৩৮/১৩৮ ক্ষেত্রে কখনো কম গোনে না; **৯২টায় বেশি গোনে** → GPT আগে থামে | — |

### P3: আসল fill volume · ১৮/১৮
| পরিস্থিতি | v1.0 | P3 / COMBINED |
|---|---|---|
| broker অর্ধেক পূরণ করে (DONE_PARTIAL) | volume 0.29 দেখায়, আসলে 0.14 | requested 0.29 · filled 0.14 · PARTIAL |
| result-এ volume নেই | — | filled None · UNKNOWN_FILL |
| আংশিক fill + result-এ volume নেই | — | filled None · UNKNOWN_FILL (অনুরোধকে পূরণ ধরে না) |
| result.volume = 0 | — | filled None · UNKNOWN_FILL |
| স্বাভাবিক | — | requested = filled = broker-এর আসল · FULL |
| পুরনো `"volume"` key | — | অপরিবর্তিত (requested) |

### P4: BUY tick None · ৩১/৩১
নকল ডেটায় v1.0-এর ৬টা আসল BUY setup খুঁজে নেওয়া হয়েছে (BTC-তে ৩টা, Gold-এ ৩টা)। প্রতিটায় tick None করা হয়েছে:
v1.0 → `AttributeError: 'NoneType' object has no attribute 'ask'` · P4 ও COMBINED → `NO_TRADE / SKIP_NO_TICK`, ০ order।
একই bar-এ tick থাকলে P4 আর COMBINED-এর signal (entry, SL, TP) v1.0-এর সাথে হুবহু এক।

### আচরণগত সমতা: GPT-এর সব প্রস্তাব
২,১৯৭টা নকল bar × ২ symbol × (`_setup` BUY/SELL + `evaluate_symbol`) মিলিয়ে **১৩,১৮২টা কল** (এর মধ্যে ২৯টা আসল signal)।
P1, P2, P3, P4 আর COMBINED — প্রতিটায় v1.0-এর সাথে **০টা পার্থক্য** (tick আছে, offset 0)।

### P5: volume spec রিপোর্ট · ৪/৪
| পরীক্ষা | ফল |
|---|---|
| P5 বসানো কপিতে ৩২-পরিস্থিতির পরীক্ষা | ৩২/৩২ |
| BTC/Gold তথ্য-লাইন (min, step, max, contract, ৫টা SL দূরত্বে min-lot ঝুঁকি ও প্রয়োজনীয় balance) | আছে; এই অংশে ০ order |
| BTC min 0.1, balance ১০,০০০ (13a2) | পরীক্ষার নিজের ৩% SL-এ ✗, ছোট দূরত্বে ✓। 13a2-এ GPT কেন order দেয়নি, তার ব্যাখ্যার সাথে মেলে |

### P6 / P6b: Claude-এর বন্ধ-যাচাই · ২৫/২৫
| ID | পরিস্থিতি | v5 (চালু) | P6 | P6b |
|---|---|---|---|---|
| T1 | স্বাভাবিক TP1 (0.04) | 0.02 বাকি | একই + "confirmed (remaining 0.02)" | একই |
| T2 | TP1-এ নকল "done" | সফল ধরে নেয়, কোনো সতর্কবার্তা নেই | WARNING + notify, `tp1_partial`=unconfirmed, ৫ বার যাচাই, BE বসে, নতুন close order নয় | একই |
| T3 | time-stop-এ নকল "done" | "EXIT_TIME" সফল লেখে অথচ পজিশন খোলা | False, WARNING; পরের চক্রে আবার বন্ধ → confirmed | একই |
| T4 | close প্রত্যাখ্যান (10018) | খোলা থাকে | একই, যাচাই ডাকা হয় না | একই |
| T5 | স্বাভাবিক EXIT_TIME / EXIT_MAXHOLD | বন্ধ | v5-এর সাথে হুবহু এক + confirmed | একই |
| T6 | broker অর্ধেকের অর্ধেক বন্ধ করে "done" বলে | ধরতে পারে না (বাকি 0.06) | "expected 0.04" WARNING | একই |
| T7 | TP1 close যাওয়ার পরেই সংযোগ বিচ্ছিন্ন, তারপর সংযোগ ফেরে | **দ্বিতীয়বার আংশিক বন্ধ** 0.04→0.02→0.01 | **একই দুর্বলতা** (WARNING দেয়) | দ্বিতীয় বন্ধ হয় না (0.02), BE বসে |
| T8 | SL→BE প্রথম ২ বার প্রত্যাখ্যান | একবারই চেষ্টা, BE বসে না | — | তৃতীয়বারে BE বসে; সবসময় প্রত্যাখ্যাত হলে ৫ বার চেষ্টা, তারপর notify "হাতে দেখুন" |

---

## ৪. "চালু করলে কী হবে": পূর্ণ suite, অস্থায়ী কপিতে (`tests/run_proposal_variants.py`)

প্রতিটা variant-এর জন্য প্যাকেজ কপি করে তাতে প্রস্তাবের ফাইল বসানো হয়েছে। GPT ফাইল বদলালে কপির preflight `GPT_SHA256`-ও নতুন hash-এ বসানো হয়েছে (অনুমোদনের পরে ঠিক এটাই করতে হবে)। তারপর সব পরীক্ষা চালানো হয়েছে। আসল প্যাকেজের ফাইল আগে-পরে এক।

| Variant | দুই-বট e2e ট্রেড | v5-এর সাথে এক? | Claude regression | ৩২ পরিস্থিতি | counter unit | মালিকানা লঙ্ঘন | counter = broker | preflight (hedging demo) | restart |
|---|---|---|---|---|---|---|---|---|---|
| v5 (চালু) | ২৯ (C ১৮, G ১১) | — | ১৭/১৭ | ৩২/৩২ | সব পাস | ০ | ✓ | ✓ | ✓ |
| P6 | ২৯ | হুবহু | ১৭/১৭ | ৩২/৩২ | সব পাস | ০ | ✓ | ✓ | ✓ |
| P6b | ২৯ | হুবহু | ১৭/১৭ | ৩২/৩২ | সব পাস | ০ | ✓ | ✓ | ✓ |
| GPT COMBINED | ২৯ | হুবহু | ১৭/১৭ | ৩২/৩২ | সব পাস | ০ | ✓ | ✓ (নতুন hash) | ✓ |
| GPT COMBINED + P6b | ২৯ | হুবহু | ১৭/১৭ | ৩২/৩২ | সব পাস | ০ | ✓ | ✓ (নতুন hash) | ✓ |

> সৎ নোট: e2e সিমুলেশনে broker offset +3, তবু COMBINED-এ GPT-এর ট্রেড বদলায়নি। কারণ এই নকল ডেটায় GPT-এর দিনে ২-লস সীমায় পৌঁছানোর ঘটনা ঘটেনি।
> তাই P2-এর প্রভাব e2e-তে দেখা যায় না; সেটা প্রমাণ হয়েছে আলাদা সময়-পরীক্ষায় (৪৮ + ৬০ + ২৪ + ১৩৮টা)।

---

## ৫. নতুন তথ্য: GPT-এর সিদ্ধান্ত দরকার
1. **P6 নাকি P6b?** T7-এ পাওয়া দুর্বলতাটা v5-এ আছে এবং P6-এও থেকে যায়: TP1 আংশিক বন্ধের পরেই সংযোগ গেলে দ্বিতীয়বার আংশিক বন্ধ হয়। P6b এটা ঠিক করে, আর BE পুনরায় চেষ্টাও যোগ করে। তবে এটা 8b-এর অনুমোদনের চেয়ে একটু বড়।
2. **Adapter / GPT মূলের `_has_position`:** MT5 `positions_get` None দিলে দুটোই ধরে নেয় "পজিশন নেই" (adapter-এ `or ()`, মূলে `return False`)। এখনো বদলানো হয়নি। চাইলে আলাদা প্রস্তাব দেওয়া যায়: None এলে এই চক্রে ট্রেড বাদ।

## ৬. জানা সীমাবদ্ধতা
1. আসল MT5-এ ০টা পরীক্ষা হয়েছে।
2. নকল broker `last_error`-এর বাস্তব মান দেয় না। P1-এর পরীক্ষায় তাই "(1, 'Success')" দেখায়; আসল মান ডেমোতে দেখা যাবে।
3. P1 নিশ্চিত করে যে একই কলে duplicate হবে না। পরের চক্রে duplicate না হওয়া নির্ভর করে broker পজিশন দেখানোর ওপর (GPT `_has_position` + নতুন M15 bar-এর শর্ত)।
4. P2-এ offset অজানা হলে রক্ষণশীল নিয়ম চলে, ফলে GPT আগে থামতে পারে (৯২/১৩৮ ক্ষেত্রে বেশি গোনে)।
5. P6-এ "unconfirmed" মানে শুধু "নিশ্চিত হয়নি"। সংযোগ কাটার ক্ষেত্রে বন্ধ আসলে হয়ে থাকতেও পারে (T7)।
6. নকল broker-এ requote, slippage বা বাস্তব latency নেই। নকল লাভ-লস কোনো প্রমাণ নয়।

## ৭. অনুমোদনের পরে চালু করার ধাপ (GPT-এর লিখিত অনুমোদন ছাড়া নয়)
1. অনুমোদিত প্রস্তাবের ফাইল মূল ফোল্ডারে কপি করতে হবে। P1–P4 সব অনুমোদিত হলে COMBINED; কিছু বাদ গেলে নতুন combined বানিয়ে আবার সব পরীক্ষা।
2. GPT ফাইল বদলালে `contest_preflight.py`-এর `GPT_SHA256` নতুন hash-এ বসাতে হবে। `GPT_ORIGINAL_SHA256.txt`-এ নতুন hash যোগ করতে হবে; v1.0-এর hash রেকর্ড হিসেবে থাকবে।
3. `gpt_original_unchanged/`-এ v1.0 আগের মতোই থাকবে।
4. সব পরীক্ষা আবার চালাতে হবে (`tests/run_proposal_variants.py` সহ), তারপর `SHA256SUMS.txt` হালনাগাদ।
5. তারপর GPT-এর অনুমতি পেলে শুধু Hedging ডেমোতে `demo_verification.py`।
6. প্রতিযোগিতা শুরুর পরে কোনো বদল নয় (জরুরি নিরাপত্তা ছাড়া)।

## ৮. ফলাফলের ফাইল (`tests/results/proposals/`)
`gpt_runtime.json` ও `_output.txt` (৭৭/৭৭) · `p2_timing_48*` · `p2_boundaries*` · `p5_volume_spec*` · `p6_close*` (২৫/২৫) · `ast_scope*` ·
`variants/` (প্রতিটা variant-এর e2e, regression, পরিস্থিতি ও counter-এর output, `variants_summary.json`, `variants_trades.json`)।
