"""v2 API: voice create + name fill, follow-up choices / .ics / upcoming, /api/transcribe
(transcriber mocked; temp WAV must be deleted), health.asr, and the v1 -> v2 migration."""
from __future__ import annotations

import os
import struct
from datetime import date, timedelta

import pytest
from sqlmodel import Session

from app import db
from app.enrichment import service
from app.models import ContactRow
from app.voice.wav import build_wav

GOLD_VOICE = ("This is Priya Shah. I met her at FinTech Forward. She runs partnerships at a payment startup. "
              "I think Stripe adjacent. She wants intros to bank CTOs. Follow up by Friday.")


def card(**kw):
    base = {"headline": "Partnerships at a payments startup", "summary": "s", "follow_ups": [], "gaps": []}
    base.update(kw)
    return base


# ---- voice create ------------------------------------------------------------------

def test_voice_create_without_name(api, model):
    model.reply = card(person_name="Priya Shah")
    r = api.post("/api/contacts", json={"source": "voice", "raw_notes": GOLD_VOICE})
    assert r.status_code == 201
    c = r.json()
    assert c["name"] == "New contact" and c["needs_name"] is True and c["enrichment_status"] == "pending"
    assert c["source"] == "voice"
    api.wait()
    c = api.get(f"/api/contacts/{c['id']}").json()
    assert c["name"] == "Priya Shah" and c["needs_name"] is False
    # the model was told the name is unknown
    assert model.calls[0][1]["content"].startswith("Person: (not given — take it from the notes if said)\n")


def test_voice_name_not_in_notes_is_ignored(api, model):
    model.reply = card(person_name="Elon Musk")
    cid = api.post("/api/contacts", json={"source": "voice", "raw_notes": "Met a founder at a meetup."}).json()["id"]
    api.wait()
    c = api.get(f"/api/contacts/{cid}").json()
    assert c["name"] == "New contact" and c["needs_name"] is True
    assert c["enrichment"]["person_name"] is None


def test_voice_create_with_name_and_patch_clears_needs_name(api, model):
    model.reply = card(person_name="Someone Else")
    c = api.post("/api/contacts", json={"source": "voice", "name": "Ana", "raw_notes": "Ana runs a bakery.",
                                        "enrich": False}).json()
    assert c["name"] == "Ana" and c["needs_name"] is False
    c = api.post("/api/contacts", json={"source": "voice", "raw_notes": "Runs a bakery.", "enrich": False}).json()
    assert c["needs_name"] is True
    c = api.patch(f"/api/contacts/{c['id']}", json={"name": "Bea"}).json()
    assert c["name"] == "Bea" and c["needs_name"] is False


def test_typed_named_contact_never_renamed(api, model):
    model.reply = card(person_name="Priya Shah")
    c = api.post("/api/contacts", json={"name": "P. Shah", "raw_notes": GOLD_VOICE}).json()
    assert c["source"] == "typed"
    cid = c["id"]
    api.wait()
    assert api.get(f"/api/contacts/{cid}").json()["name"] == "P. Shah"
    assert model.calls[0][1]["content"].startswith("Person: P. Shah\n")


@pytest.mark.parametrize("body, msg", [
    ({"source": "voice", "raw_notes": "   "}, "raw_notes: nothing was heard"),
    ({"source": "voice"}, "raw_notes: nothing was heard"),
    ({"raw_notes": "x"}, "name: is required"),
    ({"source": "typed", "name": " ", "raw_notes": "x"}, "name: is required"),
    ({"source": "phone", "name": "x"}, "source: input should be 'typed' or 'voice'"),
    ({"source": "voice", "name": "a" * 121, "raw_notes": "x"}, "name: must be at most 120 characters"),
])
def test_voice_create_validation(api, body, msg):
    r = api.post("/api/contacts", json=body)
    assert r.status_code == 400
    assert r.json() == {"error": {"code": "validation_error", "message": msg}}


# ---- follow-up choices --------------------------------------------------------------

FUS = [{"action": "Send the deck", "when_text": "by Friday"},
       {"action": "Follow up", "when_text": "after Diwali"},
       {"action": "Stay in touch", "when_text": None}]


def _enriched(api, model, follow_ups=FUS, notes="Send the deck by Friday. Follow up after Diwali."):
    model.reply = card(follow_ups=follow_ups)
    cid = api.post("/api/contacts", json={"name": "Priya", "raw_notes": notes}).json()["id"]
    api.wait()
    return cid


