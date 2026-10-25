# পরীক্ষার রিপোর্ট v5 — GPT-এর অনুমোদিত A–E সংশোধন

তারিখ: ২৫ অক্টোবর ২০২৬ · প্রস্তুত করেছে: Claude · **ZIP v5**

> **সব পরীক্ষা নকল (simulated) broker-এ। আসল MT5 / ডেমো অ্যাকাউন্টে একটাও পরীক্ষা হয়নি।**
> নতুন `demo_verification.py` GPT-এর পর্যালোচনা ও অনুমতি ছাড়া ডেমোতেও চালানো হবে না।
> কোনো বটকে বিজয়ী বা সফটওয়্যারকে বাস্তব ব্যবহারের জন্য প্রস্তুত ঘোষণা করা হচ্ছে না।

---

## ১. কী বদলেছে (v4 → v5)

| ফাইল | পরিবর্তন | কেন |
|---|---|---|
| `demo_verification.py` | সম্পূর্ণ নতুন করে লেখা (v2) | A–E |
| `verification_journal.py` | **নতুন** — `verification_positions.json` atomic লেখা + SHA-256 checksum + অবস্থা যাচাই | C, D |
| `contest_counter.py` | পরীক্ষা-ট্রেড বাদ (position, deal, order নম্বর দিয়ে); MT5 `None` দিলে `CounterDataError` (খালি হিসাব নয়); খাতা নেই/নষ্ট/অসম্পূর্ণ হলে রিপোর্টে warning ও `data_ok` | D, অতিরিক্ত |
| `contest_preflight.py` | নতুন চেক: খাতা নষ্ট বা অসম্পূর্ণ (orphan সম্ভব) হলে প্রতিযোগিতা শুরু নয় | C |
| `contest_scoreboard.py` | counter-এর warning লাল/কমলা রঙে দেখায় | D |
| `claude_pullback_v1.py` | (১) TP1 আংশিক বন্ধে বন্ধ-অংশ ও বাকি-অংশ দুটোই min/max/step যাচাই (`plan_partial_close`); (২) MT5 `None` দিলে "পজিশন নেই" ধরে না — `MT5Unavailable`, এই চক্রে কিছু না করে পরের চক্রে; (৩) `order_send` `None` দিলে অন্য filling mode-এ **আবার পাঠায় না** (দ্বিগুণ পজিশনের ঝুঁকি) | E, অতিরিক্ত |
| `gpt_liquidity_fibonacci_scalper_v1.py` | **কোনো পরিবর্তন নেই** — SHA-256 `4d41a0ea…bd81160` | — |
| `gpt_contest_adapter.py` | কোনো পরিবর্তন নেই | — |

**Claude বটের পরিবর্তন ট্রেডিং আচরণ বদলায়নি:** পূর্ণ দুই-বট সিমুলেশনে (একই নকল ডেটা) v4 ও v5-এর ট্রেড তালিকা
**হুবহু এক** — Claude ১৮টা, GPT ১১টা (symbol, দিক, খোলা ও বন্ধের সময়, নিট, volume মিলিয়ে)।

---

## ২. A–E বাস্তবায়ন

* **A** — order-এর আগে position snapshot। order-এর ফল থেকে **deal → position_id**, না পেলে **order → deal history → position_id**;
  order ticket কখনো সরাসরি position ধরা হয় না। তারপর position-টা পরীক্ষার আগে ছিল না, এবং symbol, দিক, magic, volume
  (০ < volume ≤ অনুরোধ) মেলে — তবেই `opened`। না মিললে বা না পেলে → state `unresolved`, **আর কোনো order নয়**, জরুরি সতর্কবার্তা।
  দেখা না গেলে ১০ বার পর্যন্ত আবার খোঁজে।
