"""Minimal WAV validation for /api/transcribe: 16 kHz, mono, PCM16."""
from __future__ import annotations

import struct
from dataclasses import dataclass

RATE = 16_000


@dataclass
class Wav:
    pcm: bytes          # raw little-endian int16 samples
    duration_s: float


def parse_wav(data: bytes, max_seconds: float) -> Wav:
    """Validate and return the PCM payload. Raises ValueError("audio: ...")."""
    if not data:
        raise ValueError("audio: is required")
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("audio: must be a WAV file")
    pos, fmt, pcm = 12, None, None
    while pos + 8 <= len(data):
        cid, size = data[pos:pos + 4], struct.unpack("<I", data[pos + 4:pos + 8])[0]
        body_start = pos + 8
        body_end = min(body_start + size, len(data))  # tolerate streaming/oversized sizes
        if cid == b"fmt " and body_end - body_start >= 16:
            fmt = struct.unpack("<HHIIHH", data[body_start:body_start + 16])
            if fmt[0] == 0xFFFE and body_end - body_start >= 26:  # WAVE_FORMAT_EXTENSIBLE
                sub = struct.unpack("<H", data[body_start + 24:body_start + 26])[0]
                fmt = (sub,) + fmt[1:]
        elif cid == b"data":
            pcm = data[body_start:body_end]
            break
        pos = body_start + size + (size & 1)
    if fmt is None:
        raise ValueError("audio: WAV has no format chunk")
    tag, channels, rate, _, _, bits = fmt
    if tag != 1 or channels != 1 or rate != RATE or bits != 16:
        raise ValueError("audio: must be 16 kHz mono 16-bit PCM WAV")
    if pcm is None:
        raise ValueError("audio: WAV has no data chunk")
    pcm = pcm[: len(pcm) - (len(pcm) % 2)]
    duration = len(pcm) / 2 / RATE
    if duration > max_seconds:
        raise ValueError(f"audio: must be at most {int(max_seconds // 60)} minutes")
    return Wav(pcm=pcm, duration_s=duration)


def build_wav(pcm: bytes) -> bytes:
    """A clean 44-byte-header WAV around validated PCM16 mono 16 kHz samples."""
    header = b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVE"
    header += b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, RATE, RATE * 2, 2, 16)
    header += b"data" + struct.pack("<I", len(pcm))
    return header + pcm
