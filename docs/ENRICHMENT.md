# Rolo — Enrichment Spec (v2)

Enrichment turns messy notes into a structured card. It runs on a local model via
Ollama (default `gemma4:e4b`, configurable via `ROLO_MODEL`). **It structures what the user wrote; it never adds outside facts.**

## Rules (non-negotiable)
1. Only use information present in the notes. No world knowledge about the person or
   company (the model may know a famous "Priya Shah" — ignore that).
2. Every factual field carries `confidence`:
   - `"stated"` — directly and plainly written in the notes
   - `"maybe"` — written in the notes but hedged by the user ("I think Stripe-adjacent",
     "maybe Google", "not sure but…")
   - `"inferred"` — not written, but a reasonable reading of the notes (e.g. how_i_can_help)
   Never output anything with no basis in the notes.
3. Unknown → `null` or empty list. Missing info goes in `gaps`, not guesses.
4. Hedged notes ("I think", "maybe", "not sure", "possibly") → `maybe`. A hedge applies only to the
   claim it qualifies, not the whole sentence. Keep the hedge in the value text
   ("possibly …"), and in `headline`/`summary` too — never state a hedged claim as fact there.
5. Dates: keep relative phrases verbatim in `when_text`; fill `suggested_date`
   (YYYY-MM-DD) only when computable from today's date alone (an explicit date, or an
   offset like "tomorrow", "next week", "in 3 days", a weekday). Events and holidays
   ("after Diwali", "after the conference") → null.
6. Output is JSON only, matching the schema below.

## JSON schema

```json
{
  "person_name": "string|null — the person's name only if said in the notes (e.g. 'This is Priya Shah')",
  "headline": "string <= 80 chars, e.g. 'Partnerships lead at a payments startup'",
  "summary": "1-2 sentence neutral summary of the notes",
  "role":    { "value": "string|null", "confidence": "stated|maybe|inferred" },
  "company": { "value": "string|null", "confidence": "stated|maybe|inferred" },
  "location":{ "value": "string|null", "confidence": "stated|maybe|inferred" },
  "how_we_met": { "value": "string|null", "confidence": "stated|maybe|inferred" },
  "interests":  [ { "value": "string", "confidence": "stated|maybe|inferred" } ],
  "what_they_want": [ { "value": "string", "confidence": "stated|maybe|inferred" } ],
  "how_i_can_help": [ { "value": "string", "confidence": "stated|maybe|inferred" } ],
  "personal_details": [ { "value": "string", "confidence": "stated|maybe|inferred" } ],
  "follow_ups": [
    { "action": "string", "when_text": "string|null", "suggested_date": "YYYY-MM-DD|null" }
  ],
  "gaps": [ "string — useful info that is missing, e.g. 'Exact company name'" ],
  "questions_to_ask": [ "string — max 3, natural questions for next conversation" ],
  "suggested_opener": "string — one short, professional message the user could send",
  "suggested_tags": [ "string — lowercase, 1-2 words, max 5" ],
  "contact_info": { "email": "string|null", "phone": "string|null", "linkedin": "string|null" }
}
```
`contact_info` fields are filled only if literally present in the notes.

## Prompt (backend uses this; lead owns edits)

System:
```
You are a careful assistant that organises a professional's private notes about a person
into a structured contact card. Use ONLY the information in the notes. Do not add facts
from your own knowledge, even if the name is famous. If something is uncertain or
hedged in the notes ("I think", "maybe"), mark it "maybe" — but a hedge applies only to the
claim it qualifies. Example: "Works as a designer at a bank, maybe HSBC" → role "Designer"
(stated), company "A bank, possibly HSBC" (maybe). Use "inferred" only for your own reading
of things the notes don't say directly. Keep hedges ("possibly") in the headline and
summary. Only fill suggested_date when it can be computed from today's date alone; for
holidays or events leave it null. "location" is where the person lives or works, not where
you met (that goes in how_we_met). Only list follow_ups the notes actually mention; put timing phrases
("after Diwali", "next week", "maybe in November") verbatim in when_text, not in action. The
suggested_opener must only use stated facts. Set person_name only if the notes say the
person's name. If it is not in the notes, leave
it null or empty and list it under "gaps". Be brief: summary at most 2 sentences, each list
item under 12 words. Today's date is {today}. Respond with compact single-line JSON only
(no indentation or newlines), matching the schema exactly.
```
User:
```
Person: {name_or_unknown}
Notes:
"""
{raw_notes}
"""
Schema:
{schema_json}
```

`{name_or_unknown}` is the contact's name, or `(not given — take it from the notes if said)`
when the contact was created by voice without a name.

## Ollama call
- `POST http://localhost:11434/api/chat`, `model: $ROLO_MODEL` (default `gemma4:e4b`), `stream: false`, `think: false`,
  `format: <JSON schema object>` (structured outputs), `options: { temperature: 0.2, num_ctx: 8192, num_predict: 1200 }`.
- The `format` schema sets `maxItems` matching the trim limits below (and 6 for the
  other lists, gaps ≤ 6), and `maxLength` 80 on `headline`.
- Enrichment jobs run **one at a time** through a single in-process queue (Ollama serves
  one request at a time anyway). Queued jobs are `pending`. Jobs never hold a DB session
  while waiting on the model.
- Timeout 90 s. On invalid JSON: one retry with "Your last reply was not valid JSON. Reply with JSON only."
- Validate with Pydantic. Drop unknown keys; coerce missing lists to `[]`.

