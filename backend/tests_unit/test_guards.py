"""Unit tests for deterministic post-processing guards and model-reply handling."""
from __future__ import annotations

import json
from datetime import date

import pytest

from app.enrichment.model_client import ModelNotInstalled, ModelTimeout, ModelUnavailable
from app.enrichment.service import EnrichmentFailure, apply_guards, enrich_notes
from app.models import Enrichment

GOLD = (
    "Priya Shah. Met at Fintech Forward. Runs partnerships at a payments startup, I think "
    "Stripe-adjacent. Wants intros to bank CTOs. Has a dog named Biscuit. Said to follow up after Diwali."
)


def E(**kw) -> Enrichment:
    return Enrichment.model_validate(kw)


# ---- contact_info -------------------------------------------------------------

def test_email_gap_added_when_no_contact_info():
    e = apply_guards(E(gaps=["Exact company name", "Location"]), GOLD)
    assert e.gaps == ["Exact company name", "Location", "Email or other contact details"]


@pytest.mark.parametrize("gap", ["Email address", "e-mail", "Contact details", "Her CONTACT info"])
def test_email_gap_not_duplicated(gap):
    e = apply_guards(E(gaps=[gap]), GOLD)
    assert e.gaps == [gap]


def test_email_gap_not_added_when_some_contact_info_present():
    e = apply_guards(E(contact_info={"phone": "415-555-0199"}), "call 415-555-0199")
    assert "Email or other contact details" not in e.gaps


def test_contact_info_not_in_notes_is_nulled():
    e = apply_guards(
        E(contact_info={"email": "priya@stripe.com", "phone": "+1 555 0100", "linkedin": "linkedin.com/in/priya"}),
        GOLD,
    )
    assert e.contact_info.model_dump() == {"email": None, "phone": None, "linkedin": None}


def test_contact_info_present_in_notes_is_kept_case_insensitive():
    notes = "Email her at Priya@Example.com or call 415-555-0199. linkedin.com/in/priyashah"
    e = apply_guards(
        E(contact_info={"email": "priya@example.com", "phone": "415-555-0199", "linkedin": "linkedin.com/in/priyashah"}),
        notes,
    )
    assert e.contact_info.email == "priya@example.com"
    assert e.contact_info.phone == "415-555-0199"
    assert e.contact_info.linkedin == "linkedin.com/in/priyashah"


def test_partial_contact_info_match_is_nulled():
    e = apply_guards(E(contact_info={"phone": "415-555-0199"}), "call 415-555")
    assert e.contact_info.phone is None


# ---- role / company confidence -----------------------------------------------

def test_company_with_no_word_in_notes_becomes_inferred():
    e = apply_guards(E(company={"value": "Stripe Inc", "confidence": "stated"}), "Works at a bank in Leeds.")
    assert e.company.value == "Stripe Inc"  # value kept, only confidence downgraded
    assert e.company.confidence == "inferred"


def test_role_sharing_a_word_with_notes_keeps_stated():
    e = apply_guards(E(role={"value": "Partnerships lead", "confidence": "stated"}), GOLD)
    assert e.role.confidence == "stated"


def test_role_shared_word_via_plural_stem():
    e = apply_guards(E(role={"value": "Head of Partnership", "confidence": "stated"}), GOLD)
    assert e.role.confidence == "stated"


def test_stopwords_alone_do_not_count_as_overlap():
    e = apply_guards(E(role={"value": "Head of the Company", "confidence": "stated"}), "the company of a friend")
    assert e.role.confidence == "inferred"


def test_famous_person_role_downgraded():
    e = apply_guards(
        E(role={"value": "CEO", "confidence": "stated"}, company={"value": "Tesla", "confidence": "stated"}),
        "Elon. Met him at a barbecue, likes rockets.",
    )
    assert e.role.confidence == "inferred"
    assert e.company.confidence == "inferred"


# ---- list trimming ------------------------------------------------------------

