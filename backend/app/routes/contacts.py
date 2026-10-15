from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from datetime import date as _date

from fastapi import APIRouter, Depends, Query, Response

from app.ics import follow_up_event
from sqlmodel import Session, select

from app.db import get_session
from app.enrichment.service import claim_for_enrichment, enqueue, mark_pending
from app.errors import ApiException, not_found
from app.models import (
    NOTES_MAX,
    Contact,
    ContactCreate,
    ContactList,
    ContactPatch,
    ContactRow,
    ContactSummary,
    VOICE_PLACEHOLDER_NAME,
    FollowUpPatch,
    NoteAppend,
    enrichment_for_api,
    normalise_action,
    utcnow_iso,
)

router = APIRouter(prefix="/contacts")
log = logging.getLogger("rolo.contacts")


def _get(session: Session, contact_id: str) -> ContactRow:
    row = session.get(ContactRow, contact_id)
    if row is None:
        raise not_found()
    return row


def _matches(row: ContactRow, q: str) -> bool:
    e = row.enrichment or {}
    hay = [
        row.name,
        row.raw_notes,
        *(row.tags or []),
        (e.get("company") or {}).get("value") or "",
        e.get("headline") or "",
    ]
    return any(q in (h or "").casefold() for h in hay)


# Enrichment jobs go to a single in-process worker queue (see enrichment/service.py).
# Routes commit first, then enqueue, so the request's DB session is never tied to a job.


@router.get("", response_model=ContactList)
def list_contacts(q: Optional[str] = Query(default=None), session: Session = Depends(get_session)) -> ContactList:
    rows = session.exec(select(ContactRow).order_by(ContactRow.updated_at.desc())).all()
    needle = (q or "").strip().casefold()
    if needle:
        rows = [r for r in rows if _matches(r, needle)]
    return ContactList(contacts=[ContactSummary.from_row(r) for r in rows])


@router.post("", status_code=201, response_model=Contact)
def create_contact(body: ContactCreate, session: Session = Depends(get_session)) -> Contact:
    row = ContactRow(
        name=body.name or VOICE_PLACEHOLDER_NAME, raw_notes=body.raw_notes, tags=body.tags,
        source=body.source, needs_name=body.needs_name,
    )
    job = None
    if body.enrich and row.raw_notes.strip():  # blank notes: never call the model
        job = mark_pending(row)
    session.add(row)
    session.commit()
    session.refresh(row)
    log.info("Created contact %s (source=%s, notes: %d chars, enrich=%s)", row.id, row.source, len(row.raw_notes), bool(job))
    if job:
        enqueue(row.id, job)
    return Contact.from_row(row)


@router.get("/{contact_id}", response_model=Contact)
def get_contact(contact_id: str, session: Session = Depends(get_session)) -> Contact:
    return Contact.from_row(_get(session, contact_id))


@router.patch("/{contact_id}", response_model=Contact)
def patch_contact(contact_id: str, body: ContactPatch, session: Session = Depends(get_session)) -> Contact:
    row = _get(session, contact_id)
    fields = body.model_fields_set
    if "name" in fields and body.name is not None:
        row.name = body.name
        row.needs_name = False
    if "raw_notes" in fields and body.raw_notes is not None:
        row.raw_notes = body.raw_notes
    if "tags" in fields and body.tags is not None:
        row.tags = list(body.tags)
    row.updated_at = utcnow_iso()
    session.add(row)
    session.commit()
    session.refresh(row)
    return Contact.from_row(row)


@router.post("/{contact_id}/notes", response_model=Contact)
def append_note(contact_id: str, body: NoteAppend, session: Session = Depends(get_session)) -> Contact:
    row = _get(session, contact_id)
    entry = f"[{date.today().isoformat()}] {body.text}"
    new_notes = f"{row.raw_notes}\n\n{entry}" if row.raw_notes.strip() else entry
    if len(new_notes) > NOTES_MAX:
        raise ApiException(
            400, "validation_error",
            f"text: notes would exceed {NOTES_MAX:,} characters",
        )
    row.raw_notes = new_notes
    row.updated_at = utcnow_iso()
    job = None
    if body.enrich and row.raw_notes.strip():
        # A newer job supersedes any queued/in-flight one; the stale result is discarded.
        job = mark_pending(row)
    session.add(row)
    session.commit()
    session.refresh(row)
    if job:
        enqueue(row.id, job)
    return Contact.from_row(row)


