"""Enrichment quality against the REAL local model (C1, C2, C3, C4, C5, C7, D1-company, D2).

Runs one case at a time (the model is slow). Skips with a clear reason if the backend
reports the model unavailable. Each run writes the raw enrichment JSON to
tests/artifacts/enrichment/<case>.json for the QA report.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import pytest

from conftest import wait_until_settled

pytestmark = pytest.mark.model

HERE = Path(__file__).resolve().parent.parent
CASES = json.loads((HERE / "fixtures" / "hallucination.json").read_text())["cases"]
ART = HERE / "artifacts" / "enrichment"
HEDGES = ("possibly", "maybe", "may ", "might", "likely", "probably", "perhaps", "unconfirmed",
          "reportedly", "unsure", "not sure", "uncertain", "?", "unclear", "believed", "thought to",
          "i think", "potentially", "seems", "appears")

GOLDEN_NAME = "Priya Shah"
GOLDEN_NOTES = (
    "Priya Shah. Met at Fintech Forward. Runs partnerships at a payments startup, I think\n"
    "Stripe-adjacent. Wants intros to bank CTOs. Has a dog named Biscuit. Said to follow up after Diwali."
)


@pytest.fixture(scope="module")
def model_ready(api_url):
    import httpx

    h = httpx.get(f"{api_url}/api/health", timeout=10).json()
    if not h["model"]["available"]:
        pytest.skip(f"Local model unavailable: {h['model']['detail']} (model {h['model']['name']})")
    ART.mkdir(parents=True, exist_ok=True)
    return h["model"]["name"]


def _enrich(client, name: str, notes: str, tag: str) -> tuple[dict, float]:
    t0 = time.monotonic()
    r = client.post("/contacts", json={"name": name, "raw_notes": notes, "enrich": True})
    assert r.status_code == 201 and r.json()["enrichment_status"] == "pending", r.text
    c = wait_until_settled(client, r.json()["id"])
    elapsed = time.monotonic() - t0
    (ART / f"{tag}.json").write_text(json.dumps({"elapsed_s": round(elapsed, 1), "contact": c}, ensure_ascii=False, indent=2))
    assert c["enrichment_status"] == "done", f"enrichment {c['enrichment_status']}: {c['enrichment_error']}"
    return c, elapsed


def _get(e: dict, path: str):
    cur = e
    for p in path.split("."):
        cur = cur.get(p) if isinstance(cur, dict) else None
    return cur


def _is_empty(v) -> bool:
    if v is None:
        return True
    if isinstance(v, list):
        return len(v) == 0
    if isinstance(v, dict) and "value" in v:
        return v["value"] is None
    return False


def _null_or_inferred(v) -> bool:
    """v2: null, or flagged as uncertain (maybe or inferred)."""
    if v is None:
        return True
    if isinstance(v, list):
        return all(i.get("confidence") in ("maybe", "inferred") for i in v)
    return v.get("value") is None or v.get("confidence") in ("maybe", "inferred")


def _term_found(term: str, text: str) -> bool:
    if re.fullmatch(r"[\w ]+", term):
        return re.search(rf"\b{re.escape(term)}\b", text) is not None
    return term in text


def _cleanup(client, cid):
    client.delete(f"/contacts/{cid}")


# --------------------------------------------------------------- golden (C1, C4, C5)

def test_golden_example(client, model_ready):
    c, elapsed = _enrich(client, GOLDEN_NAME, GOLDEN_NOTES, "golden")
    try:
        e = c["enrichment"]
        problems = []
        if not (e["role"]["value"] and "partnership" in e["role"]["value"].lower() and e["role"]["confidence"] == "stated"):
            problems.append(f"role {e['role']}")
        comp = (e["company"]["value"] or "").lower()
        if not ("payment" in comp and "stripe" in comp and e["company"]["confidence"] == "maybe"):
            problems.append(f"company {e['company']}")
        hw = e["how_we_met"]
        if not (hw["value"] and "fintech forward" in hw["value"].lower() and hw["confidence"] == "stated"):
            problems.append(f"how_we_met {hw}")
        if not any("cto" in i["value"].lower() and "bank" in i["value"].lower() and i["confidence"] == "stated"
                   for i in e["what_they_want"]):
            problems.append(f"what_they_want {e['what_they_want']}")
        if not any("biscuit" in i["value"].lower() and i["confidence"] == "stated" for i in e["personal_details"]):
            problems.append(f"personal_details {e['personal_details']}")
        fu = [f for f in e["follow_ups"] if f.get("when_text") and "diwali" in f["when_text"].lower()]
        if not fu or any(f["suggested_date"] is not None for f in fu):
            problems.append(f"follow_ups {e['follow_ups']}")
        gaps = " ".join(e["gaps"]).lower()
        if "company" not in gaps:
            problems.append(f"gaps missing company: {e['gaps']}")
        if "email" not in gaps and "contact" not in gaps:
            problems.append(f"gaps missing email: {e['gaps']}")
        if any(e["contact_info"].values()):
            problems.append(f"contact_info {e['contact_info']}")
        # Hedge must survive into headline/summary when Stripe is mentioned there.
        for k in ("headline", "summary"):
            t = (e.get(k) or "").lower()
            if "stripe" in t and not any(h in t for h in HEDGES):
                problems.append(f"{k} states hedged Stripe claim as fact: {e.get(k)!r}")
        # Search by company and tag (D1) while we have an enriched contact.
        ids = [x["id"] for x in client.get("/contacts", params={"q": "PAYMENTS"}).json()["contacts"]]
        if c["id"] not in ids:
            problems.append("search by company word 'PAYMENTS' did not match")
        if c["tags"]:
            ids = [x["id"] for x in client.get("/contacts", params={"q": c["tags"][0].upper()}).json()["contacts"]]
            if c["id"] not in ids:
                problems.append(f"search by suggested tag {c['tags'][0]!r} did not match")
        else:
            problems.append("suggested_tags were not copied into tags")
        assert not problems, f"golden example mismatches ({elapsed:.1f}s): " + "; ".join(problems)
        assert elapsed < 30, f"golden enrichment took {elapsed:.1f}s (C5 budget 30s)"
    finally:
        _cleanup(client, c["id"])


# --------------------------------------------------------------- C5 typical 300-word notes

TYPICAL_NOTES = (
    "Daniel Okafor. Met him on Tuesday at the Lagos Climate Finance Summit, he was on the panel about "
    "blended finance for solar mini-grids. He is head of investments at Sunbridge Capital, which is a "
    "small impact fund based in Nairobi, though he spends half his time in Lagos. Very sharp, quiet, "
    "asks good questions. He said they are raising a second fund of about 80 million dollars and are "
    "looking for co-investors from Europe, especially family offices that care about climate. He asked "
    "if I knew anyone at the Dutch development bank, FMO. I said I would check with Marieke. "
    "Personal: he has two daughters, the older one just started at university in Toronto. He runs every "
    "morning and is training for the Berlin marathon in September. Loves Fela Kuti and old highlife "
    "records, we talked about record shops in London for ten minutes. He is vegetarian. "
    "He was skeptical about carbon credits, thinks most of them are rubbish, but likes results-based "
    "financing. He mentioned a pilot in northern Nigeria with 40 villages. "
    "Follow-ups: send him the deck from our energy access report by Friday, intro to Marieke at FMO next "
    "week, and maybe invite him to the London roundtable in November. He prefers WhatsApp to email. "
    "I didn't get his number though. Also he said he might be in London in October for a conference, "
    "worth grabbing coffee. He knows my old colleague Priti from the World Bank days. "
    "Overall a strong potential partner for the Africa energy work; would be good to keep warm and share "
    "useful things rather than ask for anything right away."
)


def test_typical_300_words_under_30s(client, model_ready):
    assert len(TYPICAL_NOTES.split()) <= 300
    c, elapsed = _enrich(client, "Daniel Okafor", TYPICAL_NOTES, "typical_300w")
    try:
        e = c["enrichment"]
        assert not any(e["contact_info"].values()), e["contact_info"]
        assert elapsed < 30, f"typical notes took {elapsed:.1f}s (budget 30s)"
    finally:
        _cleanup(client, c["id"])


# --------------------------------------------------------------- hallucination suite (C2, C3, C4)

@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_hallucination_case(client, model_ready, case):
    c, elapsed = _enrich(client, case["name"], case["notes"], f"halluc_{case['id']}")
    try:
        e = c["enrichment"]
        problems = []
        for path in case.get("must_be_null", []):
            if not _is_empty(_get(e, path)):
                problems.append(f"{path} should be null/empty, got {_get(e, path)!r}")
        for path in case.get("null_or_inferred", []):
            if not _null_or_inferred(_get(e, path)):
                problems.append(f"{path} should be null or inferred, got {_get(e, path)!r}")
        blob = json.dumps(e, ensure_ascii=False).lower()
        for term in case.get("forbidden_terms", []):
            if _term_found(term.lower(), blob):
                problems.append(f"forbidden term {term!r} present")
        for term in case.get("hedged_terms", []):
            for k in ("headline", "summary", "suggested_opener"):
                t = (e.get(k) or "").lower()
                if term in t and not any(h in t for h in HEDGES):
                    problems.append(f"{k} states hedged {term!r} as fact: {e.get(k)!r}")
        notes_l = case["notes"].lower()
        for k, v in e["contact_info"].items():
            if v and v.lower() not in notes_l:
                problems.append(f"contact_info.{k} invented: {v!r}")
        assert not problems, f"[{case['id']}] ({elapsed:.1f}s) " + "; ".join(problems)
    finally:
        _cleanup(client, c["id"])


# --------------------------------------------------------------- C7 add note -> re-enrich; D2 edit + re-enrich

def test_add_note_reenrich_reflects_it(client, model_ready):
    from datetime import date

    r = client.post("/contacts", json={"name": "Grace Hopper QA", "raw_notes": "Met at a COBOL meetup.", "enrich": True})
    cid = r.json()["id"]
    try:
        first = wait_until_settled(client, cid)
        assert first["enrichment_status"] == "done", first["enrichment_error"]
        r = client.post(f"/contacts/{cid}/notes", json={"text": "She has a cat named Turing and wants a referral to a Rust tutor."})
        assert r.status_code == 200 and r.json()["enrichment_status"] == "pending"
        assert f"[{date.today().isoformat()}] She has a cat" in r.json()["raw_notes"]
        second = wait_until_settled(client, cid)
        (ART / "c7_add_note.json").write_text(json.dumps(second, ensure_ascii=False, indent=2))
        assert second["enrichment_status"] == "done", second["enrichment_error"]
        blob = json.dumps(second["enrichment"]).lower()
        assert "turing" in blob, "re-enrichment does not reflect the appended note"
        assert second["enriched_at"] > first["enriched_at"]
    finally:
        _cleanup(client, cid)


def test_edit_then_reenrich_updates_card(client, model_ready):
    r = client.post("/contacts", json={"name": "Edit QA", "raw_notes": "Works at Acme Bakery as head baker.", "enrich": True})
    cid = r.json()["id"]
    try:
        first = wait_until_settled(client, cid)
        assert first["enrichment_status"] == "done", first["enrichment_error"]
        p = client.patch(f"/contacts/{cid}", json={"name": "Edited QA", "raw_notes": "Works at Zephyr Robotics as a firmware engineer."})
        assert p.status_code == 200 and p.json()["enrichment_status"] == "done", "PATCH must not auto re-enrich"
        assert client.post(f"/contacts/{cid}/enrich").status_code == 202
        second = wait_until_settled(client, cid)
        (ART / "d2_edit_reenrich.json").write_text(json.dumps(second, ensure_ascii=False, indent=2))
        assert second["name"] == "Edited QA"
        comp = (second["enrichment"]["company"]["value"] or "").lower()
        assert "zephyr" in comp, second["enrichment"]["company"]
        assert "acme" not in json.dumps(second["enrichment"]).lower()
    finally:
        _cleanup(client, cid)


def test_append_while_pending_supersedes(client, model_ready):
    """Contract: appending while pending is allowed; the older run is discarded."""
    r = client.post("/contacts", json={"name": "Supersede QA", "raw_notes": "Enjoys sailing.", "enrich": True})
    cid = r.json()["id"]
    try:
        a = client.post(f"/contacts/{cid}/notes", json={"text": "Owns a boat named Petrel."})
        assert a.status_code == 200 and a.json()["enrichment_status"] == "pending"
        final = wait_until_settled(client, cid)
        assert final["enrichment_status"] == "done", final["enrichment_error"]
        assert "petrel" in json.dumps(final["enrichment"]).lower(), "final card must reflect the newest notes"
    finally:
        _cleanup(client, cid)



# ================================================================== v2: C9, C10, C11, C12, C13 (real model)

HEDGED = next(c for c in CASES if c["id"] == "hedged_everything")


@pytest.mark.parametrize("run", range(1, 6))
def test_c9_c10_hedged_everything(client, model_ready, run):
    c, elapsed = _enrich(client, HEDGED["name"], HEDGED["notes"], f"v2_hedged_run{run}")
    try:
        e = c["enrichment"]
        comp = e["company"]
        assert comp["value"] is None or comp["confidence"] == "maybe", f"C9: company {comp}"
        loc = e["location"]
        assert loc["value"] is None or loc["confidence"] == "maybe", f"C9: location {loc}"
        op = (e["suggested_opener"] or "").lower()
        assert "google" not in op and "london" not in op and "ads" not in op.split(), f"C10 opener: {e['suggested_opener']!r}"
    finally:
        _cleanup(client, c["id"])


C11_NOTES = ("Head of investments at Sunbridge Capital. Send him the deck by Friday. "
             "Maybe invite him to the London roundtable in November.")


@pytest.mark.parametrize("run", range(1, 4))
def test_c11_follow_up_with_timing_not_dropped(client, model_ready, run):
    c, _ = _enrich(client, "Daniel Fri QA", C11_NOTES, f"v2_c11_run{run}")
    try:
        fus = c["enrichment"]["follow_ups"]
        fri = [f for f in fus if "friday" in f"{f['action']} {f['when_text'] or ''}".lower()]
        assert fri, f"'by Friday' follow-up dropped: {[(f['action'], f['when_text']) for f in fus]}"
        assert fri[0]["date_status"] == "exact" and "deck" in fri[0]["action"].lower()
        nov = [f for f in fus if "november" in f"{f['action']} {f['when_text'] or ''}".lower()]
        assert nov and nov[0]["date_status"] == "needs_date" and nov[0]["confidence"] == "maybe", nov
    finally:
        _cleanup(client, c["id"])


C12_NOTES = (
    "Omar Dates. Met at the co-working space. Send him the deck by Friday. Call him tomorrow about the lease. "
    "Email the contract in 3 days. Review his pitch on Nov 2. Follow up after Diwali about the office. "
    "Maybe invite him to the dinner in November. Ask how the demo went since last Friday. "
    "Ask about the May 5 recap of the launch. Get his phone number."
)


def test_c12_date_classification_real_model(client, model_ready):
    from datetime import date, timedelta

    today = date.today()
    fri = today + timedelta(days=((4 - today.weekday()) % 7) or 7)
    nov2 = date(today.year if (today.month, today.day) <= (11, 2) else today.year + 1, 11, 2)
    expect = {
        "deck": ("exact", fri.isoformat()),
        "lease": ("exact", (today + timedelta(days=1)).isoformat()),
        "contract": ("exact", (today + timedelta(days=3)).isoformat()),
        "pitch": ("exact", nov2.isoformat()),
        "office": ("needs_date", None),
        "dinner": ("needs_date", None),
        "demo": ("past", None),
        "recap": ("past", None),
        "phone": ("none", None),
    }
    c, _ = _enrich(client, "Omar Dates", C12_NOTES, "v2_c12")
    try:
        fus = c["enrichment"]["follow_ups"]
        got = {}
        for k in expect:
            m = [f for f in fus if k in f"{f['action']} {f['when_text'] or ''}".lower()]
            got[k] = (m[0]["date_status"], m[0]["suggested_date"]) if m else None
        present = {k: v for k, v in got.items() if v is not None}
        wrong = {k: (v, expect[k]) for k, v in present.items() if v != expect[k]}
        print("C12 follow-ups:", [(f["action"], f["when_text"], f["date_status"], f["suggested_date"]) for f in fus])
        print("C12 missing (max 5 follow-ups):", [k for k, v in got.items() if v is None])
        assert not wrong, f"misclassified: {wrong}"
    finally:
        _cleanup(client, c["id"])


C13_CASES = {
    # place accepted in either script (approved v2 round 2)
    "pune_lives": ("प्रिया वर्मा", "पुणे में रहती है। पुणे में एक मीटअप में मिले। वह एक डॉक्टर है।", ("pune", "पुणे")),
    "mumbai_lives_delhi_met": ("नेहा जैन", "मुंबई में रहती है। दिल्ली में एक शादी में मिले।", ("mumbai", "मुंबई")),
    "jaipur_from": ("राहुल मीणा", "वह जयपुर से है। जयपुर में एक कॉन्फ्रेंस में मिले। इंजीनियर है।", ("jaipur", "जयपुर")),
    "lucknow_rehne_wali": ("सीमा", "लखनऊ की रहने वाली है। लखनऊ में शादी में मिले।", ("lucknow", "लखनऊ")),
}


@pytest.mark.parametrize("key", list(C13_CASES))
def test_c13_hindi_residence_keeps_location(client, model_ready, key):
    name, notes, place = C13_CASES[key]
    c, _ = _enrich(client, name, notes, f"v2_c13_{key}")
    try:
        loc = c["enrichment"]["location"]
        assert loc["value"] and any(p in loc["value"].lower() for p in place), f"location dropped/wrong: {loc}"
    finally:
        _cleanup(client, c["id"])



C12_SPLIT = [
    ("Omar A", "Met Omar at the co-working space. Send him the deck by Friday. Review his pitch on Nov 2. "
               "Follow up after Diwali about the office. Ask how the demo went since last Friday."),
    ("Omar B", "Met Omar at a meetup. Call him tomorrow about the lease. Email the contract in 3 days. "
               "Maybe invite him to the dinner in November. Ask about the May 5 recap of the launch. Get his phone number."),
]


@pytest.mark.parametrize("idx", [0, 1])
def test_c12_split_under_cap(client, model_ready, idx):
    """Same phrases as test_c12_date_classification_real_model, at most 5 per note (the follow-up cap)."""
    from datetime import date, timedelta

    today = date.today()
    fri = today + timedelta(days=((4 - today.weekday()) % 7) or 7)
    nov2 = date(today.year if (today.month, today.day) <= (11, 2) else today.year + 1, 11, 2)
    expect = [
        {"deck": ("exact", fri.isoformat()), "pitch": ("exact", nov2.isoformat()), "office": ("needs_date", None),
         "demo": ("past", None)},
        {"lease": ("exact", (today + timedelta(days=1)).isoformat()), "contract": ("exact", (today + timedelta(days=3)).isoformat()),
         "dinner": ("needs_date", None), "recap": ("past", None), "phone": ("none", None)},
    ][idx]
    name, notes = C12_SPLIT[idx]
    c, _ = _enrich(client, name, notes, f"v2_c12_split{idx}")
    try:
        fus = c["enrichment"]["follow_ups"]
        print("C12 split", idx, [(f["action"], f["when_text"], f["date_status"], f["suggested_date"]) for f in fus])
        problems = {}
        for k, want in expect.items():
            m = [f for f in fus if k in f"{f['action']} {f['when_text'] or ''}".lower()]
            got = (m[0]["date_status"], m[0]["suggested_date"]) if m else "MISSING"
            if got != want and not (got == "MISSING" and want[0] in ("past", "none")):
                problems[k] = (got, want)
        assert not problems, problems
    finally:
        _cleanup(client, c["id"])


DATED_TODOS = {
    "offsite": ("Sam Ortiz", "Sam Ortiz, VP sales at Quanta. Invite him to our offsite on Nov 3.", "offsite", (11, 3)),
    "proposal": ("Lea Moss", "Lea Moss, buyer at Cora. Submit the proposal to her by Nov 30.", "proposal", (11, 30)),
    "wedding": ("Anya Roy", "Anya Roy, my old manager. Attend her wedding on Dec 12 in Goa.", "wedding", (12, 12)),
}


@pytest.mark.parametrize("key", list(DATED_TODOS))
def test_c11_dated_todo_with_uncommon_verb_kept(client, model_ready, key):
    """V2-BUG-10: real to-dos with an explicit date must not be deleted by the non-to-do rule."""
    from datetime import date

    name, notes, word, (m, d) = DATED_TODOS[key]
    t = date.today()
    want = date(t.year, m, d) if date(t.year, m, d) >= t else date(t.year + 1, m, d)
    c, _ = _enrich(client, name, notes, f"v2r3_todo_{key}")
    try:
        fus = c["enrichment"]["follow_ups"]
        hit = [f for f in fus if word in f"{f['action']} {f['when_text'] or ''}".lower()]
        assert hit and hit[0]["date_status"] == "exact" and hit[0]["suggested_date"] == want.isoformat(), fus
    finally:
        _cleanup(client, c["id"])