def test_lists_trimmed_to_limits():
    e = apply_guards(
        E(
            interests=[{"value": f"i{n}", "confidence": "stated"} for n in range(12)],
            follow_ups=[{"action": f"a{n}"} for n in range(9)],
            questions_to_ask=[f"q{n}?" for n in range(6)],
            suggested_tags=[f"t{n}" for n in range(9)],
        ),
        "notes",
    )
    assert len(e.interests) == 8
    assert len(e.follow_ups) == 5
    assert len(e.questions_to_ask) == 3
    assert len(e.suggested_tags) == 5


def test_tags_lowercased_and_deduped():
    e = apply_guards(E(suggested_tags=["FinTech", "fintech", " Payments ", "Bank  CTOs"]), "x")
    assert e.suggested_tags == ["fintech", "payments", "bank ctos"]


def test_headline_capped_at_80():
    e = apply_guards(E(headline="x" * 200), "x")
    assert len(e.headline) == 80


# ---- schema coercion -----------------------------------------------------------

def test_missing_lists_coerced_and_unknown_keys_dropped():
    e = Enrichment.model_validate({"headline": "h", "bogus": 1, "interests": None, "role": None})
    assert e.interests == [] and e.gaps == [] and e.follow_ups == []
    assert e.role.value is None
    assert "bogus" not in e.model_dump()


def test_bad_confidence_and_dates_are_coerced():
    e = Enrichment.model_validate({
        "role": {"value": "CTO", "confidence": "certain"},
        "follow_ups": [{"action": "Ping", "when_text": "next week", "suggested_date": "soon"}],
    })
    assert e.role.confidence == "inferred"
    assert e.follow_ups[0].suggested_date is None
    assert e.follow_ups[0].when_text == "next week"


# ---- service with a fake model client -----------------------------------------

class FakeClient:
    name = "fake:1b"

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls: list[list[dict]] = []

    def chat_json(self, messages, schema):
        self.calls.append(messages)
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    def status(self):
        return True, None


GOOD = json.dumps({
    "headline": "Partnerships at a payments startup",
    "role": {"value": "Partnerships lead", "confidence": "stated"},
    "company": {"value": "Stripe", "confidence": "stated"},
    "contact_info": {"email": "priya@stripe.com", "phone": None, "linkedin": None},
})


def test_invalid_json_retries_once_then_succeeds():
    c = FakeClient(["not json {", GOOD])
    e = enrich_notes(c, "Priya Shah", GOLD, date(2026, 10, 14))
    assert len(c.calls) == 2
    assert c.calls[1][-1]["content"] == "Your last reply was not valid JSON. Reply with JSON only."
    assert e.contact_info.email is None        # guard applied
    assert e.company.confidence == "stated"    # "Stripe" appears in "Stripe-adjacent"


def test_invalid_json_twice_fails_with_friendly_message():
    c = FakeClient(["nope", "still nope"])
    with pytest.raises(EnrichmentFailure) as ei:
        enrich_notes(c, "Priya", GOLD, date(2026, 10, 14))
    assert "Tap Retry" in ei.value.user_message


@pytest.mark.parametrize(
    "exc, fragment",
    [
        (ModelUnavailable("refused"), "isn't running"),
        (ModelNotInstalled("missing"), "Run: ollama pull fake:1b"),
        (ModelTimeout("slow"), "took too long"),
    ],
)
def test_model_errors_map_to_friendly_messages(exc, fragment):
    with pytest.raises(EnrichmentFailure) as ei:
        enrich_notes(FakeClient([exc]), "Priya", GOLD, date(2026, 10, 14))
    assert fragment in ei.value.user_message


def test_prompt_contains_today_and_notes():
    c = FakeClient([GOOD])
    enrich_notes(c, "Priya Shah", GOLD, date(2026, 10, 14))
    sys_msg, user_msg = c.calls[0]
    assert "Today's date is 2026-10-14." in sys_msg["content"]
    assert user_msg["content"].startswith("Person: Priya Shah\nNotes:\n\"\"\"\n" + GOLD)


# ---- suggested_date: computed deterministically (BUG-11) ------------------------

from app.enrichment.dates import resolve_date

TODAY = date(2026, 10, 14)  # a Wednesday


