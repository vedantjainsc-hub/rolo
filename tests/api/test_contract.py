"""Every endpoint and error code in docs/API_CONTRACT.md (v2.1).

These tests avoid the model (enrich=False) except where a pending state is required.
"""
from __future__ import annotations

import re
import time
import uuid
from datetime import date

import httpx
import pytest

from conftest import assert_api_error, wait_until_settled

ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|\+00:00)$")
CONTACT_KEYS = {
    "id", "name", "raw_notes", "tags", "enrichment", "enrichment_status", "enrichment_error",
    "enriched_at", "model_name", "created_at", "updated_at", "needs_name", "source",
}
SUMMARY_KEYS = {"id", "name", "headline", "company", "tags", "enrichment_status", "updated_at"}


# ------------------------------------------------------------------ health

def test_health_shape(client):
    r = client.get("/health")
    assert r.status_code == 200
    b = r.json()
    assert b["status"] == "ok"
    assert set(b) == {"status", "model", "asr"}
    for k in ("model", "asr"):
        assert set(b[k]) == {"name", "available", "detail"}
        assert isinstance(b[k]["available"], bool)
        if b[k]["available"]:
            assert b[k]["detail"] is None
        else:
            assert b[k]["detail"]
    assert b["asr"]["name"] == "parakeet-tdt-0.6b-v3"


# ------------------------------------------------------------------ create

def test_create_returns_201_contact_shape(client, make_contact):
    c = make_contact(name="  Ada Lovelace  ", raw_notes="Met at the analytical engine meetup.")
    assert set(c) == CONTACT_KEYS
    assert c["name"] == "Ada Lovelace", "name must be trimmed"
    uuid.UUID(c["id"])
    assert ISO.match(c["created_at"]) and ISO.match(c["updated_at"])
    assert c["enrichment_status"] == "none"
    assert c["enrichment"] is None and c["enriched_at"] is None and c["model_name"] is None
    assert c["tags"] == []
    assert c["needs_name"] is False and c["source"] == "typed"


def test_create_is_fast_and_listed(client, make_contact):
    t0 = time.monotonic()
    c = make_contact(raw_notes="Speed check")
    assert time.monotonic() - t0 < 1.0
    ids = [x["id"] for x in client.get("/contacts").json()["contacts"]]
    assert c["id"] in ids


def test_create_without_enrich_flag_defaults_to_enrich(client):
    """enrich defaults to true -> pending, and the response does not wait for the model."""
    t0 = time.monotonic()
    r = client.post("/contacts", json={"name": "QA default enrich", "raw_notes": "Likes chess."})
    elapsed = time.monotonic() - t0
    try:
        assert r.status_code == 201
        assert r.json()["enrichment_status"] == "pending"
        assert elapsed < 1.0, f"create waited {elapsed:.2f}s - must not wait for the model"
    finally:
        client.delete(f"/contacts/{r.json()['id']}")


def test_blank_notes_with_enrich_true_is_none(client, make_contact):
    c = make_contact(raw_notes="   \n  ", enrich=True)
    assert c["enrichment_status"] == "none"


@pytest.mark.parametrize("name", ["", "   ", "\n\t "])
def test_create_rejects_empty_or_whitespace_name(client, name):
    assert_api_error(client.post("/contacts", json={"name": name, "raw_notes": "x"}), 400, "validation_error", "name")


def test_create_rejects_missing_name(client):
    e = assert_api_error(client.post("/contacts", json={"raw_notes": "x"}), 400, "validation_error", "name")
    assert e["message"] == "name: is required"


def test_name_length_limits(client, make_contact):
    c = make_contact(name="N" * 120)
    assert len(c["name"]) == 120
    assert_api_error(client.post("/contacts", json={"name": "N" * 121, "raw_notes": ""}), 400, "validation_error", "name")


def test_notes_10000_accepted_10001_rejected(client, make_contact):
    c = make_contact(raw_notes="a" * 10_000)
    assert len(c["raw_notes"]) == 10_000
    e = assert_api_error(
        client.post("/contacts", json={"name": "QA long", "raw_notes": "a" * 10_001, "enrich": False}),
        400, "validation_error", "raw_notes",
    )
    assert "10,000" in e["message"]