def test_follow_up_fields_present(api, model):
    cid = _enriched(api, model)
    fus = api.get(f"/api/contacts/{cid}").json()["enrichment"]["follow_ups"]
    assert set(fus[0]) == {"action", "when_text", "suggested_date", "date_status", "confidence",
                           "confirmed_date", "dismissed"}
    assert [f["date_status"] for f in fus] == ["exact", "needs_date", "none"]
    assert all(f["confirmed_date"] is None and f["dismissed"] is False for f in fus)


def test_confirm_date_persists_and_survives_reenrichment(api, model):
    cid = _enriched(api, model)
    r = api.patch(f"/api/contacts/{cid}/follow-ups/1", json={"confirmed_date": "2026-11-12"})
    assert r.status_code == 200
    assert r.json()["enrichment"]["follow_ups"][1]["confirmed_date"] == "2026-11-12"
    # Re-enrich: same actions, different order and punctuation/case.
    model.reply = card(follow_ups=[{"action": "follow up.", "when_text": "after Diwali"}, FUS[0]])
    assert api.post(f"/api/contacts/{cid}/enrich").status_code == 202
    api.wait()
    fus = api.get(f"/api/contacts/{cid}").json()["enrichment"]["follow_ups"]
    assert fus[0]["action"] == "follow up." and fus[0]["confirmed_date"] == "2026-11-12"
    assert fus[1]["confirmed_date"] is None


def test_dismiss_and_undo(api, model):
    cid = _enriched(api, model)
    fu = api.patch(f"/api/contacts/{cid}/follow-ups/0", json={"dismissed": True}).json()["enrichment"]["follow_ups"][0]
    assert fu["dismissed"] is True and fu["confirmed_date"] is None
    fu = api.patch(f"/api/contacts/{cid}/follow-ups/0", json={"confirmed_date": "2026-10-20"}).json()["enrichment"]["follow_ups"][0]
    assert fu["dismissed"] is False and fu["confirmed_date"] == "2026-10-20"
    fu = api.patch(f"/api/contacts/{cid}/follow-ups/0", json={"confirmed_date": None}).json()["enrichment"]["follow_ups"][0]
    assert fu["confirmed_date"] is None


def test_follow_up_patch_errors(api, model):
    cid = _enriched(api, model)
    r = api.patch(f"/api/contacts/{cid}/follow-ups/1", json={"confirmed_date": "2026-02-30"})
    assert r.status_code == 400 and r.json()["error"]["message"].startswith("confirmed_date:")
    assert api.patch(f"/api/contacts/{cid}/follow-ups/9", json={"dismissed": True}).status_code == 404
    assert api.patch("/api/contacts/nope/follow-ups/0", json={"dismissed": True}).status_code == 404
    with Session(db.get_engine()) as s:
        row = s.get(ContactRow, cid)
        row.enrichment_status = "pending"
        s.add(row)
        s.commit()
    r = api.patch(f"/api/contacts/{cid}/follow-ups/0", json={"dismissed": True})
    assert r.status_code == 409 and r.json()["error"]["code"] == "enrichment_in_progress"


# ---- .ics ------------------------------------------------------------------------------

def test_ics_download(api, model):
    cid = _enriched(api, model)
    r = api.get(f"/api/contacts/{cid}/follow-ups/0.ics")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/calendar")
    assert r.headers["content-disposition"] == 'attachment; filename="rolo-followup.ics"'
    body = r.text
    assert body.startswith("BEGIN:VCALENDAR\r\n") and body.endswith("END:VCALENDAR\r\n")
    assert "DTSTART;VALUE=DATE:" in body and "DTEND;VALUE=DATE:" in body
    assert "SUMMARY:Follow up: Priya — Send the deck" in body
    assert "When: by Friday" in body and "Partnerships at a payments startup" in body
    # confirmed date wins
    api.patch(f"/api/contacts/{cid}/follow-ups/1", json={"confirmed_date": "2026-11-12"})
    assert "DTSTART;VALUE=DATE:20261112\r\n" in api.get(f"/api/contacts/{cid}/follow-ups/1.ics").text
    assert "DTEND;VALUE=DATE:20261113\r\n" in api.get(f"/api/contacts/{cid}/follow-ups/1.ics").text


def test_ics_without_date_is_400(api, model):
    cid = _enriched(api, model)
    r = api.get(f"/api/contacts/{cid}/follow-ups/2.ics")
    assert r.status_code == 400
    assert r.json() == {"error": {"code": "validation_error", "message": "date: pick a date first"}}
    assert api.get(f"/api/contacts/{cid}/follow-ups/7.ics").status_code == 404
    api.patch(f"/api/contacts/{cid}/follow-ups/0", json={"dismissed": True})
    r = api.get(f"/api/contacts/{cid}/follow-ups/0.ics")
    assert r.status_code == 400 and r.json()["error"]["message"] == "date: pick a date first"


