# Rolo (placeholder name) — project rules for every agent

Rolo is a mobile-first personal rolodex. The user types a person's name, dumps
everything they know about them in free text, and a **local** LLM (Gemma 4 E4B via Ollama, model `gemma4:e4b`) turns those notes into a clean, structured contact card.

Read these before doing anything:
- `docs/SPEC.md` — what we're building and why (source of truth for scope)
- `docs/API_CONTRACT.md` — the ONLY interface between backend and frontend
- `docs/ENRICHMENT.md` — the enrichment prompt, JSON schema, and no-hallucination rules
- `docs/DESIGN.md` — visual system (navy / white / lots of space)
- `docs/ACCEPTANCE.md` — the checklist QA signs off against
- `docs/VOICE.md` — v2 voice capture (FluidAudio speech helper, HTTPS)
- `docs/V2_PLAN.md` — v2 scope and build order

## Team and ownership (strict)
| Agent | Owns (may write) | May read |
|---|---|---|
| backend-engineer | `backend/` | everything |
| frontend-engineer | `frontend/` | everything |
| qa-engineer | `tests/`, `docs/QA_REPORT.md` | everything |
| lead (main session) | `docs/`, `CLAUDE.md`, root files | everything |

- Never edit files outside your folder. If you need a change elsewhere, write it up
  in your final message and the lead will route it.
- `docs/API_CONTRACT.md` changes only through the lead. Both builders must match it exactly.

## Non-negotiables
1. **Everything runs locally.** No cloud APIs, no telemetry, no external analytics.
   The only network calls are browser → backend, backend → Ollama on localhost, and
   backend → the local speech helper. One-time setup downloads (`ollama pull`, FluidAudio
   models) are the only exceptions. Audio is never stored.
2. **Never invent facts about a person.** Enrichment may structure, summarise, and flag
   gaps. Hedged facts are `"maybe"`; the model's own readings are `"inferred"`. See ENRICHMENT.md.
3. **Keep it simple.** No auth, no cloud sync, no web scraping in the MVP.
4. **The app must still work if Ollama is down.** Saving notes never depends on the model;
   enrichment fails gracefully with a clear message and a retry.

## Stack
- Backend: Python 3.11+, FastAPI, SQLite (via SQLModel), httpx for Ollama.
- Model: Ollama at `http://localhost:11434`, model `gemma4:e4b` by default (env `ROLO_MODEL`; `qwen3:14b` also installed).
  The model name is never hard-coded in UI copy; show whatever the backend reports.
  Always send `"think": false` to Ollama (thinking models like qwen3 are otherwise slow).
- Frontend: React + Vite + TypeScript, Tailwind CSS, mobile-first, PWA manifest.
- Voice (v2): Swift helper `backend/asr/` (SwiftPM, FluidAudio 0.17.7, Parakeet TDT v3),
  driven by the backend over stdin/stdout. Built with Command Line Tools — no Xcode.
- Tests: pytest (backend), Playwright (end-to-end, mobile viewport).

## Ports
- Backend: `0.0.0.0:8000`
- Frontend dev server: `0.0.0.0:5173`, proxies `/api` → `http://localhost:8000`.
  HTTPS when `ROLO_CERT`/`ROLO_KEY` are set (run.sh does this; needed for the phone mic).
- Binding to 0.0.0.0 lets a phone on the same Wi-Fi open `https://<laptop-ip>:5173`.

## Definition of done for the MVP
Every item in `docs/ACCEPTANCE.md` passes, verified by qa-engineer, and
`./run.sh` starts the whole app with one command.