def test_notes_limit_counts_characters_not_bytes(client, make_contact):
    """10,000 Devanagari characters (30,000 UTF-8 bytes) must be accepted."""
    c = make_contact(raw_notes="क" * 10_000)
    assert len(c["raw_notes"]) == 10_000


def test_unicode_roundtrip(client, make_contact):
    name = "José Ñúñez 李小龙 प्रिया 🦄"
    notes = "Café ☕ meeting. नमस्ते, मिलकर अच्छा लगा. 你好. Emoji: 👩🏽‍💻🇮🇳 — accents: àéîõü"
    c = make_contact(name=name, raw_notes=notes, tags=["ड्रोन", "café"])
    got = client.get(f"/contacts/{c['id']}").json()
    assert got["name"] == name and got["raw_notes"] == notes
    assert got["tags"] == ["ड्रोन", "café"]
    listed = client.get("/contacts", params={"q": "प्रिया"}).json()["contacts"]
    assert [x["id"] for x in listed] == [c["id"]]


def test_tags_normalisation(client, make_contact):
    c = make_contact(tags=["  VC ", "vc", "", "  ", "Fintech", "fintech "])
    assert c["tags"] == ["VC", "Fintech"]


def test_tag_limits(client):
    assert_api_error(client.post("/contacts", json={"name": "t", "tags": ["x" * 41], "enrich": False}),
                     400, "validation_error", "tags")
    assert_api_error(client.post("/contacts", json={"name": "t", "tags": [f"t{i}" for i in range(21)], "enrich": False}),
                     400, "validation_error", "tags")


def test_tags_exactly_at_limits_ok(client, make_contact):
    c = make_contact(tags=[f"t{i}" for i in range(19)] + ["y" * 40])
    assert len(c["tags"]) == 20


@pytest.mark.parametrize("body", [
    {"name": 123, "raw_notes": ""},
    {"name": "ok", "raw_notes": 5},
    {"name": "ok", "tags": "notalist"},
    {"name": "ok", "enrich": "maybe"},
])
def test_create_wrong_types_are_400(client, body):
    r = client.post("/contacts", json=body)
    assert r.status_code == 400 and r.json()["error"]["code"] == "validation_error", r.text


def test_malformed_json_is_400_not_422(client):
    r = client.post("/contacts", content=b"{not json", headers={"Content-Type": "application/json"})
    assert_api_error(r, 400, "validation_error")


def test_non_object_body_is_400(client):
    assert_api_error(client.post("/contacts", json=["a"]), 400, "validation_error")


# ------------------------------------------------------------------ get / list

def test_get_unknown_is_404(client):
    assert_api_error(client.get(f"/contacts/{uuid.uuid4()}"), 404, "not_found")


def test_unknown_route_is_404_not_found(client):
    assert_api_error(client.get("/nope"), 404, "not_found")


def test_list_shape_and_order(client, make_contact):
    a = make_contact(raw_notes="first")
    time.sleep(0.01)
    b = make_contact(raw_notes="second")
    contacts = client.get("/contacts").json()["contacts"]
    for x in contacts:
        assert set(x) == SUMMARY_KEYS
    ids = [x["id"] for x in contacts]
    assert ids.index(b["id"]) < ids.index(a["id"]), "newest updated_at first"
    stamps = [x["updated_at"] for x in contacts]
    assert stamps == sorted(stamps, reverse=True)


def test_search_name_notes_tags_case_insensitive(client, make_contact):
    tag = f"zq{uuid.uuid4().hex[:6]}"
    c = make_contact(name="Wilhelmina Q", raw_notes="Collects VINTAGE typewriters", tags=[tag.upper()])
    for q in ("wilhelmina", "WILHELMINA", "typewriters", "Vintage Type", tag, tag.upper()):
        ids = [x["id"] for x in client.get("/contacts", params={"q": q}).json()["contacts"]]
        assert c["id"] in ids, f"q={q!r} did not match"
    ids = [x["id"] for x in client.get("/contacts", params={"q": "nonexistent-zzz-term"}).json()["contacts"]]
    assert c["id"] not in ids


