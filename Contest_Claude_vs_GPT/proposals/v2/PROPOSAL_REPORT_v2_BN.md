# প্রস্তাব রিপোর্ট v2 — কোড পর্যালোচনা ও সংশোধিত প্রস্তাব

তারিখ: ২৫ অক্টোবর ২০২৬ · প্রস্তুত করেছে: Claude · ভিত্তি: GitHub `Hasanur4828/claude-and-gpt-competition-mt5-bot`, commit `bdb7253`

> **সব পরীক্ষা নকল (simulated) broker-এ চালানো হয়েছে। আসল MT5 বা ডেমো অ্যাকাউন্টে একটাও পরীক্ষা হয়নি, কোনো আসল order যায়নি।**
> নকল broker-এ পাস করা মানে আসল MT5-এ নিরাপদ, এমন নয়। এখানে শুধু দেখানো হয়েছে, যে পরিস্থিতিগুলো বানানো হয়েছিল সেগুলোতে কোড কী করে।
> **কোনো প্রস্তাব চালু করা হয়নি।** চালু ফাইলগুলো আগের মতোই আছে (নিচের hash দেখুন)। লিখিত অনুমোদন না পেলে কিছু চালু হবে না।

---

## ০. পর্যালোচনার শুরুতে রিপোজিটরির অবস্থা (যাচাই করা)
* `origin/main` = local `bdb7253`। `SHA256SUMS.txt`-এর সাথে প্রতিটা ফাইল মিলিয়ে দেখা হয়েছে: সব ঠিক।
* চালু ফাইল (অপরিবর্তিত):

| ফাইল | SHA-256 |
|---|---|
| `gpt_liquidity_fibonacci_scalper_v1.py` (GPT core v1.0) | `4d41a0ea7e75176002f1fc90a1530f77893c47e964f1420f91c1ba58bdd81160` |
| `gpt_contest_adapter.py` | `bfb2b4aef7626c7bc65752c2fbb994a775d7df629fd3c71c4405571f4529f436` |
| `claude_pullback_v1.py` (v5) | `0516a96f508db10a94b56c40ec68c719855882cf8d237a2dded2d5c90265bb96` |
| `demo_verification.py` (v2) | `c708da0cf7394450163091f0ca0fcd0587f6e0d79d2093291042d0018e6e197d` |
| `contest_preflight.py` | `b22d98fb92cd731d8ffec1dfb8b9a3f898651a4a99aa212a32c916eccf7f121e` |

---

## ১. আসল কোড পর্যালোচনায় যা পাওয়া গেছে