# ---- upcoming ----------------------------------------------------------------------

def test_upcoming(api, model):
    today = date.today()
    soon = (today + timedelta(days=3)).isoformat()
    later = (today + timedelta(days=30)).isoformat()
    a = _enriched(api, model, follow_ups=[{"action": "Call", "when_text": "tomorrow"},
                                          {"action": "Lunch", "when_text": "after Diwali"},
                                          {"action": "Coffee", "when_text": "in 2 days"}], notes="x")
    api.patch(f"/api/contacts/{a}/follow-ups/1", json={"confirmed_date": soon})
    api.patch(f"/api/contacts/{a}/follow-ups/2", json={"dismissed": True})
    b = _enriched(api, model, follow_ups=[{"action": "Send deck", "when_text": "today"},
                                          {"action": "Visit", "when_text": "in 1 month"}], notes="y")
    items = api.get("/api/follow-ups/upcoming").json()["items"]
    assert [(i["action"], i["date"]) for i in items] == [
        ("Send deck", today.isoformat()), ("Call", (today + timedelta(days=1)).isoformat()), ("Lunch", soon)]
    assert items[0]["contact_id"] == b and items[1]["index"] == 0 and items[2]["contact_name"] == "Priya"
    assert any(i["date"] == later or i["action"] == "Visit"
               for i in api.get("/api/follow-ups/upcoming?days=60").json()["items"])
    assert api.get("/api/follow-ups/upcoming?days=0").json()["items"][0]["action"] == "Send deck"
    for bad in ("61", "-1", "abc"):
        r = api.get(f"/api/follow-ups/upcoming?days={bad}")
        assert r.status_code == 400 and r.json()["error"]["message"].startswith("days:")


def test_upcoming_excludes_past_confirmed(api, model):
    a = _enriched(api, model, follow_ups=[{"action": "Call", "when_text": "after Diwali"}], notes="x")
    api.patch(f"/api/contacts/{a}/follow-ups/0", json={"confirmed_date": (date.today() - timedelta(days=1)).isoformat()})
    assert api.get("/api/follow-ups/upcoming").json()["items"] == []


# ---- /api/transcribe (transcriber mocked) ---------------------------------------------

