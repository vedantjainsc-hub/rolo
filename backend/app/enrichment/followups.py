"""Follow-up post-processing (ENRICHMENT.md v2): the scan guard (BUG-15), timing
extraction, and date_status classification (BUG-14). Deterministic; never calls the model."""
from __future__ import annotations

import re
from datetime import date

from app.enrichment.dates import _MONTH_RE, PAST_WORDS, resolve_date
from app.models import Enrichment, FollowUp, normalise_action  # noqa: F401  (re-export)

MAX_FOLLOW_UPS = 5
ACTION_MAX_WORDS = 12

_WEEKDAY = r"(?:mon|tues|wednes|thurs|fri|satur|sun)days?"
_NUM = r"(?:\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten|a\s+couple\s+of|a\s+few|few)"
_PREP = r"(?:on|by|before|until|till|this|next)"
_STOP_AFTER = {"and", "to", "so", "but", "then", "about", "with", "for", "in", "at", "on", "if", "or", "because"}

# Each pattern finds one kind of timing phrase. "strict" ones are safe to lift out of an
# action ("Send the Friday report" must not become a Friday follow-up).
_P_ISO = rf"(?:{_PREP}\s+)?\d{{4}}-\d{{1,2}}-\d{{1,2}}"
_P_MONDAY = rf"(?:{_MONTH_RE})\.?\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s+\d{{4}})?\b"
_P_DAYMON = rf"\d{{1,2}}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:{_MONTH_RE})\b\.?(?:,?\s+\d{{4}})?"
_P_IN_N = rf"in\s+{_NUM}\s+(?:day|week|month)s?\b"
_P_NEXT = r"(?:next|this)\s+(?:week|month)\b"
_P_REL = r"(?:the\s+)?(?:day\s+after\s+tomorrow|tomorrow|today|tonight)\b"
_P_WEEKDAY_PREP = rf"{_PREP}\s+{_WEEKDAY}\b"
_P_WEEKDAY = rf"{_WEEKDAY}\b"
_P_AFTER = r"after\s+[^\s.,;:!?]+(?:\s+[^\s.,;:!?]+){0,3}"
_P_BY = r"by\s+(?:the\s+)?(?:end\s+of\s+(?:the\s+)?(?:day|week|month|year|quarter)|eod|eow|noon)\b"

_SCAN = re.compile(
    "|".join(f"(?:{p})" for p in (
        _P_ISO, rf"(?:{_PREP}\s+)?{_P_MONDAY}", rf"(?:{_PREP}\s+)?{_P_DAYMON}", _P_IN_N, _P_NEXT,
        _P_REL, _P_WEEKDAY_PREP, _P_WEEKDAY, _P_AFTER, _P_BY,
    )),
    re.I,
)
_STRICT = re.compile(
    "|".join(f"(?:{p})" for p in (
        _P_ISO, rf"{_PREP}\s+{_P_MONDAY}", rf"{_PREP}\s+{_P_DAYMON}", _P_IN_N, _P_NEXT,
        _P_REL, _P_WEEKDAY_PREP, _P_AFTER,
    )),
    re.I,
)
_EXPLICIT_DATE = re.compile(rf"\d{{4}}-\d{{1,2}}-\d{{1,2}}|{_P_MONDAY}|{_P_DAYMON}", re.I)
_PAST_CUE = r"(?:was|were|did|recap|recaps|happened|had|held|went|took\s+place)"
_ACTION_CUE = re.compile(
    r"\b(?:follow(?:ing)?[\s-]?up|send|call|email|e-mail|meet|meeting|intro(?:duce|duction)?s?|ping|"
    r"check\s+in|catch\s+up|lunch|coffee|review|schedule|demo|pitch|deadline|due|remind(?:er)?|book|"
    r"share|text|message|attend|invite|submit|visit|pay|interview|pick\s+(?:\w+\s+)?up)\b",
    re.I,
)
_HEDGE = re.compile(r"\b(?:maybe|might|possibly|perhaps|probably|i\s+think|not\s+sure|likely|could)\b", re.I)


_SENTENCE_PAST = re.compile(
    r"\b(?:was|were|did|had|met|went|happened|recap|recaps|last|ago|yesterday|since|held)\b", re.I
)


def _tidy(phrase: str) -> str:
    """Trim an after/by phrase at the first connector word ("after Diwali and then" -> "after Diwali")."""
    phrase = phrase.strip().rstrip(".,;:!?")
    words = phrase.split()
    if words and words[0].lower() in ("after", "by"):
        out = [words[0]]
        for w in words[1:]:
            if w.lower() in _STOP_AFTER:
                break
            out.append(w)
        if len(out) == 1 or (len(out) == 2 and out[1].lower() in ("the", "a")):
            return ""
        return " ".join(out)
    return phrase.strip()