| # | গুরুত্ব | কোথায় | সমস্যা | প্রমাণ (নকল broker) |
|---|---|---|---|---|
| F1 | **উচ্চ** | GPT core `_has_position()` ও adapter `_has_position()` | `positions_get()` None দিলে core বলে `False`, adapter-এর `or ()`-ও বলে "পজিশন নেই"। ফলে আগে থেকে পজিশন থাকা অবস্থাতেও নতুন signal দিতে পারে, অর্থাৎ পজিশনের ওপর পজিশন জমতে পারে | GPT পজিশন খোলা, positions_get None → v1.0 ও চালু adapter দুটোই BUY signal দেয় |
| F2 | **উচ্চ** | GPT `_send_order()` | `order_send` None দিলে অন্য filling mode দিয়ে একই order আবার পাঠায়। retcode 10012 (timeout) ও 10031 (connection)-এও আবার পাঠায় | v1.0: ৩ বার পাঠায় → **৩টা পজিশন**; 10031/10012-এ order আসলে খুললেও একই ফল |
| F3 | **উচ্চ** | GPT `_daily_loss_count()` | (ক) deal history বা account None হলে ফেরত দেয় `0`, মানে দৈনিক ২-লস সীমা কাজ করে না। (খ) UTC-র দিন ধরে query করে, অথচ deal time server time-এ, তাই সাম্প্রতিক লস বাদ পড়ে | (ক) v1.0 ০ দেয় · (খ) ৬০টা boundary ক্ষেত্রে v1.0 সঠিক মাত্র ২৩টায় |
| F4 | মাঝারি | আগের প্রস্তাব P2 (v1) | offset অজানা হলে "রক্ষণশীল" অনুমান করে (−১৪ ঘণ্টা); একাধিক tick আলাদা offset দেখালে বড়টা নেয়। GPT-এর নতুন শর্ত: অনুমান নয়, UNKNOWN | P2 v1 tick না থাকলেও একটা সংখ্যা দেয় (যেমন ৩) |
| F5 | মাঝারি | GPT `_setup()` BUY শাখা; `_send_order()` | BUY-এ tick None হলে exception (adapter ধরে ফেলে, কিন্তু মূল ফাইলে crash)। order দেওয়ার আগে tick পুরনো বা দাম অবৈধ কি না দেখা হয় না | v1.0: ৬টা BUY setup-এই AttributeError |
| F6 | মাঝারি | GPT `_send_order()` | সফল হলে `volume` হিসেবে অনুরোধ করা volume দেখায়। আগের P3 শুধু result.volume দেখত, deal history-র সাথে মেলাত না | অর্ধেক fill: v1.0 0.29 দেখায়, আসলে 0.14 |
| F7 | মাঝারি | Claude `_close()` (v5) | broker "done" বললেই বিশ্বাস করে | নকল "done": v5 সফল ধরে নেয় |
| F8 | মাঝারি | Claude TP1 (v5) | TP1-এর আংশিক বন্ধ হয়ে যাওয়ার পরে সংযোগ গেলে `tp1_done` লেখা হয় না। ফলে সংযোগ ফিরলে বা restart-এর পরে **দ্বিতীয়বার আংশিক বন্ধ** হয়। SL→BE ব্যর্থ হলে আর চেষ্টা করে না | 0.04 → 0.02 → 0.01; BE বসে না |
| F9 | মাঝারি | Claude entry ও restart (v5) | entry-তে `order_send` None দিল অথচ পজিশন খুলেছে, অথবা state লেখার আগেই crash — দুই ক্ষেত্রেই পজিশন state-এ নেই। তাতে TP1, BE, time-stop কিছুই চলে না; থাকে শুধু broker-এর SL/TP2 | v5: পজিশন ব্যবস্থাপনার বাইরে থেকে যায় |
| F10 | কম | Claude `_try_entry` | order ticket থেকে পজিশন খুঁজে না পেলে ভুল ticket-এ state লেখে। পরে সেটা "বন্ধ, নিট 0" হিসেবে রেকর্ড হয়; টাকার হিসাবে প্রভাব নেই | পরীক্ষা হয়নি — শুধু কোড পড়ে পাওয়া; **ঠিক করা হয়নি** |
| F11 | কম | GPT `_send_order()` | নতুন দামে risk দূরত্ব আবার হিসাব হয়, কিন্তু `sl_min_atr`/`sl_max_atr` আর যাচাই হয় না | কৌশলের বিষয়, **বদলানো হয়নি** |
| F12 | কম | GPT `_daily_loss_count()` | নিট হিসাবে শুধু profit + commission + swap; `fee` ধরা হয় না | কৌশলের হিসাব, **বদলানো হয়নি** |

---

## ২. সংশোধিত প্রস্তাব (সব `proposals/v2/`-এ; প্রতিটার সাথে diff, SHA-256 ও README)

| ID | ফাইল | কী ঠিক করে | SHA-256 |
|---|---|---|---|
| **G2** | `v2/G2_gpt_core_combined/gpt_liquidity_fibonacci_scalper_v1.py` | F1 (core), F2, F3, F4, F5, F6 — H + P1r + P2r + P3r + P4r | `64308ee75bd727de0ffcc7ecc12e07a8f92809c78c6f643513a6fea544d7064a` |
| **A1** | `v2/A1_adapter_position_state/gpt_contest_adapter.py` | F1 (adapter) | `0709cf15dd2f3badddf0eeba6f8c723d275e9c8fca04dae6cb9579525b358dbc` |
| **P6c** | `v2/P6c_claude_close_tp1_be_reconcile/claude_pullback_v1.py` | F7, F8, F9 | `d10f490a9609694fb5c9a6174bd5bb43ac543beb2caba2e9e3174c3976ef1c24` |
| P5 | `P5_demo_volume_spec_report/demo_verification.py` (অপরিবর্তিত) | শুধু রিপোর্ট | `bed38da8690320cb5fe1b9aaab12f7d25956684cdfaebcd16cc9d882b7e47335` |