@pytest.mark.parametrize(
    "text, expected",
    [
        # required cases
        ("by Friday", "2026-10-16"),
        ("next Monday", "2026-10-19"),
        ("Wednesday", "2026-10-21"),          # today is Wednesday -> +7
        ("on 2026-11-02", "2026-11-02"),
        ("Nov 2", "2026-11-02"),
        ("tomorrow", "2026-10-15"),
        ("in 3 days", "2026-10-17"),
        ("in 2 weeks", "2026-10-28"),
        ("next week", "2026-10-19"),
        ("next month", "2026-11-01"),
        ("in November", None),
        ("after Diwali", None),
        ("maybe in November", None),
        # more coverage
        ("next Wednesday", "2026-10-21"),
        ("Thursday", "2026-10-15"),
        ("on Fridays", "2026-10-16"),
        ("today", "2026-10-14"),
        ("Tonight", "2026-10-14"),
        ("day after tomorrow", "2026-10-16"),
        ("maybe tomorrow", "2026-10-15"),     # hedge stays in when_text; date still computable
        ("in a week", "2026-10-21"),
        ("in two weeks", "2026-10-28"),
        ("in 1 month", "2026-11-14"),
        ("2 November", "2026-11-02"),
        ("2nd of November", "2026-11-02"),
        ("November 2nd, 2027", "2027-11-02"),
        ("Oct 1", "2027-10-01"),              # already passed this year -> next year
        ("Oct 14", "2026-10-14"),
        ("Feb 30", None),                     # impossible date
        ("2026-13-01", None),
        ("after the conference", None),
        ("soon", None),
        ("end of month", None),
        ("next year", None),
        ("Nov 2026", None),                   # month + year, no day
        ("", None),
        (None, None),
    ],
)
def test_resolve_date(text, expected):
    got = resolve_date(text, TODAY)
    assert (got.isoformat() if got else None) == expected


def test_next_month_from_end_of_january_and_december():
    assert resolve_date("next month", date(2026, 12, 31)) == date(2027, 1, 1)
    assert resolve_date("in 1 month", date(2026, 1, 31)) == date(2026, 2, 28)


def test_model_date_is_ignored_and_recomputed():
    e = apply_guards(
        E(follow_ups=[
            {"action": "Send deck", "when_text": "by Friday", "suggested_date": "2026-10-17"},  # model's wrong arithmetic
            {"action": "Follow up", "when_text": "after Diwali", "suggested_date": "2026-11-12"},
            {"action": "Review his pitch on 2026-11-02", "when_text": None, "suggested_date": None},
            {"action": "Lunch", "when_text": None, "suggested_date": "2026-10-19"},
        ]),
        "x",
        TODAY,
    )
    assert [f.suggested_date for f in e.follow_ups] == ["2026-10-16", None, "2026-11-02", None]
    assert e.follow_ups[0].when_text == "by Friday"  # when_text kept verbatim


# ---- location that is only the meeting place (BUG-9 remainder) -----------------

def test_location_tokyo_hotel_lobby_is_nulled():
    notes = "Works at Sony. Chatted in the hotel lobby in Tokyo while waiting for a taxi. Likes jazz records."
    # Model output as seen by QA: how_we_met without the city.
    e = apply_guards(E(location={"value": "Tokyo", "confidence": "stated"},
                       how_we_met={"value": "In the hotel lobby while waiting for a taxi", "confidence": "stated"}), notes)
    assert e.location.value is None
    # And when the city is inside how_we_met.
    e = apply_guards(E(location={"value": "Tokyo", "confidence": "stated"},
                       how_we_met={"value": "Hotel lobby in Tokyo", "confidence": "stated"}), notes)
    assert e.location.value is None


def test_location_delhi_wedding_is_nulled():
    notes = "दिल्ली में एक शादी में मिले। उन्हें क्रिकेट बहुत पसंद है। अगले महीने फिर मिलने की बात हुई।"
    e = apply_guards(E(location={"value": "Delhi", "confidence": "stated"},
                       how_we_met={"value": "A wedding in Delhi", "confidence": "stated"}), notes)
    assert e.location.value is None


