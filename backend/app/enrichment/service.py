"""Runs enrichment: call the model, validate, apply deterministic guards, persist."""
from __future__ import annotations

import json
import logging
import queue
import re
import threading
import time
import uuid
from datetime import date

from pydantic import ValidationError
from sqlalchemy import update
from sqlmodel import Session, select

from app import config
from app.db import get_engine
from app.enrichment import prompt
from app.enrichment.followups import classify, drop_non_action_dated, scan_follow_ups
from app.enrichment.model_client import (
    ModelBadResponse,
    ModelClient,
    ModelNotInstalled,
    ModelTimeout,
    ModelUnavailable,
    get_model_client,
)
from app.models import ContactRow, Enrichment, utcnow_iso

log = logging.getLogger("rolo.enrichment")

INTERRUPTED_MSG = "Enrichment was interrupted. Tap Retry."

LIMITS = {"interests": 8, "follow_ups": 5, "questions_to_ask": 3, "suggested_tags": 5}
HEADLINE_MAX = prompt.HEADLINE_MAX
CONTACT_GAP = "Email or other contact details"
_CONTACT_GAP_RE = re.compile(r"e-?mail|contact", re.IGNORECASE)

_STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "at", "in", "on", "for", "to", "with", "by",
    "from", "as", "is", "are", "was", "be", "it", "its", "their", "his", "her", "they",
    "co", "inc", "ltd", "llc", "corp", "company", "possibly", "maybe", "probably",
    "likely", "some", "kind", "sort", "unknown", "not", "sure",
}


class EnrichmentFailure(Exception):
    """Carries a user-safe message."""

    def __init__(self, user_message: str):
        super().__init__(user_message)
        self.user_message = user_message


# ------------------------------------------------------------------ guards


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"\w+", text.lower()) if (len(w) >= 3 or w.isdigit()) and w not in _STOPWORDS}


def _shares_meaningful_word(value: str, notes: str) -> bool:
    vw = _words(value)
    if not vw:
        return False
    nw = _words(notes)
    if vw & nw:
        return True
    # Light stemming: "partnerships" ~ "partnership", "payments" ~ "payment".
    def stem(w: str) -> str:
        for suf in ("ing", "es", "s"):
            if len(w) > len(suf) + 2 and w.endswith(suf):
                return w[: -len(suf)]
        return w
    return bool({stem(w) for w in vw} & {stem(w) for w in nw})


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s.]+$")
_PHONE_RE = re.compile(r"^\+?[\d()\-\s.]+$")
_PHONE_EXT = re.compile(r"\s*(?:ext\.?|extension|x)\s*\d{1,6}$", re.I)
_DATE_LIKE = re.compile(r"^(?:\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{4})$")
_LINKEDIN_RE = re.compile(r"^(?:\S*linkedin\.com/\S+|in/\S+)$", re.I)
_HANDLE_RE = re.compile(r"^@?[A-Za-z0-9][A-Za-z0-9._-]{2,99}$")


def _phone_ok(v: str, notes: str) -> bool:
    core = _PHONE_EXT.sub("", v).strip()
    digits = sum(ch.isdigit() for ch in core)
    return bool(_PHONE_RE.match(core)) and 7 <= digits <= 15 and not _DATE_LIKE.match(core)


def _linkedin_ok(v: str, notes: str) -> bool:
    if _LINKEDIN_RE.match(v):
        return True
    # A bare handle only counts when the notes label it as LinkedIn ("LinkedIn: priyashah").
    if _HANDLE_RE.match(v):
        label = rf"linked\s*in\b[^.\n]{{0,20}}?[:\-–]?\s*(?:is\s+)?@?{re.escape(v.lstrip('@'))}(?![\w-]|\.\w)"
        return bool(re.search(label, notes, re.I))
    return False


_CONTACT_SHAPE = {
    "email": lambda v, notes: bool(_EMAIL_RE.match(v)),
    "phone": _phone_ok,
    "linkedin": _linkedin_ok,
}


def _in_notes(value: str | None, notes: str) -> bool:
    return bool(value) and value.strip().lower() in notes.lower()