G2-এর মূল বিষয়গুলো:
* চালু v1.0-এর মাত্র **১১টা লাইন বাদ গেছে বা বদলেছে**। বাকি সব যোগ করা লাইন। কৌশলের কোনো parameter বদলায়নি।
* `positions_get` None → `SKIP_POSITION_STATE_UNKNOWN`, সেই চক্রে order যায় না।
* `order_send` None, 10012 বা 10031 পেলে আর পাঠায় না। তখন:
  * পাঠানোর আগে নেওয়া snapshot (নিজের পজিশন + সবচেয়ে বড় deal ticket) দিয়ে মেলায়।
  * পাওয়া গেলে status `OPENED_RECONCILED`।
  * না পেলে `UNKNOWN`, আর ওই symbol-এ block।
  * block-টা ফাইলে থাকে, তাই restart-এর পরেও টিকে থাকে।
  * মীমাংসা দুইভাবে: order পাওয়া গেলে, অথবা সব query ঠিক থাকা অবস্থায় ≥৬০ সেকেন্ড পরেও কিছু না পাওয়া গেলে।
* দৈনিক লস:
  * offset নেওয়া হয় শুধু তাজা tick থেকে। tick না থাকলে বা tick-গুলোর offset না মিললে `None`।
  * deal history বা account পাওয়া না গেলেও `None`।
  * `None` হলে `SKIP_DAILY_LOSS_UNKNOWN`, নতুন entry বন্ধ।
* fill volume নেওয়া হয় broker-এর deal record থেকে। ফলে `fill_source` ও `position_id` আলাদা করে দেখানো থাকে।
* `_send_order` অবৈধ tick, ১২০ সেকেন্ডের বেশি পুরনো tick, বা বয়স মাপা যায় না এমন tick থেকে কখনো order দেয় না।

**G2 আর A1 একসাথেই চালু করতে হবে।** চালু adapter None পেলে "পজিশন নেই" বলে দেয়, ফলে G2 সমস্যাটা দেখতেই পায় না। আবার A1 v1.0 core-এর সাথে চালালে None-কে "false" ধরা হয়, ফলে আগের মতোই fail-open। দুটোই পরীক্ষায় দেখানো হয়েছে।

---

## ৩. পরীক্ষার ফল — সব নকল broker-এ, **বাস্তবে চালানো হয়েছে**
(ফলের ফাইল আছে `tests/results/proposals_v2/`-এ। প্রতিটা পরীক্ষার আগে ও পরে চালু ফাইলের SHA-256 মিলিয়ে দেখা হয়েছে: অপরিবর্তিত।)

| পরীক্ষার ফাইল | বিষয় | ফল |
|---|---|---|
| `test_v2_gpt.py` | H, P1r, P3r, P4r, আচরণগত সমতা | **৫৯/৫৯** |
| `test_v2_p2.py` | P2r: boundary, offset, tick-age, অজানা বা অসংগত offset, DST, evaluate | **১৭/১৭** |
| `test_v2_gpt_restart.py` | G2 restart ও block ফাইল | **৫/৫** |
| `test_v2_p6c.py` | P6, P6b, P6c (T1–T15) | **৪৬/৪৬** |
| `verify_proposal_scope.py` (v2) | AST: শুধু অনুমোদিত অংশ বদলেছে কি না | **৩/৩ SCOPE OK** |
| `run_proposal_variants.py` (v2) | চালু করলে কী হবে — পূর্ণ suite | **৪টা variant, সব পাস — §৩.৭ দেখুন** |

### ৩.১ H / A1 — positions_get None
| পরিস্থিতি | প্রত্যাশিত | আসল |
|---|---|---|
| GPT পজিশন খোলা, positions_get None, signal bar — core v1.0 / চালু adapter + v1.0 / চালু adapter + G2 / A1 + v1.0 | আগের বা অসম্পূর্ণ অবস্থা দেখানো | চারটাতেই **BUY signal** দেয় (run_once-এ দ্বিতীয় order চলে যেত) |
| একই পরিস্থিতি — core G2 / A1 + G2 | নিরাপদ | `SKIP_POSITION_STATE_UNKNOWN` |
| তিন অবস্থা (G2, A1+G2) | পজিশন আছে / query ঠিক কিন্তু নেই / query ব্যর্থ | `SKIP_POSITION_EXISTS` · signal · `_has_position` False / None |
| শুধু Claude-এর পজিশন আছে (A1+G2) | আগের মতো উপেক্ষা | signal দেয় |
| order-এর আগের snapshot-এ positions_get বা history_deals_get None | order নয় | `SKIP_PRECHECK_QUERY_FAILED`, ০ order |

