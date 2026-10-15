"""Speech-to-text. The ONLY module that knows about the rolo-asr helper (backend/asr/),
mirroring enrichment/model_client.py: everything else talks to a `Transcriber`.

The helper is a long-running Swift process speaking JSON lines (docs/VOICE.md):
  stdout once loaded: {"ready": true}
  stdin:  {"id": "...", "wav": "/abs/path.wav"}
  stdout: {"id": "...", "text": "...", "duration_s": 3.2} | {"id": "...", "error": "..."}
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Protocol, runtime_checkable

from app import config

log = logging.getLogger("rolo.asr")

ASR_NAME = "parakeet-tdt-0.6b-v3"
MSG_NOT_SET_UP = "Voice isn't set up. Run ./run.sh once on the laptop."
MSG_STARTING = "Voice is still setting up on your laptop. Try again in a minute."
DETAIL_NOT_SET_UP = "Run ./run.sh once to set up voice"
READY_TIMEOUT_S = 180.0  # first load compiles CoreML models; later starts take < 1 s


class AsrUnavailable(Exception):
    """Speech helper missing, starting, or crashed. `user_message` is safe to show."""

    def __init__(self, user_message: str):
        super().__init__(user_message)
        self.user_message = user_message


class AsrFailed(Exception):
    """The helper answered with an error for this audio."""


@runtime_checkable
class Transcriber(Protocol):
    name: str

    def status(self) -> tuple[bool, str | None]:
        """(available, detail) for /api/health."""
        ...

    def unavailable_message(self) -> str:
        """User-facing 503 message for the current state."""
        ...

    async def start(self) -> None:
        """Begin starting up in the background. Must not block app startup."""
        ...

    async def stop(self) -> None: ...

    async def transcribe(self, wav_path: str, timeout_s: float) -> tuple[str, float]:
        """Return (text, duration_s). Raises AsrUnavailable / AsrFailed / TimeoutError."""
        ...


class FluidAudioTranscriber:
    """Runs backend/asr/.build/release/rolo-asr as a child process."""

    def __init__(self, binary: str | None = None, models_dir: str | None = None, max_restarts: int = 1):
        self.name = ASR_NAME
        self.binary = Path(binary or config.ASR_BIN)
        self.models_dir = Path(models_dir or config.ASR_MODELS_DIR).expanduser()
        self.max_restarts = max_restarts
        self._restarts = 0
        self._state = "idle"  # idle | missing | starting | ready | failed
        self._proc: asyncio.subprocess.Process | None = None
        self._lock: asyncio.Lock | None = None
        self._start_task: asyncio.Task | None = None

    # ---- status ------------------------------------------------------------------
    def _installed(self) -> bool:
        models_ok = self.models_dir.is_dir() and any(self.models_dir.iterdir())
        return self.binary.is_file() and os.access(self.binary, os.X_OK) and models_ok

    def status(self) -> tuple[bool, str | None]:
        if self._state == "ready":
            return True, None
        if self._state in ("missing", "idle") and not self._installed():
            return False, f"Speech helper isn't built or its models aren't downloaded. {DETAIL_NOT_SET_UP}."
        if self._state in ("starting", "idle"):
            return False, "Speech helper is starting."
        return False, f"Speech helper stopped working. {DETAIL_NOT_SET_UP}, then restart Rolo."

    def unavailable_message(self) -> str:
        return MSG_STARTING if self._state in ("starting", "idle") and self._installed() else MSG_NOT_SET_UP

    # ---- lifecycle ---------------------------------------------------------------
    async def start(self) -> None:
        self._lock = asyncio.Lock()
        if not self._installed():
            self._state = "missing"
            log.info("Speech helper not set up (binary or models missing); voice disabled")
            return
        self._state = "starting"
        self._start_task = asyncio.create_task(self._spawn())

    async def _spawn(self) -> None:
        try:
            self._proc = await asyncio.create_subprocess_exec(
                str(self.binary),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                limit=1 << 20,
            )
            loop = asyncio.get_running_loop()
            started = loop.time()
            while True:
                left = READY_TIMEOUT_S - (loop.time() - started)
                line = await asyncio.wait_for(self._proc.stdout.readline(), timeout=max(left, 0.1))
                if not line:
                    raise RuntimeError("helper exited during startup")
                msg = _parse(line)
                if msg and "ready" in msg:
                    if msg["ready"] is True:
                        self._state = "ready"
                        log.info("Speech helper ready in %.1fs", loop.time() - started)
                        return
                    raise RuntimeError("helper could not load its models")
        except Exception as exc:  # noqa: BLE001
            log.warning("Speech helper failed to start: %s", type(exc).__name__)
            await self._kill()
            self._state = "failed"

    async def _kill(self) -> None:
        proc, self._proc = self._proc, None
        if proc and proc.returncode is None:
            proc.kill()
            try:
                await asyncio.wait_for(proc.wait(), 2)
            except Exception:  # noqa: BLE001
                pass

    async def _crashed(self) -> None:
        await self._kill()
        if self._restarts < self.max_restarts:
            self._restarts += 1
            log.warning("Speech helper crashed; restarting (%d/%d)", self._restarts, self.max_restarts)
            self._state = "starting"
            self._start_task = asyncio.create_task(self._spawn())
        else:
            log.warning("Speech helper crashed again; voice disabled until restart")
            self._state = "failed"

    async def stop(self) -> None:
        if self._start_task and not self._start_task.done():
            self._start_task.cancel()
        if self._proc and self._proc.stdin:
            try:
                self._proc.stdin.close()
            except Exception:  # noqa: BLE001
                pass
        await self._kill()

    # ---- work --------------------------------------------------------------------
    async def transcribe(self, wav_path: str, timeout_s: float) -> tuple[str, float]:
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:  # the helper handles one request at a time
            if self._state != "ready" or self._proc is None:
                raise AsrUnavailable(self.unavailable_message())
            req_id = str(uuid.uuid4())
            proc = self._proc
            try:
                proc.stdin.write((json.dumps({"id": req_id, "wav": wav_path}) + "\n").encode())
                await proc.stdin.drain()

                async def read_answer() -> dict:
                    while True:
                        line = await proc.stdout.readline()
                        if not line:
                            raise ConnectionError("helper exited")
                        msg = _parse(line)
                        if msg and msg.get("id") == req_id:
                            return msg

                msg = await asyncio.wait_for(read_answer(), timeout=timeout_s)
            except asyncio.TimeoutError:
                await self._crashed()  # a hung helper is treated like a crash
                raise TimeoutError("transcription timed out") from None
            except (ConnectionError, BrokenPipeError, ConnectionResetError):
                await self._crashed()
                raise AsrUnavailable(self.unavailable_message()) from None
            if "error" in msg:
                raise AsrFailed(str(msg["error"]))
            return str(msg.get("text", "")), float(msg.get("duration_s", 0.0))


def _parse(line: bytes) -> dict | None:
    try:
        obj = json.loads(line.decode("utf-8", "replace"))
        return obj if isinstance(obj, dict) else None
    except ValueError:
        return None  # not a protocol line


_transcriber: Transcriber | None = None


def get_transcriber() -> Transcriber:
    global _transcriber
    if _transcriber is None:
        _transcriber = FluidAudioTranscriber()
    return _transcriber


def set_transcriber(t: Transcriber | None) -> None:
    """Override the transcriber (used by tests)."""
    global _transcriber
    _transcriber = t