# Residence/work cues tied to a place. Count anywhere in the notes, in either order.
_DEV = "\u0900-\u0963\u0966-\u097F"  # Devanagari letters/signs/digits, NOT the danda \u0964 / \u0965
_W = rf"[\w{_DEV}]"  # word chars incl. Devanagari (letters + vowel signs)
_NB = rf"(?<!{_W})"                  # word boundary that works for Devanagari too
_NA = rf"(?!{_W})"
_CUE_BEFORE = (  # "<cue> ... X" within one sentence
    r"(?:lives?|living|lived|based|works?\s+(?:in|at|out\s+of)|working\s+(?:in|at|out\s+of)|from"
    r"|moved\s+to|(?:her|his|their)\s+(?:flat|apartment|home|house|place|office|studio)\s+in"
    r"|runs\s+the)"
)
_CUE_AFTER = (  # "X ... <cue>" within one sentence
    r"(?:-?\s*based|,?\s+where\s+(?:she|he|they)\s+(?:lives?|works?|is\s+based|are\s+based)"
    r"|\s+(?:mein|me)\s+(?:rehti|rehta|rehte|kaam)"
    r"|\s+में\s+(?:रहती|रहता|रहते|काम\s+कर)"      # X में रहती/रहता है, X में रहते हैं, X में काम करती
    r"|\s+की\s+रहने\s+वाल[ीा]|\s+का\s+रहने\s+वाला"  # X की रहने वाली / X का रहने वाला
    r"|\s+से\s+हैं?)"                               # X से है/हैं
)
_SENT = r"[^.!?\n।;]"
# Hindi residence places: the Devanagari word right before a residence cue.
_HINDI_RESIDENCE_PLACE = re.compile(
    rf"([{_DEV}]+)\s+(?:में\s+(?:रहती|रहता|रहते|काम\s+कर)|की\s+रहने\s+वाल[ीा]|का\s+रहने\s+वाला|से\s+हैं?)"
)
# Sentences in the notes that describe the meeting itself count as how_we_met context.
_MEETING_CUE = re.compile(
    r"\b(?:met|meet|meeting|chatted|ran into|bumped into|introduced|sat next to)\b|मिले|मुलाकात", re.I
)

# Rough Devanagari -> Latin consonant skeleton, so "Delhi" can be matched to "दिल्ली"
# and "Mumbai" to "मुंबई" without a transliteration library.
_DEV_CONS = {
    "क": "k", "ख": "k", "ग": "g", "घ": "g", "ङ": "n", "च": "c", "छ": "c", "ज": "j", "झ": "j",
    "ञ": "n", "ट": "t", "ठ": "t", "ड": "d", "ढ": "d", "ण": "n", "त": "t", "थ": "t", "द": "d",
    "ध": "d", "न": "n", "प": "p", "फ": "f", "ब": "b", "भ": "b", "म": "m", "य": "", "र": "r",
    "ल": "l", "व": "v", "श": "s", "ष": "s", "स": "s", "ह": "", "ळ": "l", "क़": "k", "ज़": "j",
    "फ़": "f", "ड़": "r", "ढ़": "r", "ं": "n", "ँ": "n",
}


def _squash(s: str) -> str:
    return re.sub(r"(.)\1+", r"\1", s)


def _latin_skeleton(word: str) -> str:
    w = word.lower().replace("ph", "f").replace("w", "v").replace("q", "k")
    return _squash(re.sub(r"[aeiouhy\W\d_]", "", w))


def _dev_skeletons(word: str) -> set[str]:
    out = "".join(_DEV_CONS.get(ch, "") for ch in word)
    no_nasal = "".join(_DEV_CONS.get(ch, "") for ch in word if ch not in "ंँ")
    return {_squash(out), _squash(no_nasal)}


def _same_place(latin: str, devanagari: str) -> bool:
    sk = _latin_skeleton(latin)
    return len(sk) >= 2 and sk in _dev_skeletons(devanagari)


def _tokens(text: str) -> list[str]:
    return re.findall(rf"{_W}+", text.lower())


def _lives_there(word: str, notes: str) -> bool:
    w = re.escape(word)
    before = rf"\b{_CUE_BEFORE}\b{_SENT}{{0,40}}?{_NB}{w}{_NA}"
    after = rf"{_NB}{w}{_NA}{_CUE_AFTER}{_NA}"
    if re.search(before, notes, re.I) or re.search(after, notes, re.I):
        return True
    # Latin location vs a Devanagari place in a Hindi residence cue.
    # Script-to-script (Devanagari value) or rough Latin <-> Devanagari.
    return any(m.group(1) == word or _same_place(word, m.group(1)) for m in _HINDI_RESIDENCE_PLACE.finditer(notes))


def _in_text(word: str, text: str) -> bool:
    if re.search(rf"{_NB}{re.escape(word)}{_NA}", text, re.I):
        return True
    return any(_same_place(word, t) for t in re.findall(rf"[{_DEV}]+", text))


