# Rolo — API Contract (v2.1)

The ONLY interface between `backend/` and `frontend/`. Base path: `/api`.
All bodies are JSON, except `POST /api/transcribe` (WAV in) and the `.ics` endpoint (calendar out). Timestamps are ISO-8601 UTC strings. IDs are UUID strings.
Changes go through the lead and bump the version at the top of this file.

## Types

```ts
type EnrichmentStatus = "none" | "pending" | "done" | "failed";
type Confidence = "stated" | "maybe" | "inferred";          // v2: "maybe" added
type DateStatus = "exact" | "needs_date" | "none" | "past";

// Shape of each item in enrichment.follow_ups as returned by the API (backend adds the
// last four fields; the model only produces action/when_text).
interface FollowUp {
  action: string;
  when_text: string | null;
  suggested_date: string | null;      // YYYY-MM-DD, computed by backend; null unless exact
  date_status: DateStatus;
  confidence: Confidence;
  confirmed_date: string | null;      // YYYY-MM-DD the user picked; survives re-enrichment
  dismissed: boolean;                 // user chose "No date"
}

interface Contact {
  id: string;
  name: string;
  needs_name: boolean;                // v2: true when created by voice without a name
  source: "typed" | "voice";          // v2.1: how the contact was first captured
  raw_notes: string;
  tags: string[];
  enrichment: Enrichment | null;      // schema in ENRICHMENT.md
  enrichment_status: EnrichmentStatus;
  enrichment_error: string | null;    // human-readable, safe to show the user
  enriched_at: string | null;
  model_name: string | null;
  created_at: string;
  updated_at: string;
}

interface ContactSummary {             // used in the list view
  id: string;
  name: string;
  headline: string | null;            // enrichment.headline, if any
  company: string | null;             // enrichment.company.value, if any
  tags: string[];
  enrichment_status: EnrichmentStatus;
  updated_at: string;
}

interface ApiError { error: { code: string; message: string } }
```

## Endpoints

### `GET /api/health`
→ `200 { "status": "ok",
         "model": { "name": "gemma4:e4b", "available": boolean, "detail": string | null },
         "asr":   { "name": "parakeet-tdt-0.6b-v3", "available": boolean, "detail": string | null } }`
`available` is false if Ollama is unreachable or the model isn't pulled; `detail` says which.
`asr.available` is false if the speech helper isn't built or its models aren't downloaded;
`detail` gives the fix ("Run ./run.sh once to set up voice").

### `GET /api/contacts?q=<text>`
→ `200 { "contacts": ContactSummary[] }`, newest `updated_at` first.
`q` (optional) matches case-insensitively against name, raw_notes, tags, company, headline.

### `POST /api/contacts`
Body: `{ "name"?: string, "raw_notes": string, "tags"?: string[], "enrich"?: boolean, "source"?: "typed" | "voice" }`
- `name` required, trimmed, 1–120 chars — **except** when `source` is `"voice"`: then it
  may be blank/omitted; the contact is saved with `name: "New contact"`, `needs_name: true`,
  and enrichment fills the name from what was said (see ENRICHMENT.md). `raw_notes` 0–10,000 chars.
- Voice contacts with blank `raw_notes` → 400 `raw_notes: nothing was heard`.
- Lengths are counted in Unicode code points (Python `len`, JS `[...str].length`), so an
  emoji counts as 1.
- `tags`: trimmed, empty dropped, de-duplicated case-insensitively, each ≤ 40 chars, ≤ 20 tags.
- If `raw_notes` is blank, no model call is made: status is `none` even when `enrich` is true.
- Saves immediately and returns `201 Contact`.
- If `enrich` is true (default true), sets `enrichment_status: "pending"` and starts
  enrichment in the background. The response does NOT wait for the model.

### `GET /api/contacts/{id}`
→ `200 Contact` | `404`

### `PATCH /api/contacts/{id}`
Body (all optional): `{ "name"?: string, "raw_notes"?: string, "tags"?: string[] }`
→ `200 Contact`. Does not auto re-enrich. Setting `name` sets `needs_name: false`.

