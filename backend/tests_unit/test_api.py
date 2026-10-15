"""API smoke tests with a temp DB and a fake model client (no Ollama needed)."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app import db
from app.enrichment import model_client, service
from app.models import ContactRow

GOOD = json.dumps({
    "headline": "Café owner",
    "company": {"value": "Le Croissant", "confidence": "stated"},
    "suggested_tags": ["Food"],
    "contact_info": {"email": "made@up.com"},
})


class Fake:
    name = "fake:1b"

    def chat_json(self, messages, schema):
        return GOOD

    def status(self):
        return True, None


class FakeTranscriber:
    """Never spawn the real speech helper in unit tests."""
    name = "parakeet-tdt-0.6b-v3"

    def status(self):
        return False, "not in tests"

    def unavailable_message(self):
        return "Voice isn't set up. Run ./run.sh once on the laptop."

    async def start(self):
        pass

    async def stop(self):
        pass

    async def transcribe(self, wav_path, timeout_s):
        raise AssertionError("not used")


@pytest.fixture()
def client(tmp_path):
    from app.voice import transcriber

    db._engine = db.make_engine(tmp_path / "t.db")
    model_client.set_model_client(Fake())
    transcriber.set_transcriber(FakeTranscriber())
    from app.main import app

    with TestClient(app) as c:
        yield c
    model_client.set_model_client(None)
    transcriber.set_transcriber(None)
    db._engine = None


def test_create_enrich_and_search(client):
    r = client.post("/api/contacts", json={"name": "  Ana  ", "raw_notes": "Runs Le Croissant café."})
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "Ana" and body["enrichment_status"] == "pending"
    assert service.wait_idle()
    c = client.get(f"/api/contacts/{body['id']}").json()
    assert c["enrichment_status"] == "done" and c["model_name"] == "fake:1b"
    assert c["enrichment"]["contact_info"]["email"] is None
    assert c["tags"] == ["food"]  # seeded from suggestions
    assert [x["company"] for x in client.get("/api/contacts?q=croissant").json()["contacts"]] == ["Le Croissant"]


@pytest.mark.parametrize(
    "body, message",
    [
        ({"name": " "}, "name: is required"),
        ({"raw_notes": "x"}, "name: is required"),
        ({"name": "a" * 121}, "name: must be at most 120 characters"),
        ({"name": "x", "raw_notes": "n" * 10001}, "raw_notes: must be at most 10,000 characters"),
        ({"name": "x", "tags": "x"}, "tags: must be a list of strings"),
        ({"name": "x", "tags": ["t" * 41]}, "tags: each tag must be at most 40 characters"),
    ],
)
def test_validation_messages_start_with_field(client, body, message):
    r = client.post("/api/contacts", json=body)
    assert r.status_code == 400
    assert r.json() == {"error": {"code": "validation_error", "message": message}}


def test_malformed_json_and_patch_messages(client):
    r = client.post("/api/contacts", content=b'{"name":', headers={"content-type": "application/json"})
    assert r.status_code == 400 and r.json()["error"]["message"].startswith("body:")
    cid = client.post("/api/contacts", json={"name": "P", "enrich": False}).json()["id"]
    assert client.patch(f"/api/contacts/{cid}", json={"name": "  "}).json()["error"]["message"] == "name: is required"
    assert client.patch(f"/api/contacts/{cid}", json={"name": None}).json()["error"]["message"] == "name: must be a string"
    r = client.patch(f"/api/contacts/{cid}", json={"tags": ["a"]})
    assert r.status_code == 200 and r.json()["name"] == "P"  # omitted fields untouched


def test_other_errors(client):
    assert client.post("/api/contacts", json={"name": "x", "raw_notes": "n" * 10000, "enrich": False}).status_code == 201
    assert client.get("/api/contacts/nope").json() == {"error": {"code": "not_found", "message": "Contact not found."}}
    assert client.get("/api/nothing").json()["error"]["code"] == "not_found"


def test_blank_notes_never_call_model(client):
    class Boom(Fake):
        def chat_json(self, messages, schema):
            raise AssertionError("model must not be called")

    model_client.set_model_client(Boom())
    r = client.post("/api/contacts", json={"name": "Blank", "raw_notes": "   \n "})
    assert r.status_code == 201 and r.json()["enrichment_status"] == "none"
    cid = r.json()["id"]
    r = client.post(f"/api/contacts/{cid}/enrich")
    assert r.status_code == 400
    assert r.json()["error"] == {"code": "validation_error", "message": "raw_notes: add some notes before enriching"}
    assert service.wait_idle()
    assert client.get(f"/api/contacts/{cid}").json()["enrichment_status"] == "none"


def test_append_overflow_message(client):
    cid = client.post("/api/contacts", json={"name": "L", "raw_notes": "n" * 9995, "enrich": False}).json()["id"]
    r = client.post(f"/api/contacts/{cid}/notes", json={"text": "more", "enrich": False})
    assert r.status_code == 400
    assert r.json()["error"]["message"] == "text: notes would exceed 10,000 characters"
    r = client.post(f"/api/contacts/{cid}/notes", json={"text": " "})
    assert r.json()["error"]["message"] == "text: is required"


def test_enrich_conflict_and_notes_append(client):
    cid = client.post("/api/contacts", json={"name": "Bo", "raw_notes": "hi", "enrich": False}).json()["id"]
    with Session(db.get_engine()) as s:
        row = s.get(ContactRow, cid)
        row.enrichment_status = "pending"
        s.add(row)
        s.commit()
    r = client.post(f"/api/contacts/{cid}/enrich")
    assert r.status_code == 409 and r.json()["error"]["code"] == "enrichment_in_progress"
    r = client.post(f"/api/contacts/{cid}/notes", json={"text": "met again", "enrich": False})
    assert r.status_code == 200
    assert r.json()["raw_notes"].startswith("hi\n\n[") and r.json()["raw_notes"].endswith("] met again")


def test_startup_resets_pending(tmp_path):
    from app.voice import transcriber

    transcriber.set_transcriber(FakeTranscriber())
    db._engine = db.make_engine(tmp_path / "t.db")
    db.init_db()
    with Session(db.get_engine()) as s:
        s.add(ContactRow(id="p1", name="P", enrichment_status="pending"))
        s.commit()
    from app.main import app

    with TestClient(app) as c:
        got = c.get("/api/contacts/p1").json()
    assert got["enrichment_status"] == "failed"
    assert got["enrichment_error"] == "Enrichment was interrupted. Tap Retry."
    db._engine = None


# ---- round-1 QA fixes ----------------------------------------------------------

import threading
import time


class Gate(Fake):
    """A model that blocks until released, to simulate a slow/hung Ollama."""

    def __init__(self):
        self.release = threading.Event()
        self.calls = 0

    def chat_json(self, messages, schema):
        self.calls += 1
        self.release.wait(10)
        return GOOD


def test_bug1_saves_never_wait_on_enrichment(client):
    gate = Gate()
    model_client.set_model_client(gate)
    try:
        t0 = time.monotonic()
        ids = []
        for i in range(25):
            r = client.post("/api/contacts", json={"name": f"P{i}", "raw_notes": "Runs Le Croissant café."})
            assert r.status_code == 201
            ids.append(r.json()["id"])
        assert client.get("/api/contacts").status_code == 200
        assert time.monotonic() - t0 < 5
        time.sleep(0.2)
        assert gate.calls == 1  # one job at a time
    finally:
        gate.release.set()
    assert service.wait_idle(20)
    assert gate.calls == 25
    assert {client.get(f"/api/contacts/{i}").json()["enrichment_status"] for i in ids} == {"done"}


def test_bug2_crash_marks_failed_and_retry_works(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(service, "enrich_notes", boom)
    cid = client.post("/api/contacts", json={"name": "C", "raw_notes": "notes"}).json()["id"]
    assert service.wait_idle()
    got = client.get(f"/api/contacts/{cid}").json()
    assert got["enrichment_status"] == "failed"
    assert got["enrichment_error"] == service.CRASH_MSG
    assert "kaboom" not in got["enrichment_error"]
    monkeypatch.undo()
    assert client.post(f"/api/contacts/{cid}/enrich").status_code == 202
    assert service.wait_idle()
    assert client.get(f"/api/contacts/{cid}").json()["enrichment_status"] == "done"


def test_bug5_concurrent_enrich_only_one_wins(client):
    gate = Gate()
    model_client.set_model_client(gate)
    try:
        for _ in range(5):
            cid = client.post("/api/contacts", json={"name": "R", "raw_notes": "n", "enrich": False}).json()["id"]
            barrier = threading.Barrier(6)
            codes = []

            def hit():
                barrier.wait()
                codes.append(client.post(f"/api/contacts/{cid}/enrich").status_code)

            ts = [threading.Thread(target=hit) for _ in range(6)]
            [t.start() for t in ts]
            [t.join() for t in ts]
            assert sorted(codes) == [202, 409, 409, 409, 409, 409]
    finally:
        gate.release.set()
    assert service.wait_idle(20)


def test_405_uses_api_error(client):
    r = client.put("/api/contacts")
    assert r.status_code == 405
    assert r.json()["error"]["code"] == "method_not_allowed"