def _location_is_meeting_place(location: str, how_we_met: str | None, notes: str) -> bool:
    """True if the location only describes where we met, not where the person lives/works."""
    loc_words = [w for w in _tokens(location) if len(w) >= 3 and w not in _STOPWORDS]
    if not loc_words:
        return False
    sentences = re.split(r"(?<=[.!?।])\s+|\n+", notes)
    meeting_ctx = " ".join([how_we_met or ""] + [s for s in sentences if _MEETING_CUE.search(s)])
    if not any(_in_text(w, meeting_ctx) for w in loc_words):
        return False
    return not any(_lives_there(w, notes) for w in loc_words)


_NOT_A_TITLE = re.compile(r"^\s*(?:works?|working|employed)\b", re.I)
_AS_TITLE = re.compile(r"\bas\s+(?:an?\s+|the\s+)?(.+?)\s*\.?$", re.I)
JOB_TITLE_GAP = "Job title"


def _norm(s: str) -> str:
    return re.sub(r"[\W_]+", " ", s).strip().casefold()


def _clean_role(role: str, company: str | None) -> str | None:
    """Return a usable job title, or None if role.value isn't one.
    - "Works at Google as a product manager" -> "Product manager"
    - "Works at a startup" / "Employed by Deloitte" -> None
    - role equal to the whole company name -> None
    - "Partner" at "Partner Capital Group" -> kept
    """
    if _NOT_A_TITLE.search(role):
        m = _AS_TITLE.search(role)
        if not m:
            return None
        title = m.group(1).strip()
        return title[:1].upper() + title[1:] if title else None
    if company and _norm(role) == _norm(company):
        return None
    return role


_HEDGE_CUE = re.compile(r"\b(?:i\s+think|maybe|might|possibly|perhaps|probably|not\s+sure|likely)\b", re.I)
_GENERIC = _STOPWORDS | {
    "about", "with", "their", "them", "your", "you", "this", "that", "work", "working", "works",
    "help", "helping", "provide", "offer", "great", "good", "would", "love", "like", "more",
}


# Maybe upgrade: a hedge only covers the clause it sits in. Conservative: when unsure, keep maybe.
_HEDGED_CLAUSE_CUE = re.compile(
    r"\b(?:i\s+think|maybe|possibly|probably|not\s+sure|might|perhaps|guess|likely)\b|शायद|\bshayad\b", re.I
)
# Hedge words inside the value itself ("possibly Stripe-adjacent", "Boston or NYC") -> never upgrade.
_VALUE_HEDGE = re.compile(
    r"\b(?:i\s+think|maybe|possibly|probably|likely|perhaps|might|not\s+sure|or|guess)\b|\?|शायद|या", re.I
)
_TRAILING_HEDGE = re.compile(rf"(?:{_HEDGED_CLAUSE_CUE.pattern})\W*$", re.I)


def _stem(w: str) -> str:
    for suf in ("ing", "es", "s"):
        if len(w) > len(suf) + 2 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def _hedged_clause_words(notes: str) -> set[str]:
    # Line breaks inside a sentence are just wrapping: join them before splitting into clauses.
    flat = re.sub(r"\s*\n\s*", " ", notes)
    clauses = [c for c in re.split(r"[.,;:!?।]", flat)]
    hedged: set[str] = set()
    carry = False  # a hedge that ends a clause/sentence applies to the next clause
    for c in clauses:
        if not c.strip():
            continue
        if carry or _HEDGED_CLAUSE_CUE.search(c):
            hedged |= {_stem(w) for w in _tokens(c)}
        carry = bool(_TRAILING_HEDGE.search(c))
    return hedged


def _upgrade_maybe(f, hedged: set[str], note_words: set[str]) -> None:
    """maybe -> stated only when the value has no hedge word, every meaningful word of it is
    in the notes, and none of them sits in a hedged clause. Never the reverse."""
    if f.confidence != "maybe" or not f.value or _VALUE_HEDGE.search(f.value):
        return
    words = {_stem(w) for w in _tokens(f.value) if len(w) >= 3 and w not in _STOPWORDS}
    if words and words <= note_words and not (words & hedged):
        f.confidence = "stated"


def _person_name_in_notes(person_name: str | None, notes: str) -> str | None:
    if not person_name:
        return None
    name = re.sub(r"\s+", " ", person_name).strip(" .,'\"")
    if len(name) < 2 or len(name) > 120:
        return None
    return name if name.casefold() in re.sub(r"\s+", " ", notes).casefold() else None


