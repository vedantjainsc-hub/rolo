# Rolo (working name)

A private, mobile-first rolodex. Type a name, brain-dump what you know, and a model
running on your own laptop turns it into a clean contact card.

## One-time setup (Mac)
1. **Ollama** — download from https://ollama.com/download, open it, then in Terminal:
   ```
   ollama pull gemma4:e4b
   ollama run gemma4:e4b "Say hello in five words"
   ```
   (About a 9.6 GB download. Set `ROLO_MODEL` to use a different model, e.g. `gemma4:e4b`.)
2. **Node 20+** — `brew install node` (or from nodejs.org).
3. **Python 3.11+** — `brew install python@3.12`.
4. **Claude Code** — install per https://docs.claude.com/en/docs/claude-code, then run
   `claude` once to sign in.

## Build it
```
cd rolo
claude
```
Paste the prompt in `KICKOFF.md`. The lead session coordinates three agents:
- **backend-engineer** — API, database, local-model enrichment
- **frontend-engineer** — the mobile web app
- **qa-engineer** — tests everything against `docs/ACCEPTANCE.md`

## Run it (after the build)
```
./run.sh
```
- Laptop: http://localhost:5173
- Phone (same Wi-Fi): the `http://<laptop-ip>:5173` URL that run.sh prints.
  In Safari/Chrome, use "Add to Home Screen" to make it feel like an app.

## Project map
```
CLAUDE.md                 rules every agent follows
KICKOFF.md                the prompt that starts the build
docs/SPEC.md              what and why
docs/API_CONTRACT.md      backend ⇄ frontend interface
docs/ENRICHMENT.md        prompt, schema, no-hallucination rules
docs/DESIGN.md            navy/white visual system
docs/ACCEPTANCE.md        definition of done
.claude/agents/           the three agent definitions
backend/ frontend/ tests/ created by the agents
```

## Roadmap after the MVP
1. Voice capture (Gemma 4 E4B accepts audio natively).
2. Follow-up reminders.
3. Native app with on-device inference (swap `OllamaClient` for an on-device client).
4. Optional, opt-in public-profile lookup via a search API.