### ৩.২ P1r — অনিশ্চিত order-এর ফল (duplicate ঠেকানোর ওপর বিশেষ জোর)
| পরিস্থিতি | v1.0 | G2 |
|---|---|---|
| None, অথচ order খোলে (BUY ও SELL) | ৩ send → **৩ পজিশন** | ১ send → ১ পজিশন, `OPENED_RECONCILED`, filled = আসল, block নেই |
| None, কিছুই খোলেনি | — | `UNKNOWN`, ১ send, block, last_error |
| block থাকা অবস্থায় আবার order / evaluate | — | `SKIP_EXECUTION_UNKNOWN`, নতুন send নয় |
| ≥৬০ সেকেন্ড পরে, query ঠিক, কিছু পাওয়া যায়নি | — | একবার `RESOLVED_NOT_EXECUTED` (NO_TRADE), তারপর স্বাভাবিক |
| None, order পরে দেরিতে খোলে | — | `UNKNOWN` → `RESOLVED_OPENED` → `SKIP_POSITION_EXISTS`; মোট ১ পজিশন |
| None, তারপর reconcile query-ও ব্যর্থ (৪৫০ সেকেন্ড) | — | block থেকে যায়; query ঠিক হলে তবেই মীমাংসা |
| None, order খুলেই সাথে সাথে SL-এ বন্ধ (শুধু deal history-তে আছে) | — | deal থেকে `OPENED_RECONCILED`, still_open False |
| retcode 10031 বা 10012, order আসলে খোলে / খোলে না | ৩ send (খুললে ৩ পজিশন) | ১ send; খুললে `OPENED_RECONCILED`, না খুললে `UNKNOWN` |
| স্বাভাবিক FOK / শুধু RETURN (10030 fallback) / কোনো filling গ্রহণ নয় | — | v1.0-এর সাথে request ক্রম ও ফল হুবহু এক |
| **restart:** None, অথচ খোলে → নতুন instance | — | `SKIP_POSITION_EXISTS` |
| **restart:** None, order তখনো দেখা যায় না → নতুন instance → পরে খোলে | — | ফাইল থেকে block ফিরে আসে → `SKIP_EXECUTION_UNKNOWN`, নতুন send নয় → `RESOLVED_OPENED` → মোট ১ পজিশন, ফাইল মুছে যায় |
| **restart:** None, কিছুই খোলেনি → ≥৬০ সেকেন্ড | — | `RESOLVED_NOT_EXECUTED`, ফাইল মুছে যায় |
| block ফাইল নষ্ট | — | evaluate ও send দুটোই `SKIP_EXEC_STATE_UNREADABLE`, ০ order |

### ৩.৩ P2r — দৈনিক লস ও server offset
| পরীক্ষা | v1.0 | P2 (v1) | G2 |
|---|---|---|---|
| ৬টা boundary সময় × ১০টা offset (−12 থেকে +14 ঘণ্টা), সব tick তাজা | ২৩/৬০ | ৬০/৬০ | **৬০/৬০** |
| tick-এর বয়স 0/120/299/−120 সেকেন্ড (জানা), 301/900 সেকেন্ড (অজানা) × ৪ offset | — | — | জানা হলে সঠিক, অজানা হলে **None** — ২৪/২৪ |
| কোনো tick নেই / সব tick ২০ মিনিট পুরনো / ৫:৪৫ ঘণ্টার offset | ২ (কম গোনে) | ৩ (অনুমান) | **None** |
| অসংগত: BTC +3h আর XAU +2h, অথবা BTC +3h আর ETH +3.5h | ২ | ৩ | **None** |
| XAU ও ETH নেই, শুধু BTC তাজা / XAU পুরনো (সপ্তাহান্তের মতো) | — | — | সঠিক ৩ |
| history_deals_get None / account_info None | **০** (লস নেই ধরে নেয়) | ০ | **None** |
| DST: offset +2 থেকে +3 | — | — | দুটোতেই সঠিক |
| evaluate_symbol, offset অজানা বা deal history None | এগিয়ে যায় | — | `SKIP_DAILY_LOSS_UNKNOWN` |