def _risky_terms(e: Enrichment, notes: str) -> tuple[list[str], set[str]]:
    """Value texts marked maybe/inferred, plus their distinctive words, for the opener guard."""
    stated_text, risky_values = [], []
    singles = [e.role, e.company, e.location, e.how_we_met]
    lists = e.interests + e.what_they_want + e.how_i_can_help + e.personal_details
    for f in singles + lists:
        if not f.value:
            continue
        (stated_text if f.confidence == "stated" else risky_values).append(f.value)
    stated_words = set(_tokens(" ".join(stated_text)))
    # Words the user hedged in the notes ("I think Stripe-adjacent" -> stripe, adjacent).
    hedged = set()
    for m in _HEDGE_CUE.finditer(notes):
        clause = re.split(r"[.!?;,\n]", notes[m.end():], maxsplit=1)[0]
        hedged |= set(_tokens(clause)[:6])
    words: set[str] = set()
    for v in risky_values:
        toks = re.findall(rf"{_W}+", v)
        for i, t in enumerate(toks):
            tl = t.lower()
            if len(tl) < 3 or tl in _GENERIC or tl in stated_words:
                continue
            proper = t[:1].isupper() and (i > 0 or len(toks) == 1)
            if tl in hedged or proper:
                words.add(tl)
    phrases = [v.casefold() for v in risky_values if len(v) >= 4]
    return phrases, words


def _opener_states_unconfirmed(e: Enrichment, notes: str) -> bool:
    opener = (e.suggested_opener or "").casefold()
    if not opener:
        return False
    phrases, words = _risky_terms(e, notes)
    if any(p in opener for p in phrases):
        return True
    return any(re.search(rf"{_NB}{re.escape(w)}{_NA}", opener) for w in words)


def neutral_opener(e: Enrichment) -> str:
    where = e.how_we_met.value if e.how_we_met.value and e.how_we_met.confidence == "stated" else None
    if where:
        where = re.sub(r"^(?:at|in|during|on)\s+", "", where.strip().rstrip("."), flags=re.I)
        return f"Great meeting you at {where}. Would love to continue our conversation."
    return "Great meeting you. Would love to continue our conversation."


def apply_guards(e: Enrichment, notes: str, today: date | None = None) -> Enrichment:
    """Deterministic post-processing from ENRICHMENT.md. Returns a new object."""
    e = e.model_copy(deep=True)
    today = today or date.today()

    # contact_info must be literally present in the notes.
    ci = e.contact_info
    for key in ("email", "phone", "linkedin"):
        v = getattr(ci, key)
        if not _in_notes(v, notes) or not _CONTACT_SHAPE[key](v.strip(), notes):
            setattr(ci, key, None)

    # Maybe upgrade (before the checks below, which may still downgrade to inferred).
    hedged, note_words = _hedged_clause_words(notes), {_stem(w) for w in _tokens(notes)}
    for f in [e.role, e.company, e.location, e.how_we_met, *e.interests, *e.what_they_want,
              *e.how_i_can_help, *e.personal_details]:
        _upgrade_maybe(f, hedged, note_words)

    # role must be a job title.
    cleaned = _clean_role(e.role.value, e.company.value) if e.role.value else None
    if e.role.value and cleaned is not None:
        e.role.value = cleaned
    elif e.role.value:
        e.role.value = None
        e.role.confidence = "inferred"
        if not any("job title" in g.lower() for g in e.gaps):
            e.gaps.append(JOB_TITLE_GAP)

    # role / company with no word in common with the notes -> inferred.
    for key in ("role", "company"):
        f = getattr(e, key)
        if f.value and not _shares_meaningful_word(f.value, notes):
            f.confidence = "inferred"

    # No contact info at all -> make sure the card says so.
    if not (ci.email or ci.phone or ci.linkedin) and not any(_CONTACT_GAP_RE.search(g) for g in e.gaps):
        e.gaps.append(CONTACT_GAP)

    # person_name only if the notes actually say it.
    e.person_name = _person_name_in_notes(e.person_name, notes)

    # Follow-ups: add stated ones the model dropped, then classify every one (never the model).
    e.follow_ups = e.follow_ups[: LIMITS["follow_ups"]]
    e.follow_ups = drop_non_action_dated(e.follow_ups, notes, today)
    scan_follow_ups(e, notes, today)
    for fu in e.follow_ups:
        classify(fu, today, notes)
        fu.confirmed_date, fu.dismissed = None, False  # user choices live on the row

    # location that is really just where you met -> null.
    if e.location.value and _location_is_meeting_place(e.location.value, e.how_we_met.value, notes):
        e.location.value = None

    # Tags: lowercase, de-duplicated.
    seen: list[str] = []
    for t in e.suggested_tags:
        t = re.sub(r"\s+", " ", t.strip().lower())
        if t and t not in seen:
            seen.append(t)
    e.suggested_tags = seen

    # Trim lists.
    e.interests = e.interests[: LIMITS["interests"]]
    e.follow_ups = e.follow_ups[: LIMITS["follow_ups"]]
    e.questions_to_ask = e.questions_to_ask[: LIMITS["questions_to_ask"]]
    e.suggested_tags = e.suggested_tags[: LIMITS["suggested_tags"]]

    # Opener must only use stated facts.
    if _opener_states_unconfirmed(e, notes):
        e.suggested_opener = neutral_opener(e)

    if e.headline and len(e.headline) > HEADLINE_MAX:
        e.headline = e.headline[: HEADLINE_MAX - 1].rstrip() + "…"
    return e