def _past_context(text: str, start: int, end: int) -> bool:
    """A past cue just before ("last", "since") or a past-tense word within 3 words of the phrase."""
    before = text[:start]
    if re.search(r"\b(?:last|since)\s*$", before, re.I) or re.match(r"\s*ago\b", text[end:], re.I):
        return True
    near_before = " ".join(before.split()[-3:])
    near_after = " ".join(text[end:].split()[:3])
    return bool(re.search(rf"\b{_PAST_CUE}\b", f"{near_before} {near_after}", re.I))


def extract_timing(text: str | None, strict: bool = True) -> str | None:
    """First timing phrase in `text` (strict patterns by default), or None."""
    if not text:
        return None
    rx = _STRICT if strict else _SCAN
    for m in rx.finditer(text):
        phrase = _tidy(m.group(0))
        if phrase and not _past_context(text, m.start(), m.end()):
            return phrase
    return None


def _sentences(notes: str) -> list[str]:
    # Line breaks inside a sentence are wrapping, not sentence ends.
    flat = re.sub(r"(?<![.!?।])\s*\n\s*", " ", notes)
    return [s.strip() for s in re.split(r"(?<=[.!?।])\s+|\n+", flat) if s.strip()]


_PAST_MENTION = re.compile(
    rf"\b(?:last|since|previous)\s+(?:{_WEEKDAY}|week|month|year|\w+)\b|\b\w+\s+(?:days?|weeks?|months?|years?)\s+ago\b|\byesterday\b",
    re.I,
)


def _same_timing(phrase: str, fu: FollowUp, today: date) -> bool:
    """Does `fu` already cover this (future) timing phrase? Past mentions never count."""
    if fu.date_status == "past" or (fu.when_text and PAST_WORDS.search(fu.when_text)):
        return False
    p = phrase.casefold()
    hay = _PAST_MENTION.sub(" ", f"{fu.when_text or ''} {fu.action}").casefold()
    if p in hay or (fu.when_text and fu.when_text.casefold() in p):
        return True
    core = re.sub(rf"^(?:{_PREP}|after|in)\s+", "", p)
    if core and core != p and re.search(rf"(?<!\w){re.escape(core)}(?!\w)", hay):
        return True
    d1 = resolve_date(phrase, today)
    return d1 is not None and fu.when_text is not None and resolve_date(fu.when_text, today) == d1


def _action_from_sentence(sentence: str) -> str:
    words = sentence.strip().rstrip(".!?।;:").split()
    text = " ".join(words[:ACTION_MAX_WORDS])
    return text[:1].upper() + text[1:]


_GENERIC_WORDS = {
    "follow", "up", "the", "a", "an", "him", "her", "them", "his", "to", "and", "with", "about",
    "send", "call", "email", "ping", "check", "in", "on", "by", "for", "it", "of", "at", "she", "he",
}


def _content_words(text: str) -> set[str]:
    return {w for w in re.findall(r"\w+", text.lower()) if len(w) >= 3 and w not in _GENERIC_WORDS}


def scan_follow_ups(e: Enrichment, notes: str, today: date) -> None:
    """BUG-15 backstop: restore stated follow-up timing the model dropped. If a follow-up
    for the same action exists without timing, the phrase is attached to it; otherwise, only
    for sentences with an action cue, a new follow-up is added (max 5 in total)."""
    for sentence in _sentences(notes):
        has_cue = bool(_ACTION_CUE.search(sentence))
        for m in _SCAN.finditer(sentence):
            phrase = _tidy(m.group(0))
            if not phrase or _past_context(sentence, m.start(), m.end()):
                continue
            # Without an action cue, only an explicit date counts, and it may only be attached to
            # an existing follow-up about the same thing; it never creates one ("Raised their
            # Series A on Sep 3", "Her birthday is on Nov 12").
            if not has_cue and (not _EXPLICIT_DATE.search(phrase) or _SENTENCE_PAST.search(sentence)):
                continue
            if any(_same_timing(phrase, fu, today) for fu in e.follow_ups):
                continue
            words = _content_words(sentence)
            match = next((fu for fu in e.follow_ups if not fu.when_text and words & _content_words(fu.action)), None)
            if match is not None:
                match.when_text = phrase
            elif has_cue and len(e.follow_ups) < MAX_FOLLOW_UPS:
                e.follow_ups.append(FollowUp(
                    action=_action_from_sentence(sentence), when_text=phrase, confidence="stated",
                ))


