"""Enrichment prompt and JSON schema, exactly as docs/ENRICHMENT.md."""
from __future__ import annotations

from datetime import date
from typing import Any

SYSTEM_PROMPT = (
    "You are a careful assistant that organises a professional's private notes about a person\n"
    'into a structured contact card. Use ONLY the information in the notes. Do not add facts\n'
    'from your own knowledge, even if the name is famous. If something is uncertain or\n'
    'hedged in the notes ("I think", "maybe"), mark it "maybe" — but a hedge applies only to the\n'
    'claim it qualifies. Example: "Works as a designer at a bank, maybe HSBC" → role "Designer"\n'
    '(stated), company "A bank, possibly HSBC" (maybe). Use "inferred" only for your own reading\n'
    'of things the notes don\'t say directly. Keep hedges ("possibly") in the headline and\n'
    "summary. Only fill suggested_date when it can be computed from today's date alone; for\n"
    'holidays or events leave it null. "location" is where the person lives or works, not where\n'
    'you met (that goes in how_we_met). Only list follow_ups the notes actually mention; put timing phrases\n'
    '("after Diwali", "next week", "maybe in November") verbatim in when_text, not in action. The\n'
    'suggested_opener must only use stated facts. Set person_name only if the notes say the\n'
    "person's name. If it is not in the notes, leave\n"
    'it null or empty and list it under "gaps". Be brief: summary at most 2 sentences, each list\n'
    "item under 12 words. Today's date is {today}. Respond with compact single-line JSON only\n"
    '(no indentation or newlines), matching the schema exactly.'
)

USER_PROMPT = (
    'Person: {name_or_unknown}\n'
    'Notes:\n'
    '"""\n'
    '{raw_notes}\n'
    '"""\n'
    'Schema:\n'
    '{schema_json}'
)

# Used for {name_or_unknown} when a voice contact has no name yet.
UNKNOWN_NAME = '(not given — take it from the notes if said)'

RETRY_PROMPT = "Your last reply was not valid JSON. Reply with JSON only."

# Human-readable schema shown to the model in the user prompt (verbatim from ENRICHMENT.md).
SCHEMA_JSON_TEXT = (
    '{\n'
    '  "person_name": "string|null — the person\'s name only if said in the notes (e.g. \'This is Priya Shah\')",\n'
    '  "headline": "string <= 80 chars, e.g. \'Partnerships lead at a payments startup\'",\n'
    '  "summary": "1-2 sentence neutral summary of the notes",\n'
    '  "role":    { "value": "string|null", "confidence": "stated|maybe|inferred" },\n'
    '  "company": { "value": "string|null", "confidence": "stated|maybe|inferred" },\n'
    '  "location":{ "value": "string|null", "confidence": "stated|maybe|inferred" },\n'
    '  "how_we_met": { "value": "string|null", "confidence": "stated|maybe|inferred" },\n'
    '  "interests":  [ { "value": "string", "confidence": "stated|maybe|inferred" } ],\n'
    '  "what_they_want": [ { "value": "string", "confidence": "stated|maybe|inferred" } ],\n'
    '  "how_i_can_help": [ { "value": "string", "confidence": "stated|maybe|inferred" } ],\n'
    '  "personal_details": [ { "value": "string", "confidence": "stated|maybe|inferred" } ],\n'
    '  "follow_ups": [\n'
    '    { "action": "string", "when_text": "string|null", "suggested_date": "YYYY-MM-DD|null" }\n'
    '  ],\n'
    '  "gaps": [ "string — useful info that is missing, e.g. \'Exact company name\'" ],\n'
    '  "questions_to_ask": [ "string — max 3, natural questions for next conversation" ],\n'
    '  "suggested_opener": "string — one short, professional message the user could send",\n'
    '  "suggested_tags": [ "string — lowercase, 1-2 words, max 5" ],\n'
    '  "contact_info": { "email": "string|null", "phone": "string|null", "linkedin": "string|null" }\n'
    '}'
)

# Machine schema passed to Ollama's `format` (structured outputs).
_CONF = {"type": "string", "enum": ["stated", "maybe", "inferred"]}
_NULLABLE_STR = {"type": ["string", "null"]}
_FIELD = {
    "type": "object",
    "properties": {"value": _NULLABLE_STR, "confidence": _CONF},
    "required": ["value", "confidence"],
}
_ITEM = {
    "type": "object",
    "properties": {"value": {"type": "string"}, "confidence": _CONF},
    "required": ["value", "confidence"],
}
# maxItems mirror the post-processing trim limits (6 for lists without a trim limit).
LIST_MAX = {
    "interests": 8, "follow_ups": 5, "questions_to_ask": 3, "suggested_tags": 5,
    "what_they_want": 6, "how_i_can_help": 6, "personal_details": 6, "gaps": 6,
}
HEADLINE_MAX = 80


def _items(key: str) -> dict[str, Any]:
    return {"type": "array", "items": _ITEM, "maxItems": LIST_MAX[key]}


def _strs(key: str) -> dict[str, Any]:
    return {"type": "array", "items": {"type": "string"}, "maxItems": LIST_MAX[key]}


FORMAT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "person_name": _NULLABLE_STR,
        "headline": {"type": "string", "maxLength": HEADLINE_MAX},
        "summary": {"type": "string"},
        "role": _FIELD,
        "company": _FIELD,
        "location": _FIELD,
        "how_we_met": _FIELD,
        "interests": _items("interests"),
        "what_they_want": _items("what_they_want"),
        "how_i_can_help": _items("how_i_can_help"),
        "personal_details": _items("personal_details"),
        "follow_ups": {
            "type": "array",
            "maxItems": LIST_MAX["follow_ups"],
            "items": {
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "when_text": _NULLABLE_STR,
                    "suggested_date": _NULLABLE_STR,
                },
                "required": ["action", "when_text", "suggested_date"],
            },
        },
        "gaps": _strs("gaps"),
        "questions_to_ask": _strs("questions_to_ask"),
        "suggested_opener": {"type": "string"},
        "suggested_tags": _strs("suggested_tags"),
        "contact_info": {
            "type": "object",
            "properties": {"email": _NULLABLE_STR, "phone": _NULLABLE_STR, "linkedin": _NULLABLE_STR},
            "required": ["email", "phone", "linkedin"],
        },
    },
    "required": [
        "person_name", "headline", "summary", "role", "company", "location", "how_we_met",
        "interests", "what_they_want", "how_i_can_help", "personal_details",
        "follow_ups", "gaps", "questions_to_ask", "suggested_opener",
        "suggested_tags", "contact_info",
    ],
}


def build_messages(name: str | None, raw_notes: str, today: date) -> list[dict[str, str]]:
    """`name` None means "not given" (voice contact without a name)."""
    return [
        {"role": "system", "content": SYSTEM_PROMPT.format(today=today.isoformat())},
        {
            "role": "user",
            "content": USER_PROMPT.format(
                name_or_unknown=name if name else UNKNOWN_NAME, raw_notes=raw_notes, schema_json=SCHEMA_JSON_TEXT
            ),
        },
    ]