* **B** — cleanup শুধু খাতায় নিশ্চিত (position_id মেলে) পজিশন বন্ধ করে, তার নিজের magic দিয়ে; বন্ধের আগে magic ও symbol আবার মেলায়।
  পরীক্ষার পরে snapshot তুলনা: নতুন-দেখা প্রতিযোগিতা-magic পজিশন যার সম্পর্ক নিশ্চিত নয় → **বন্ধ করা হয় না**, ticket-সহ জরুরি সতর্কবার্তা।
  broker "done" বললেও পজিশন সত্যিই বন্ধ হয়েছে কি না আবার দেখে; না হলে আবার চেষ্টা।
* **C** — বাইরের `try/finally`: স্বাভাবিক শেষ, exception, Ctrl+C — সবক্ষেত্রে cleanup → রিপোর্ট → `mt5.shutdown()`;
  প্রতিটা ধাপ আলাদা `try`-এ, একটা ব্যর্থ হলেও বাকিগুলো চলে। cleanup চলার সময় Ctrl+C এলে আরেকবার cleanup।
  রিপোর্ট atomic (tmp → replace)। **প্রতিটা order পাঠানোর আগেই খাতায় লেখা** — process/VPS মরে গেলেও পরের বার চালুতে orphan ধরা পড়ে;
  খাতায় নিশ্চিত orphan বন্ধ হয়, অনিশ্চিতগুলোর জন্য সতর্কবার্তা; orphan পাওয়া গেলে সেই run-এ নতুন পরীক্ষা হয় না।
* **D** — খাতায় প্রতিটা পরীক্ষার position_id, order ticket, deal ticket ও **সব deal_ids**। Counter এর যেকোনো একটা মিললে পুরো position বাদ দেয়।
  খাতা নেই → NOTE; নষ্ট/checksum ভুল/অর্ধেক লেখা → ERROR, `data_ok = False`; অসম্পূর্ণ → WARNING; preflight-ও আটকায়।
* **E** — `plan_partial_close()`: বন্ধ-অংশ = floor(volume/2 ÷ step) × step; বন্ধ-অংশ ও বাকি-অংশ দুটোই ≥ volume_min, ≤ volume_max, step-এর গুণিতক;
  না হলে আংশিক বন্ধ বাদ, কারণ log। Claude বটের TP1 ও verification দুটোতেই এটা।

---

## ৩. GPT-এর ১৫টা পরিস্থিতি — প্রত্যাশিত বনাম আসল (সব নকল broker)

**ফল: ৩২টা পরীক্ষার ৩২টা প্রত্যাশামতো।** (GPT-এর ১৫টা পরিস্থিতি ৩২টা পরীক্ষায় ভাগ করা)

