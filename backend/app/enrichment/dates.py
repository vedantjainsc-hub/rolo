"""Deterministic follow-up date resolution (ENRICHMENT.md, post-processing guards).

The model's own suggested_date is ignored; we compute it from the timing phrase.
Supported: ISO dates, "Nov 2" / "2 November" (next occurrence if no year), today, tonight,
tomorrow, "in N days/weeks/months", next week (next Monday), next month (1st), and weekday
names ("Friday", "by Friday", "next Monday": the next such day after today, +7 if today
is that weekday). Anything else (holidays, events, "in November", "soon") -> None.
"""
from __future__ import annotations

import calendar
import re
from datetime import date, timedelta

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3, "apr": 4, "april": 4,
    "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7, "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9, "oct": 10, "october": 10, "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}
_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
}
_NUMBERS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "couple of": 2, "a couple of": 2, "few": 3, "a few": 3,
}

_MONTH_RE = "|".join(sorted(_MONTHS, key=len, reverse=True))
_ISO = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")
_MON_DAY = re.compile(rf"\b({_MONTH_RE})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s+(\d{{4}})\b)?", re.I)
_DAY_MON = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({_MONTH_RE})\b\.?(?:,?\s+(\d{{4}})\b)?", re.I)
_NUM_RE = r"\d+|" + "|".join(sorted((re.escape(k) for k in _NUMBERS), key=len, reverse=True))
_IN_N = re.compile(rf"\bin\s+({_NUM_RE})\s+(day|week|month)s?\b", re.I)
_WEEKDAY = re.compile(rf"\b({'|'.join(_WEEKDAYS)})s?\b", re.I)


def _safe(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _next_occurrence(today: date, month: int, day: int, year: int | None) -> date | None:
    if year:
        return _safe(year, month, day)
    d = _safe(today.year, month, day)
    if d is None or d < today:
        d = _safe(today.year + 1, month, day)
    return d


def _add_months(d: date, n: int) -> date:
    m0 = d.month - 1 + n
    y, m = d.year + m0 // 12, m0 % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def _num(s: str) -> int:
    s = s.lower()
    return int(s) if s.isdigit() else _NUMBERS[s]


PAST_WORDS = re.compile(r"\b(?:last|since|ago|yesterday|earlier|previous(?:ly)?)\b", re.I)


def resolve_date(text: str | None, today: date) -> date | None:
    """Return the date a timing phrase refers to, or None if it can't be computed.
    Past references ("last Friday", "since", "ago", "yesterday") are never turned into
    a future date. An explicit date with a year may be in the past; callers check that."""
    if not text or not text.strip():
        return None
    t = text.strip()
    low = t.lower()
    if PAST_WORDS.search(t):
        return None

    if m := _ISO.search(t):
        return _safe(int(m[1]), int(m[2]), int(m[3]))
    if m := _MON_DAY.search(t):
        return _next_occurrence(today, _MONTHS[m[1].lower()], int(m[2]), int(m[3]) if m[3] else None)
    if m := _DAY_MON.search(t):
        return _next_occurrence(today, _MONTHS[m[2].lower()], int(m[1]), int(m[3]) if m[3] else None)

    if re.search(r"\bday after tomorrow\b", low):
        return today + timedelta(days=2)
    if re.search(r"\btomorrow\b", low):
        return today + timedelta(days=1)
    if re.search(r"\b(today|tonight)\b", low):
        return today

    if m := _IN_N.search(t):
        n, unit = _num(m[1]), m[2].lower()
        if unit == "day":
            return today + timedelta(days=n)
        if unit == "week":
            return today + timedelta(weeks=n)
        return _add_months(today, n)

    if re.search(r"\bnext\s+week\b", low):
        return today + timedelta(days=7 - today.weekday())  # next Monday
    if re.search(r"\bnext\s+month\b", low):
        return _add_months(today.replace(day=1), 1)

    if m := _WEEKDAY.search(t):
        ahead = (_WEEKDAYS[m[1].lower()] - today.weekday()) % 7
        return today + timedelta(days=ahead or 7)

    return None
