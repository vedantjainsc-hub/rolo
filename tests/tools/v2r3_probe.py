"""v2 round-3 real-model probes: V2-BUG-7/8 re-verification (3 runs) + false-negative break-it (2 runs)."""
import json
import sys
from datetime import date
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from conftest import wait_until_settled  # noqa: E402

ART = Path(__file__).resolve().parents[1] / "artifacts" / "enrichment" / "v2r3"
ART.mkdir(parents=True, exist_ok=True)
c = httpx.Client(base_url="http://localhost:8000/api", timeout=30)
T = date.today()


def nxt(m, d):
    x = date(T.year, m, d)
    return (x if x >= T else date(T.year + 1, m, d)).isoformat()


def fus(e):
    return [(f["action"], f["when_text"], f["date_status"], f["suggested_date"]) for f in e["follow_ups"]]


def none_mention(*words):
    return lambda e: (not any(w in f"{a} {wt or ''}".lower() for a, wt, *_ in fus(e) for w in words), fus(e))


def has(word, d):
    return lambda e: (any(word in f"{a} {wt or ''}".lower() and s == "exact" and dd == d for a, wt, s, dd in fus(e)), fus(e))


def ci(key, expect_kept, val_sub=None):
    def f(e):
        v = e["contact_info"][key]
        ok = (v is not None and (val_sub is None or val_sub in v)) if expect_kept else v is None
        return ok, e["contact_info"]
    return f


CASES = [
    ("series_a", "Ravi Iyer", "Ravi Iyer, CFO at Finlo. Raised their Series A on Sep 3. Wants intros to Indian bank treasurers.", 3, none_mention("series a", "sep 3")),
    ("birthday", "Meera Rao", "Meera Rao, product lead at Zeno. Her birthday is on Nov 12. Loves trail running.", 3, none_mention("birthday", "nov 12")),
    ("nov2_pitch", "Omar Dates", "Met Omar at the co-working space. Review his pitch on Nov 2. Follow up after Diwali about the office.", 3, has("pitch", nxt(11, 2))),
    ("phone_vs_date", "Lina Park", "Lina Park, ops at Tidal. Met on 2026-10-10 at the expo. Her number is +1 415 555 0100.", 3, ci("phone", True, "555")),
    ("phone_ext", "Tom Baker", "Tom Baker, procurement at Hexa. Call him at +44 20 7946 0958 ext 12 about the tender.", 3, ci("phone", True, "ext")),
    ("linkedin_handle", "Priya Shah", "Priya Shah, partnerships at a payments startup. LinkedIn: priya-shah-123. Wants intros to bank CTOs.", 3, ci("linkedin", True, "priya-shah-123")),
    ("fn_visit", "Kai Lee", "Kai Lee, founder of Brightloop. Visit his office on Nov 5 to see the prototype.", 2, has("visit", nxt(11, 5))),
    ("fn_wedding", "Anya Roy", "Anya Roy, my old manager. Attend her wedding on Dec 12 in Goa.", 2, has("wedding", nxt(12, 12))),
    ("fn_offsite", "Sam Ortiz", "Sam Ortiz, VP sales at Quanta. Invite him to our offsite on Nov 3.", 2, has("offsite", nxt(11, 3))),
    ("fn_proposal", "Lea Moss", "Lea Moss, buyer at Cora. Submit the proposal to her by Nov 30.", 2, has("proposal", nxt(11, 30))),
    ("past_items", "Omar Haddad", "Omar Haddad, founder at Leasely. Ask him how the demo went last Friday. "
     "Ask about the May 5 recap of the launch. Joined Leasely on 2024-03-01.", 3,
     lambda e: (bool(fus(e)) and all(s == "past" for _a, _w, s, _d in fus(e)), fus(e))),
]
RUNS3 = {"fn_visit", "fn_wedding", "fn_offsite", "fn_proposal"}
CASES = [(k, n, no, 3 if k in RUNS3 else r, ch) for (k, n, no, r, ch) in CASES]
only = set(sys.argv[1:])
summary = {}
for key, name, notes, runs, check in CASES:
    if only and key not in only:
        continue
    n = 0
    for i in range(1, runs + 1):
        r = c.post("/contacts", json={"name": name, "raw_notes": notes}).json()
        d = wait_until_settled(c, r["id"])
        (ART / f"{key}_run{i}.json").write_text(json.dumps(d, ensure_ascii=False, indent=1))
        ok, detail = check(d["enrichment"]) if d["enrichment"] else (False, d["enrichment_error"])
        n += bool(ok)
        print(f"{key} run{i}: {'OK' if ok else 'FAIL'} {json.dumps(detail, ensure_ascii=False)[:230]}", flush=True)
        c.delete(f"/contacts/{r['id']}")
    summary[key] = f"{n}/{runs}"
print("SUMMARY", summary)