def test_search_blank_q_returns_all(client, make_contact):
    make_contact()
    all_ = client.get("/contacts").json()["contacts"]
    blank = client.get("/contacts", params={"q": "   "}).json()["contacts"]
    assert len(blank) == len(all_)


# ------------------------------------------------------------------ patch

def test_patch_name_notes_tags(client, make_contact):
    c = make_contact(raw_notes="old")
    r = client.patch(f"/contacts/{c['id']}", json={"name": " New Name ", "raw_notes": "new notes", "tags": ["a", "A"]})
    assert r.status_code == 200
    u = r.json()
    assert u["name"] == "New Name" and u["raw_notes"] == "new notes" and u["tags"] == ["a"]
    assert u["updated_at"] > c["updated_at"]
    assert u["enrichment_status"] == "none", "PATCH must not auto re-enrich"


def test_patch_partial_leaves_other_fields(client, make_contact):
    c = make_contact(raw_notes="keep me", tags=["x"])
    u = client.patch(f"/contacts/{c['id']}", json={"name": "Only Name"}).json()
    assert u["raw_notes"] == "keep me" and u["tags"] == ["x"]


def test_patch_validation(client, make_contact):
    c = make_contact()
    assert_api_error(client.patch(f"/contacts/{c['id']}", json={"name": "  "}), 400, "validation_error", "name")
    assert_api_error(client.patch(f"/contacts/{c['id']}", json={"raw_notes": "a" * 10_001}), 400, "validation_error", "raw_notes")
    assert_api_error(client.patch(f"/contacts/{c['id']}", json={"name": None}), 400, "validation_error", "name")


def test_patch_unknown_is_404(client):
    assert_api_error(client.patch(f"/contacts/{uuid.uuid4()}", json={"name": "x"}), 404, "not_found")


# ------------------------------------------------------------------ notes append

def test_append_note_format(client, make_contact):
    c = make_contact(raw_notes="Original line")
    r = client.post(f"/contacts/{c['id']}/notes", json={"text": "Second thing", "enrich": False})
    assert r.status_code == 200
    today = date.today().isoformat()
    assert r.json()["raw_notes"] == f"Original line\n\n[{today}] Second thing"
    assert r.json()["enrichment_status"] == "none"


def test_append_note_to_empty_has_no_leading_blank(client, make_contact):
    c = make_contact(raw_notes="")
    r = client.post(f"/contacts/{c['id']}/notes", json={"text": "First", "enrich": False})
    assert r.json()["raw_notes"] == f"[{date.today().isoformat()}] First"


def test_append_note_validation(client, make_contact):
    c = make_contact(raw_notes="")
    assert_api_error(client.post(f"/contacts/{c['id']}/notes", json={"text": ""}), 400, "validation_error", "text")
    assert_api_error(client.post(f"/contacts/{c['id']}/notes", json={"text": "   "}), 400, "validation_error", "text")
    assert_api_error(client.post(f"/contacts/{c['id']}/notes", json={"text": "a" * 10_001}), 400, "validation_error", "text")


def test_append_note_combined_limit(client, make_contact):
    c = make_contact(raw_notes="a" * 9_990)
    # "\n\n[YYYY-MM-DD] " is 15 chars, so 9,990 + 15 + 1 > 10,000
    assert_api_error(client.post(f"/contacts/{c['id']}/notes", json={"text": "bbbbbbbbbb", "enrich": False}),
                     400, "validation_error")
    unchanged = client.get(f"/contacts/{c['id']}").json()
    assert unchanged["raw_notes"] == "a" * 9_990


def test_append_unknown_is_404(client):
    assert_api_error(client.post(f"/contacts/{uuid.uuid4()}/notes", json={"text": "x"}), 404, "not_found")


# ------------------------------------------------------------------ enrich

def test_enrich_blank_notes_is_400(client, make_contact):
    c = make_contact(raw_notes="  ")
    e = assert_api_error(client.post(f"/contacts/{c['id']}/enrich"), 400, "validation_error", "raw_notes")
    assert e["message"] == "raw_notes: add some notes before enriching"


def test_enrich_unknown_is_404(client):
    assert_api_error(client.post(f"/contacts/{uuid.uuid4()}/enrich"), 404, "not_found")


