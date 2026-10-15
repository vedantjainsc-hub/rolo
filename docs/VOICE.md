# Rolo — Voice Capture Spec (v2, web)

Talk instead of type. Speech-to-text runs **on the laptop** with
[FluidAudio](https://github.com/FluidInference/FluidAudio) (Parakeet TDT v3 on the Apple
Neural Engine). Audio goes only from the phone's browser to the laptop on your Wi-Fi, and
it is never stored.

## Components
```
Phone browser (HTTPS)                         Laptop
  mic → AudioWorklet → 16 kHz PCM16 WAV
  every ~1.5 s: POST /api/transcribe ───────▶ FastAPI ──stdin/stdout──▶ rolo-asr (Swift)
  live text ◀─────────────────────────────── { text }  ◀──────────────  FluidAudio AsrManager
  Stop → POST /api/contacts {source:"voice"} → enrichment (Gemma) as usual
```

### `backend/asr/` — `rolo-asr` helper (owned by backend-engineer)
- A small SwiftPM executable package that depends on FluidAudio, **pinned to `0.17.7`**
  (`.package(url: "https://github.com/FluidInference/FluidAudio.git", exact: "0.17.7")`).
  It builds with the Command Line Tools; Xcode isn't needed. The lead verified this.
- A long-running process that loads `AsrModels.downloadAndLoad(version: .v3)` once, then
  serves JSON lines:
  - in: `{"id": "<uuid>", "wav": "/abs/path.wav"}`
  - out: `{"id": "<uuid>", "text": "...", "duration_s": 3.2}` or `{"id": "...", "error": "..."}`
  - It prints `{"ready": true}` once the models are loaded.
- `backend/asr/build.sh`: `swift build -c release`, then runs the helper once in a
  `--warmup` mode so the models download (~1.3 GB, one time, to
  `~/Library/Application Support/FluidAudio`). It does nothing if the build is already up to date.
- The model download from Hugging Face at setup is the **only** network call besides
  Ollama's own `ollama pull`. Nothing at runtime goes off-machine.

### Backend side
- `app/voice/transcriber.py`: a `Transcriber` protocol plus `FluidAudioTranscriber`, which
  spawns the helper at startup in the background. It doesn't block startup, restarts the
  helper once if it crashes, and serialises requests with an asyncio lock.
  It is the ONLY code that knows about the helper, mirroring `ModelClient`.
- `POST /api/transcribe` validates the WAV header (16 kHz, mono, PCM16, ≤ 5 min), writes it to
  a temp file, transcribes it, deletes the file in `finally`, and returns the text. Timeout 20 s.
- If the helper binary is missing, or not yet `ready` → 503 `asr_unavailable`, with the
  message "Voice is still setting up on your laptop. Try again in a minute." or "Voice isn't
  set up. Run ./run.sh once on the laptop."
- Never log the transcript text; log only durations and lengths.

### Frontend side (owned by frontend-engineer)
- `src/voice/recorder.ts`: `getUserMedia({audio: true})` → AudioWorklet (inline module) →
  downsample to 16 kHz mono Float32 → keep a growing buffer → encode PCM16 WAV on demand.
  Max 5 minutes, with an auto-stop and a notice at that point.
- While recording: every 1.5 s, if no request is in flight, POST the whole buffer so far.
  Show the newest returned text, and ignore any response older than the one already shown.
- On Stop: one final transcription, then `POST /api/contacts` with
  `{ source: "voice", raw_notes: text, enrich: true }`, then navigate to `/c/:id`. The card
  shows the usual "Organising your notes…" state.
- If `asr.available` is false in `/api/health`, the Speak button shows a short reason and
  links to Settings. Typing always still works.
- Errors: mic permission denied → "Allow microphone access for this site in your browser
  settings." Not a secure context → "Voice needs the secure address: https://<laptop-ip>:5173".

### HTTPS (owned by lead, in `run.sh`)
Phone browsers only allow the mic on secure pages.
- `run.sh` creates a certificate in `certs/` (git-ignored). It uses **mkcert** if installed,
  which makes it trusted on the laptop. Otherwise it uses openssl with a self-signed
  certificate covering localhost and the laptop IP.
- Vite serves HTTPS when `ROLO_CERT`/`ROLO_KEY` are set; `run.sh` sets them.
  The phone URL becomes `https://<laptop-ip>:5173`.
- On the phone, the first visit shows a certificate warning. Tap "Show Details → visit this
  website" (Safari) or "Advanced → Proceed" (Chrome) once. For no warning at all, AirDrop
  mkcert's `rootCA.pem` to the phone and trust it (instructions in README).

## Languages
Parakeet TDT v3 covers English plus 24 European languages. **Hindi is not supported**, so
the Speak screen says "Voice works in English and major European languages."

## Performance targets
- Live text appears ≤ 2.5 s behind speech on the laptop.
- A 60-second recording transcribes in ≤ 2 s once warm.
