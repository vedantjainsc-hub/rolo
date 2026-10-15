"""Break-it tests for the round-3 deterministic guards (no model needed).

Run with the BACKEND venv, because these import backend code directly:
    cd tests && ../backend/.venv/bin/python -m pytest guards -q -p no:cacheprovider
Each case states what a correct card should contain; a failure is a guard regression.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.enrichment.dates import resolve_date  # noqa: E402
from app.enrichment.service import apply_guards  # noqa: E402
from app.models import Enrichment  # noqa: E402

TODAY = date(2026, 10, 14)  # Wednesday


def _card(**kw) -> Enrichment:
    base = {"headline": "h", "summary": "s", "gaps": [], "contact_info": {}}
    base.update(kw)
    return Enrichment.model_validate(base)


# ------------------------------------------------------------------ BUG-11 dates

@pytest.mark.parametrize("when,expected", [
    ("by Friday", "2026-10-16"),
    ("Friday", "2026-10-16"),
    ("next Monday", "2026-10-19"),
    ("tomorrow", "2026-10-15"),
    ("day after tomorrow", "2026-10-16"),
    ("in 3 days", "2026-10-17"),
    ("in a week", "2026-10-21"),
    ("in two weeks", "2026-10-28"),
    ("next week", "2026-10-19"),
    ("next month", "2026-11-01"),
    ("on 2026-11-02", "2026-11-02"),
    ("Nov 2", "2026-11-02"),
    ("2 November", "2026-11-02"),
    ("March 3", "2027-03-03"),
    ("tonight", "2026-10-14"),
    ("next Wednesday", "2026-10-21"),
    ("after Diwali", None),
    ("in November", None),
    ("after the conference", None),
    ("soon", None),
    ("maybe in November", None),
    ("November 2026", None),
    ("sometime next year", None),
])
def test_resolve_date(when, expected):
    got = resolve_date(when, TODAY)
    assert (got.isoformat() if got else None) == expected


@pytest.mark.parametrize("when", ["maybe next week", "possibly Friday", "I think tomorrow"])
def test_hedged_timing_still_resolves(when):
    assert resolve_date(when, TODAY) is not None


def test_model_date_is_ignored_and_recomputed():
    e = _card(follow_ups=[{"action": "Send deck", "when_text": "by Friday", "suggested_date": "2026-10-17"}])
    assert apply_guards(e, "Send deck by Friday", TODAY).follow_ups[0].suggested_date == "2026-10-16"


@pytest.mark.parametrize("action", [
    "Send the Friday report",          # 'Friday' is part of a noun, not a time
    "Ask about the May 5 launch recap",  # past event mentioned in the action
])
def test_action_without_timing_should_not_get_a_date(action):
    e = _card(follow_ups=[{"action": action, "when_text": None, "suggested_date": None}])
    assert apply_guards(e, action, TODAY).follow_ups[0].suggested_date is None


def test_past_reference_not_turned_into_future():
    assert resolve_date("since last Friday", TODAY) is None


# ------------------------------------------------------------------ BUG-9 location guard

def _loc(notes, loc, met=None):
    e = _card(location={"value": loc, "confidence": "stated"}, how_we_met={"value": met, "confidence": "stated"})
    return apply_guards(e, notes, TODAY).location.value


@pytest.mark.parametrize("notes,loc,met", [
    ("Chatted in the hotel lobby in Tokyo while waiting for a taxi.", "Tokyo", "In the hotel lobby in Tokyo"),
    ("दिल्ली में एक शादी में मिले।", "Delhi", "A wedding in Delhi"),
    ("Met at my cousin's wedding in Pune.", "Pune", "Cousin's wedding in Pune"),
    ("Met at the Lagos Climate Finance Summit.", "Lagos", "Lagos Climate Finance Summit"),
])
def test_meeting_place_is_nulled(notes, loc, met):
    assert _loc(notes, loc, met) is None


@pytest.mark.parametrize("notes,loc,met", [
    ("Lives in Berlin. Met her at a Berlin meetup.", "Berlin", "Berlin meetup"),
    ("She's based in Paris. Met at a conference in Paris.", "Paris", "Conference in Paris"),
    ("Met him in Austin; he's Austin-based.", "Austin", "In Austin"),
    ("Bangalore mein rehti hai. Bangalore mein mile.", "Bangalore", "In Bangalore"),
    ("From Mumbai. Met in Mumbai at Diwali party.", "Mumbai", "Diwali party in Mumbai"),
    ("Met her in London, where she lives.", "London", "In London"),
    ("Met at her flat in Brooklyn for dinner.", "Brooklyn", "Dinner at her flat in Brooklyn"),
    ("Met at his office in Zurich. He runs the Zurich team.", "Zurich", "At his office in Zurich"),
    ("पुणे में रहती है। पुणे में मिले।", "Pune", "In Pune"),
    ("Met at a meetup. Lives in Lisbon.", "Lisbon", "A meetup"),
    ("Lives in New York. Met at a NYC dinner.", "New York", "NYC dinner"),
])
def test_real_location_is_kept(notes, loc, met):
    assert _loc(notes, loc, met) == loc


# ------------------------------------------------------------------ role guard

def _role(role, company, notes):
    e = _card(role={"value": role, "confidence": "stated"}, company={"value": company, "confidence": "stated"})
    out = apply_guards(e, notes, TODAY)
    return out.role.value, out.gaps


@pytest.mark.parametrize("role,company,notes", [
    ("Works at Sony", "Sony", "Works at Sony."),
    ("Sony", "Sony", "Works at Sony."),
    ("Employed by Deloitte", "Deloitte", "Employed by Deloitte."),
])
def test_non_title_role_is_nulled_with_gap(role, company, notes):
    value, gaps = _role(role, company, notes)
    assert value is None and "Job title" in gaps


@pytest.mark.parametrize("role,company,notes", [
    ("Product manager", "Google", "Product manager at Google."),
    ("Head of Investments", "Sunbridge Capital", "Head of investments at Sunbridge Capital."),
    ("Partner", "Partner Capital Group", "She's a partner at Partner Capital Group."),
    ("Founder", "Founders Fund", "Founder, invests via Founders Fund."),
    ("Engineer", "Engineering Ltd", "Engineer at Engineering Ltd."),
    ("Works at Google as a product manager", "Google", "Works at Google as a product manager."),
    ("Owner", "Owner's Bakery", "Owner of Owner's Bakery."),
    ("Chief of staff", "Stripe", "Works for the CEO at Stripe as chief of staff."),
])
def test_real_role_is_kept(role, company, notes):
    value, _ = _role(role, company, notes)
    assert value is not None, f"real job title {role!r} was nulled"


# ------------------------------------------------------------------ round 4: edge probes for the new cues

@pytest.mark.parametrize("notes,loc,met", [
    # Lives elsewhere; the model wrongly gives the meeting city -> must still be nulled.
    ("Met at a conference in Berlin. She lives in Paris.", "Berlin", "Conference in Berlin"),
    ("Met at a Tokyo hotel, she flew in from London.", "Tokyo", "Tokyo hotel"),
    # Hindi: lives in Mumbai, met in Delhi; model says Delhi -> should be nulled.
    ("मुंबई में रहती है। दिल्ली में एक शादी में मिले।", "Delhi", "A wedding in Delhi"),
])
def test_meeting_city_still_nulled_when_residence_is_elsewhere(notes, loc, met):
    assert _loc(notes, loc, met) is None


def test_role_from_works_at_as_title_is_extracted():
    value, gaps = _role("Works at Google as a product manager", "Google", "Works at Google as a product manager.")
    assert value and "product manager" in value.lower() and "Job title" not in gaps



# ================================================================== v2 (ENRICHMENT.md v2)

from app.enrichment.followups import classify  # noqa: E402
from app.models import FollowUp  # noqa: E402


@pytest.mark.parametrize("action,when,status,date_", [
    ("Send him the deck", "by Friday", "exact", "2026-10-16"),
    ("Call about the lease", "tomorrow", "exact", "2026-10-15"),
    ("Send the contract", "in 3 days", "exact", "2026-10-17"),
    ("Review his pitch", "Nov 2", "exact", "2026-11-02"),
    ("Follow up", "after Diwali", "needs_date", None),
    ("Invite to London roundtable", "in November", "needs_date", None),
    ("Ask how the demo went", "since last Friday", "past", None),
    ("Ask about the May 5 launch recap", None, "past", None),
    ("Ask about the launch", "May 5 recap", "past", None),
    ("Send the Friday report", None, "none", None),
    ("Get his number", None, "none", None),
])
def test_c12_classification(action, when, status, date_):
    fu = classify(FollowUp(action=action, when_text=when), TODAY, "")
    assert (fu.date_status, fu.suggested_date) == (status, date_)


def test_c12_hedged_timing_is_maybe():
    fu = classify(FollowUp(action="Invite him to the London roundtable", when_text="maybe in November"), TODAY,
                  "Maybe invite him to the London roundtable in November.")
    assert fu.date_status == "needs_date" and fu.confidence == "maybe"


def test_c11_scan_restores_dropped_follow_up():
    notes = "Head of investments at Sunbridge Capital. Send him the deck by Friday. Maybe invite him to the London roundtable in November."
    e = _card(follow_ups=[{"action": "Invite to London roundtable", "when_text": "in November"}])
    out = apply_guards(e, notes, TODAY)
    fri = [f for f in out.follow_ups if f.when_text and "friday" in f.when_text.lower()]
    assert fri and fri[0].date_status == "exact" and fri[0].suggested_date == "2026-10-16", out.follow_ups


@pytest.mark.parametrize("notes,loc,met", [
    ("पुणे में रहती है। पुणे में एक मीटअप में मिले।", "Pune", "A meetup in Pune"),
    ("पुणे में रहते हैं। पुणे में मिले।", "Pune", "In Pune"),
    ("वह पुणे की रहने वाली है। पुणे में मिले।", "Pune", "In Pune"),
    ("वह पुणे का रहने वाला है। पुणे में मिले।", "Pune", "In Pune"),
    ("वह पुणे से है। पुणे में मिले।", "Pune", "In Pune"),
    ("मुंबई में काम करती है। मुंबई में मिले।", "Mumbai", "In Mumbai"),
    ("दिल्ली में रहता है। दिल्ली में शादी में मिले।", "Delhi", "A wedding in Delhi"),
])
def test_c13_hindi_residence_keeps_location(notes, loc, met):
    assert _loc(notes, loc, met) == loc


# ------------------------------------------------------------------ v2 maybe label

def _maybe_company(notes, value):
    e = _card(company={"value": value, "confidence": "maybe"})
    return apply_guards(e, notes, TODAY).company.confidence


@pytest.mark.parametrize("notes,value", [
    ("Runs partnerships at a payments startup, I think Stripe-adjacent.", "A payments startup, possibly Stripe-adjacent"),
    ("Runs partnerships at a payments startup, I think\nStripe-adjacent.", "A payments startup, possibly Stripe-adjacent"),
    ("I think he works at Google,\nmaybe in ads.", "Google"),
    ("Works at a bank, maybe\nHSBC.", "A bank, possibly HSBC"),
])
def test_hedge_survives_line_breaks(notes, value):
    """Notes typed on a phone wrap lines anywhere; a line break must not cancel the hedge."""
    assert _maybe_company(notes, value) == "maybe"


def test_unhedged_maybe_is_upgraded():
    assert _maybe_company("Works at Acme Robotics. I think he likes jazz.", "Acme Robotics") == "stated"


# ------------------------------------------------------------------ v2 opener guard (C10)

@pytest.mark.parametrize("opener", [
    "Hi Rahul, curious about your work at Google.",
    "Hope the move to London goes well!",
    "Great to hear about your role at a payments startup, possibly Stripe-adjacent.",
])
def test_opener_with_unconfirmed_fact_is_replaced(opener):
    notes = "I think he works at Google, maybe something in ads? Possibly moving to London next year. Into marathon running."
    e = _card(company={"value": "Google", "confidence": "maybe"},
              location={"value": "London", "confidence": "maybe"},
              personal_details=[{"value": "Possibly moving to London next year", "confidence": "maybe"}],
              how_we_met={"value": None, "confidence": "stated"},
              suggested_opener=opener)
    out = apply_guards(e, notes, TODAY)
    assert "google" not in out.suggested_opener.lower() and "london" not in out.suggested_opener.lower()


def test_opener_with_only_stated_facts_kept():
    notes = "Met at Fintech Forward. Wants intros to bank CTOs."
    e = _card(how_we_met={"value": "Fintech Forward", "confidence": "stated"},
              suggested_opener="Great meeting you at Fintech Forward. Happy to help with bank CTO intros.")
    assert apply_guards(e, notes, TODAY).suggested_opener.startswith("Great meeting you at Fintech Forward. Happy")


# ------------------------------------------------------------------ v2 name from voice

@pytest.mark.parametrize("person_name,notes,expected", [
    ("Priya Shah", "This is Priya Shah. Met at Fintech Forward.", "Priya Shah"),
    ("Priya Shah", "Met someone at Fintech Forward.", None),          # not said -> not used
    ("Satya Nadella", "Met a guy who looks like a famous CEO.", None),
])
def test_person_name_only_if_in_notes(person_name, notes, expected):
    e = _card(person_name=person_name)
    assert apply_guards(e, notes, TODAY).person_name == expected


# ================================================================== v2 round 2: break-it on the new guards

def _fus_after(notes, model_fus=()):
    e = _card(follow_ups=list(model_fus))
    return [(f.action, f.when_text, f.date_status, f.suggested_date) for f in apply_guards(e, notes, TODAY).follow_ups]


# --- explicit-date scan (V2-BUG-5 fix) must not invent follow-ups from non-action dates

@pytest.mark.parametrize("notes", [
    "Joined Stripe on 2024-03-01. Runs partnerships.",
    "Raised their Series A on Sep 3. Growing fast.",
    "Born on 1990-05-04 in Pune.",
    "Her birthday is on Nov 2.",
    "Moved to London on 2025-06-01.",
    "Graduated from IIT on May 20, 2015.",
])
def test_scan_no_follow_up_from_non_action_dates(notes):
    assert _fus_after(notes) == [], "a date that is not something to do was turned into a follow-up"


@pytest.mark.parametrize("notes,expect", [
    ("Review his pitch on Nov 2.", ("exact", "2026-11-02")),
    ("Demo day is on 2026-11-20, worth attending.", ("exact", "2026-11-20")),
])
def test_scan_keeps_real_explicit_dates(notes, expect):
    fus = _fus_after(notes)
    assert fus and (fus[0][2], fus[0][3]) == expect, fus


# --- V2-BUG-2 fix: past items never cover future phrases, and a future item still covers itself

def test_scan_past_item_does_not_hide_future():
    notes = "Send him the deck by Friday. Ask him how the demo went last Friday."
    fus = _fus_after(notes, [{"action": "Ask how the demo went", "when_text": "last Friday"}])
    assert any(w == "by Friday" and s == "exact" for _, w, s, _d in fus), fus


def test_scan_no_duplicate_when_model_already_has_it():
    notes = "Send him the deck by Friday."
    fus = _fus_after(notes, [{"action": "Send the deck", "when_text": "by Friday"}])
    assert len(fus) == 1, fus


# --- contact-info shapes (V2-BUG-4 fix): false positives and false negatives

@pytest.mark.parametrize("key,value,notes,kept", [
    ("email", "priya@stripe.com", "Email: priya@stripe.com", True),
    ("email", "priya.shah@sub.example.co.uk", "mail priya.shah@sub.example.co.uk", True),
    ("phone", "+1 (415) 555-0100", "Call +1 (415) 555-0100", True),
    ("phone", "98765 43210", "Number 98765 43210", True),
    ("phone", "+44 20 7946 0958 ext 12", "Phone +44 20 7946 0958 ext 12", True),
    ("linkedin", "linkedin.com/in/priyashah", "linkedin.com/in/priyashah", True),
    ("linkedin", "https://www.linkedin.com/in/priya-shah-123/", "see https://www.linkedin.com/in/priya-shah-123/", True),
    ("linkedin", "priya-shah-123", "LinkedIn: priya-shah-123", True),
    # should be rejected
    ("linkedin", "probably under his full name", "His LinkedIn is probably under his full name", False),
    ("phone", "2026-11-02", "Review his pitch on 2026-11-02", False),
    ("phone", "10/14/2026", "Met on 10/14/2026", False),
    ("email", "his work address", "email his work address", False),
])
def test_contact_info_shapes(key, value, notes, kept):
    e = _card(contact_info={key: value})
    got = getattr(apply_guards(e, notes, TODAY).contact_info, key)
    assert (got is not None) == kept, f"{key}={value!r} kept={got is not None}"


# --- hedge upgrade (V2-BUG-1 fix): no false 'stated' and no lost upgrades

_V2BUG9 = pytest.mark.xfail(reason="V2-BUG-9 deferred (over-cautious only)", strict=False)


@pytest.mark.parametrize("notes,value,expected", [
    ("Runs partnerships at a payments startup, I think\nStripe-adjacent.", "A payments startup, possibly Stripe-adjacent", "maybe"),
    pytest.param("- Works at Acme Robotics\n- maybe moving to Berlin", "Acme Robotics", "stated", marks=_V2BUG9),
    pytest.param("Works at Acme Robotics\nMaybe moving to Berlin", "Acme Robotics", "stated", marks=_V2BUG9),
    ("Not sure about lunch. Works at Acme Robotics.", "Acme Robotics", "stated"),
    ("Works at Acme Robotics. I think he likes jazz.", "Acme Robotics", "stated"),
    ("I think he works at Acme Robotics.", "Acme Robotics", "maybe"),
    ("Works at a bank, maybe\nHSBC.", "A bank, possibly HSBC", "maybe"),
])
def test_hedge_upgrade_cases(notes, value, expected):
    assert _maybe_company(notes, value) == expected


# ================================================================== v2 round 3: false negatives of the non-to-do rule

REAL_TODOS = [
    ("Visit his office on Nov 5.", "Visit his office", "on Nov 5", "2026-11-05"),
    ("Dinner with Omar on Nov 8.", "Dinner with Omar", "on Nov 8", "2026-11-08"),
    ("Attend her wedding on Dec 12.", "Attend her wedding", "on Dec 12", "2026-12-12"),
    ("Invite him to the offsite on Nov 3.", "Invite him to the offsite", "on Nov 3", "2026-11-03"),
    ("Submit the proposal by Nov 30.", "Submit the proposal", "by Nov 30", "2026-11-30"),
    ("Pay the invoice on 2026-11-30.", "Pay the invoice", "on 2026-11-30", "2026-11-30"),
    ("Interview with their CTO on Nov 4.", "Interview with their CTO", "on Nov 4", "2026-11-04"),
    ("Pick him up from the airport on Nov 6.", "Pick him up from the airport", "on Nov 6", "2026-11-06"),
    ("Ask for the signed contract by Nov 20.", "Ask for the signed contract", "by Nov 20", "2026-11-20"),
]


@pytest.mark.parametrize("notes,action,when,d", REAL_TODOS, ids=[r[1] for r in REAL_TODOS])
def test_model_todo_with_date_is_kept(notes, action, when, d):
    """The model got it right; the guard must not delete it."""
    fus = _fus_after(notes, [{"action": action, "when_text": when}])
    assert any(a == action and s == "exact" and dd == d for a, _w, s, dd in fus), fus


_OFF_LIST = pytest.mark.xfail(reason="informational: verb not on the spec action-cue list", strict=False)
_SCAN_CASES = [pytest.param(*r, id=r[1], marks=_OFF_LIST) if r[1].split()[0] in ("Dinner", "Ask") else pytest.param(*r, id=r[1])
               for r in REAL_TODOS]


@pytest.mark.parametrize("notes,action,when,d", _SCAN_CASES)
def test_scan_restores_dropped_todo_with_date(notes, action, when, d):
    """The model dropped it; the backstop should restore it (informational: spec only scans listed cues)."""
    fus = _fus_after(notes)
    assert any(s == "exact" and dd == d for _a, _w, s, dd in fus), fus


@pytest.mark.parametrize("notes,action,when", [
    ("Raised their Series A on Sep 3. Growing fast.", "Raised their Series A", "on Sep 3"),
    ("Her birthday is on Nov 12.", "Her birthday", "on Nov 12"),
])
def test_model_non_todo_dropped(notes, action, when):
    assert _fus_after(notes, [{"action": action, "when_text": when}]) == []


def test_model_past_dated_followup_kept_as_past():
    """Lead ruling: a model follow-up from a past-dated sentence is kept and shown as past."""
    notes = "Joined Stripe on 2024-03-01."
    fus = _fus_after(notes, [{"action": "Ask how joining Stripe went", "when_text": "on 2024-03-01"}])
    assert fus and fus[0][2] == "past", fus


@pytest.mark.parametrize("key,value,notes,kept", [
    ("phone", "+44 20 7946 0958 x12", "Phone +44 20 7946 0958 x12", True),
    ("phone", "14.10.2026", "Met on 14.10.2026", False),
    ("phone", "2026/11/02", "deadline 2026/11/02", False),
    ("phone", "1234567", "Room code 1234567", True),  # shape-valid; accepted by design (literal in notes)
    ("linkedin", "@priyashah", "LinkedIn: @priyashah", True),
    ("linkedin", "priyashah", "find her on LinkedIn as priyashah", True),
    ("linkedin", "priyashah", "Her dog is called priyashah", False),
])
def test_contact_info_shapes_round3(key, value, notes, kept):
    e = _card(contact_info={key: value})
    got = getattr(apply_guards(e, notes, TODAY).contact_info, key)
    assert (got is not None) == kept, f"{key}={value!r} kept={got is not None}"



# ================================================================== v2 round 4: "model follow-ups kept by default"

@pytest.mark.parametrize("notes,action,when", [
    ("Need to call her before she's married on Dec 5.", "Call her", "on Dec 5"),
    ("Remember to send flowers for her birthday on Nov 12.", "Send flowers for her birthday", "on Nov 12"),
    ("They launched v2 on Nov 20; we should demo our integration that day.", "Demo our integration", "on Nov 20"),
])
def test_todo_in_sentence_with_fact_cue_is_kept(notes, action, when):
    fus = _fus_after(notes, [{"action": action, "when_text": when}])
    assert fus and fus[0][2] == "exact", fus


@pytest.mark.parametrize("notes,action,when", [
    ("Joined Stripe on 2024-03-01.", "Joined Stripe", "on 2024-03-01"),
    ("Raised their Series A on Sep 3, 2025.", "Raised their Series A", "on Sep 3, 2025"),
])
def test_past_fact_from_model_kept_as_past(notes, action, when):
    fus = _fus_after(notes, [{"action": action, "when_text": when}])
    assert fus and fus[0][2] == "past", fus
