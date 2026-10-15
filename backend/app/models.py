"""Database table + API schemas mirroring docs/API_CONTRACT.md and docs/ENRICHMENT.md."""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field as PField, field_validator, model_validator
from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

EnrichmentStatus = Literal["none", "pending", "done", "failed"]
Confidence = Literal["stated", "maybe", "inferred"]
DateStatus = Literal["exact", "needs_date", "none", "past"]
Source = Literal["typed", "voice"]
VOICE_PLACEHOLDER_NAME = "New contact"

NAME_MAX = 120
NOTES_MAX = 10_000
TAG_MAX = 40
TAGS_MAX = 20


def utcnow_iso() -> str:
    """ISO-8601 UTC timestamp, fixed width so it sorts lexicographically."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


# --------------------------------------------------------------------------- DB


class ContactRow(SQLModel, table=True):
    __tablename__ = "contacts"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    name: str
    raw_notes: str = ""
    tags: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    enrichment: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))
    enrichment_status: str = "none"
    enrichment_error: Optional[str] = None
    enriched_at: Optional[str] = None
    model_name: Optional[str] = None
    needs_name: bool = Field(default=False)
    source: str = Field(default="typed")
    # User's follow-up choices, stored apart from the model output and keyed by the
    # normalised action text: {"follow up": {"confirmed_date": "2026-11-02", "dismissed": false}}
    follow_up_choices: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False, default=dict))
    # Internal: identifies the latest enrichment job so stale jobs can't overwrite newer ones.
    enrichment_job: Optional[str] = None
    created_at: str = Field(default_factory=utcnow_iso)
    updated_at: str = Field(default_factory=utcnow_iso, index=True)


# --------------------------------------------------------------- Enrichment


class _Lenient(BaseModel):
    model_config = ConfigDict(extra="ignore")


def _coerce_conf(v: Any) -> str:
    v = v.strip().lower() if isinstance(v, str) else ""
    return v if v in ("stated", "maybe") else "inferred"


def _clean_str(v: Any) -> Optional[str]:
    if v is None:
        return None
    if not isinstance(v, str):
        v = str(v)
    v = v.strip()
    if not v or v.lower() in {"null", "none", "n/a", "unknown"}:
        return None
    return v


def _valid_iso_date(v: Any) -> Optional[str]:
    v = _clean_str(v)
    if v is None or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        return None
    try:
        datetime.strptime(v, "%Y-%m-%d")
    except ValueError:
        return None
    return v


class FactField(_Lenient):
    """A single-valued fact: { value, confidence }."""

    value: Optional[str] = None
    confidence: Confidence = "inferred"

    @field_validator("value", mode="before")
    @classmethod
    def _v(cls, v: Any) -> Optional[str]:
        return _clean_str(v)

    @field_validator("confidence", mode="before")
    @classmethod
    def _c(cls, v: Any) -> str:
        return _coerce_conf(v)


class Item(_Lenient):
    value: str
    confidence: Confidence = "inferred"

    @field_validator("confidence", mode="before")
    @classmethod
    def _c(cls, v: Any) -> str:
        return _coerce_conf(v)


class FollowUp(_Lenient):
    action: str
    when_text: Optional[str] = None
    suggested_date: Optional[str] = None
    date_status: DateStatus = "none"
    confidence: Confidence = "stated"
    confirmed_date: Optional[str] = None   # overlaid from ContactRow.follow_up_choices
    dismissed: bool = False

    @field_validator("date_status", mode="before")
    @classmethod
    def _ds(cls, v: Any) -> str:
        return v if v in ("exact", "needs_date", "none", "past") else "none"

    @field_validator("confidence", mode="before")
    @classmethod
    def _fc(cls, v: Any) -> str:
        return _coerce_conf(v) if v is not None else "stated"

    @field_validator("confirmed_date", mode="before")
    @classmethod
    def _cd(cls, v: Any) -> Optional[str]:
        return _valid_iso_date(v)

    @field_validator("when_text", mode="before")
    @classmethod
    def _w(cls, v: Any) -> Optional[str]:
        return _clean_str(v)

    @field_validator("suggested_date", mode="before")
    @classmethod
    def _d(cls, v: Any) -> Optional[str]:
        return _valid_iso_date(v)


class ContactInfo(_Lenient):
    email: Optional[str] = None
    phone: Optional[str] = None
    linkedin: Optional[str] = None

    @field_validator("email", "phone", "linkedin", mode="before")
    @classmethod
    def _s(cls, v: Any) -> Optional[str]:
        return _clean_str(v)


def _items(v: Any) -> list:
    """Coerce missing/odd lists; accept bare strings as items; drop empty values."""
    if v is None:
        return []
    if not isinstance(v, list):
        v = [v]
    out = []
    for x in v:
        if isinstance(x, str):
            x = {"value": x, "confidence": "inferred"}
        if isinstance(x, dict) and _clean_str(x.get("value")):
            out.append(x)
    return out


def _strs(v: Any) -> list:
    if v is None:
        return []
    if not isinstance(v, list):
        v = [v]
    return [s.strip() for s in v if isinstance(s, str) and s.strip()]


class Enrichment(_Lenient):
    person_name: Optional[str] = None
    headline: Optional[str] = None
    summary: Optional[str] = None
    role: FactField = PField(default_factory=FactField)
    company: FactField = PField(default_factory=FactField)
    location: FactField = PField(default_factory=FactField)
    how_we_met: FactField = PField(default_factory=FactField)
    interests: list[Item] = PField(default_factory=list)
    what_they_want: list[Item] = PField(default_factory=list)
    how_i_can_help: list[Item] = PField(default_factory=list)
    personal_details: list[Item] = PField(default_factory=list)
    follow_ups: list[FollowUp] = PField(default_factory=list)
    gaps: list[str] = PField(default_factory=list)
    questions_to_ask: list[str] = PField(default_factory=list)
    suggested_opener: Optional[str] = None
    suggested_tags: list[str] = PField(default_factory=list)
    contact_info: ContactInfo = PField(default_factory=ContactInfo)

    @field_validator("person_name", "headline", "summary", "suggested_opener", mode="before")
    @classmethod
    def _s(cls, v: Any) -> Optional[str]:
        return _clean_str(v)

    @field_validator("role", "company", "location", "how_we_met", "contact_info", mode="before")
    @classmethod
    def _obj(cls, v: Any) -> Any:
        if v is None:
            return {}
        if isinstance(v, str):  # model gave a bare string instead of an object
            return {"value": v, "confidence": "inferred"}
        return v

    @field_validator("interests", "what_they_want", "how_i_can_help", "personal_details", mode="before")
    @classmethod
    def _l(cls, v: Any) -> list:
        return _items(v)

    @field_validator("follow_ups", mode="before")
    @classmethod
    def _f(cls, v: Any) -> list:
        if v is None:
            return []
        if not isinstance(v, list):
            v = [v]
        return [x for x in v if isinstance(x, dict) and _clean_str(x.get("action"))]

    @field_validator("gaps", "questions_to_ask", "suggested_tags", mode="before")
    @classmethod
    def _ls(cls, v: Any) -> list:
        return _strs(v)


# ------------------------------------------------------------------ API I/O


def _clean_tags(v: Any) -> list[str]:
    if v is None:
        return []
    if not isinstance(v, list):
        raise ValueError("must be a list of strings")
    out: list[str] = []
    for t in v:
        if not isinstance(t, str):
            raise ValueError("must be a list of strings")
        t = t.strip()
        if not t:
            continue
        if len(t) > TAG_MAX:
            raise ValueError(f"each tag must be at most {TAG_MAX} characters")
        if t.lower() not in {x.lower() for x in out}:
            out.append(t)
    if len(out) > TAGS_MAX:
        raise ValueError(f"at most {TAGS_MAX} tags allowed")
    return out


def _check_name(v: Any) -> str:
    if not isinstance(v, str):
        raise ValueError("must be a string")
    v = v.strip()
    if not v:
        raise ValueError("is required")
    if len(v) > NAME_MAX:
        raise ValueError(f"must be at most {NAME_MAX} characters")
    return v


def _check_notes(v: Any) -> str:
    if v is None:
        return ""
    if not isinstance(v, str):
        raise ValueError("must be a string")
    if len(v) > NOTES_MAX:
        raise ValueError(f"must be at most {NOTES_MAX:,} characters")
    return v


class ContactCreate(BaseModel):
    name: Optional[str] = None
    raw_notes: str = ""
    tags: list[str] = PField(default_factory=list)
    enrich: bool = True
    source: Source = "typed"

    @field_validator("name", mode="before")
    @classmethod
    def _n(cls, v: Any) -> Optional[str]:
        # Requiredness depends on `source`, so it's checked in _rules below.
        if v is None:
            return None
        if not isinstance(v, str):
            raise ValueError("must be a string")
        v = v.strip()
        if len(v) > NAME_MAX:
            raise ValueError(f"must be at most {NAME_MAX} characters")
        return v

    @model_validator(mode="after")
    def _rules(self) -> "ContactCreate":
        if self.source == "voice":
            if not self.raw_notes.strip():
                raise ValueError("raw_notes: nothing was heard")
        elif not self.name:
            raise ValueError("name: is required")
        return self

    @property
    def needs_name(self) -> bool:
        return self.source == "voice" and not self.name

    @field_validator("raw_notes", mode="before")
    @classmethod
    def _r(cls, v: Any) -> str:
        return _check_notes(v)

    @field_validator("tags", mode="before")
    @classmethod
    def _t(cls, v: Any) -> list[str]:
        return _clean_tags(v)


class ContactPatch(BaseModel):
    name: Optional[str] = None
    raw_notes: Optional[str] = None
    tags: Optional[list[str]] = None

    # Field validators only run for keys present in the body, so omitted keys stay unchanged.
    @field_validator("name", mode="before")
    @classmethod
    def _n(cls, v: Any) -> str:
        return _check_name(v)

    @field_validator("raw_notes", mode="before")
    @classmethod
    def _r(cls, v: Any) -> str:
        if v is None:
            raise ValueError("must be a string")
        return _check_notes(v)

    @field_validator("tags", mode="before")
    @classmethod
    def _t(cls, v: Any) -> list[str]:
        return _clean_tags(v)


class NoteAppend(BaseModel):
    text: str
    enrich: bool = True

    @field_validator("text", mode="before")
    @classmethod
    def _t(cls, v: Any) -> str:
        if not isinstance(v, str):
            raise ValueError("must be a string")
        v = v.strip()
        if not v:
            raise ValueError("is required")
        if len(v) > NOTES_MAX:
            raise ValueError(f"must be at most {NOTES_MAX:,} characters")
        return v


def normalise_action(action: str) -> str:
    """Key used to store the user's follow-up date choice apart from the model output."""
    return re.sub(r"[\W_]+", " ", action or "").strip().casefold()


