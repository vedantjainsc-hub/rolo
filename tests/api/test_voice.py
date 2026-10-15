"""POST /api/transcribe against the real speech helper (G4, G7 codes, G8, performance).

Skips with a clear reason if /api/health reports asr unavailable.
Run the backend from ./run.sh; ROLO_RUN_LOG (optional) points at its log for the G8 log check.
"""
from __future__ import annotations

import concurrent.futures as cf
import glob
import io
import os
import re
import struct
import subprocess
import tempfile
import threading
import time
import wave
from pathlib import Path

import httpx
import pytest

from conftest import assert_api_error

FIX = Path(__file__).resolve().parent.parent / "fixtures"
VOICE = FIX / "voice"
GOLDEN = FIX / "golden_sample_16k.wav"


@pytest.fixture(scope="module")
def asr_ready(api_url):
    h = httpx.get(f"{api_url}/api/health", timeout=10).json()
    if not h["asr"]["available"]:
        pytest.skip(f"Speech helper unavailable: {h['asr']['detail']}")
    return h["asr"]["name"]


def _wav(samples: bytes, rate=16000, channels=1, width=2) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(samples)
    return buf.getvalue()


def _pcm(path: Path) -> bytes:
    with wave.open(str(path), "rb") as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1
        return w.readframes(w.getnframes())


def _post(client, data: bytes, timeout=60) -> httpx.Response:
    return client.post("/transcribe", content=data, headers={"Content-Type": "audio/wav"}, timeout=timeout)


# ------------------------------------------------------------------ G4 accuracy

@pytest.mark.parametrize("path", [GOLDEN, VOICE / "golden_16k.wav"], ids=["lead_sample", "say_golden"])
def test_golden_transcript_contains_key_phrases(client, asr_ready, path):
    r = _post(client, path.read_bytes())
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"text", "duration_s"}
    text = body["text"].lower()
    missing = [p for p in ("priya shah", "fintech forward", "bank ctos", "friday") if p not in text]
    assert not missing, f"missing {missing} in transcript: {body['text']!r}"
    assert abs(body["duration_s"] - len(_pcm(path)) / 32000) < 0.5


# ------------------------------------------------------------------ performance (VOICE.md: 60 s in <= 2 s warm)

def test_sixty_seconds_transcribes_in_two_seconds(client, asr_ready):
    pcm = _pcm(VOICE / "script30_16k.wav")
    data = _wav(pcm + pcm[: 16000 * 2 * 29])  # ~60 s
    _post(client, _wav(pcm[: 32000]))  # warm
    t0 = time.monotonic()
    r = _post(client, data)
    dt = time.monotonic() - t0
    assert r.status_code == 200 and "marcus" in r.json()["text"].lower()
    print(f"60 s audio transcribed in {dt:.2f}s")
    assert dt <= 2.0, f"{dt:.2f}s"


# ------------------------------------------------------------------ validation

def test_empty_wav_returns_empty_text(client, asr_ready):
    r = _post(client, _wav(b""))
    assert r.status_code == 200 and r.json() == {"text": "", "duration_s": 0}


def test_silence_returns_200(client, asr_ready):
    r = _post(client, _wav(b"\x00\x00" * 16000 * 2))
    assert r.status_code == 200 and isinstance(r.json()["text"], str)


@pytest.mark.parametrize("fixture", ["golden_44k.wav", "golden_48k.wav", "golden_stereo16k.wav"])
def test_wrong_format_rejected(client, fixture):
    e = assert_api_error(_post(client, (VOICE / fixture).read_bytes()), 400, "validation_error", "audio")
    assert "16 kHz" in e["message"]


def test_8bit_rejected(client):
    assert_api_error(_post(client, _wav(b"\x80" * 16000, width=1)), 400, "validation_error", "audio")


def test_over_five_minutes_rejected(client):
    data = _wav(b"\x00\x00" * 16000 * 301)  # 301 s, 9.6 MB (< 10 MB)
    e = assert_api_error(_post(client, data), 400, "validation_error", "audio")
    assert "5 minutes" in e["message"]


def test_exactly_five_minutes_accepted(client, asr_ready):
    r = _post(client, _wav(b"\x00\x00" * 16000 * 300), timeout=60)
    assert r.status_code == 200, r.text


