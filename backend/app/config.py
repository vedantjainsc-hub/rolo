"""Runtime configuration, read from environment variables."""
from __future__ import annotations

import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent

MODEL_NAME: str = os.environ.get("ROLO_MODEL", "gemma4:e4b")
OLLAMA_URL: str = os.environ.get("OLLAMA_URL", "http://localhost:11434").rstrip("/")
DB_PATH: Path = Path(os.environ.get("ROLO_DB_PATH", str(BACKEND_DIR / "data" / "rolo.db"))).expanduser()

# Seconds to wait for a single model call.
MODEL_TIMEOUT_S: float = float(os.environ.get("ROLO_MODEL_TIMEOUT", "90"))

CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "https://localhost:5173",
    "https://127.0.0.1:5173",
]
# Phones on the LAN reach the Vite dev server, which proxies /api, so they are same-origin.
# This regex additionally allows direct LAN access to the dev server origin on port 5173.
CORS_ORIGIN_REGEX = r"^https?://(localhost|127\.0\.0\.1|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+)(:5173)?$"

# Speech helper (v2 voice). See docs/VOICE.md.
ASR_BIN: str = os.environ.get("ROLO_ASR_BIN", str(BACKEND_DIR / "asr" / ".build" / "release" / "rolo-asr"))
ASR_MODELS_DIR: str = os.environ.get(
    "ROLO_ASR_MODELS_DIR",
    str(Path.home() / "Library" / "Application Support" / "FluidAudio" / "Models" / "parakeet-tdt-0.6b-v3"),
)
ASR_TIMEOUT_S: float = float(os.environ.get("ROLO_ASR_TIMEOUT", "20"))
AUDIO_MAX_BYTES = 10 * 1024 * 1024
AUDIO_MAX_SECONDS = 300
