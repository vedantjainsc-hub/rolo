from __future__ import annotations

from fastapi import APIRouter
from starlette.concurrency import run_in_threadpool

from app.enrichment.model_client import get_model_client
from app.models import Health, ModelStatus
from app.voice.transcriber import get_transcriber

router = APIRouter()


@router.get("/health", response_model=Health)
async def health() -> Health:
    client = get_model_client()
    available, detail = await run_in_threadpool(client.status)
    t = get_transcriber()
    asr_ok, asr_detail = t.status()
    return Health(
        model=ModelStatus(name=client.name, available=available, detail=detail),
        asr=ModelStatus(name=t.name, available=asr_ok, detail=asr_detail),
    )