@pytest.mark.parametrize("notes", [
    "Based in Delhi, met at a wedding in Delhi.",
    "She lives in Delhi. We met at a wedding in Delhi.",
    "Works in Delhi; met at a wedding in Delhi.",
    "Originally from Delhi. Met at a wedding in Delhi.",
    "Delhi-based designer. Met at a wedding in Delhi.",
    "Delhi mein rehti hai. Met at a wedding in Delhi.",
])
def test_location_kept_when_notes_say_they_live_there(notes):
    e = apply_guards(E(location={"value": "Delhi", "confidence": "stated"},
                       how_we_met={"value": "A wedding in Delhi", "confidence": "stated"}), notes)
    assert e.location.value == "Delhi"


def test_location_unrelated_to_meeting_is_kept():
    notes = "Runs a bakery in Lyon. Met at Fintech Forward."
    e = apply_guards(E(location={"value": "Lyon", "confidence": "stated"},
                       how_we_met={"value": "Fintech Forward", "confidence": "stated"}), notes)
    assert e.location.value == "Lyon"


def test_system_prompt_matches_enrichment_doc():
    from pathlib import Path

    from app.enrichment.prompt import SYSTEM_PROMPT

    doc = (Path(__file__).resolve().parents[2] / "docs" / "ENRICHMENT.md").read_text()
    block = doc.split("System:\n```\n")[1].split("\n```")[0]
    assert SYSTEM_PROMPT == block


# ---- model client error mapping (BUG-8) and request shape (BUG-3) ---------------

import httpx

from app.enrichment import prompt
from app.enrichment.model_client import OllamaClient


def _client_raising(monkeypatch, exc):
    def post(self, *a, **k):
        raise exc

    monkeypatch.setattr(httpx.Client, "post", post)
    return OllamaClient(model="m", base_url="http://x", timeout_s=1)


def test_connect_timeout_is_unavailable_not_slow(monkeypatch):
    c = _client_raising(monkeypatch, httpx.ConnectTimeout("connect timed out"))
    with pytest.raises(EnrichmentFailure) as ei:
        enrich_notes(c, "P", "notes", date(2026, 10, 14))
    assert "isn't running" in ei.value.user_message


def test_connect_refused_is_unavailable(monkeypatch):
    c = _client_raising(monkeypatch, httpx.ConnectError("refused"))
    with pytest.raises(EnrichmentFailure) as ei:
        enrich_notes(c, "P", "notes", date(2026, 10, 14))
    assert "isn't running" in ei.value.user_message


def test_read_timeout_is_slow(monkeypatch):
    c = _client_raising(monkeypatch, httpx.ReadTimeout("read timed out"))
    with pytest.raises(EnrichmentFailure) as ei:
        enrich_notes(c, "P", "notes", date(2026, 10, 14))
    assert "took too long" in ei.value.user_message


def test_request_body_matches_spec(monkeypatch):
    seen = {}

    def post(self, url, json=None, **k):
        seen.update(json)
        return httpx.Response(200, json={"message": {"content": "{}"}}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.Client, "post", post)
    OllamaClient(model="m", base_url="http://x").chat_json([{"role": "user", "content": "hi"}], prompt.FORMAT_SCHEMA)
    assert seen["think"] is False and seen["stream"] is False
    assert seen["options"] == {"temperature": 0.2, "num_ctx": 8192, "num_predict": 1200}
    props = seen["format"]["properties"]
    assert props["headline"]["maxLength"] == 80
    assert {k: props[k]["maxItems"] for k in prompt.LIST_MAX} == {
        "interests": 8, "follow_ups": 5, "questions_to_ask": 3, "suggested_tags": 5,
        "what_they_want": 6, "how_i_can_help": 6, "personal_details": 6, "gaps": 6,
    }


# ---- role must be a job title ---------------------------------------------------

@pytest.mark.parametrize("role", [
    "Works at a startup", "works in fintech", "Works for Sony", "Employed at Acme", "Working at a bank",
])
def test_role_that_is_not_a_title_is_nulled(role):
    e = apply_guards(E(role={"value": role, "confidence": "inferred"}, gaps=["Company name"]), "x")
    assert e.role.value is None
    assert e.gaps.count("Job title") == 1


