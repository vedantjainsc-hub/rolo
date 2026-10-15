# Rolo QA tests

Everything QA owns lives here. The tests run against a **live** app, so start it first.

## One-time setup

```bash
cd tests
python3 -m venv .venv
.venv/bin/pip install pytest httpx playwright uvicorn starlette icalendar
.venv/bin/python -m playwright install chromium
```

## Start the app (use a throwaway DB)

```bash
# from the repo root
ROLO_DB_PATH=/tmp/rolo-qa.db ./run.sh > /tmp/rolo-qa.log 2>&1 &
# stop it later with:
pkill -TERM -f "bash ./run.sh"
```

Env vars the tests read: `ROLO_API` (default `http://localhost:8000`), `ROLO_WEB` (default `https://localhost:5173`; v2 serves HTTPS with a self-signed cert, so the e2e suite uses `ignore_https_errors`), `ROLO_RUN_LOG` (backend log, for the G8 log check), `ROLO_G7_WEB` (default `https://localhost:5174`), and `ROLO_SLOW=1` (enables the 5-minute auto-stop test).

## Run

```bash
cd tests
.venv/bin/python -m pytest api/test_contract.py -q          # every endpoint + error code (~2 s, a few model calls)
.venv/bin/python -m pytest api/test_enrichment_quality.py -v # golden + hallucination suite on the REAL model (~8 min)
.venv/bin/python -m pytest e2e -q                            # Playwright, 375x812 and 412x915 (~4 min)
.venv/bin/python -m pytest -m "not model" -q                 # everything except the slow model-quality tests
```

- `test_enrichment_quality.py` skips with a clear reason if `/api/health` reports the model unavailable.
  It runs one case at a time and writes each card to `artifacts/enrichment/<case>.json`.
- The e2e suite writes screenshots to `artifacts/screenshots/<viewport>/` and the per-screen
  touch-target, font and contrast audit to `artifacts/ui_audit.json`.
- `e2e/test_zz_network.py` (F1) checks every request the browser made during the e2e run, so run it
  together with `e2e/test_app.py`.

## Guard break-it tests (no model)

`guards/test_guard_regressions.py` imports backend code directly, so run it with the backend venv:

```bash
cd tests && ../backend/.venv/bin/python -m pytest guards -q -p no:cacheprovider
```

`tools/r3_probe.py` and `tools/r4_probe.py` re-run the round-3/round-4 real-model probes (dates, Tokyo/Delhi, legitimate-location and role cases)
and writes `artifacts/enrichment/r3/`.

## Voice tests (v2)

- `api/test_voice.py` posts WAVs straight to `/api/transcribe` (16 kHz mono PCM16).
- `e2e/test_voice_ui.py` launches Chromium with a fake mic that plays a WAV:
  `--use-fake-device-for-media-stream --use-file-for-fake-audio-capture=<ABSOLUTE path>%noloop`.
  The path must be absolute with no `..`, or Chrome records silence. The page WAVs are 48 kHz.
- Make new samples with `say -o x.aiff "..." && afconvert -f WAVE -d LEI16@16000 -c 1 x.aiff x.wav`
  (use `LEI16@48000` for the fake mic).
- G7 needs a second stack with no speech helper:
  `ROLO_ASR_BIN=/nonexistent ROLO_DB_PATH=/tmp/g7.db backend/.venv/bin/uvicorn app.main:app --port 8011` (from `backend/`) and
  `ROLO_BACKEND_URL=http://localhost:8011 ROLO_CERT=../certs/rolo.pem ROLO_KEY=../certs/rolo-key.pem ./node_modules/.bin/vite --port 5174`
  (from `frontend/`).

## Fixtures

`fixtures/hallucination.json` has 10 note sets built to tempt the model into inventing facts: famous names,
hedges, no company, no role, Hindi, Hinglish, very short, contradictory, and contact-info bait. Each case lists
the fields that must be null or `inferred`, plus terms that must never appear.

## Break-it tools

- `tools/fake_ollama.py PORT hang|garbage|error` is a fake Ollama used to simulate a hung model, a non-JSON
  reply, or a 500. Point a second backend at it, e.g.
  `OLLAMA_URL=http://127.0.0.1:11999 ROLO_DB_PATH=/tmp/x.db backend/.venv/bin/uvicorn app.main:app --port 8011`
  (run from `backend/`). Never use it for acceptance of model quality.
- `tools/c6_ui_check.py down|retry [id]` drives the C6 flow in the browser. Run `down` with the backend started
  with `OLLAMA_URL=http://localhost:1`, then `retry <id>` once the backend is restarted with the real Ollama.
