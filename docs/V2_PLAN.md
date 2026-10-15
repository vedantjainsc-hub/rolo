# Rolo v2 — Plan (web)

Decisions taken with the user on 2026-10-14:
- v2 ships as the **web app** (the native iPhone app is deferred).
- Labels: **Stated / Maybe / Inferred**.
- Follow-ups get a **mini calendar + Add to Calendar (.ics)**.
- Known v1 issues are fixed as part of v2.

## Scope
1. **Voice capture:** tap "🎤 Speak" at the top of Contacts, talk, and the words appear live. On Stop
   the contact is saved and enrichment starts. FluidAudio runs **on the laptop** as a small
   Swift helper; the phone browser streams audio to it over Wi-Fi via HTTPS. Spec: `VOICE.md`.
2. **Maybe label:** a third confidence level, plus an opener guard. Spec: `ENRICHMENT.md`.
3. **Follow-up dates:** the backend classifies each follow-up (exact / needs_date / none / past).
   The card shows a mini calendar, a "When should you follow up?" question with quick picks,
   and Add to Calendar. There is also an Upcoming strip. Spec: `API_CONTRACT.md` v2.0 and `DESIGN.md` v2.
4. **v1 known issues:**
   - BUG-14: past-date detection plus user confirmation.
   - BUG-15: follow-up scan guard.
   - BUG-16: opener guard.
   - BUG-17: Hindi residence cues.

## Feasibility (verified by lead)
- The FluidAudio CLI builds on this Mac with the Command Line Tools only (no Xcode), in ~4.5 min.
- The golden sample spoken by macOS `say` transcribed almost verbatim: "...She runs
  partnerships at a payment startup. I think Stripe adjacent... Follow up by Friday."
- It took 0.34 s warm for ~12 s of audio. Models are 1.3 GB in `~/Library/Application Support/FluidAudio`.

## Build order
| Phase | Who | What |
|---|---|---|
| 1 | lead | Specs: contract v2.0, ENRICHMENT v2, VOICE.md, DESIGN v2, ACCEPTANCE C9–C13/G/H ✅ |
| 2 | backend + frontend (parallel) | Backend: Swift helper + transcriber + `/api/transcribe`, maybe label, guards, follow-up classification, follow-up PATCH/.ics/upcoming, voice create. Frontend: Speak screen + recorder, maybe chip, calendar/question/chips, Upcoming strip, HTTPS-aware Vite config |
| 3 | lead | `run.sh`: cert generation, helper build/warm-up, HTTPS phone URL; end-to-end check |
| 4 | qa | Full v1 + v2 acceptance, with voice tested by feeding `say`-generated WAVs into the page (Chromium fake-audio flag) |
| 5 | all | Fix loop, max 3 rounds, then check in with the user. The user does the phone checks (A2, E6, G2) |

## Later (v3)
Native iPhone app with on-device FluidAudio and on-device Gemma, so no laptop is needed.