# ------------------------------------------------------------ model call


def _parse(raw: str) -> Enrichment:
    text = re.sub(r"<think>.*?</think>", "", raw, flags=re.S).strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text).strip()
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("top-level JSON is not an object")
    return Enrichment.model_validate(data)


def enrich_notes(client: ModelClient, name: str | None, notes: str, today: date) -> Enrichment:
    """Call the model (with one JSON retry), validate, guard. Raises EnrichmentFailure.
    `name` None means a voice contact without a name yet."""
    messages = prompt.build_messages(name, notes, today)
    try:
        for attempt in (1, 2):
            raw = client.chat_json(messages, prompt.FORMAT_SCHEMA)
            try:
                parsed = _parse(raw)
            except (ValueError, ValidationError) as exc:
                log.warning("Model reply not valid JSON/schema (attempt %d): %s", attempt, type(exc).__name__)
                if attempt == 2:
                    raise EnrichmentFailure(
                        "The model's reply couldn't be read, even after a retry. Tap Retry."
                    ) from exc
                messages = messages + [
                    {"role": "assistant", "content": raw},
                    {"role": "user", "content": prompt.RETRY_PROMPT},
                ]
                continue
            return apply_guards(parsed, notes, today)
    except ModelUnavailable as exc:
        raise EnrichmentFailure("The local model isn't running. Start Ollama and tap Retry.") from exc
    except ModelNotInstalled as exc:
        raise EnrichmentFailure(
            f"The model {client.name} isn't installed. Run: ollama pull {client.name}"
        ) from exc
    except ModelTimeout as exc:
        raise EnrichmentFailure(
            f"The model took too long to respond (over {int(config.MODEL_TIMEOUT_S)} seconds). Tap Retry."
        ) from exc
    except ModelBadResponse as exc:
        log.warning("Model returned a bad response: %s", exc)
        raise EnrichmentFailure("The local model returned an error. Tap Retry.") from exc
    raise EnrichmentFailure("The model's reply couldn't be read. Tap Retry.")  # pragma: no cover


# --------------------------------------------------------------- lifecycle

CRASH_MSG = "Something went wrong while organising your notes. Tap Retry."


def mark_pending(row: ContactRow) -> str:
    """Flag a row as pending and return the new job id (caller commits, then calls enqueue)."""
    job = str(uuid.uuid4())
    row.enrichment_status = "pending"
    row.enrichment_error = None
    row.enrichment_job = job
    row.updated_at = utcnow_iso()
    return job


def claim_for_enrichment(contact_id: str) -> str | None:
    """Atomically flip a non-pending contact to pending. Returns the job id, or None if
    it was already pending (or vanished). Single conditional UPDATE, so concurrent
    callers can't both win."""
    job = str(uuid.uuid4())
    with Session(get_engine()) as s:
        result = s.execute(
            update(ContactRow)
            .where(ContactRow.id == contact_id, ContactRow.enrichment_status != "pending")
            .values(enrichment_status="pending", enrichment_error=None,
                    enrichment_job=job, updated_at=utcnow_iso())
        )
        s.commit()
        return job if result.rowcount == 1 else None