def test_over_ten_mb_rejected(client):
    data = b"RIFF" + b"\x00" * (10 * 1024 * 1024 + 10)
    assert_api_error(_post(client, data), 400, "validation_error", "audio")


def test_truncated_and_garbage_headers(client):
    good = (VOICE / "golden_16k.wav").read_bytes()
    for bad in (good[:20], b"RIFF\x00\x00\x00\x00WAVE", b"RIFF" + good[4:12] + b"junk" + b"\x10\x00\x00\x00"):
        r = _post(client, bad)
        assert r.status_code == 400 and r.json()["error"]["code"] == "validation_error", (bad[:24], r.text)


def test_streaming_header_with_oversized_sizes_is_tolerated(client, asr_ready):
    """Browsers' live WAVs are well-formed, but data-size fields larger than the body must not 500."""
    good = bytearray((VOICE / "golden_16k.wav").read_bytes())
    i = good.find(b"data")
    good[i + 4:i + 8] = struct.pack("<I", 0xFFFFFFF0)
    r = _post(client, bytes(good))
    assert r.status_code == 200 and "priya" in r.json()["text"].lower()


def test_parallel_requests_all_succeed(client, asr_ready):
    data = (VOICE / "noname_16k.wav").read_bytes()
    url = f"{client.base_url}transcribe"
    with cf.ThreadPoolExecutor(max_workers=4) as ex:
        res = list(ex.map(lambda _: httpx.post(url, content=data, timeout=60), range(4)))
    assert [r.status_code for r in res] == [200] * 4
    assert all("climate" in r.json()["text"].lower() for r in res)


# ------------------------------------------------------------------ G8 no audio left on disk, no transcript in logs

def _backend_tmpdirs() -> set[str]:
    dirs = {tempfile.gettempdir(), "/tmp", "/private/tmp", "/var/tmp"}
    try:
        pid = subprocess.run(["lsof", "-nP", "-tiTCP:8000", "-sTCP:LISTEN"], capture_output=True, text=True).stdout.split()[0]
        env = subprocess.run(["ps", "eww", "-o", "command=", "-p", pid], capture_output=True, text=True).stdout
        m = re.search(r"\bTMPDIR=(\S+)", env)
        if m:
            dirs.add(m.group(1))
    except (IndexError, OSError):
        pass
    return {d.rstrip("/") for d in dirs if os.path.isdir(d)}


def _leftovers(dirs) -> list[str]:
    return [f for d in dirs for f in glob.glob(os.path.join(d, "rolo-asr-*.wav"))]


def test_no_audio_left_after_ten_transcriptions(client, asr_ready):
    dirs = _backend_tmpdirs()
    before = set(_leftovers(dirs))
    seen: set[str] = set()
    stop = threading.Event()

    def watch():  # prove we are watching the directory the backend actually uses
        while not stop.is_set():
            seen.update(_leftovers(dirs))
            time.sleep(0.005)

    th = threading.Thread(target=watch, daemon=True)
    th.start()
    data = (VOICE / "script30_16k.wav").read_bytes()
    for _ in range(10):
        assert _post(client, data).status_code == 200
    stop.set()
    th.join()
    after = set(_leftovers(dirs))
    print(f"temp dirs watched: {sorted(dirs)}; temp files observed during requests: {len(seen - before)}")
    assert after == before, f"leftover audio: {sorted(after - before)}"
    assert seen - before, "never saw the temp file; watching the wrong directory?"


def test_transcript_text_not_in_log(client, asr_ready):
    log = os.environ.get("ROLO_RUN_LOG")
    if not log or not Path(log).exists():
        pytest.skip("set ROLO_RUN_LOG to the backend log file to check it")
    _post(client, (VOICE / "script30_16k.wav").read_bytes())
    _post(client, GOLDEN.read_bytes())
    time.sleep(0.5)
    text = Path(log).read_text(errors="replace").lower()
    for word in ("kinetica", "marcus", "fintech", "biscuit", "logistics", "priya"):
        assert word not in text, f"transcript word {word!r} found in log"
    assert "transcribed" in text, "expected the duration-only log line"