def test_enrich_202_then_409_while_pending(client, make_contact):
    c = make_contact(raw_notes="Met Sam at a book fair. Sam edits poetry.")
    r = client.post(f"/contacts/{c['id']}/enrich")
    assert r.status_code == 202, r.text
    assert r.json()["enrichment_status"] == "pending"
    # Double tap
    r2 = client.post(f"/contacts/{c['id']}/enrich")
    assert_api_error(r2, 409, "enrichment_in_progress")
    # Deleting while enriching must succeed and not resurrect the row.
    assert client.delete(f"/contacts/{c['id']}").status_code == 204
    time.sleep(0.5)
    assert client.get(f"/contacts/{c['id']}").status_code == 404


def test_concurrent_enrich_calls_only_one_202(client, make_contact):
    """Race: two enrich calls at the same instant must not both start a job."""
    import concurrent.futures as cf

    c = make_contact(raw_notes="Race test. Likes tennis.")
    url = f"{client.base_url}contacts/{c['id']}/enrich"

    def hit():
        return httpx.post(url, timeout=30).status_code

    results = []
    try:
        for _ in range(10):  # repeat: the round-1 race was intermittent
            with cf.ThreadPoolExecutor(max_workers=6) as ex:
                codes = sorted(ex.map(lambda _: hit(), range(6)))
            results.append(codes)
            # make it non-pending again for the next round without waiting for the model
            client.patch(f"/contacts/{c['id']}", json={"raw_notes": "Race test. Likes tennis."})
            client.delete(f"/contacts/{c['id']}")
            c = client.post("/contacts", json={"name": "QA race", "raw_notes": "Race test. Likes tennis.", "enrich": False}).json()
            url = f"{client.base_url}contacts/{c['id']}/enrich"
    finally:
        client.delete(f"/contacts/{c['id']}")
    bad = [r for r in results if r.count(202) != 1 or r.count(409) != 5]
    assert not bad, f"expected one 202 + five 409 per round, bad rounds: {bad}"


# ------------------------------------------------------------------ delete

def test_delete_then_404(client):
    r = client.post("/contacts", json={"name": "QA delete", "raw_notes": "", "enrich": False})
    cid = r.json()["id"]
    d = client.delete(f"/contacts/{cid}")
    assert d.status_code == 204 and d.content == b""
    assert_api_error(client.get(f"/contacts/{cid}"), 404, "not_found")
    assert_api_error(client.delete(f"/contacts/{cid}"), 404, "not_found")


# ------------------------------------------------------------------ export

def test_export_contains_all_contacts(client, make_contact):
    a = make_contact(name="Export A", raw_notes="ä 👋")
    b = make_contact(name="Export B")
    r = client.get("/export")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"exported_at", "contacts"}
    assert ISO.match(body["exported_at"])
    ids = {x["id"] for x in body["contacts"]}
    assert {a["id"], b["id"]} <= ids
    listed = {x["id"] for x in client.get("/contacts").json()["contacts"]}
    assert ids == listed
    for x in body["contacts"]:
        assert set(x) == CONTACT_KEYS
    got_a = next(x for x in body["contacts"] if x["id"] == a["id"])
    assert got_a["raw_notes"] == "ä 👋"


# ------------------------------------------------------------------ misc safety

def test_method_not_allowed_is_405(client):
    """Contract v1.2: wrong method on a known route -> 405 method_not_allowed."""
    assert_api_error(client.put("/contacts"), 405, "method_not_allowed")
    assert_api_error(client.delete("/contacts"), 405, "method_not_allowed")


def test_emoji_name_and_notes_limits_in_code_points(client, make_contact):
    c = make_contact(name="😀" * 120, raw_notes="😀" * 10_000)
    assert len(c["name"]) == 120 and len(c["raw_notes"]) == 10_000
    assert_api_error(client.post("/contacts", json={"name": "😀" * 121, "enrich": False}), 400, "validation_error", "name")
    assert_api_error(client.post("/contacts", json={"name": "e", "raw_notes": "😀" * 10_001, "enrich": False}),
                     400, "validation_error", "raw_notes")