def _finish(contact_id: str, job_id: str, person_name: str | None = None, **values) -> bool:
    """Write the job outcome only if this job is still the current one.
    `person_name` fills the name of a voice contact that still needs one."""
    with Session(get_engine()) as s:
        row = s.get(ContactRow, contact_id)
        if row is None or row.enrichment_job != job_id:
            return False
        for k, v in values.items():
            setattr(row, k, v)
        if person_name and row.needs_name:
            row.name = person_name[:120]
            row.needs_name = False
        row.enrichment_job = None
        row.updated_at = utcnow_iso()
        s.add(row)
        s.commit()
        return True


def run_enrichment(contact_id: str, job_id: str) -> None:
    """Run one job. Never raises; never leaves the row pending; never holds a DB
    session while the model is working."""
    try:
        # 1. Short read session.
        with Session(get_engine()) as s:
            row = s.get(ContactRow, contact_id)
            if row is None or row.enrichment_job != job_id:
                return  # deleted or superseded while queued
            name = None if row.needs_name else row.name
            notes = row.raw_notes

        if not notes.strip():  # blank notes: never call the model
            _finish(contact_id, job_id, enrichment_status="none", enrichment_error=None)
            return

        # 2. Model call with no session open.
        client = get_model_client()
        started = time.monotonic()
        try:
            result = enrich_notes(client, name, notes, date.today()).model_dump(
                exclude={"follow_ups": {"__all__": {"confirmed_date", "dismissed"}}}
            )
        except EnrichmentFailure as exc:
            elapsed = time.monotonic() - started
            if _finish(contact_id, job_id, enrichment_status="failed", enrichment_error=exc.user_message):
                log.info("Enrichment failed for contact %s after %.1fs: %s", contact_id, elapsed, exc.user_message)
            return
        elapsed = time.monotonic() - started

        # 3. Short write session.
        values = dict(
            enrichment=result, enrichment_status="done", enrichment_error=None,
            enriched_at=utcnow_iso(), model_name=client.name,
        )
        with Session(get_engine()) as s:
            row = s.get(ContactRow, contact_id)
            if row is not None and not row.tags and result.get("suggested_tags"):
                values["tags"] = list(result["suggested_tags"])
        if _finish(contact_id, job_id, person_name=result.get("person_name"), **values):
            log.info("Enriched contact %s with %s in %.1fs", contact_id, client.name, elapsed)
        else:
            log.info("Discarding stale enrichment for contact %s", contact_id)
    except Exception:  # noqa: BLE001
        log.exception("Enrichment task crashed for contact %s", contact_id)
        try:
            _finish(contact_id, job_id, enrichment_status="failed", enrichment_error=CRASH_MSG)
        except Exception:  # noqa: BLE001
            log.exception("Could not mark contact %s as failed", contact_id)


# ------------------------------------------------------------ job queue
# One in-process worker: Ollama serves one request at a time anyway, and a single
# consumer means at most one DB connection is ever used by enrichment.

_queue: "queue.Queue[tuple[str, str] | None]" = queue.Queue()
_worker: threading.Thread | None = None
_worker_lock = threading.Lock()


def _worker_loop() -> None:
    while True:
        item = _queue.get()
        try:
            if item is None:
                return
            run_enrichment(*item)
        except Exception:  # noqa: BLE001  (run_enrichment never raises, belt and braces)
            log.exception("Enrichment worker error")
        finally:
            _queue.task_done()


def start_worker() -> None:
    global _worker
    with _worker_lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_worker_loop, name="rolo-enrichment", daemon=True)
            _worker.start()


def stop_worker(timeout: float = 2.0) -> None:
    global _worker
    with _worker_lock:
        w = _worker
        _worker = None
    if w is not None and w.is_alive():
        _queue.put(None)
        w.join(timeout)


def enqueue(contact_id: str, job_id: str) -> None:
    """Queue a job. Returns immediately; the row is already `pending`."""
    start_worker()
    _queue.put((contact_id, job_id))


def wait_idle(timeout: float = 10.0) -> bool:
    """Block until the queue is drained (tests / shutdown)."""
    deadline = time.monotonic() + timeout
    while _queue.unfinished_tasks:
        if time.monotonic() > deadline:
            return False
        time.sleep(0.01)
    return True


def reset_interrupted() -> int:
    """On startup: any contact left pending by a previous process becomes failed."""
    with Session(get_engine()) as s:
        rows = s.exec(select(ContactRow).where(ContactRow.enrichment_status == "pending")).all()
        for r in rows:
            r.enrichment_status = "failed"
            r.enrichment_error = INTERRUPTED_MSG
            r.enrichment_job = None
            s.add(r)
        s.commit()
        return len(rows)
