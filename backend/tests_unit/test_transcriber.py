"""FluidAudioTranscriber against a fake helper process speaking the VOICE.md protocol."""
from __future__ import annotations

import asyncio
import os
import sys
import textwrap

import pytest

from app.voice.transcriber import MSG_NOT_SET_UP, MSG_STARTING, AsrFailed, AsrUnavailable, FluidAudioTranscriber

FAKE = textwrap.dedent('''\
    #!{python}
    import json, os, sys, time
    mode = os.environ.get("FAKE_MODE", "ok")
    print("library noise that is not JSON", flush=True)
    if mode == "noready":
        print(json.dumps({{"ready": False, "error": "no models"}}), flush=True); sys.exit(2)
    print(json.dumps({{"ready": True}}), flush=True)
    for line in sys.stdin:
        req = json.loads(line)
        if mode == "crash" and not os.path.exists(os.environ["FAKE_FLAG"]):
            open(os.environ["FAKE_FLAG"], "w").close(); sys.exit(1)
        if mode == "hang":
            time.sleep(30)
        if req["wav"].endswith("bad.wav"):
            print(json.dumps({{"id": req["id"], "error": "transcription failed"}}), flush=True); continue
        print(json.dumps({{"id": "someone-else", "text": "ignore me"}}), flush=True)
        print(json.dumps({{"id": req["id"], "text": "heard " + os.path.basename(req["wav"]), "duration_s": 2.5}}), flush=True)
''')


@pytest.fixture()
def helper(tmp_path):
    exe = tmp_path / "rolo-asr"
    exe.write_text(FAKE.format(python=sys.executable))
    exe.chmod(0o755)
    models = tmp_path / "models"
    models.mkdir()
    (models / "Encoder.mlmodelc").mkdir()
    return str(exe), str(models)


async def _ready(t, timeout=10.0):
    for _ in range(int(timeout / 0.02)):
        if t.status()[0]:
            return
        await asyncio.sleep(0.02)
    raise AssertionError(f"helper never became ready: {t.status()}")


def run(coro):
    return asyncio.run(coro)


def test_missing_binary_or_models(tmp_path):
    async def go():
        t = FluidAudioTranscriber(binary=str(tmp_path / "nope"), models_dir=str(tmp_path))
        await t.start()
        ok, detail = t.status()
        assert not ok and "Run ./run.sh once to set up voice" in detail
        assert t.unavailable_message() == MSG_NOT_SET_UP
        with pytest.raises(AsrUnavailable):
            await t.transcribe("/x.wav", 1)
    run(go())


def test_protocol_roundtrip(helper):
    async def go():
        t = FluidAudioTranscriber(binary=helper[0], models_dir=helper[1])
        await t.start()
        assert t.unavailable_message() == MSG_STARTING  # not ready yet, but installed
        await _ready(t)
        assert await t.transcribe("/tmp/a.wav", 5) == ("heard a.wav", 2.5)
        texts = await asyncio.gather(*(t.transcribe(f"/tmp/{i}.wav", 5) for i in range(5)))  # serialised by the lock
        assert [x[0] for x in texts] == [f"heard {i}.wav" for i in range(5)]
        with pytest.raises(AsrFailed):
            await t.transcribe("/tmp/bad.wav", 5)
        await t.stop()
    run(go())


def test_not_ready_helper_is_failed(helper, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "noready")

    async def go():
        t = FluidAudioTranscriber(binary=helper[0], models_dir=helper[1])
        await t.start()
        await asyncio.sleep(0.5)
        ok, detail = t.status()
        assert not ok and "stopped working" in detail
        assert t.unavailable_message() == MSG_NOT_SET_UP
    run(go())


def test_crash_restarts_once(helper, monkeypatch, tmp_path):
    monkeypatch.setenv("FAKE_MODE", "crash")
    monkeypatch.setenv("FAKE_FLAG", str(tmp_path / "crashed"))

    async def go():
        t = FluidAudioTranscriber(binary=helper[0], models_dir=helper[1])
        await t.start()
        await _ready(t)
        with pytest.raises(AsrUnavailable):  # first request kills the helper
            await t.transcribe("/tmp/a.wav", 5)
        await _ready(t)  # restarted
        assert (await t.transcribe("/tmp/b.wav", 5))[0] == "heard b.wav"
        await t.stop()
    run(go())


def test_second_crash_disables(helper, monkeypatch, tmp_path):
    monkeypatch.setenv("FAKE_MODE", "hang")

    async def go():
        t = FluidAudioTranscriber(binary=helper[0], models_dir=helper[1], max_restarts=1)
        await t.start()
        await _ready(t)
        with pytest.raises(TimeoutError):
            await t.transcribe("/tmp/a.wav", 0.3)  # hang -> killed and restarted
        await _ready(t)
        with pytest.raises(TimeoutError):
            await t.transcribe("/tmp/b.wav", 0.3)  # second time -> disabled
        assert t.status()[0] is False
        await t.stop()
    run(go())