### ৩.৪ P3r — fill volume · ৭/৭
| পরিস্থিতি | G2 |
|---|---|
| আংশিক fill | filled 0.14 (আসল 0.14), PARTIAL, source deal_history, position_id আছে |
| result-এ volume নেই, deal আছে | filled 0.29 (deal history থেকে), FULL |
| আংশিক fill + result-এ volume নেই | filled 0.14, PARTIAL |
| ভুল deal নম্বর, volume আছে | source order_result, FULL |
| ভুল deal নম্বর + volume নেই | filled None, UNKNOWN_FILL |
| broker সব filling প্রত্যাখ্যান করে | FAILED, কোনো filled দাবি নেই, ০ পজিশন |

### ৩.৫ P4r — tick · ১৪/১৪
* নকল ডেটার ৬টা আসল BUY setup-এ (BTC ৩টা, Gold ৩টা) tick None → `SKIP_NO_TICK`, ০ order।
* `_send_order`:
  * ask = 0, bid < 0, ask < bid → `SKIP_INVALID_TICK`।
  * tick ১২১ বা ৩০০ সেকেন্ড পুরনো → `SKIP_STALE_TICK`।
  * offset অজানা → `SKIP_TICK_AGE_UNKNOWN`।
  * প্রতিটাতেই ০ order।
  * ৬০ বা ১২০ সেকেন্ড পুরনো tick → order যায় (সীমার ভেতরে)।

**আচরণগত সমতা:** স্বাভাবিক অবস্থায় (offset 0, সব query ঠিক) ৭,৯০৮টা `_setup`/`evaluate_symbol` কলে G2 আর v1.0-এর মধ্যে **০টা পার্থক্য**।
এর মধ্যে evaluate_symbol-এর signal ছিল মাত্র ৩টা — নমুনা ছোট।

### ৩.৬ P6c — Claude · ৪৬/৪৬ (v5 = চালু)
| ID | পরিস্থিতি | v5 | P6 | P6b | P6c |
|---|---|---|---|---|---|
| T2 | TP1-এ নকল "done" | সফল ধরে নেয় | WARNING, unconfirmed | একই | একই |
| T3 | time-stop-এ নকল "done" | মিথ্যা EXIT_TIME লেখে | পরের চক্রে আবার বন্ধ করে, confirmed | একই | একই |
| T6 | broker কম বন্ধ করে "done" বলে | ধরতে পারে না | WARNING | একই | একই |
| T7 | TP1-এর পরে সংযোগ বিচ্ছিন্ন, তারপর সংযোগ ফেরে | **দ্বিতীয় আংশিক বন্ধ** | **দ্বিতীয় আংশিক বন্ধ** | ঠিক | ঠিক |
| T8 | SL→BE প্রত্যাখ্যাত | একবারই চেষ্টা | — | ৫ বার পর্যন্ত চেষ্টা, তারপর notify | একই |
| T9 | TP1-এর পরে সংযোগ বিচ্ছিন্ন → **restart** | দ্বিতীয় আংশিক বন্ধ | — | ঠিক (তবে unconfirmed থেকে যায়) | ঠিক + `ok (reconciled)` |
| T10 | entry-তে None অথচ পজিশন খোলা | ব্যবস্থাপনার বাইরে | — | — | পরের চক্রে adopt করে, TP1 = 1R, ০ নতুন order |
| T11 | adopt করা পজিশন TP1 ছোঁয় | — | — | — | অর্ধেক বন্ধ + BE |
| T12 | state ফাইল নেই → restart | ব্যবস্থাপনার বাইরে | — | — | adopt করে |
| T13 | SL আগেই BE-তে এমন পজিশন adopt | — | — | — | `tp1_done`, আর আংশিক বন্ধ নয় |
| T14 | GPT বা অজানা magic-এর পজিশন; positions_get None | — | — | — | অন্যের পজিশন adopt করে না; MT5 None হলে কিছু বদলায় না |
| T1, T4, T5, T15 | স্বাভাবিক, close প্রত্যাখ্যাত, কিছু ঘটছে না | — | v5-এর সাথে broker-এর ফল হুবহু এক; অতিরিক্ত request ০ | একই | একই |

### ৩.৭ "চালু করলে কী হবে" — পূর্ণ suite, অস্থায়ী কপিতে
প্রতিটা variant-এর জন্য প্যাকেজের একটা কপি নিয়ে তাতে প্রস্তাবের ফাইল বসানো হয়েছে। G2 বসানো কপিতে preflight-এর `GPT_SHA256`-ও নতুন hash-এ বদলানো হয়েছে।
তারপর চলেছে দুই-বট e2e সিমুলেশন, Claude regression, demo_verification-এর ৩২টা পরিস্থিতি আর counter unit test। আসল প্যাকেজের ফাইল পরীক্ষার আগে-পরে এক।

