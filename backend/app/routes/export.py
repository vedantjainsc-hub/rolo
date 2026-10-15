from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.db import get_session
from app.models import Contact, ContactRow, ExportOut, utcnow_iso

router = APIRouter()


@router.get("/export", response_model=ExportOut)
def export(session: Session = Depends(get_session)) -> ExportOut:
    rows = session.exec(select(ContactRow).order_by(ContactRow.updated_at.desc())).all()
    return ExportOut(exported_at=utcnow_iso(), contacts=[Contact.from_row(r) for r in rows])