_FACT_CUE = re.compile(
    r"\b(?:raised|founded|launched|joined|left|graduated|born|birthday|anniversary|married|moved|"
    r"started\s+at|closed|acquired)\b",
    re.I,
)
_FUTURE_CUE = re.compile(
    r"\b(?:will|need\s+to|needs\s+to|should|must|plan(?:s|ning)?\s+to|going\s+to|to-?do|remember\s+to)\b|\w'll\b",
    re.I,
)
_NOT_IMPERATIVE_START = {
    "her", "his", "their", "the", "a", "an", "my", "our", "your", "she", "he", "they", "it", "we", "i",
    "this", "that", "these", "those", "there", "is", "was", "are", "were",
}


def _imperative(text: str) -> bool:
    """Rough check: does the text start with a bare verb ("Attend ...", "Submit ...")?"""
    m = re.match(r"\s*(?:[-*•]\s*)?([A-Za-z]+)", text or "")
    if not m:
        return False
    w = m.group(1).lower()
    return w not in _NOT_IMPERATIVE_START and not w.endswith("ed") and not _FACT_CUE.match(w)


def _date_reads_past(fu: FollowUp, sentences: list[str], today: date) -> bool:
    text = f"{fu.when_text or ''} {fu.action}"
    if PAST_WORDS.search(fu.when_text or ""):
        return True
    for m in _EXPLICIT_DATE.finditer(text):
        if _past_context(text, m.start(), m.end()):
            return True
        d = resolve_date(m.group(0), today)
        if d is not None and d < today:  # explicit year already gone
            return True
    return any(_SENTENCE_PAST.search(s) and not _FACT_CUE.search(s) for s in sentences)


def drop_non_action_dated(follow_ups: list[FollowUp], notes: str, today: date | None = None) -> list[FollowUp]:
    """Model follow-ups are kept by default. One is dropped only when its source sentence (or
    its action) states a fact rather than a to-do: a fact cue (raised, joined, birthday, ...)
    AND no action cue AND no future/imperative cue. Past-dated ones are kept (shown as past)."""
    today = today or date.today()
    sentences = _sentences(notes)
    kept = []
    for fu in follow_ups:
        timing = [fu.when_text] if fu.when_text else []
        timing += [m.group(0) for m in _EXPLICIT_DATE.finditer(fu.action)]
        source = [s for s in sentences if any(t and t.casefold().strip() in s.casefold() for t in timing)]
        texts = [fu.action, *source]
        is_fact = any(_FACT_CUE.search(t) for t in texts)
        has_action = any(_ACTION_CUE.search(t) for t in texts)
        # "Imperative verb first" is judged on what the user wrote (the source sentence);
        # the model's action is only used when the sentence can't be found.
        has_future = any(_FUTURE_CUE.search(t) for t in texts) or any(_imperative(t) for t in (source or [fu.action]))
        if is_fact and not has_action and not has_future and not _date_reads_past(fu, source, today):
            continue
        kept.append(fu)
    return kept


def _is_past(fu: FollowUp, today: date) -> bool:
    wt = fu.when_text or ""
    if wt and PAST_WORDS.search(wt):
        return True
    for text in (wt, fu.action):
        for m in _EXPLICIT_DATE.finditer(text or ""):
            if _past_context(text, m.start(), m.end()):
                return True
    if wt:
        d = resolve_date(wt, today)
        if d is not None and d < today:  # explicit date with a year, already gone
            return True
    return False


def _source_sentence_hedged(fu: FollowUp, notes: str) -> bool:
    """Is the notes sentence this follow-up came from hedged ("Maybe invite him ... in November")?"""
    if not notes or not fu.when_text:
        return False
    words = _content_words(fu.action)
    for sentence in _sentences(notes):
        if fu.when_text.casefold() in sentence.casefold() and (not words or words & _content_words(sentence)):
            if _HEDGE.search(sentence):
                return True
    return False


def classify(fu: FollowUp, today: date, notes: str = "") -> FollowUp:
    """Set when_text (lifted from the action if missing), suggested_date, date_status, confidence."""
    if not fu.when_text:
        fu.when_text = extract_timing(fu.action, strict=True)
    if _is_past(fu, today):
        fu.date_status, fu.suggested_date = "past", None
    else:
        d = resolve_date(fu.when_text, today) if fu.when_text else None
        if d is not None:
            fu.date_status, fu.suggested_date = "exact", d.isoformat()
        else:
            fu.suggested_date = None
            fu.date_status = "needs_date" if fu.when_text else "none"
    hedged = _HEDGE.search(f"{fu.when_text or ''} {fu.action}") or _source_sentence_hedged(fu, notes)
    fu.confidence = "maybe" if hedged else "stated"
    return fu