| ID | GPT-এর # | পরিস্থিতি | প্রত্যাশিত ফল | আসল ফল (নকল broker) | মিলেছে |
|---|---|---|---|---|---|
| S0 | — | Baseline: normal Hedging demo | all checks pass, 0 test positions left, journal OK, shutdown called | ok=True failed=[] urgent=0 requests=6 contest_open=[] journal=OK shutdown=True | ✅ |
| 1a | 1 | Broker returns None for the open (but the order executed) | position cannot be linked → NOT auto-closed, urgent warning with tickets, Claude order never sent, journal INCOMPLETE (note: GPT's own _send_order retries other filling modes on None, so >1 GPT position can appear) | ok=False failed=['A: GPT position confirmed (deal→position, symbol, side, magic, volume)', 'Cleanup: no test or unlinked positions left, journal complete'] urgent=4 requests=3 contest_open=[5001, 5003, 5005] journal=INCOMPLETE shutdown=True / GPT positions … | ✅ |
| 1b | 1 | Broker returns a wrong order ticket (deal ticket correct) | resolved via deal → position_id; all pass; nothing left | ok=True failed=[] urgent=0 requests=6 contest_open=[] journal=OK shutdown=True | ✅ |
| 1c | 1 | Broker returns a wrong deal ticket (order ticket correct) | resolved via order → deal history; all pass; nothing left | ok=True failed=[] urgent=0 requests=6 contest_open=[] journal=OK shutdown=True | ✅ |
| 1d | 1 | Both order and deal tickets wrong | cannot confirm → stop further orders, urgent, the 1 GPT position NOT auto-closed, journal INCOMPLETE | ok=False failed=['A: GPT position confirmed (deal→position, symbol, side, magic, volume)', 'Cleanup: no test or unlinked positions left, journal complete'] urgent=2 requests=1 contest_open=[5001] journal=INCOMPLETE shutdown=True | ✅ |
| 2 | 2 | Order succeeds but position not visible for the first 3 queries | polling finds it; all pass; nothing left | ok=True failed=[] urgent=0 requests=6 contest_open=[] journal=OK shutdown=True | ✅ |
| 3 | 3 | Orders only partially filled (50%) | accepted with actual volume (logged), partial-close plan uses actual volume; all pass; nothing left | ok=True failed=[] urgent=0 requests=5 contest_open=[] journal=OK shutdown=True / partial-fill logged | ✅ |
| 4 | 4 | A manual position (magic 0) already open on BTCUSDm | manual position untouched; all pass | ok=True failed=[] urgent=0 requests=6 contest_open=[] journal=OK shutdown=True | ✅ |
| 5 | 5 | Another strategy's position (magic 777) pre-exists + a manual one is opened DURING the test | both untouched (not contest magic, not linked), no urgent; all pass | ok=True failed=[] urgent=0 requests=7 contest_open=[] journal=OK shutdown=True / other positions still open: [5001, 5005] | ✅ |
| 6a | 6 | Adapter's Claude magic wrongly equals GPT's | guard fails, 0 orders sent | ok=False failed=['GUARD: magic numbers correct and distinct'] urgent=0 requests=0 contest_open=[] journal=MISSING shutdown=True | ✅ |
| 6b | 6 | Claude bot magic wrongly set to GPT's number | guard fails, 0 orders sent | ok=False failed=['GUARD: magic numbers correct and distinct'] urgent=0 requests=0 contest_open=[] journal=MISSING shutdown=True | ✅ |
| 7 | 7 | Connection lost during cleanup with BOTH test positions still open, then restored and re-run | run1: states unknown → urgent, 2 test positions left open, journal INCOMPLETE; run2: orphans found via journal, both closed with their own magic, journal resolved, run stops safely | RUN1 ok=False failed=['Unexpected error', 'Cleanup: no test or unlinked positions left, journal complete'] urgent=1 requests=2 contest_open=[5001, 5003] journal=INCOMPLETE shutdown=True // RUN2 ok=True failed=[] urgent=0 requests=2 contest_open=[] journal=O… | ✅ |
| 8a | 8 | Cleanup close returns DONE but position stays open (first 2 times) | cleanup re-checks, sees still open, retries, finally closed; all pass | ok=True failed=[] urgent=0 requests=8 contest_open=[] journal=OK shutdown=True / 'still open' retry logged | ✅ |
| 8b | 8 | Claude BOT's own close returns DONE but position stays open | verification detects it (FAIL 'Claude fully closed'), cleanup still closes everything, journal OK. FINDING: Claude bot trusts retcode, no re-check | ok=False failed=['E: Claude partial close (close & remaining both valid)', 'Claude fully closed its position', 'Counter accuracy without exclusion (claude): counted once, net = MT5 history', 'D: journal has all deal IDs (claude)'] urgent=0 requests=7 contes… | ✅ |
| 9a | 9 | Ctrl+C in the middle of the checks (before cleanup) | cleanup runs, both test positions closed, report written, shutdown called, journal complete | ok=False failed=['Interrupted by Ctrl+C'] urgent=0 requests=4 contest_open=[] journal=OK shutdown=True | ✅ |
| 9b | 9 | Ctrl+C while cleanup is running | cleanup restarts once and finishes, positions closed, report written, shutdown called | ok=False failed=['Unexpected error'] urgent=1 requests=4 contest_open=[] journal=OK shutdown=True / 'Ctrl+C during cleanup' logged | ✅ |
| 9c | 9 | Ctrl+C while the report is being written | shutdown still called, positions already closed, journal complete (separate file), error logged | ok=True failed=[] urgent=0 requests=6 contest_open=[] journal=OK shutdown=True / REPORT ERROR logged | ✅ |
| 10a | 10 | verification_positions.json is garbage | guard fails (0 orders); counter: data_ok False + ERROR warning; preflight fails | ok=False failed=['GUARD: verification journal readable'] urgent=0 requests=0 contest_open=[] journal=CORRUPT shutdown=True / counter data_ok=False warning='ERROR: verification_positions.json পড়া যায়নি: JSONDecodeEr…' preflight_ok=False | ✅ |
| 10b | 10 | verification_positions.json valid JSON but checksum wrong (tampered) | same as 10a | ok=False failed=['GUARD: verification journal readable'] urgent=0 requests=0 contest_open=[] journal=CORRUPT shutdown=True / counter data_ok=False warning='ERROR: verification_positions.json-এর checksum মেলেনি (নষ্ট …' preflight_ok=False | ✅ |
| 10c | 10 | verification_positions.json truncated (partially written) | same as 10a | ok=False failed=['GUARD: verification journal readable'] urgent=0 requests=0 contest_open=[] journal=CORRUPT shutdown=True / counter data_ok=False warning='ERROR: verification_positions.json পড়া যায়নি: JSONDecodeEr…' preflight_ok=False | ✅ |
| 10d | 10 | verification_positions.json missing | counter not silent: NOTE warning shown | status=MISSING warnings=['NOTE: verification_positions.json নেই — demo_verification এখনো চালানো হয়নি (বা ফাইল সরানো হয়েছে) — এই ফোল্ডারে verification চালালে ফাইলটা এখানেই থাকার কথা'] | ✅ |
| 11 | 11 | Counter after restart + D both directions (contest trades before AND after verification) | both real contest trades counted exactly once, both verification trades excluded, new counter instance gives identical result | counted [5001, 5014] (contest trades before=5001, after=5014); excluded verification [5004, 5006]; second counter instance identical=True | ✅ |
| 12a | 12 | Netting account | stops before any order (0 requests) | ok=False failed=['GUARD: account is HEDGING'] urgent=0 requests=0 contest_open=[] journal=MISSING shutdown=True | ✅ |
| 12b | 12 | Real account | stops before any order (0 requests) | ok=False failed=['GUARD: account is DEMO'] urgent=0 requests=0 contest_open=[] journal=MISSING shutdown=True | ✅ |
| 13a | 13 | Unusual volume rules: min 0.1, step 0.1 (balance 100,000) | Claude test volume 0.2 → close 0.1 / remain 0.1 (both valid); all pass | ok=True failed=[] urgent=0 requests=6 contest_open=[] journal=OK shutdown=True | ✅ |
| 13a2 | 13 | min lot 0.1 with balance 10,000: GPT's 1%-risk lot < min lot | GPT's own rule refuses the order (SKIP_LOT_TOO_SMALL), verification reports it, 0 orders, nothing left. FINDING: on such accounts GPT would never trade | ok=False failed=['A: GPT position confirmed (deal→position, symbol, side, magic, volume)'] urgent=0 requests=0 contest_open=[] journal=OK shutdown=True / GPT SKIPPED (lot too small) logged | ✅ |
| 13b | 13 | volume_max 0.01 (no valid partial close possible) | partial close skipped with reason; full close works; all pass | ok=True failed=[] urgent=0 requests=5 contest_open=[] journal=OK shutdown=True / partial skipped & logged | ✅ |
| 13c | 13 | Broker accepts only RETURN filling mode | both bots fall back FOK→IOC→RETURN; all pass | ok=True failed=[] urgent=0 requests=16 contest_open=[] journal=OK shutdown=True | ✅ |
| 14 | 14 | Claude's close/modify on GPT position refused, and the reverse | both refusal checks PASS; GPT code has no close/modify path (static check) | ok=True failed=[] urgent=0 requests=6 contest_open=[] journal=OK shutdown=True / refusal-both-ways PASS=True static-GPT PASS=True | ✅ |
| 15a | 15 | Symbol name not found | guard fails, 0 orders | ok=False failed=['GUARD: symbol BTCUSDm available'] urgent=0 requests=0 contest_open=[] journal=MISSING shutdown=True | ✅ |
| 15b | 15 | No tick for the symbol | guard fails, 0 orders | ok=False failed=['GUARD: BTCUSDm has a tick'] urgent=0 requests=0 contest_open=[] journal=MISSING shutdown=True | ✅ |
| 15c | 15 | SL/TP would break broker stop level | guard fails, 0 orders | ok=False failed=['GUARD: test SL/TP respect broker stop level'] urgent=0 requests=0 contest_open=[] journal=MISSING shutdown=True | ✅ |

### প্রথম চালানোর পরে যে প্রত্যাশা বদলেছি (স্বচ্ছতার জন্য)
প্রথম চালানোয় ৩০টার মধ্যে ৪টা প্রত্যাশামতো হয়নি। কোড-দোষ না পরীক্ষা-দোষ, তা যাচাই করে:
| ID | প্রথম প্রত্যাশা | যা ঘটেছিল | কারণ ও বদল |
|---|---|---|---|
| 1c | wrong deal → order দিয়ে খুঁজে পাস | পাস হয়নি | **পরীক্ষা-পরিবেশের দোষ:** নকল broker-এর সময় মার্চ ২০২৬, স্ক্রিপ্ট আসল "এখন"-এর আশেপাশে deal খোঁজে। নকল broker-এর সময় আজকের কাছাকাছি করা হলো — কোড বদলায়নি। |
| 7 | cleanup-এ সংযোগ বিচ্ছিন্ন → ১টা পজিশন খোলা থাকবে | ০টা খোলা (আগেই বন্ধ হয়ে গিয়েছিল), স্ক্রিপ্ট ঠিকই "অজানা" সতর্কবার্তা দিয়েছিল | orphan-বন্ধ অংশ আসলে পরীক্ষা হচ্ছিল না। এখন দুই পজিশন খোলা অবস্থায় সংযোগ কাটা হয় → run2-এ orphan হিসেবে দুটোই বন্ধ হয়। |
| 8 | "done কিন্তু খোলা" → retry → সব পাস | নকল "done" প্রথমে **Claude বটের নিজের** close-এ লেগেছিল; verification FAIL ধরেছে, cleanup সব বন্ধ করেছে | দুটো আলাদা পরীক্ষা: 8a (cleanup-এর close) ও 8b (বটের close)। **8b একটা আসল তথ্য দেয় — নিচে জানা সমস্যা ২।** |
| 13a | min 0.1/step 0.1 → partial পরীক্ষা পাস | GPT order-ই পাঠায়নি | GPT-এর নিজের ১%-ঝুঁকির lot (≈0.05) min lot 0.1-এর কম → GPT-এর সঠিক আচরণ। দুটো পরীক্ষা: 13a (balance ১,০০,০০০) ও 13a2 (balance ১০,০০০)। **জানা সমস্যা ৩।** |

---

## ৪. Claude বটের regression test (নকল broker)

**১৭/১৭ পাস**, আর পূর্ণ সিমুলেশনে v4-এর সাথে ট্রেড হুবহু এক।

| পরীক্ষা | প্রত্যাশিত | আসল | মিলেছে |
|---|---|---|---|
| R1 plan_partial_close(vol=0.02, min=0.01, step=0.01, max=100) | [0.01, 0.01] | (0.01, 0.01) | ✅ |
| R1 plan_partial_close(vol=0.03, min=0.01, step=0.01, max=100) | [0.01, 0.02] | (0.01, 0.02) | ✅ |
| R1 plan_partial_close(vol=0.01, min=0.01, step=0.01, max=100) | None | None close 0.0 < volume_min 0.01 | ✅ |
| R1 plan_partial_close(vol=0.1, min=0.1, step=0.1, max=100) | None | None close 0.0 < volume_min 0.1 | ✅ |
| R1 plan_partial_close(vol=0.3, min=0.1, step=0.1, max=100) | [0.1, 0.2] | (0.1, 0.2) | ✅ |
| R1 plan_partial_close(vol=0.25, min=0.1, step=0.05, max=100) | [0.1, 0.15] | (0.1, 0.15) | ✅ |
| R1 plan_partial_close(vol=0.15, min=0.1, step=0.05, max=100) | None | None close 0.05 < volume_min 0.1 | ✅ |
| R1 plan_partial_close(vol=5.0, min=0.01, step=0.01, max=2.0) | None | None close 2.5 / remaining 2.5 > volume_max 2.0 | ✅ |
| R1 plan_partial_close(vol=0.02, min=0.01, step=0.0, max=100) | None | None volume_step 0.0 <= 0 | ✅ |
| R2a TP1 with min 0.1 / step 0.1, lot 0.1 → partial skipped, SL moved to entry | volume 0.1, sl == entry, tp1_done, log says skipped | volume 0.1, sl==entry True, tp1_done True, logged True | ✅ |
| R2b TP1 with min 0.1 / step 0.1, lot 0.3 → close 0.1, keep 0.2, SL→entry | volume 0.2, sl == entry | volume 0.2, sl==entry True | ✅ |
| R2c TP1 normal rules (min 0.01 / step 0.01), lot 0.04 → half closed (same as v4) | volume 0.02, sl == entry | volume 0.02, sl==entry True | ✅ |
| R2d TP1 not reached → nothing changes | volume 0.04, sl unchanged, tp1_done False | volume 0.04, tp1_done False | ✅ |
| R3a MT5 disconnected → open trade NOT recorded as closed, kept in management | trade still tracked, 0 closed records, log 'MT5 unavailable' | tracked True, closed 0, logged True | ✅ |
| R3b connection back, position closed by SL → recorded once with correct net | 1 closed record, net -2.32 | 1 record(s), net -2.32 | ✅ |
| R4 positions_get → None raises MT5Unavailable (never treated as 'no positions') | MT5Unavailable | True | ✅ |
| R5 order_send returns None (outcome unknown) → Claude does NOT resend with other filling modes | 1 send, result None, 1 position at most | sends 1, result None, positions 1 | ✅ |

> R2-এর নোট: নকল broker দাম symbol-এর digits-এ round করে না, বট SL বসায় round(entry, digits)-এ। প্রথমবার পরীক্ষা অ-round দামের
> সাথে মেলাচ্ছিল বলে ৩টা ভুল FAIL এসেছিল — পরীক্ষার তুলনা ঠিক করা হয়েছে, বটের কোড নয়।

---

## ৫. আগের সব পরীক্ষা আবার (regression, v5 কোডে, নকল)
| পরীক্ষা | ফল |
|---|---|
| Counter unit test | ৪০/৪০ |
| দুই-বট পূর্ণ সিমুলেশন | মালিকানা লঙ্ঘন ০ · অন্যের কারণে আটকানো ০/০ · counter = broker হুবহু · restart ঠিক · GPT ফাইল অপরিবর্তিত · ট্রেড v4-এর সাথে হুবহু এক |
| GPT দৈনিক-লস সময়-পরীক্ষা | v1.0 ১৪/৪৮ · v1.1 ৪৮/৪৮ (প্রস্তাব অপরিবর্তিত, চালু নয়) |
| v1.1 পরিসর (AST) | শুধু অনুমোদিত দুই ফাংশন |
| Contest Runner | preflight ১২/১২ (নতুন খাতা-চেক সহ), loop error ০ |
| সব ফাইল compile | পাস |
| পুরনো `test_demo_verification_on_sim.py` | **সরানো** — নতুন ৩২-পরিস্থিতির পরীক্ষা এর জায়গা নিয়েছে |

---

## ৬. GPT-এর মূল ফাইল
* SHA-256 `4d41a0ea7e75176002f1fc90a1530f77893c47e964f1420f91c1ba58bdd81160` — পাঠানো ফাইল, চালু ফাইল, `gpt_original_unchanged/` — তিনটাই এক।
* সব পরীক্ষার আগে-পরে এক। v5-এ এই ফাইল ও adapter স্পর্শ করা হয়নি।

---

## ৭. জানা সমস্যা ও সীমাবদ্ধতা (গোপন না করে)
1. **আসল MT5-এ ০টা পরীক্ষা।** নতুন demo_verification GPT-এর অনুমতির পরে Hedging ডেমোতে চালাতে হবে।
2. **Claude বট broker-এর "done" উত্তর বিশ্বাস করে** (8b): TP1 আংশিক বন্ধ বা time-stop বন্ধের পরে পজিশন সত্যিই বদলেছে কি না আবার দেখে না।
   আসল MT5-এ DONE মানে সাধারণত সম্পন্ন, তাই ঝুঁকি কম — কিন্তু চাইলে বটে "বন্ধের পরে আবার যাচাই" যোগ করা যায় (Claude-এর কৌশল নয়, শুধু
   execution-নিরাপত্তা; প্রতিযোগিতা শুরুর **আগে**ই সিদ্ধান্ত দরকার)।
3. **GPT ছোট অ্যাকাউন্টে বড় min-lot symbol-এ ট্রেড নেবে না** (13a2): GPT-এর ১%-ঝুঁকির lot min lot-এর কম হলে order দেয় না (এটা GPT-এর নিয়ম,
   বদলানো হয়নি)। Exness BTCUSDm/XAUUSDm-এ min 0.01 হলে সমস্যা নেই — demo_verification-এর symbol তথ্য দেখে নিশ্চিত হতে হবে।
4. **GPT-এর `_send_order` `None` পেলে পরের filling mode-এ আবার পাঠায়** (1a): order আসলে broker-এ পৌঁছে গিয়ে থাকলে একই order ২–৩ বার
   খুলতে পারে। GPT-এর ফাইল বদলানো হয়নি — GPT-এর সিদ্ধান্তের বিষয়। (Claude বটে এটা v5-এ বন্ধ করা হয়েছে।)
5. **order `None` + আসলে খোলা** হলে পজিশনের সাথে নিশ্চিত সম্পর্ক প্রমাণ করা যায় না → GPT-এর শর্ত অনুযায়ী স্বয়ংক্রিয়ভাবে বন্ধ হয় না,
   শুধু সতর্কবার্তা — ব্যবহারকারীকে হাতে বন্ধ করতে হবে।
6. Python process বা VPS হঠাৎ বন্ধ হলে সেই মুহূর্তে cleanup চলে না — পরের বার চালুতে খাতা দিয়ে orphan ধরা পড়ে (৭ নং পরীক্ষা)।
   তবে order পাঠানো আর খাতায় ticket লেখার মাঝের মিলিসেকেন্ডে মরে গেলে position_id খাতায় থাকে না → "sending" অবস্থা দেখে সতর্কবার্তা দেয়,
   নিজে বন্ধ করে না।
7. নকল broker-এ requote, slippage, বাস্তব latency নেই; প্রতি candle-এ ৪টা tick।
8. ForexFactory নিউজ ফিড আসল ইন্টারনেটে পরীক্ষিত নয়।
9. Symbol নাম Exness "m" ধরে নেওয়া।
10. GPT v1.1 দৈনিক-লস প্রস্তাব এখনো চালু নয় — GPT-এর সিদ্ধান্তের অপেক্ষায়।
11. নকল লাভ-লস কোনো প্রমাণ নয়।

---

## ৮. পরের ধাপ
1. GPT পরিবর্তিত কোড ও এই রিপোর্ট পর্যালোচনা করবে।
2. জানা সমস্যা ২ ও ৪ নিয়ে GPT-এর সিদ্ধান্ত (প্রতিযোগিতা শুরুর আগে)।
3. GPT অনুমতি দিলে **শুধু Hedging ডেমোতে** `demo_verification.py` → রিপোর্ট, log, `verification_positions.json` পাঠানো।
4. তারপরই প্রতিযোগিতা শুরুর সিদ্ধান্ত।