def enrichment_for_api(enrichment: Optional[dict], choices: Optional[dict]) -> Optional[dict]:
    """Stored enrichment -> API shape. Fills v2 defaults for old (v1) rows and overlays the
    user's follow-up choices (confirmed_date / dismissed) by normalised action."""
    if not enrichment:
        return enrichment
    try:
        e = Enrichment.model_validate(enrichment)
    except Exception:  # noqa: BLE001  (never fail a read on an odd stored row)
        return enrichment
    raw_fus = enrichment.get("follow_ups") or []
    for i, fu in enumerate(e.follow_ups):
        raw = raw_fus[i] if i < len(raw_fus) and isinstance(raw_fus[i], dict) else {}
        if "date_status" not in raw:  # v1 row: derive from what was stored
            fu.date_status = "exact" if fu.suggested_date else ("needs_date" if fu.when_text else "none")
        choice = (choices or {}).get(normalise_action(fu.action)) or {}
        fu.confirmed_date = _valid_iso_date(choice.get("confirmed_date"))
        fu.dismissed = bool(choice.get("dismissed", False))
    return e.model_dump()


class Contact(BaseModel):
    id: str
    name: str
    needs_name: bool = False
    source: Source = "typed"
    raw_notes: str
    tags: list[str]
    enrichment: Optional[dict] = None
    enrichment_status: EnrichmentStatus
    enrichment_error: Optional[str] = None
    enriched_at: Optional[str] = None
    model_name: Optional[str] = None
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, r: ContactRow) -> "Contact":
        return cls(
            id=r.id, name=r.name, needs_name=bool(r.needs_name),
            source=r.source if r.source in ("typed", "voice") else "typed", raw_notes=r.raw_notes, tags=list(r.tags or []),
            enrichment=enrichment_for_api(r.enrichment, r.follow_up_choices),
            enrichment_status=r.enrichment_status,  # type: ignore[arg-type]
            enrichment_error=r.enrichment_error, enriched_at=r.enriched_at,
            model_name=r.model_name, created_at=r.created_at, updated_at=r.updated_at,
        )


