from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select

from app.db import get_session
from app.errors import ApiException
from app.models import ContactRow, UpcomingItem, UpcomingOut, enrichment_for_api

router = APIRouter(prefix="/follow-ups")


@router.get("/upcoming", response_model=UpcomingOut)
def upcoming(days: str | None = Query(default=None), session: Session = Depends(get_session)) -> UpcomingOut:
    if days is None or days == "":
        n = 14
    elif days.isdigit() and int(days) <= 60:
        n = int(days)
    else:
        raise ApiException(400, "validation_error", "days: must be a whole number from 0 to 60")
    today = date.today()
    last = today + timedelta(days=n)
    items: list[UpcomingItem] = []
    for row in session.exec(select(ContactRow).where(ContactRow.enrichment.is_not(None))).all():
        e = enrichment_for_api(row.enrichment, row.follow_up_choices) or {}
        for i, fu in enumerate(e.get("follow_ups") or []):
            if fu.get("dismissed"):
                continue
            day = fu.get("confirmed_date") or (fu.get("suggested_date") if fu.get("date_status") == "exact" else None)
            if not day or not (today.isoformat() <= day <= last.isoformat()):
                continue
            items.append(UpcomingItem(contact_id=row.id, contact_name=row.name, index=i, action=fu["action"], date=day))
    items.sort(key=lambda x: (x.date, x.contact_name.casefold(), x.index))
    return UpcomingOut(items=items)