def test_role_restating_employer_is_nulled():
    e = apply_guards(E(role={"value": "Sony", "confidence": "stated"},
                       company={"value": "Sony", "confidence": "stated"}), "Works at Sony.")
    assert e.role.value is None and "Job title" in e.gaps


def test_job_title_gap_not_duplicated():
    e = apply_guards(E(role={"value": "Works at a startup"}, gaps=["Job title"]), "x")
    assert e.gaps.count("Job title") == 1


@pytest.mark.parametrize("role", ["Partnerships lead", "Runs partnerships", "Head of Investments", "Designer"])
def test_real_titles_kept(role):
    e = apply_guards(E(role={"value": role, "confidence": "stated"},
                       company={"value": "A payments startup", "confidence": "inferred"}), GOLD)
    assert e.role.value == role
    assert "Job title" not in e.gaps


# ---- round 4: BUG-12 residence cues in either order / Hindi ----------------------

@pytest.mark.parametrize("notes, loc, met", [
    ("Met her in London, where she lives. Runs a design studio called Fjord.", "London", "In London"),
    ("पुणे में रहती है। पुणे में एक मीटअप में मिले।", "Pune", "A meetup in Pune"),
    ("Met at a meetup in Berlin. Lives in Berlin.", "Berlin", "A meetup in Berlin"),
    ("Met him in Austin; he's Austin-based.", "Austin", "In Austin"),
    ("From Mumbai. Met in Mumbai at a Diwali party.", "Mumbai", "Diwali party in Mumbai"),
    ("Met at her flat in Brooklyn for dinner.", "Brooklyn", "Dinner at her flat in Brooklyn"),
    ("Met at his office in Zurich. He runs the Zurich team.", "Zurich", "At his office in Zurich"),
    ("Met in Oslo, where he works.", "Oslo", "In Oslo"),
])
def test_bug12_residence_kept(notes, loc, met):
    e = apply_guards(E(location={"value": loc, "confidence": "stated"},
                       how_we_met={"value": met, "confidence": "stated"}), notes)
    assert e.location.value == loc


@pytest.mark.parametrize("notes, loc, met", [
    ("Works at Sony. Chatted in the hotel lobby in Tokyo while waiting for a taxi.", "Tokyo", "Hotel lobby in Tokyo"),
    ("दिल्ली में एक शादी में मिले। उन्हें क्रिकेट बहुत पसंद है।", "Delhi", "A wedding in Delhi"),
    ("Met in Tokyo; he lives in Osaka.", "Tokyo", "In Tokyo"),   # cue tied to another place
    ("Met at a wedding in Pune. मुंबई में रहती है।", "Pune", "Wedding in Pune"),  # place is in notes, cue isn't tied
])
def test_bug12_meeting_place_still_nulled(notes, loc, met):
    e = apply_guards(E(location={"value": loc, "confidence": "stated"},
                       how_we_met={"value": met, "confidence": "stated"}), notes)
    assert e.location.value is None


# ---- round 4: BUG-13 role equals whole company only ------------------------------

@pytest.mark.parametrize("role, company, expected", [
    ("Partner", "Partner Capital Group", "Partner"),
    ("Owner", "Owner's Bakery", "Owner"),
    ("Founder", "Founders Fund", "Founder"),
    ("Engineer", "Engineering Ltd", "Engineer"),
    ("Works at Google as a product manager", "Google", "Product manager"),
    ("Partner Capital Group", "partner capital group", None),   # whole company name, any case
    ("Sony", "Sony.", None),
    ("Works at a startup", None, None),
    ("Employed by Deloitte", "Deloitte", None),
    ("Working at a bank", None, None),
])
def test_bug13_role_rules(role, company, expected):
    e = apply_guards(E(role={"value": role, "confidence": "stated"},
                       company={"value": company, "confidence": "stated"}), "x")
    assert e.role.value == expected
    assert ("Job title" in e.gaps) is (expected is None)