def test_no_stack_traces_on_bad_input(client):
    for body in (b"\x00\x01", b"null", b'{"name": {"x": 1}}', b'{"name": "a", "tags": [1,2]}'):
        r = client.post("/contacts", content=body, headers={"Content-Type": "application/json"})
        assert r.status_code == 400, (body, r.status_code, r.text)
        assert "Traceback" not in r.text and "pydantic" not in r.text.lower()


# ------------------------------------------------------------------ v2: voice create, needs_name

def test_voice_create_without_name(client, make_contact):
    r = client.post("/contacts", json={"raw_notes": "Met someone at a meetup.", "source": "voice", "enrich": False})
    assert r.status_code == 201, r.text
    c = r.json()
    try:
        assert c["name"] == "New contact" and c["needs_name"] is True and c["source"] == "voice"
        u = client.patch(f"/contacts/{c['id']}", json={"name": "Dana Ruiz"}).json()
        assert u["name"] == "Dana Ruiz" and u["needs_name"] is False and u["source"] == "voice"
    finally:
        client.delete(f"/contacts/{c['id']}")


@pytest.mark.parametrize("name", ["", "   "])
def test_voice_create_blank_name_ok(client, name):
    r = client.post("/contacts", json={"name": name, "raw_notes": "Likes chess.", "source": "voice", "enrich": False})
    assert r.status_code == 201, r.text
    assert r.json()["needs_name"] is True
    client.delete(f"/contacts/{r.json()['id']}")


def test_voice_create_with_name_does_not_need_name(client):
    r = client.post("/contacts", json={"name": "Ola", "raw_notes": "Likes chess.", "source": "voice", "enrich": False})
    assert r.status_code == 201 and r.json()["needs_name"] is False and r.json()["name"] == "Ola"
    client.delete(f"/contacts/{r.json()['id']}")


@pytest.mark.parametrize("notes", ["", "   ", None])
def test_voice_create_blank_notes_rejected(client, notes):
    body = {"source": "voice", "enrich": False}
    if notes is not None:
        body["raw_notes"] = notes
    e = assert_api_error(client.post("/contacts", json=body), 400, "validation_error", "raw_notes")
    assert e["message"] == "raw_notes: nothing was heard"


def test_typed_create_still_requires_name(client):
    assert_api_error(client.post("/contacts", json={"raw_notes": "x", "source": "typed"}), 400, "validation_error", "name")


def test_bad_source_rejected(client):
    assert_api_error(client.post("/contacts", json={"name": "x", "source": "telepathy"}), 400, "validation_error", "source")


# ------------------------------------------------------------------ v2: follow-up endpoints (non-model paths)

def test_followup_endpoints_404(client, make_contact):
    c = make_contact(raw_notes="no enrichment")
    unknown = uuid.uuid4()
    assert_api_error(client.patch(f"/contacts/{unknown}/follow-ups/0", json={"dismissed": True}), 404, "not_found")
    assert_api_error(client.patch(f"/contacts/{c['id']}/follow-ups/0", json={"dismissed": True}), 404, "not_found")
    assert_api_error(client.get(f"/contacts/{unknown}/follow-ups/0.ics"), 404, "not_found")
    assert_api_error(client.get(f"/contacts/{c['id']}/follow-ups/0.ics"), 404, "not_found")


@pytest.mark.parametrize("days,status", [("0", 200), ("14", 200), ("60", 200), ("61", 400), ("-1", 400), ("abc", 400), ("1.5", 400)])
def test_upcoming_days_validation(client, days, status):
    r = client.get("/follow-ups/upcoming", params={"days": days})
    if status == 200:
        assert r.status_code == 200 and set(r.json()) == {"items"}
    else:
        assert_api_error(r, 400, "validation_error", "days")


def test_upcoming_default(client):
    r = client.get("/follow-ups/upcoming")
    assert r.status_code == 200 and isinstance(r.json()["items"], list)


# ------------------------------------------------------------------ v2: transcribe error codes (no helper needed)

def test_transcribe_validation_errors(client):
    assert_api_error(client.post("/transcribe", content=b""), 400, "validation_error", "audio")
    assert_api_error(client.post("/transcribe", content=b"not a wav at all"), 400, "validation_error", "audio")
    assert_api_error(client.get("/transcribe"), 405, "method_not_allowed")