## Post-processing guards (backend, deterministic)
- If `contact_info.email` / `phone` / `linkedin` is not a substring of the notes → set null.
  Shapes: email `x@y.z`; phone = 7–15 digits with optional + ( ) - . spaces and an optional
  trailing "ext N", and NOT a date pattern (YYYY-MM-DD, DD/MM/YYYY, DD.MM.YYYY); linkedin =
  contains `linkedin.com/`, starts with `in/`, or is a bare handle that the notes label as
  LinkedIn ("LinkedIn: priyashah").
- If `company.value` or `role.value` shares no meaningful word with the notes →
  set confidence to `"inferred"`.
- `suggested_date` is computed by the backend from `when_text`, never taken from the model.
  Supported: explicit ISO/`Nov 2`/`2 November` dates (next occurrence if no year), today,
  tonight, tomorrow, "in N days/weeks/months", next week (next Monday), next month (1st),
  weekday names ("Friday", "by Friday", "next Monday" → the next such day after today;
  "next <weekday>" when today is that weekday → +7). Anything else (holidays, events,
  "in November", "soon") → null. Hedged timing keeps its hedge in `when_text`.
- If `location.value` appears in the meeting context (`how_we_met.value` or note sentences
  describing the meeting: met, chatted, ran into, मिले…), and the notes don't say the person
  lives/works/is based there → set `location` to null (it's where you met, not where they live).
  Residence cues count anywhere in the notes when tied to that place, in either order:
  "lives in X", "X, where she lives", "based in X", "X-based", "from X", Hindi "X में रहती/रहता है",
  "X में रहते हैं", "X की रहने वाली/वाला", "X से है/हैं" (BUG-17).
- `role.value` must be a job title. If it starts with "works at/in/for" or "employed at" or
  only restates the employer (role equals the whole company name, case-insensitive) →
  set `role` to null and add the gap "Job title". A title word that merely also appears in
  the company name ("Partner" at "Partner Capital Group") is kept.
- Blank notes → never call the model.
- **Name from voice:** if the contact has `needs_name: true` and `person_name` is non-null
  and appears in the notes (case-insensitive) → set the contact's `name` to it and
  `needs_name` to false. Otherwise leave it.
- **Maybe upgrade:** a value labelled `maybe` becomes `stated` when none of its meaningful
  words appear inside a hedged clause of the notes (a clause containing I think, maybe,
  possibly, probably, not sure, might, perhaps, guess, या शायद). The reverse never happens here.
- **Opener guard:** if `suggested_opener` contains (case-insensitive) any value text marked
  `maybe` or `inferred` (or its distinctive words, e.g. "Google" from "maybe Google") →
  replace with the neutral template "Great meeting you{ at <how_we_met if stated>}. Would love
  to continue our conversation." No second model call.
- **Follow-up scan (backend):** find timing phrases in the notes (weekday names, today/
  tomorrow/tonight, next week/month, in N days/weeks/months, explicit dates, "after <X>",
  "by <X>") inside sentences with an action cue (follow up, send, call, email, meet, intro,
  ping, check in, catch up, lunch, coffee, review, schedule, demo, pitch, meeting, call,
  deadline, due, remind, book, share, introduce, attend, invite, submit, visit, pay,
  interview, pick up).
  A date in a sentence with **no** action cue (e.g. "Raised their Series A on Sep 3",
  "Birthday is May 12") may only attach its timing to an existing follow-up whose action
  shares a meaningful word with that sentence. It never creates a new follow-up.
- **Model follow-ups are kept by default.** The backend drops a model follow-up only when its
  source sentence (or its action) describes a fact, not a to-do: it contains a fact cue
  (raised, founded, launched, joined, left, graduated, born, birthday, anniversary, married,
  moved, started at, closed, acquired) AND no action cue AND no future/imperative cue
  (will, need to, should, must, plan to, going to, to-do, remember to, or an imperative verb
  first). If its date reads as past, it is kept and shown as `past` instead of dropped. If no follow-up already contains that phrase in
  `when_text` or `action`, append `{ action: <that sentence, ≤ 12 words>, when_text: <phrase> }`
  with `confidence: "stated"`. Max 5 follow-ups total.
- **Follow-up classification (backend, never the model)** — each follow-up gets
  `date_status`:
  - `past` — the timing refers to the past: "last <X>", "since", "ago", "yesterday", or an
    explicit date before today with a year, or a past-tense cue ("was", "did", "recap") right
    before an explicit date. `suggested_date` = null.
  - `exact` — `suggested_date` was computed by the date rules above.
  - `needs_date` — `when_text` is non-null but no date could be computed ("after Diwali",
    "in November", "soon").
  - `none` — no timing at all.
  - Each follow-up also gets `confidence` (`maybe` if the timing or action is hedged).
- If email, phone and linkedin are all null and no gap mentions email or contact details →
  append the gap "Email or other contact details".
- Trim lists: interests ≤ 8, follow_ups ≤ 5, questions_to_ask ≤ 3, suggested_tags ≤ 5.

## Golden example
Notes: "Priya Shah. Met at Fintech Forward. Runs partnerships at a payments startup, I think
Stripe-adjacent. Wants intros to bank CTOs. Has a dog named Biscuit. Said to follow up after Diwali."

Expected highlights:
- role "Partnerships lead" (stated); company "Payments startup, possibly Stripe-adjacent" (maybe)
- how_we_met "Fintech Forward" (stated)
- what_they_want ["Introductions to bank CTOs"] (stated)
- personal_details ["Has a dog named Biscuit"] (stated)
- follow_ups [{ action: "Follow up", when_text: "after Diwali" }]
- gaps include exact company name, email
- contact_info all null
