from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import time

from fastapi import APIRouter, Request

from app import config
from app.errors import ApiException
from app.models import TranscribeOut
from app.voice.transcriber import AsrFailed, AsrUnavailable, get_transcriber
from app.voice.wav import build_wav, parse_wav

router = APIRouter()
log = logging.getLogger("rolo.voice")


@router.post("/transcribe", response_model=TranscribeOut)
async def transcribe(request: Request) -> TranscribeOut:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > config.AUDIO_MAX_BYTES:
        raise ApiException(400, "validation_error", "audio: must be at most 10 MB")
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > config.AUDIO_MAX_BYTES:
            raise ApiException(400, "validation_error", "audio: must be at most 10 MB")
    try:
        wav = parse_wav(bytes(body), config.AUDIO_MAX_SECONDS)
    except ValueError as exc:
        raise ApiException(400, "validation_error", str(exc)) from None

    t = get_transcriber()
    available, _ = t.status()
    if not available:
        raise ApiException(503, "asr_unavailable", t.unavailable_message())
    if not wav.pcm:
        return TranscribeOut(text="", duration_s=0.0)

    fd, path = tempfile.mkstemp(prefix="rolo-asr-", suffix=".wav")
    started = time.monotonic()
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(build_wav(wav.pcm))
        text, duration = await t.transcribe(path, config.ASR_TIMEOUT_S)
    except AsrUnavailable as exc:
        raise ApiException(503, "asr_unavailable", exc.user_message) from None
    except (TimeoutError, asyncio.TimeoutError):
        raise ApiException(503, "asr_unavailable", "Voice took too long to respond. Try again.") from None
    except AsrFailed:
        raise ApiException(400, "validation_error", "audio: couldn't be transcribed") from None
    finally:
        try:
            os.unlink(path)  # audio is never kept
        except FileNotFoundError:
            pass
    # Never log transcript text: durations and lengths only.
    log.info("Transcribed %.1fs of audio -> %d chars in %.2fs", wav.duration_s, len(text), time.monotonic() - started)
    return TranscribeOut(text=text, duration_s=round(duration or wav.duration_s, 3))
