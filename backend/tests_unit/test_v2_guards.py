"""v2 deterministic guards: maybe label, opener, person_name, follow-up scan and
classification (BUG-14/15/16), Hindi residence cues (BUG-17), prompt = doc."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from app.enrichment import prompt
from app.enrichment.followups import classify, extract_timing, scan_follow_ups
from app.enrichment.service import apply_guards, neutral_opener
from app.models import Enrichment, FollowUp

TODAY = date(2026, 10, 14)  # Wednesday
DOC = (Path(__file__).resolve().parents[2] / "docs" / "ENRICHMENT.md").read_text()


def E(**kw) -> Enrichment:
    return Enrichment.model_validate(kw)


def G(notes: str, **kw) -> Enrichment:
    return apply_guards(E(**kw), notes, TODAY)


# ---- prompt and schema copied exactly from ENRICHMENT.md v2 -----------------------

def test_system_prompt_equals_doc():
    assert prompt.SYSTEM_PROMPT == DOC.split("System:\n```\n")[1].split("\n```")[0]


def test_user_prompt_and_readable_schema_equal_doc():
    assert prompt.USER_PROMPT == DOC.split("User:\n```\n")[1].split("\n```")[0]
    assert prompt.SCHEMA_JSON_TEXT == DOC.split("## JSON schema\n\n```json\n")[1].split("\n```")[0]
    assert prompt.UNKNOWN_NAME == "(not given — take it from the notes if said)"


def test_person_line_for_unnamed_voice_contact():
    named = prompt.build_messages("Priya Shah", "notes", TODAY)[1]["content"]
    unnamed = prompt.build_messages(None, "notes", TODAY)[1]["content"]
    assert named.startswith("Person: Priya Shah\n")
    assert unnamed.startswith("Person: (not given — take it from the notes if said)\n")


def test_format_schema_has_maybe_and_person_name():
    props = prompt.FORMAT_SCHEMA["properties"]
    assert props["role"]["properties"]["confidence"]["enum"] == ["stated", "maybe", "inferred"]
    assert props["interests"]["items"]["properties"]["confidence"]["enum"] == ["stated", "maybe", "inferred"]
    assert props["person_name"] == {"type": ["string", "null"]}
    assert "person_name" in prompt.FORMAT_SCHEMA["required"]


# ---- maybe label ---------------------------------------------------------------------

def test_maybe_confidence_is_kept_and_unknown_becomes_inferred():
    e = E(company={"value": "A bank, possibly HSBC", "confidence": "maybe"},
          interests=[{"value": "jazz", "confidence": "MAYBE"}, {"value": "golf", "confidence": "certain"}])
    assert e.company.confidence == "maybe"
    assert [i.confidence for i in e.interests] == ["maybe", "inferred"]


def test_company_not_in_notes_still_downgraded_to_inferred():
    e = G("Works at a bank.", company={"value": "Goldman Sachs", "confidence": "maybe"})
    assert e.company.confidence == "inferred"


# ---- person_name guard -----------------------------------------------------------------

def test_person_name_kept_only_if_in_notes():
    assert G("This is Priya Shah, met at a meetup.", person_name="Priya Shah").person_name == "Priya Shah"
    assert G("this is PRIYA shah", person_name="Priya Shah").person_name == "Priya Shah"
    assert G("Met a founder at a meetup.", person_name="Elon Musk").person_name is None
    assert G("Met someone.", person_name="  ").person_name is None


# ---- opener guard (BUG-16) -------------------------------------------------------------

NEUTRAL = "Great meeting you. Would love to continue our conversation."


def test_opener_with_maybe_company_is_replaced():
    notes = "Met at a dinner. Works in tech, maybe Google. Likes chess."
    e = G(notes, company={"value": "Google", "confidence": "maybe"},
          how_we_met={"value": "A dinner", "confidence": "stated"},
          suggested_opener="Curious to hear about your work at Google!")
    assert e.suggested_opener == "Great meeting you at A dinner. Would love to continue our conversation."


def test_opener_with_hedged_words_is_replaced():
    notes = "Runs partnerships at a payments startup, I think Stripe-adjacent."
    e = G(notes, company={"value": "A payments startup, possibly Stripe-adjacent", "confidence": "maybe"},
          suggested_opener="Loved hearing about your Stripe work.")
    assert e.suggested_opener == NEUTRAL


def test_opener_with_inferred_full_value_is_replaced():
    e = G("Met at Fintech Forward. Wants intros to bank CTOs.",
          how_i_can_help=[{"value": "Introduce her to fintech investors", "confidence": "inferred"}],
          suggested_opener="Happy to introduce her to fintech investors.")
    assert "Would love to continue" in e.suggested_opener


def test_opener_with_only_stated_facts_is_kept():
    notes = "Priya Shah. Met at Fintech Forward. Runs partnerships at a payments startup, I think Stripe-adjacent. Wants intros to bank CTOs."
    opener = "Great meeting you at Fintech Forward. Happy to help with intros to bank CTOs."
    e = G(notes, how_we_met={"value": "Fintech Forward", "confidence": "stated"},
          what_they_want=[{"value": "Intros to bank CTOs", "confidence": "stated"}],
          how_i_can_help=[{"value": "Provide introductions to bank CTOs", "confidence": "inferred"}],
          company={"value": "A payments startup, possibly Stripe-adjacent", "confidence": "maybe"},
          suggested_opener=opener)
    assert e.suggested_opener == opener


def test_neutral_opener_template():
    assert neutral_opener(E(how_we_met={"value": "at Fintech Forward.", "confidence": "stated"})) == \
        "Great meeting you at Fintech Forward. Would love to continue our conversation."
    assert neutral_opener(E(how_we_met={"value": "Fintech Forward", "confidence": "maybe"})) == NEUTRAL


# ---- follow-up scan (BUG-15) -----------------------------------------------------------

def test_scan_adds_dropped_follow_up_with_timing():
    notes = "Head of investments at Sunbridge Capital. Send him the deck by Friday. Maybe invite him to the London roundtable in November."
    e = G(notes, follow_ups=[{"action": "Invite to London roundtable", "when_text": "maybe in November"}])
    acts = [(f.action, f.when_text, f.date_status, f.suggested_date) for f in e.follow_ups]
    assert ("Send him the deck by Friday", "by Friday", "exact", "2026-10-16") in acts
    assert len(e.follow_ups) == 2


def test_scan_does_not_duplicate_existing_timing():
    notes = "Send him the deck by Friday. Said to follow up after Diwali."
    e = G(notes, follow_ups=[{"action": "Send deck", "when_text": "Friday"},
                             {"action": "Follow up", "when_text": "After Diwali"}])
    assert len(e.follow_ups) == 2


def test_scan_attaches_dropped_timing_to_matching_follow_up():
    e = G("Call him to review the pitch on 2026-11-02.", follow_ups=[{"action": "Review his pitch"}])
    assert [(f.action, f.when_text, f.suggested_date) for f in e.follow_ups] == [
        ("Review his pitch", "on 2026-11-02", "2026-11-02")]


def test_scan_adds_new_when_no_matching_action():
    e = G("Call him to review the pitch on 2026-11-02.", follow_ups=[{"action": "Intro to Sam"}])
    assert [(f.action, f.when_text) for f in e.follow_ups] == [
        ("Intro to Sam", None), ("Call him to review the pitch on 2026-11-02", "on 2026-11-02")]


@pytest.mark.parametrize("notes", [
    "Send the deck by email.",                 # "by email" is not timing
    "Had coffee last Tuesday.",                # past
    "We met at the conference on Friday.",     # no action cue
    "Grabbed lunch yesterday.",
])
def test_scan_ignores_non_follow_ups(notes):
    assert G(notes, follow_ups=[]).follow_ups == []


def test_scan_respects_max_five():
    notes = ("Call him tomorrow. Send the deck by Friday. Email her in 3 days. "
             "Ping Sam next week. Lunch next month. Coffee on Nov 2.")
    e = G(notes, follow_ups=[])
    assert len(e.follow_ups) == 5
    assert all(f.confidence == "stated" for f in e.follow_ups)


# ---- classification (BUG-14, C12) --------------------------------------------------------

@pytest.mark.parametrize("action, when, status, day", [
    ("Send the deck", "by Friday", "exact", "2026-10-16"),
    ("Call", "tomorrow", "exact", "2026-10-15"),
    ("Send the contract", "in 3 days", "exact", "2026-10-17"),
    ("Review pitch", "Nov 2", "exact", "2026-11-02"),
    ("Follow up", "after Diwali", "needs_date", None),
    ("Invite to roundtable", "in November", "needs_date", None),
    ("Invite to roundtable", "maybe in November", "needs_date", None),
    ("Ask how it went", "since last Friday", "past", None),
    ("Discuss", "2 weeks ago", "past", None),
    ("Check in", "yesterday", "past", None),
    ("Review", "on 2025-01-05", "past", None),          # explicit date with a year, already gone
    ("Ask about the May 5 launch recap", None, "past", None),
    ("Discuss what was decided", "was May 5", "past", None),
    ("Send the Friday report", None, "none", None),     # Friday is a noun here
    ("Stay in touch", None, "none", None),
    ("Review his pitch on 2026-11-02", None, "exact", "2026-11-02"),  # timing lifted from action
    ("Follow up after Diwali", None, "needs_date", None),
])
def test_classify(action, when, status, day):
    fu = classify(FollowUp(action=action, when_text=when, suggested_date="2030-01-01"), TODAY)
    assert (fu.date_status, fu.suggested_date) == (status, day)


def test_classify_lifts_timing_into_when_text():
    fu = classify(FollowUp(action="Review his pitch on 2026-11-02"), TODAY)
    assert fu.when_text == "on 2026-11-02"


@pytest.mark.parametrize("action, when, conf", [
    ("Send deck", "by Friday", "stated"),
    ("Invite to roundtable", "maybe in November", "maybe"),
    ("Possibly intro to Sam", None, "maybe"),
    ("Call", "I think tomorrow", "maybe"),
])
def test_follow_up_confidence(action, when, conf):
    assert classify(FollowUp(action=action, when_text=when), TODAY).confidence == conf


def test_model_suggested_date_is_never_trusted():
    e = G("x", follow_ups=[{"action": "Send deck", "when_text": "by Friday", "suggested_date": "2026-10-17"},
                           {"action": "Follow up", "when_text": "after Diwali", "suggested_date": "2026-11-12"}])
    assert [f.suggested_date for f in e.follow_ups] == ["2026-10-16", None]


def test_extract_timing_strict_vs_scan():
    assert extract_timing("Send the Friday report") is None
    assert extract_timing("Send it by Friday") == "by Friday"
    assert extract_timing("Send the Friday report", strict=False) == "Friday"
    assert extract_timing("Follow up after Diwali and then call") == "after Diwali"


# ---- BUG-17 Hindi residence cues -----------------------------------------------------

@pytest.mark.parametrize("notes, loc, met, keep", [
    ("मुंबई में रहती है। दिल्ली में एक शादी में मिले।", "Delhi", "A wedding in Delhi", False),
    ("मुंबई में रहती है। दिल्ली में एक शादी में मिले।", "Mumbai", "A wedding in Delhi", True),
    ("मुंबई में रहती है। मुंबई में एक शादी में मिले।", "Mumbai", "A wedding in Mumbai", True),
    ("पुणे में रहता है। पुणे में एक मीटअप में मिले।", "Pune", "A meetup in Pune", True),
    ("वे दिल्ली में रहते हैं। दिल्ली में मिले।", "Delhi", "In Delhi", True),
    ("पुणे की रहने वाली है। पुणे में मिले।", "Pune", "In Pune", True),
    ("वो दिल्ली से है। दिल्ली में शादी में मिले।", "Delhi", "A wedding in Delhi", True),
    ("बेंगलुरु में काम करती है। बेंगलुरु में मिले।", "Bangalore", "In Bangalore", True),
    ("दिल्ली में एक शादी में मिले।", "Delhi", "A wedding in Delhi", False),
    ("मुंबई में रहती है। दिल्ली में मिले।", "दिल्ली", "दिल्ली में", False),  # Devanagari value
    ("मुंबई में रहती है। मुंबई में मिले।", "मुंबई", "मुंबई में", True),
])
def test_bug17_hindi_residence(notes, loc, met, keep):
    e = G(notes, location={"value": loc, "confidence": "stated"}, how_we_met={"value": met, "confidence": "stated"})
    assert (e.location.value == loc) is keep


def test_follow_up_confidence_from_hedged_source_sentence():
    notes = "Send him the deck by Friday. Maybe invite him to the London roundtable in November."
    e = G(notes, follow_ups=[{"action": "Invite to London roundtable", "when_text": "November"},
                             {"action": "Send deck", "when_text": "by Friday"}])
    assert [f.confidence for f in e.follow_ups] == ["maybe", "stated"]


# ---- maybe upgrade -------------------------------------------------------------------

GOLDEN = ("Priya Shah. Met at Fintech Forward. Runs partnerships at a payments startup, I think "
          "Stripe-adjacent. Wants intros to bank CTOs. Has a dog named Biscuit. Said to follow up after Diwali.")


def test_maybe_upgrade_golden():
    e = G(GOLDEN, role={"value": "Runs partnerships", "confidence": "maybe"},
          company={"value": "Payments startup, possibly Stripe-adjacent", "confidence": "maybe"},
          what_they_want=[{"value": "Intros to bank CTOs", "confidence": "maybe"}])
    assert e.role.confidence == "stated"
    assert e.company.confidence == "maybe"
    assert e.what_they_want[0].confidence == "stated"


@pytest.mark.parametrize("notes, value, expected", [
    ("Works in tech, maybe Google.", "Google", "maybe"),
    ("Designer at a bank, maybe HSBC.", "Designer", "stated"),
    ("Designer at a bank, maybe HSBC.", "A bank, possibly HSBC", "maybe"),
    ("Not sure but she is in London.", "London", "maybe"),
    ("Lives in London. Might move to Paris.", "London", "stated"),
    ("Lives in London. Might move to Paris.", "Paris", "maybe"),
    ("I guess he leads sales.", "Sales lead", "maybe"),
    ("दिल्ली या शायद मुंबई में रहती है।", "मुंबई", "maybe"),
    ("Met at a meetup.", "Google", "maybe"),       # not in the notes at all: no upgrade
])
def test_maybe_upgrade_cases(notes, value, expected):
    e = G(notes, location={"value": value, "confidence": "maybe"})
    assert e.location.value is None or e.location.confidence == expected
    e = G(notes, interests=[{"value": value, "confidence": "maybe"}])
    assert e.interests[0].confidence == expected


def test_maybe_upgrade_never_downgrades_or_touches_inferred():
    e = G("Works in tech, maybe Google.", company={"value": "Google", "confidence": "stated"},
          interests=[{"value": "tech", "confidence": "inferred"}])
    assert e.company.confidence == "stated"
    assert e.interests[0].confidence == "inferred"


# ---- v2 round 1 fixes (QA's exact inputs) ----------------------------------------------

GOLDEN_WRAPPED = ("Priya Shah. Met at Fintech Forward. Runs partnerships at a payments startup, I think\n"
                  "Stripe-adjacent. Wants intros to bank CTOs. Has a dog named Biscuit. Said to follow up after Diwali.")


@pytest.mark.parametrize("notes, value", [
    ("Runs partnerships at a payments startup, I think Stripe-adjacent.", "A payments startup, possibly Stripe-adjacent"),
    ("Runs partnerships at a payments startup, I think\nStripe-adjacent.", "A payments startup, possibly Stripe-adjacent"),
    ("I think he works at Google,\nmaybe in ads.", "Google"),
    ("Works at a bank, maybe\nHSBC.", "A bank, possibly HSBC"),
    ("Works at a bank, maybe\nHSBC.", "HSBC"),                 # value without hedge word, hedge wrapped
    ("Works at a bank. I think.\nHSBC.", "HSBC"),              # hedge ends a sentence -> next clause
    ("Lives in Boston or NYC.", "Boston or NYC"),             # value contains a hedge word
    ("Works at Acme.", "Acme, likely"),
])
def test_v2bug1_hedge_survives_line_breaks(notes, value):
    assert G(notes, company={"value": value, "confidence": "maybe"}).company.confidence == "maybe"


def test_v2bug1_golden_wrapped():
    e = G(GOLDEN_WRAPPED, role={"value": "Runs partnerships", "confidence": "maybe"},
          company={"value": "Payments startup, possibly Stripe-adjacent", "confidence": "maybe"},
          interests=[{"value": "Stripe-adjacent payments", "confidence": "maybe"}])
    assert e.role.confidence == "stated"
    assert e.company.confidence == "maybe"
    assert e.interests[0].confidence == "maybe"


def test_v2bug1_unhedged_maybe_still_upgraded():
    e = G("Works at Acme Robotics. I think he likes jazz.", company={"value": "Acme Robotics", "confidence": "maybe"})
    assert e.company.confidence == "stated"


def test_v2bug1_partial_word_match_is_not_enough():
    e = G("Works at Acme.", company={"value": "Acme Robotics", "confidence": "maybe"})
    assert e.company.confidence == "maybe"


def test_v2bug2_past_mention_does_not_cover_future_timing():
    notes = "Send him the deck by Friday. Ask him how the demo went last Friday."
    e = G(notes, follow_ups=[{"action": "Ask how the demo went", "when_text": "last Friday"}])
    got = [(f.action, f.when_text, f.date_status, f.suggested_date) for f in e.follow_ups]
    assert ("Send him the deck by Friday", "by Friday", "exact", "2026-10-16") in got
    assert ("Ask how the demo went", "last Friday", "past", None) in got
    # a past mention inside the action text doesn't count either
    e = G(notes, follow_ups=[{"action": "Ask him how the demo went last Friday", "when_text": None}])
    assert any(f.when_text == "by Friday" and f.date_status == "exact" for f in e.follow_ups)


def test_v2bug3_devanagari_location_kept_with_hindi_cue():
    notes = "वह जयपुर से है। जयपुर में एक कॉन्फ्रेंस में मिले।"
    for loc, met in [("जयपुर", "जयपुर में एक कॉन्फ्रेंस"), ("Jaipur", "A conference in Jaipur")]:
        e = G(notes, location={"value": loc, "confidence": "stated"}, how_we_met={"value": met, "confidence": "stated"})
        assert e.location.value == loc
    # and still nulled when the cue is for another place
    e = G("वह जयपुर से है। दिल्ली में एक कॉन्फ्रेंस में मिले।", location={"value": "दिल्ली", "confidence": "stated"},
          how_we_met={"value": "दिल्ली में एक कॉन्फ्रेंस", "confidence": "stated"})
    assert e.location.value is None


@pytest.mark.parametrize("field, value, keep", [
    ("linkedin", "probably under his full name", False),       # QA contact_info_bait
    ("linkedin", "linkedin.com/in/raj-mehta", True),
    ("linkedin", "https://www.linkedin.com/in/raj", True),
    ("linkedin", "in/raj-mehta", True),
    ("linkedin", "raj mehta", False),
    ("email", "raj@example.com", True),
    ("email", "raj at example dot com", False),
    ("email", "raj@example", False),
    ("phone", "+1 (415) 555-0199", True),
    ("phone", "415-555-0199", True),
    ("phone", "555-01", False),
    ("phone", "call me later", False),
])
def test_v2bug4_contact_info_shape(field, value, keep):
    notes = f"Contact: {value}. Email him maybe."
    e = G(notes, contact_info={field: value})
    assert (getattr(e.contact_info, field) == value) is keep


@pytest.mark.parametrize("notes, existing, expected", [
    ("Review his pitch on Nov 2.", [], ("Review his pitch on Nov 2", "on Nov 2", "exact", "2026-11-02")),
    ("Review his pitch on Nov 2.", [{"action": "Review his pitch"}], ("Review his pitch", "on Nov 2", "exact", "2026-11-02")),
    ("Board meeting 2026-11-20.", [], ("Board meeting 2026-11-20", "2026-11-20", "exact", "2026-11-20")),
    ("Pitch review 2 November.", [], ("Pitch review 2 November", "2 November", "exact", "2026-11-02")),
])
def test_v2bug5_explicit_date_without_action_cue(notes, existing, expected):
    e = G(notes, follow_ups=existing)
    assert [(f.action, f.when_text, f.date_status, f.suggested_date) for f in e.follow_ups] == [expected]


@pytest.mark.parametrize("notes", [
    "The launch was on Nov 2.",           # past tense near the date
    "Ask about the May 5 launch recap.",  # recap -> past (classified past, not added as future)
    "Met him at the Nov 2 meetup last year.",
])
def test_v2bug5_past_dates_not_added(notes):
    e = G(notes, follow_ups=[])
    assert all(f.date_status == "past" for f in e.follow_ups) or e.follow_ups == []


# ---- v2 round 2: V2-BUG-7 (non-action dates) and V2-BUG-8 (contact shapes) -------------

@pytest.mark.parametrize("notes", [
    "Joined Stripe on 2024-03-01. Runs partnerships.",
    "Raised their Series A on Sep 3. Growing fast.",
    "Born on 1990-05-04 in Pune.",
    "Her birthday is on Nov 2.",
    "Moved to London on 2025-06-01.",
    "Graduated from IIT on May 20, 2015.",
    "Ravi Iyer, CFO at Finlo. Raised their Series A on Sep 3. Her birthday is on Nov 12.",
])
def test_v2bug7_non_action_dates_never_create_follow_ups(notes):
    assert G(notes, follow_ups=[]).follow_ups == []


@pytest.mark.parametrize("notes, expect", [
    ("Review his pitch on Nov 2.", ("exact", "2026-11-02")),
    ("Demo day is on 2026-11-20, worth attending.", ("exact", "2026-11-20")),
    ("Schedule the board meeting on 2026-11-20.", ("exact", "2026-11-20")),
])
def test_v2bug7_real_explicit_dates_still_work(notes, expect):
    fus = G(notes, follow_ups=[]).follow_ups
    assert fus and (fus[0].date_status, fus[0].suggested_date) == expect


def test_v2bug7_no_cue_date_attaches_to_matching_follow_up():
    e = G("Board offsite is on Nov 20. Great team.", follow_ups=[{"action": "Prepare for board offsite"}])
    assert [(f.action, f.when_text, f.suggested_date) for f in e.follow_ups] == [
        ("Prepare for board offsite", "on Nov 20", "2026-11-20")]


def test_v2bug7_model_follow_ups_from_biographical_dates_are_dropped():
    notes = "Ravi Iyer, CFO at Finlo. Raised their Series A on Sep 3. Her birthday is on Nov 12. Send him the deck by Friday."
    e = G(notes, follow_ups=[
        {"action": "Raised their Series A", "when_text": "on Sep 3"},
        {"action": "Her birthday", "when_text": "Nov 12"},
        {"action": "Send him the deck", "when_text": "by Friday"},
    ])
    assert [(f.action, f.date_status) for f in e.follow_ups] == [("Send him the deck", "exact")]


def test_v2bug7_past_mention_kept_as_past():
    e = G("Ask about the May 5 launch recap.", follow_ups=[{"action": "Ask about the May 5 launch recap"}])
    assert [(f.date_status, f.suggested_date) for f in e.follow_ups] == [("past", None)]


@pytest.mark.parametrize("field, value, notes, keep", [
    ("phone", "2026-11-02", "Call on 2026-11-02.", False),
    ("phone", "02/11/2026", "Date 02/11/2026.", False),
    ("phone", "02.11.2026", "Date 02.11.2026.", False),
    ("phone", "+44 20 7946 0958 ext 12", "Phone +44 20 7946 0958 ext 12.", True),
    ("phone", "415-555-0199 x5", "Phone 415-555-0199 x5.", True),
    ("phone", "415.555.0199", "Phone 415.555.0199.", True),
    ("phone", "1234567890123456", "Number 1234567890123456.", False),       # > 15 digits
    ("linkedin", "priya-shah-123", "LinkedIn: priya-shah-123.", True),
    ("linkedin", "priya-shah-123", "Her linkedin is priya-shah-123", True),
    ("linkedin", "priya-shah-123", "Her handle is priya-shah-123", False),   # not labelled LinkedIn
    ("linkedin", "probably under his full name", "LinkedIn is probably under his full name.", False),
])
def test_v2bug8_contact_shapes(field, value, notes, keep):
    e = G(notes, contact_info={field: value})
    assert (getattr(e.contact_info, field) == value) is keep


# ---- v2 round 4: model follow-ups kept by default (V2-BUG-10/11) -------------------------

REAL_TODOS = [
    ("Visit his office on Nov 5.", "Visit his office", "on Nov 5", "2026-11-05"),
    ("Dinner with Omar on Nov 8.", "Dinner with Omar", "on Nov 8", "2026-11-08"),
    ("Attend her wedding on Dec 12.", "Attend her wedding", "on Dec 12", "2026-12-12"),
    ("Attend her wedding on Dec 12 in Goa.", "Attend her wedding", "Dec 12", "2026-12-12"),
    ("Invite him to the offsite on Nov 3.", "Invite him to the offsite", "on Nov 3", "2026-11-03"),
    ("Invite him to our offsite on Nov 3.", "Invite him to our offsite", "Nov 3", "2026-11-03"),
    ("Submit the proposal by Nov 30.", "Submit the proposal", "by Nov 30", "2026-11-30"),
    ("Submit the proposal to her by Nov 30.", "Submit the proposal", "by Nov 30", "2026-11-30"),
    ("Pay the invoice on 2026-11-30.", "Pay the invoice", "on 2026-11-30", "2026-11-30"),
    ("Interview with their CTO on Nov 4.", "Interview with their CTO", "on Nov 4", "2026-11-04"),
    ("Pick him up from the airport on Nov 6.", "Pick him up from the airport", "on Nov 6", "2026-11-06"),
    ("Ask for the signed contract by Nov 20.", "Ask for the signed contract", "by Nov 20", "2026-11-20"),
    ("Review his pitch on Nov 2.", "Review his pitch", "on Nov 2", "2026-11-02"),
    ("Celebrate her birthday on Nov 12.", "Celebrate her birthday", "on Nov 12", "2026-11-12"),  # imperative wins
    ("Her birthday is on Nov 12, need to send a gift.", "Send a gift", "Nov 12", "2026-11-12"),
]


@pytest.mark.parametrize("notes, action, when, day", REAL_TODOS, ids=[r[0] for r in REAL_TODOS])
def test_v2bug10_model_todo_with_date_is_kept(notes, action, when, day):
    e = G(notes, follow_ups=[{"action": action, "when_text": when}])
    assert any(f.action == action and f.date_status == "exact" and f.suggested_date == day for f in e.follow_ups), \
        [(f.action, f.when_text, f.date_status, f.suggested_date) for f in e.follow_ups]


@pytest.mark.parametrize("notes, action, when", [
    ("Raised their Series A on Sep 3. Growing fast.", "Raised their Series A", "on Sep 3"),
    ("Her birthday is on Nov 12.", "Her birthday", "on Nov 12"),
    ("Birthday is May 12.", "Birthday", "May 12"),
    ("Ravi Iyer, CFO at Finlo. Raised their Series A on Sep 3.", "Series A funding", "Sep 3"),
])
def test_v2bug10_model_non_todo_dropped(notes, action, when):
    e = G(notes, follow_ups=[{"action": action, "when_text": when}])
    assert not any(f.date_status in ("exact", "needs_date") for f in e.follow_ups)
    assert e.follow_ups == []


def test_v2bug11_past_dated_model_follow_up_kept_as_past():
    e = G("Joined Stripe on 2024-03-01.", follow_ups=[{"action": "Ask how joining Stripe went", "when_text": "on 2024-03-01"}])
    assert [(f.action, f.date_status, f.suggested_date) for f in e.follow_ups] == [("Ask how joining Stripe went", "past", None)]


# ---- round 5: extended action cues (attend, invite, submit, visit, pay, interview, pick up) ----

@pytest.mark.parametrize("notes, day", [
    ("Attend her wedding on Dec 12 in Goa.", "2026-12-12"),
    ("Invite him to our offsite on Nov 3.", "2026-11-03"),
    ("Submit the proposal to her by Nov 30.", "2026-11-30"),
    ("Visit his office on Nov 5.", "2026-11-05"),
    ("Pay the invoice on 2026-11-30.", "2026-11-30"),
    ("Interview with their CTO on Nov 4.", "2026-11-04"),
    ("Pick him up from the airport on Nov 6.", "2026-11-06"),
])
def test_scan_creates_follow_up_for_new_cues(notes, day):
    fus = G(notes, follow_ups=[]).follow_ups
    assert [(f.date_status, f.suggested_date) for f in fus] == [("exact", day)]


def test_wedding_scan_exact():
    fus = G("Attend her wedding on Dec 12 in Goa.", follow_ups=[]).follow_ups
    assert [(f.action, f.when_text, f.date_status, f.suggested_date) for f in fus] == [
        ("Attend her wedding on Dec 12 in Goa", "on Dec 12", "exact", "2026-12-12")]


@pytest.mark.parametrize("notes", ["Visited Goa last May.", "Visited Goa last May. Loves the beach.", "Paid the invoice last week."])
def test_past_visit_creates_no_future_follow_up(notes):
    fus = G(notes, follow_ups=[]).follow_ups
    assert not any(f.date_status in ("exact", "needs_date") for f in fus)