### `POST /api/contacts/{id}/notes`
Body: `{ "text": string, "enrich"?: boolean }`
Appends to `raw_notes` as `\n\n[YYYY-MM-DD] <text>` (no leading blank line if notes were empty).
`text` 1–10,000 chars, and the combined notes must stay ≤ 10,000, else 400.
If `enrich` (default true), re-enriches. Allowed while pending: the new run supersedes the
running one (the older result is discarded).
→ `200 Contact`

### `POST /api/contacts/{id}/enrich`
Starts (re-)enrichment in the background. → `202 Contact` with `enrichment_status: "pending"`.
If already pending → `409`. If `raw_notes` is blank → `400 validation_error`
("raw_notes: add some notes before enriching").

### `DELETE /api/contacts/{id}`
→ `204` | `404`

### `PATCH /api/contacts/{id}/follow-ups/{index}`  (v2)
Body: `{ "confirmed_date"?: "YYYY-MM-DD" | null, "dismissed"?: boolean }` → `200 Contact`.
`index` is the position in the *current* `enrichment.follow_ups` (re-read after re-enrichment).
Confirming a date clears `dismissed`; dismissing clears `confirmed_date` (unless both are sent). 404 if the contact or index doesn't
exist; 409 `enrichment_in_progress` while pending. The choice is stored apart from the model
output, keyed by the normalised `action` text, and re-applied after re-enrichment when a
follow-up with the same normalised action reappears.

### `GET /api/contacts/{id}/follow-ups/{index}.ics`  (v2)
→ `200 text/calendar` with `Content-Disposition: attachment; filename="rolo-followup.ics"`.
One all-day VEVENT on `confirmed_date ?? suggested_date`; SUMMARY "Follow up: {name} — {action}";
DESCRIPTION includes `when_text` and the contact headline. 400 `validation_error`
("date: pick a date first") if neither date exists or the item is dismissed.

### `GET /api/follow-ups/upcoming?days=14`  (v2)
→ `200 { "items": { "contact_id": string, "contact_name": string, "index": number,
         "action": string, "date": string }[] }`, soonest first.
`date` = `confirmed_date`, else `suggested_date` when `date_status` is `exact`. Excludes
dismissed and past items; includes today through today+`days` (default 14, 0–60).

### `POST /api/transcribe`  (v2)
Body: raw `audio/wav`, 16 kHz mono PCM16, max 5 minutes / 10 MB.
→ `200 { "text": string, "duration_s": number }`.
The audio is transcribed on this machine and never stored (temp file deleted immediately).
Errors: 400 `validation_error` ("audio: …") for bad/too-long/undecodable audio; 503
`asr_unavailable` with a friendly message if the speech helper isn't ready or times out (20 s).
Empty audio → `{ "text": "", "duration_s": 0 }`.
The frontend may call this repeatedly with the growing recording (every ~1.5 s) to show
live text; the backend handles one transcription at a time per request and requests from
the same page are independent.

### `GET /api/export`
→ `200 { "exported_at": string, "contacts": Contact[] }`

## Polling
While a contact is `pending`, the frontend polls `GET /api/contacts/{id}` every 1.5 s
(stop after 120 s and show a timeout message with Retry). The backend model timeout is
90 s (env `ROLO_MODEL_TIMEOUT`), so the UI cutoff must always exceed it.

## Validation messages
`message` starts with the field name, e.g. `"name: is required"`, `"raw_notes: must be at most 10,000 characters"`,
so the UI can show it under the right input. Malformed JSON → 400 `validation_error`.
Validation errors are always 400 with the `ApiError` body, never FastAPI's default 422.

## Error codes
| HTTP | code | when |
|---|---|---|
| 400 | `validation_error` | bad input; `message` names the field |
| 404 | `not_found` | unknown id or unknown route |
| 405 | `method_not_allowed` | wrong HTTP method on a known route |
| 409 | `enrichment_in_progress` | enrich called while pending (checked atomically) |
| 503 | `asr_unavailable` | speech helper not set up or crashed; message says how to fix |
| 500 | `internal_error` | unexpected; never leak stack traces |

Enrichment failures are NOT HTTP errors: they set `enrichment_status: "failed"` and a
friendly `enrichment_error`, e.g. "The local model isn't running. Start Ollama and tap Retry."