| Variant | e2e ট্রেড | v5-এর সাথে হুবহু এক? | regression | ৩২ পরিস্থিতি | counter unit | মালিকানা লঙ্ঘন | counter = broker | preflight | restart |
|---|---|---|---|---|---|---|---|---|---|
| v5 (চালু) | ২৯ (Claude ১৮, GPT ১১) | — | ১৭/১৭ | ৩২/৩২ | সব পাস | ০ | ✓ | ✓ | ✓ |
| P6c | ২৯ | হ্যাঁ | ১৭/১৭ | ৩২/৩২ | সব পাস | ০ | ✓ | ✓ | ✓ |
| G2 + A1 | ২৯ | হ্যাঁ | ১৭/১৭ | ৩২/৩২ | সব পাস | ০ | ✓ | ✓ (নতুন hash) | ✓ |
| G2 + A1 + P6c | ২৯ | হ্যাঁ | ১৭/১৭ | ৩২/৩২ | সব পাস | ০ | ✓ | ✓ (নতুন hash) | ✓ |

demo_verification-এর পরিস্থিতি **1a** (GPT-এর order_send None, অথচ order খোলে):
* v5-এ GPT **৩টা** পজিশন খুলে ফেলে রেখেছিল (5001, 5003, 5005)।
* G2 + A1-এ খোলে মাত্র **১টা** (5001)। GPT নিজে reconcile করে `OPENED_RECONCILED` দেয়।
* demo_verification সেই পজিশনটাকে তবুও "unresolved" ধরে জরুরি সতর্কবার্তা দেয়, আর নিজে থেকে বন্ধ করে না (সীমাবদ্ধতা ৯)।
  পরিস্থিতিটার প্রত্যাশাও এটাই ছিল, তাই ফল "প্রত্যাশামতো"।

> সৎ নোট: e2e সিমুলেশনে কোনো None, অনিশ্চিত retcode, orphan বা দৈনিক ২-লস সীমার ঘটনা ঘটেনি। তাই এখানে "ট্রেড হুবহু এক" শুধু দেখায় যে স্বাভাবিক পথে কিছু বদলায়নি।
> ত্রুটির পথগুলো প্রমাণ হয়েছে §৩.১–৩.৬-এর আলাদা পরীক্ষায়।

---

## ৪. বাকি সীমাবদ্ধতা (খোলাখুলি)
1. **আসল MT5-এ ০টা পরীক্ষা হয়েছে।** নকল broker-এ requote, slippage, বাস্তব latency, আসল `last_error` মান বা আসল retcode-এর ধরন নেই।
   `history_deals_get(ticket=…)` order-এর ঠিক পরেই আসল MT5-এ পাওয়া যায় কি না, সেটাও ডেমোতে দেখতে হবে।
2. P1r-এর "৬০ সেকেন্ড পরেও কিছু না পাওয়া মানে order হয়নি" একটা নিয়ম, প্রমাণ নয়। খুব দেরিতে (৬০ সেকেন্ডের পরে) কার্যকর হওয়া order এতে ধরা পড়বে না।
   এরপর `_has_position` তা ধরবে, তবে মাঝের সময়টায় ঝুঁকি থাকে। আসল run_once নতুন M15 bar ছাড়া (≈১৫ মিনিট) আবার evaluate করে না, তাই বাস্তবে সময়ের ফাঁকটা বড়।
3. P1r-এর snapshot "সবচেয়ে বড় deal ticket" ধরে কাজ করে। এর ভিত্তি একটা অনুমান — MT5-এ deal ticket সবসময় বাড়ে — যা ডেমোতে যাচাই করতে হবে।
4. P2r: ঠিক n×৩০ মিনিট (±৫ মিনিট) পুরনো একটা tick দেখতে "অন্য offset-এর তাজা tick"-এর মতো লাগে। তখন G2 অসংগত ধরে UNKNOWN দেয়, entry বন্ধ থাকে।
   এটা নিরাপদ দিক, তবে Gold-এর দৈনিক বিরতিতে কিছু মিনিট BTC-ও আটকে যেতে পারে। কখনো ভুল offset নেওয়া হয় না।
