"""Shared fixtures for v2 tests: temp DB, fake model, fake transcriber."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import db
from app.enrichment import model_client, service
from app.voice import transcriber


class ScriptedModel:
    """Fake ModelClient: returns `reply` (a dict or callable(messages)->dict)."""

    name = "fake:1b"

    def __init__(self, reply=None):
        self.reply = reply or {}
        self.calls: list[list[dict]] = []

    def chat_json(self, messages, schema):
        self.calls.append(messages)
        r = self.reply(messages) if callable(self.reply) else self.reply
        return json.dumps(r)

    def status(self):
        return True, None


class RecordingTranscriber:
    """Fake Transcriber that records the temp WAV path and whether it existed."""

    name = "parakeet-tdt-0.6b-v3"

    def __init__(self, text="hello there", available=True, error: Exception | None = None):
        self.text, self.available, self.error = text, available, error
        self.paths: list[str] = []
        self.existed: list[bool] = []
        self.sizes: list[int] = []

    def status(self):
        return (True, None) if self.available else (False, "Speech helper is starting.")

    def unavailable_message(self):
        return "Voice is still setting up on your laptop. Try again in a minute."

    async def start(self):
        pass

    async def stop(self):
        pass

    async def transcribe(self, wav_path, timeout_s):
        import os

        self.paths.append(wav_path)
        self.existed.append(os.path.exists(wav_path))
        self.sizes.append(os.path.getsize(wav_path))
        if self.error:
            raise self.error
        return self.text, 1.5


@pytest.fixture()
def model():
    m = ScriptedModel()
    model_client.set_model_client(m)
    yield m
    model_client.set_model_client(None)


@pytest.fixture()
def asr():
    t = RecordingTranscriber()
    transcriber.set_transcriber(t)
    yield t
    transcriber.set_transcriber(None)


@pytest.fixture()
def api(tmp_path, model, asr):
    db._engine = db.make_engine(tmp_path / "t.db")
    from app.main import app

    with TestClient(app) as c:
        c.wait = lambda: service.wait_idle(10)
        yield c
    db._engine = None