class ContactSummary(BaseModel):
    id: str
    name: str
    headline: Optional[str] = None
    company: Optional[str] = None
    tags: list[str]
    enrichment_status: EnrichmentStatus
    updated_at: str

    @classmethod
    def from_row(cls, r: ContactRow) -> "ContactSummary":
        e = r.enrichment or {}
        return cls(
            id=r.id, name=r.name, headline=e.get("headline"),
            company=(e.get("company") or {}).get("value"),
            tags=list(r.tags or []), enrichment_status=r.enrichment_status,  # type: ignore[arg-type]
            updated_at=r.updated_at,
        )


class ContactList(BaseModel):
    contacts: list[ContactSummary]


class FollowUpPatch(BaseModel):
    confirmed_date: Optional[str] = None
    dismissed: Optional[bool] = None

    @field_validator("confirmed_date", mode="before")
    @classmethod
    def _cd(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        if not isinstance(v, str) or _valid_iso_date(v) is None:
            raise ValueError("must be a date in YYYY-MM-DD format")
        return v


class UpcomingItem(BaseModel):
    contact_id: str
    contact_name: str
    index: int
    action: str
    date: str


class UpcomingOut(BaseModel):
    items: list[UpcomingItem]


class TranscribeOut(BaseModel):
    text: str
    duration_s: float


class ModelStatus(BaseModel):
    name: str
    available: bool
    detail: Optional[str] = None


class Health(BaseModel):
    status: Literal["ok"] = "ok"
    model: ModelStatus
    asr: ModelStatus


class ExportOut(BaseModel):
    exported_at: str
    contacts: list[Contact]
