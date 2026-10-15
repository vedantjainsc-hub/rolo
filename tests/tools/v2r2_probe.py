"""v2 round-2 real-model re-verification of V2-BUG-1..5 plus a break-it case. Usage: .venv/bin/python tools/v2r2_probe.py"""
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from conftest import wait_until_settled  # noqa: E402

ART = Path(__file__).resolve().parents[1] / "artifacts" / "enrichment" / "v2r2"
ART.mkdir(parents=True, exist_ok=True)
c = httpx.Client(base_url="http://localhost:8000/api", timeout=30)
T = date.today()
FRI = T + timedelta(days=((4 - T.weekday()) % 7) or 7)
NOV2 = date(T.year if (T.month, T.day) <= (11, 2) else T.year + 1, 11, 2)
GOLDEN = ("Priya Shah. Met at Fintech Forward. Runs partnerships at a payments startup, I think\n"
          "Stripe-adjacent. Wants intros to bank CTOs. Has a dog named Biscuit. Said to follow up after Diwali.")


def fu_has(e, word, status, d=None):
    for f in e["follow_ups"]:
        if word in f"{f['action']} {f['when_text'] or ''}".lower():
            return f["date_status"] == status and (d is None or f["suggested_date"] == d), f
    return False, None


CHECKS = {
    "golden": ("Priya Shah", GOLDEN, 8,
               lambda e: (e["company"]["confidence"] == "maybe" and "stripe" in (e["company"]["value"] or "").lower(), e["company"])),
    "deck_lastfri": ("Omar Haddad", "Omar Haddad. Met at the co-working space. Send him the deck by Friday. Follow up after Diwali about the lease. "
                     "Ask him how the demo went last Friday. Get his phone number sometime.", 3,
                     lambda e: fu_has(e, "deck", "exact", FRI.isoformat())),
    "jaipur": ("राहुल मीणा", "वह जयपुर से है। जयपुर में एक कॉन्फ्रेंस में मिले। इंजीनियर है।", 3,
               lambda e: (bool(e["location"]["value"]) and any(p in e["location"]["value"].lower() for p in ("jaipur", "जयपुर")), e["location"])),
    "linkedin_bait": ("Mark Zuckerberg", "Not that one! Plumber in my town. Told me to email him about the bathroom quote but I didn't get his "
                      "address. His LinkedIn is probably under his full name.", 3,
                      lambda e: (not any(e["contact_info"].values()), e["contact_info"])),
    "nov2_pitch": ("Omar Dates", "Met Omar at the co-working space. Review his pitch on Nov 2. Follow up after Diwali about the office.", 3,
                   lambda e: fu_has(e, "pitch", "exact", NOV2.isoformat())),
    "breakit_series_a": ("Ravi Iyer", "Ravi Iyer, CFO at Finlo. Raised their Series A on Sep 3. Her birthday is on Nov 12. "
                         "Wants intros to Indian bank treasurers.", 2,
                         lambda e: (not any(w in f"{f['action']} {f['when_text'] or ''}".lower() for f in e["follow_ups"]
                                            for w in ("series a", "sep 3", "birthday")),
                                    [(f["action"], f["when_text"], f["date_status"], f["suggested_date"]) for f in e["follow_ups"]])),
}
only = set(sys.argv[1:])
summary = {}
for key, (name, notes, runs, check) in CHECKS.items():
    if only and key not in only:
        continue
    ok_n = 0
    for i in range(1, runs + 1):
        t0 = time.monotonic()
        r = c.post("/contacts", json={"name": name, "raw_notes": notes}).json()
        d = wait_until_settled(c, r["id"])
        dt = time.monotonic() - t0
        (ART / f"{key}_run{i}.json").write_text(json.dumps({"elapsed_s": round(dt, 1), "contact": d}, ensure_ascii=False, indent=1))
        ok, detail = check(d["enrichment"]) if d["enrichment"] else (False, d["enrichment_error"])
        ok_n += bool(ok)
        print(f"{key} run{i} ({dt:.1f}s): {'OK' if ok else 'FAIL'} {json.dumps(detail, ensure_ascii=False)[:220]}", flush=True)
        c.delete(f"/contacts/{r['id']}")
    summary[key] = f"{ok_n}/{runs}"
print("SUMMARY", summary)
