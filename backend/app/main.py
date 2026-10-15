"""Rolo backend: FastAPI app. Run from backend/: uvicorn app.main:app --host 0.0.0.0 --port 8000"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import config, errors
from app.db import init_db
from app.enrichment.service import reset_interrupted, start_worker, stop_worker
from app.routes import contacts, export, followups, health, voice
from app.voice.transcriber import get_transcriber

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("rolo")
# httpx logs every request (incl. health polls of /api/tags) at INFO; keep the console quiet.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(_: FastAPI):
    added = init_db()
    if added:
        log.info("Migrated database: added columns %s", ", ".join(added))
    n = reset_interrupted()
    if n:
        log.info("Marked %d interrupted enrichment(s) as failed", n)
    start_worker()
    await get_transcriber().start()  # spawns the speech helper in the background
    log.info("Rolo backend ready (model=%s, ollama=%s, db=%s)", config.MODEL_NAME, config.OLLAMA_URL, config.DB_PATH)
    yield
    await get_transcriber().stop()
    stop_worker()


app = FastAPI(title="Rolo API", version="2", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_origin_regex=config.CORS_ORIGIN_REGEX,
    allow_methods=["*"],
    allow_headers=["*"],
)
errors.install(app)

for r in (health.router, contacts.router, followups.router, export.router, voice.router):
    app.include_router(r, prefix="/api")
