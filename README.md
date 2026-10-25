# Claude vs GPT — MT5 প্রতিযোগিতা (v7: প্রস্তাব v2)

> **সব পরীক্ষা নকল (simulated) broker-এ। আসল MT5 বা ডেমো অ্যাকাউন্টে একটাও পরীক্ষা হয়নি।**
> কোনো প্রস্তাব চালু করা হয়নি। লিখিত অনুমোদন ছাড়া প্রতিযোগিতায় কোনো নতুন সংস্করণ চলবে না।

## কী কোথায়

| জায়গা | কী আছে |
|---|---|
| `Contest_Claude_vs_GPT/` | পুরো প্যাকেজ (ZIP v6 খুললে যা পাওয়া যায়, হুবহু) |
| `Contest_Claude_vs_GPT/proposals/v2/` | **নতুন প্রস্তাব v2:** G2 (GPT core), A1 (adapter), P6c (Claude) — ফাইল, diff, SHA-256, README |
| `Contest_Claude_vs_GPT/proposals/v2/PROPOSAL_REPORT_v2_BN.md` | **v2 রিপোর্ট:** কোড পর্যালোচনার ফল, গুরুত্ব, সংশোধন, পরীক্ষা, সুপারিশ |
| `Contest_Claude_vs_GPT/proposals/` | আগের প্রস্তাব P1–P6b (v1; v2 এগুলোর জায়গা নিয়েছে) |
| `Contest_Claude_vs_GPT/proposals/PROPOSAL_REPORT_BN.md` | প্রস্তাব রিপোর্ট: প্রত্যাশিত বনাম আসল ফল |
| `Contest_Claude_vs_GPT/TEST_REPORT_BN.md` | চালু (v5) কোডের পরীক্ষার রিপোর্ট |
| `Contest_Claude_vs_GPT/SHA256SUMS.txt` | প্যাকেজের প্রতিটা ফাইলের SHA-256 |
| `zip/Contest_Claude_vs_GPT_v7.zip` | বর্তমান প্যাকেজ (প্রস্তাব v2 সহ), ZIP আকারে |
| `zip/Contest_Claude_vs_GPT_v6.zip` | আগের সংস্করণ (রেকর্ডের জন্য) |

## যাচাইয়ের জন্য SHA-256

| ফাইল | SHA-256 |
|---|---|
| GPT মূল ফাইল (চালু, অপরিবর্তিত) | `4d41a0ea7e75176002f1fc90a1530f77893c47e964f1420f91c1ba58bdd81160` |
| GPT core প্রস্তাব G2 (চালু নয়) | `64308ee75bd727de0ffcc7ecc12e07a8f92809c78c6f643513a6fea544d7064a` |
| ZIP v7 | `48bed929d7a49627136519e3364db9c6d0433ad6755e7d75a9aaf6f579fc9a99` |
| ZIP v6 | `9f5967d3e6a6f71a350d09f00ca34d7b301078fd48f82dfb841cba03b3682233` |

ZIP ও প্যাকেজের প্রতিটা ফাইল `Contest_Claude_vs_GPT/SHA256SUMS.txt`-এর সাথে মিলিয়ে দেখা যায়: `sha256sum -c SHA256SUMS.txt`।
