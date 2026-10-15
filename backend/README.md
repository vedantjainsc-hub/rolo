# Rolo backend

FastAPI + SQLModel (SQLite) + a local model through Ollama. Implements
`docs/API_CONTRACT.md` and `docs/ENRICHMENT.md`.

## Run

```bash
cd backend
./run_dev.sh                      # creates .venv on first run, then serves on 0.0.0.0:8000
```

Equivalent manual steps:

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```

`run_dev.sh` passes extra args through to uvicorn (e.g. `./run_dev.sh --reload`); `PORT=8011 ./run_dev.sh` changes the port.

## Config (env vars)

| Var | Default | Meaning |
|---|---|---|
| `ROLO_MODEL` | `gemma4:e4b` | Ollama model tag |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama base URL |
| `ROLO_DB_PATH` | `backend/data/rolo.db` | SQLite file (dir is created) |
| `ROLO_MODEL_TIMEOUT` | `90` | seconds per model call |

## Tests

```bash
cd backend && .venv/bin/python -m pytest      # tests_unit/, no Ollama needed
```

## Layout

- `app/main.py`: app, CORS (localhost:5173 + LAN :5173), routers under `/api`, startup reset of stuck `pending`
- `app/models.py`: `ContactRow` table, request/response schemas, lenient `Enrichment` validator
- `app/routes/`: `contacts.py`, `health.py`, `export.py`
- `app/enrichment/model_client.py`: `ModelClient` protocol + `OllamaClient` (the only Ollama-aware file)
- `app/enrichment/prompt.py`: prompt text and schema from ENRICHMENT.md, plus the JSON Schema sent as `format`
- `app/enrichment/service.py`: model call, one JSON retry, Pydantic validation, deterministic guards, persistence
- `app/errors.py`: `{ "error": { code, message } }` envelopes, 400 for validation, 500 without stack traces

## Behaviour notes

- Enrichment jobs go through one in-process queue with a single worker thread, so the model only
  ever gets one request at a time. Create, append and enrich commit their change first, then queue
  the job and return immediately. Queued jobs show as `pending`.
- A job reads the notes in a short DB session, closes it, calls the model without any session open,
  then writes the result in a new short session. Saves never wait on enrichment.
- Any unexpected crash inside a job marks the contact `failed` with a friendly message, so Retry works.
- `POST /enrich` claims the contact with one conditional UPDATE (`WHERE enrichment_status != 'pending'`),
  so if several calls arrive at once, only one gets 202 and the rest get 409.
- Every enrichment gets a job id. If a newer job starts (e.g. a note is appended while one is pending),
  the older result is thrown away.
- When enrichment finishes, `suggested_tags` become the contact's `tags` only if the user hasn't set any tags.
- Notes are never logged. Logs only show contact ids, note lengths, timings and error categories.
- If the notes are blank, the model is never called: create/append leave the status at `none`, and
  `POST /enrich` returns 400 `raw_notes: add some notes before enriching`.
- Validation messages always start with the field name (`name: is required`).

## v2: voice (speech helper)

`asr/` is a SwiftPM executable, `rolo-asr`, built on FluidAudio (pinned to exactly 0.17.7, Parakeet TDT v3).

```bash
backend/asr/build.sh          # build if sources changed + one-time warm-up; prints the binary path
backend/asr/build.sh --force  # rebuild and warm up again
```
- The first build takes about 3–5 minutes with the Command Line Tools; no Xcode is needed. Later runs are a no-op that takes under 1 s.
- The warm-up downloads the models (~1.3 GB) to `~/Library/Application Support/FluidAudio` the first time.
- Exit code 0 means voice is ready. The warm-up result is cached in `asr/.build/.warmup-ok`.
- The backend starts the helper in the background at startup. `/api/health` shows `asr.available: true` once it is ready, usually under 1 s after launch.
- If the binary or models are missing, the backend still runs: `/api/transcribe` returns 503 `asr_unavailable`.

| Var | Default | Meaning |
|---|---|---|
| `ROLO_ASR_BIN` | `backend/asr/.build/release/rolo-asr` | helper binary |
| `ROLO_ASR_MODELS_DIR` | `~/Library/Application Support/FluidAudio/Models/parakeet-tdt-0.6b-v3` | must exist, or voice is reported unavailable (nothing is downloaded at runtime) |
| `ROLO_ASR_TIMEOUT` | `20` | seconds per transcription |