5. P2r/P4r: PC-র ঘড়ি broker থেকে ৫ মিনিটের বেশি এগিয়ে বা পিছিয়ে থাকলে offset সবসময় অজানা হবে, ফলে GPT কোনো ট্রেডই নেবে না (নিরাপদ দিক)।
   VPS-এ সময় সিঙ্ক থাকা দরকার। demo_verification-এ এই মানগুলো দেখা যায়।
6. G2 নতুন একটা ফাইল লিখতে পারে: `gpt_exec_unknown_state.json`, module-এর পাশে, শুধু UNKNOWN অবস্থায়।
   preflight এখনো এই ফাইল আছে কি না দেখে না — চালু করার সময় একটা চেক যোগ করার প্রস্তাব (§৬)।
7. P6c adoption: entry-র আসল bar-এর সময় জানা নেই, তাই পজিশনের খোলার সময় থেকে M15 bar অনুমান করা হয়। SL না থাকলে R জানা যায় না, তখন TP1 বাদ।
   adopt করা পজিশনের `risk_money` হিসাব হয় পজিশনের এখনকার volume থেকে।
8. F10, F11, F12 ঠিক করা হয়নি (কম গুরুত্ব বা কৌশলের বিষয়)।
9. demo_verification (চালু v2) G2-এর `OPENED_RECONCILED` ফলের `reconcile.position_ids` পড়ে না, পড়ে শুধু order/deal ticket।
   তাই অনিশ্চিত ফলের ক্ষেত্রে সেটা পজিশনকে "unresolved" ধরে জরুরি সতর্কবার্তা দেবে — নিরাপদ দিক, তবে একটা অসম্পূর্ণতা।

---

## ৫. সুপারিশ (চূড়ান্ত সিদ্ধান্ত GPT ও ব্যবহারকারীর)

| প্রস্তাব | সুপারিশ | কারণ |
|---|---|---|
| P1, P2, P3, P4, COMBINED (v1) | **REJECT** (G2 এগুলোর জায়গা নিয়েছে) | reconcile, block বা UNKNOWN অবস্থা ছিল না; P2 v1 offset অনুমান করত |
| **G2** (A1-এর সাথে) | **APPROVE — শুধু ডেমো-যাচাইয়ের ধাপের জন্য** | F1–F6 ঠিক করে; সব নকল পরীক্ষা পাস; স্বাভাবিক অবস্থায় আচরণ v1.0-এর মতো। প্রতিযোগিতার আগে ডেমোর ফল লাগবে |
| **A1** | **APPROVE — শুধু G2-এর সাথে** | একা চালালে কোনো লাভ নেই |
| P5 | **APPROVE** | শুধু রিপোর্ট; এই অংশ কোনো order পাঠায় না; চালু ট্রেডিং আচরণ বদলায় না |
| P6, P6b | **REJECT** (P6c এদের জায়গা নিয়েছে) | P6-এ দ্বিতীয় আংশিক বন্ধ থেকে যায়; P6b orphan বা restart-এর পরে মেলায় না |
| **P6c** | **APPROVE — শুধু ডেমো-যাচাইয়ের ধাপের জন্য** | F7–F9 ঠিক করে; কৌশল বদলায় না |

## ৬. অনুমোদনের পরে যা করতে হবে (তার আগে কিছু নয়)
1. অনুমোদিত ফাইলগুলো মূল ফোল্ডারে বসাতে হবে (G2 + A1 + P6c + P5)।
2. `contest_preflight.py`:
   * `GPT_SHA256` = `64308ee7…7064a`; v1.0-এর hash রেকর্ড হিসেবে থাকবে।
   * নতুন চেক: `gpt_exec_unknown_state.json` নেই বা খালি (অমীমাংসিত order থাকলে প্রতিযোগিতা শুরু হবে না)।
3. demo_verification-এ G2-এর `OPENED_RECONCILED`/`UNKNOWN` ফল পড়ার ব্যবস্থা — আলাদা ছোট প্রস্তাব হিসেবে, আবার পর্যালোচনার জন্য।
4. সব পরীক্ষা আবার চালাতে হবে, তারপর `SHA256SUMS.txt` হালনাগাদ।
5. GPT-এর অনুমতি পেলে শুধু Hedging ডেমোতে `demo_verification.py`। তার ফল আর log পর্যালোচনা না হওয়া পর্যন্ত প্রতিযোগিতা নয়।