@router.post("/{contact_id}/enrich", status_code=202, response_model=Contact)
def enrich_contact(contact_id: str, session: Session = Depends(get_session)) -> Contact:
    row = _get(session, contact_id)
    if row.enrichment_status == "pending":
        raise ApiException(409, "enrichment_in_progress", "This contact is already being enriched.")
    if not row.raw_notes.strip():
        raise ApiException(400, "validation_error", "raw_notes: add some notes before enriching")
    session.rollback()  # end the read transaction before the atomic claim
    job = claim_for_enrichment(contact_id)  # conditional UPDATE: only one concurrent caller wins
    if job is None:
        session.expire_all()
        if session.get(ContactRow, contact_id) is None:
            raise not_found()
        raise ApiException(409, "enrichment_in_progress", "This contact is already being enriched.")
    enqueue(contact_id, job)
    session.expire_all()
    return Contact.from_row(_get(session, contact_id))


@router.delete("/{contact_id}", status_code=204)
def delete_contact(contact_id: str, session: Session = Depends(get_session)) -> Response:
    row = _get(session, contact_id)
    session.delete(row)
    session.commit()
    return Response(status_code=204)


# ------------------------------------------------------------------ follow-ups (v2)


def _follow_up(row: ContactRow, index: int) -> dict:
    e = enrichment_for_api(row.enrichment, row.follow_up_choices) or {}
    fus = e.get("follow_ups") or []
    if index < 0 or index >= len(fus):
        raise ApiException(404, "not_found", "Follow-up not found.")
    return fus[index]


@router.patch("/{contact_id}/follow-ups/{index:int}", response_model=Contact)
def patch_follow_up(
    contact_id: str, index: int, body: FollowUpPatch, session: Session = Depends(get_session)
) -> Contact:
    row = _get(session, contact_id)
    if row.enrichment_status == "pending":
        raise ApiException(409, "enrichment_in_progress", "This contact is being organised. Try again in a moment.")
    fu = _follow_up(row, index)
    key = normalise_action(fu["action"])
    choices = dict(row.follow_up_choices or {})
    choice = dict(choices.get(key) or {"confirmed_date": None, "dismissed": False})
    fields = body.model_fields_set
    if "confirmed_date" in fields:
        choice["confirmed_date"] = body.confirmed_date
        if body.confirmed_date and "dismissed" not in fields:
            choice["dismissed"] = False
    if "dismissed" in fields and body.dismissed is not None:
        choice["dismissed"] = body.dismissed
        if body.dismissed and "confirmed_date" not in fields:
            choice["confirmed_date"] = None
    choices[key] = choice
    row.follow_up_choices = choices  # reassign so SQLAlchemy sees the JSON change
    row.updated_at = utcnow_iso()
    session.add(row)
    session.commit()
    session.refresh(row)
    return Contact.from_row(row)


@router.get("/{contact_id}/follow-ups/{index:int}.ics")
def follow_up_ics(contact_id: str, index: int, session: Session = Depends(get_session)) -> Response:
    row = _get(session, contact_id)
    fu = _follow_up(row, index)
    day = fu.get("confirmed_date") or fu.get("suggested_date")
    if not day or fu.get("dismissed"):
        raise ApiException(400, "validation_error", "date: pick a date first")
    headline = (row.enrichment or {}).get("headline")
    desc = "\n".join(x for x in (
        f"When: {fu['when_text']}" if fu.get("when_text") else None,
        headline,
        "From Rolo",
    ) if x)
    body = follow_up_event(
        _date.fromisoformat(day), f"Follow up: {row.name} — {fu['action']}", desc,
        uid=f"{row.id}-{index}",
    )
    return Response(
        content=body,
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="rolo-followup.ics"'},
    )