def wav(seconds=1.0, rate=16000, channels=1, bits=16, fmt_tag=1):
    frames = int(seconds * rate)
    pcm = b"\x01\x00" * frames * channels * (bits // 16)
    hdr = b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVE"
    hdr += b"fmt " + struct.pack("<IHHIIHH", 16, fmt_tag, channels, rate, rate * channels * bits // 8,
                                  channels * bits // 8, bits)
    return hdr + b"data" + struct.pack("<I", len(pcm)) + pcm


def post_wav(api, data):
    return api.post("/api/transcribe", content=data, headers={"content-type": "audio/wav"})


def test_transcribe_ok_and_temp_file_deleted(api, asr):
    r = post_wav(api, wav(2.0))
    assert r.status_code == 200
    assert r.json() == {"text": "hello there", "duration_s": 1.5}
    assert asr.existed == [True] and asr.sizes == [44 + 64000]
    assert not os.path.exists(asr.paths[0])
    assert os.path.basename(asr.paths[0]).startswith("rolo-asr-")


def test_transcribe_temp_file_deleted_on_error(api, asr):
    from app.voice.transcriber import AsrUnavailable

    asr.error = AsrUnavailable("Voice is still setting up on your laptop. Try again in a minute.")
    r = post_wav(api, wav(1.0))
    assert r.status_code == 503 and r.json()["error"]["code"] == "asr_unavailable"
    assert asr.existed == [True] and not os.path.exists(asr.paths[0])
    asr.error = TimeoutError()
    assert post_wav(api, wav(1.0)).status_code == 503
    assert not any(os.path.exists(p) for p in asr.paths)


def test_transcribe_streaming_size_header_is_tolerated(api, asr):
    data = bytearray(wav(1.0))
    data[40:44] = struct.pack("<I", 0xFFFFFFFF)  # some encoders write "unknown" sizes
    assert post_wav(api, bytes(data)).status_code == 200
    assert asr.sizes == [44 + 32000]


@pytest.mark.parametrize("data, msg", [
    (b"", "audio: is required"),
    (b"not a wav file at all", "audio: must be a WAV file"),
    (wav(1.0, rate=44100), "audio: must be 16 kHz mono 16-bit PCM WAV"),
    (wav(1.0, channels=2), "audio: must be 16 kHz mono 16-bit PCM WAV"),
    (wav(1.0, fmt_tag=3), "audio: must be 16 kHz mono 16-bit PCM WAV"),
    (wav(301.0), "audio: must be at most 5 minutes"),
])
def test_transcribe_validation(api, asr, data, msg):
    r = post_wav(api, data)
    assert r.status_code == 400 and r.json() == {"error": {"code": "validation_error", "message": msg}}
    assert asr.paths == []


def test_transcribe_too_big(api, asr):
    r = post_wav(api, b"RIFF" + b"\x00" * (10 * 1024 * 1024 + 1))
    assert r.status_code == 400 and r.json()["error"]["message"] == "audio: must be at most 10 MB"


def test_transcribe_unavailable_and_empty(api, asr):
    assert post_wav(api, wav(0.0)).json() == {"text": "", "duration_s": 0.0}
    assert asr.paths == []
    asr.available = False
    r = post_wav(api, wav(1.0))
    assert r.status_code == 503
    assert r.json() == {"error": {"code": "asr_unavailable",
                                  "message": "Voice is still setting up on your laptop. Try again in a minute."}}


def test_health_reports_asr(api, asr):
    h = api.get("/api/health").json()
    assert h["asr"] == {"name": "parakeet-tdt-0.6b-v3", "available": True, "detail": None}
    asr.available = False
    assert api.get("/api/health").json()["asr"]["available"] is False


def test_transcript_never_logged(api, asr, caplog):
    asr.text = "secret transcript words"
    with caplog.at_level("DEBUG"):
        post_wav(api, wav(1.0))
    assert "secret transcript" not in caplog.text


# ---- v1 -> v2 migration ------------------------------------------------------------

V1_SCHEMA = """CREATE TABLE contacts (
    id VARCHAR NOT NULL PRIMARY KEY, name VARCHAR NOT NULL, raw_notes VARCHAR NOT NULL,
    tags JSON NOT NULL, enrichment JSON, enrichment_status VARCHAR NOT NULL,
    enrichment_error VARCHAR, enriched_at VARCHAR, model_name VARCHAR, enrichment_job VARCHAR,
    created_at VARCHAR NOT NULL, updated_at VARCHAR NOT NULL)"""
V1_ENRICHMENT = ('{"headline":"Old card","summary":"s","role":{"value":"CTO","confidence":"inferred"},'
                 '"follow_ups":[{"action":"Follow up","when_text":"after Diwali","suggested_date":null},'
                 '{"action":"Call","when_text":"Friday","suggested_date":"2026-10-16"},'
                 '{"action":"Say hi","when_text":null,"suggested_date":null}],'
                 '"gaps":[],"contact_info":{"email":null,"phone":null,"linkedin":null}}')


def test_migration_from_v1_keeps_data(tmp_path, model, asr):
    from fastapi.testclient import TestClient

    path = tmp_path / "v1.db"
    engine = db.make_engine(path)
    with engine.begin() as conn:
        conn.exec_driver_sql(V1_SCHEMA)
        conn.exec_driver_sql(
            "INSERT INTO contacts VALUES ('c1','Old Friend','notes','[\"a\"]',?, 'done', NULL, "
            "'2026-01-01T00:00:00.000000Z','qwen3:14b',NULL,'2026-01-01T00:00:00.000000Z','2026-01-01T00:00:00.000000Z')",
            (V1_ENRICHMENT,),
        )
    db._engine = engine
    from app.main import app

    with TestClient(app) as c:
        got = c.get("/api/contacts/c1").json()
        assert got["name"] == "Old Friend" and got["needs_name"] is False and got["tags"] == ["a"]
        assert got["source"] == "typed"
        e = got["enrichment"]
        assert e["headline"] == "Old card" and e["role"] == {"value": "CTO", "confidence": "inferred"}
        assert e["person_name"] is None
        assert [(f["date_status"], f["confidence"], f["confirmed_date"], f["dismissed"]) for f in e["follow_ups"]] == [
            ("needs_date", "stated", None, False), ("exact", "stated", None, False), ("none", "stated", None, False)]
        # choices work on migrated rows
        r = c.patch("/api/contacts/c1/follow-ups/0", json={"confirmed_date": "2026-11-12"})
        assert r.status_code == 200 and r.json()["enrichment"]["follow_ups"][0]["confirmed_date"] == "2026-11-12"
        exported = c.get("/api/export").json()["contacts"][0]
        assert exported["id"] == "c1" and exported["source"] == "typed"
    # running the migration again is a no-op
    assert db.migrate(engine) == []
    db._engine = None
