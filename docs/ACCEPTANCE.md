# Rolo — Acceptance Checklist (v1 MVP + v2)

qa-engineer verifies every item and records results in `docs/QA_REPORT.md`
(pass / fail / blocked, with evidence). MVP is done when all are PASS.

## A. Setup & run
- [ ] A1 `./run.sh` starts backend + frontend with one command on macOS.
- [ ] A2 App loads at `https://localhost:5173` and at `https://<laptop-ip>:5173` from a phone on the same Wi-Fi (v2: HTTPS only).
- [ ] A3 `GET /api/health` reports model available when the configured model (default `gemma4:e4b`) is pulled and Ollama is running.

## B. Capture & storage
- [ ] B1 Create contact with name + notes → appears in list within 1 s, before enrichment finishes.
- [ ] B2 Empty name rejected with a clear inline message; whitespace-only name rejected.
- [ ] B3 10,000-char notes accepted; 10,001 rejected with clear message.
- [ ] B4 Unicode (emoji, accents, Devanagari, CJK) saved and displayed correctly.
- [ ] B5 Data persists across backend restart.
- [ ] B6 "Save without enriching" saves with status `none` and no model call.

## C. Enrichment
- [ ] C1 Golden example (ENRICHMENT.md) produces a card containing all expected highlights.
- [ ] C2 Hallucination suite (tests/fixtures/hallucination.json, ≥ 8 cases incl. famous names) → zero invented role/company/contact_info.
- [ ] C3 Hedged statements ("I think…") are marked inferred and visibly flagged in the UI.
- [ ] C4 No email/phone/linkedin appears unless present in the notes.
- [ ] C5 Typical notes (≤ 300 words) enrich in < 30 s on the M-series laptop.
- [ ] C6 Ollama stopped → contact still saves; status `failed`; friendly message; Retry works after Ollama restarts.
- [ ] C7 Add a note to existing contact → appended with date → re-enrichment reflects it.
- [ ] C8 Calling enrich while pending returns 409; UI prevents double-tap.

## D. List, search, edit, delete
- [ ] D1 Search matches name, company, tag, and words in notes; case-insensitive.
- [ ] D2 Edit name/notes saves; Re-enrich updates the card.
- [ ] D3 Delete requires confirmation and removes the contact.
- [ ] D4 Export downloads valid JSON containing all contacts.

## E. UI / UX
- [ ] E1 All screens usable at 375×812 (iPhone) and 412×915 (Android) with no horizontal scroll.
- [ ] E2 Touch targets ≥ 44 px; inputs ≥ 16 px font.
- [ ] E3 Colors and type match DESIGN.md; text meets WCAG AA contrast.
- [ ] E4 Loading, empty, error, and timeout states exist for every async action.
- [ ] E5 Suggested opener has a working Copy button.
- [ ] E6 PWA manifest present; "Add to Home Screen" shows name and navy icon.

## F. Privacy & safety
- [ ] F1 No requests to any host other than the backend and localhost Ollama (verify in network log).
- [ ] F2 No stack traces or raw model output shown to the user.
- [ ] F3 Settings shows the privacy line and correct model status.

## v2 — must pass in addition to all of A–F

### C+. Enrichment v2
- [ ] C9 Hedged statements ("I think…", "maybe…") are labelled `maybe` (not `inferred`) and show the maybe chip.
- [ ] C10 Suggested opener never contains a `maybe`/`inferred` fact (hedged_everything case, 5/5 runs).
- [ ] C11 Follow-ups with timing in the notes are never dropped ("Send him the deck by Friday" → present, 3/3 runs).
- [ ] C12 Date classification: by Friday/tomorrow/in 3 days/Nov 2 → `exact` with correct date; after Diwali/in November → `needs_date`; since last Friday/May 5 recap → `past`; no timing → `none`.
- [ ] C13 Hindi residence cues keep the location (BUG-17 cases).

### G. Voice (laptop transcription, phone browser)
- [ ] G1 `./run.sh` builds the speech helper and downloads its models on first run; later runs start in < 10 s. `/api/health` reports `asr.available: true`.
- [ ] G2 The app is served over HTTPS at `https://<laptop-ip>:5173`, and the mic works in a browser on that address (phone check by the user).
- [ ] G3 Live text: while speaking a 30 s scripted sample (a macOS `say` WAV fed to the page), text updates at least every 2.5 s.
- [ ] G4 Accuracy: the golden sample spoken via `say` → transcript contains "Priya Shah", "Fintech Forward", "bank CTOs", "Friday".
- [ ] G5 Stop → contact saved with `source: voice` in < 2 s after the final text, card enriches, and the name is filled from speech (`needs_name` false).
- [ ] G6 No name said → contact shows "New contact" plus an "Add a name" prompt; editing the name clears it.
- [ ] G7 Helper not built / not ready → Speak shows a friendly reason, `/api/transcribe` → 503 `asr_unavailable`, typing still works.
- [ ] G8 Audio is never written to disk outside a temp file that is deleted (check the temp dir after 10 transcriptions), and no transcript text appears in logs.
- [ ] G9 Mic permission denied → clear message; recording auto-stops at 5 min.

### H. Follow-ups and calendar
- [ ] H1 Each `date_status` renders as DESIGN.md describes (calendar / question with chips / Add a date / already happened).
- [ ] H2 Picking a date (chip or calendar) persists, and survives re-enrichment of the same notes.
- [ ] H3 "No date" persists as dismissed, and the item is excluded from Upcoming.
- [ ] H4 `.ics` download is valid (parses with Python `icalendar`), is all-day, and has the right date and summary.
- [ ] H5 The Upcoming strip lists confirmed/exact items within 14 days, soonest first; tapping one opens the card.
- [ ] H6 Calendar and chips are usable at 375 px, with ≥ 44 px targets and no horizontal scroll.
