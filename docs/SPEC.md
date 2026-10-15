# Rolo — Product Spec (MVP)

## Problem
Professionals, consultants, and networkers meet many people and lose the details:
where they met, what the person cares about, what was promised. Existing CRMs are
built for sales pipelines, are slow to enter data into, and send personal notes to
the cloud.

## Product in one line
Type a name, brain-dump what you know, tap **Enrich**, get a clean contact card —
all processed by a model running on your own device.

## Audience
Consultants, VCs, BD and partnerships people, and active networkers. Professional,
time-poor, often capturing notes right after a conversation on their phone.

## Tone
Professional, calm, trustworthy. Clean corporate look: navy, white, generous space.

## Core user flow
1. Open app → contact list.
2. Tap **+** → Quick Capture: name field + large notes box.
3. Tap **Save & Enrich** → notes are saved immediately, then enrichment runs.
4. Contact Card shows the structured profile, with original notes underneath.
5. Later: search, open, edit notes, re-enrich, delete.

## MVP scope
**In**
- Create contact (name + raw notes). Saving never waits on the model.
- Enrich with a local model (default Gemma 4 E4B, `gemma4:e4b`) → structured card (schema in ENRICHMENT.md).
- Contact card view: summary, role/company, how we met, interests, what they want,
  personal details, follow-ups, gaps, suggested opener, tags.
- Append more notes to an existing contact and re-enrich.
- Contact list with search (name, company, tags, notes).
- Edit name/notes, delete contact (with confirm).
- Settings: model status (is Ollama up, which model), export all data as JSON.
- Mobile-first responsive UI usable at 375px width; works on laptop too.

**Out (later phases)**
- Accounts, login, cloud sync
- Voice capture / transcription (Gemma 4 E4B supports audio — strong v2 candidate)
- Web research / public-profile lookup
- Relationship graph, reminders/notifications, calendar integration
- Native iOS/Android app with on-device inference

## Where the model runs (important)
- **MVP:** Gemma 4 E4B runs in Ollama on the laptop. The phone opens the web app over
  Wi-Fi and the laptop does the inference. Data never leaves your network.
- **Later:** a native app (or LiteRT / MediaPipe LLM Inference) runs E4B on the phone
  itself. To make that swap easy, the backend talks to the model through one small
  `ModelClient` interface — nothing else in the code knows it's Ollama.

## Data model
`Contact`
- id (uuid), name (str, required), raw_notes (str), created_at, updated_at
- enrichment (JSON, nullable) — matches ENRICHMENT.md schema
- enrichment_status: `none | pending | done | failed`
- enrichment_error (str, nullable), enriched_at (nullable), model_name (nullable)
- tags (list[str]) — user-editable; when the contact has no tags, enrichment copies
  `suggested_tags` into `tags`. Existing user tags are never overwritten.

## Success criteria for the prototype
- Capture → saved in < 1 second.
- Enrichment on the laptop in < 30 seconds for typical notes (≤ 300 words).
- Zero invented facts on the acceptance test set.
- Usable one-handed on a phone.
