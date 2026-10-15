#!/usr/bin/env bash
# Start Rolo: checks Ollama, then runs the backend (:8000) and frontend (:5173) together.
# Ctrl+C stops both.
set -euo pipefail
cd "$(dirname "$0")"

MODEL="${ROLO_MODEL:-gemma4:e4b}"
OLLAMA_URL="${OLLAMA_URL:-http://localhost:11434}"
export ROLO_MODEL="$MODEL" OLLAMA_URL

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
warn() { printf '\033[33m! %s\033[0m\n' "$*"; }
fail() { printf '\033[31m✗ %s\033[0m\n' "$*"; exit 1; }

# --- Prerequisites ----------------------------------------------------------
command -v python3 >/dev/null || fail "Python 3.11+ not found. Install: brew install python@3.12"
command -v npm >/dev/null || fail "Node 20+ not found. Install: brew install node"

for port in 8000 5173; do
  if pid=$(lsof -nP -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null | head -1) && [ -n "$pid" ]; then
    fail "Port $port is already in use by: $(ps -o command= -p "$pid" | cut -c1-80) (pid $pid). Stop it and re-run."
  fi
done

# --- Ollama check (the app still runs without it; enrichment just fails gracefully) ---
if ! curl -sf -m 3 "$OLLAMA_URL/api/tags" >/dev/null; then
  warn "Ollama isn't running at $OLLAMA_URL. Notes will save, but enrichment is off until you open Ollama."
elif ! curl -sf -m 3 "$OLLAMA_URL/api/tags" | grep -q "\"name\":\"$MODEL\""; then
  warn "Model $MODEL isn't pulled. Run: ollama pull $MODEL"
else
  echo "✓ Ollama running with $MODEL"
fi

# --- Dependencies (first run only) -----------------------------------------
[ -d frontend/node_modules ] || (echo "Installing frontend dependencies…" && cd frontend && npm install --silent)

# --- Voice helper (FluidAudio). First run builds it (~5 min) and downloads models. ---
if [ -x backend/asr/build.sh ]; then
  if command -v swift >/dev/null; then
    echo "Preparing voice (first run takes a few minutes)…"
    ./backend/asr/build.sh || warn "Voice setup failed; typing still works. See the output above."
  else
    warn "Swift not found, so voice is off. Install: xcode-select --install"
  fi
fi

# --- HTTPS (phone browsers only allow the microphone on secure pages) ---------
IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)
mkdir -p certs
CERT=certs/rolo.pem KEY=certs/rolo-key.pem
if [ ! -f "$CERT" ] || [ ! -f certs/.ip ] || [ "$(cat certs/.ip)" != "$IP" ]; then
  echo "Creating HTTPS certificate for localhost${IP:+ and $IP}…"
  if command -v mkcert >/dev/null; then
    mkcert -cert-file "$CERT" -key-file "$KEY" localhost 127.0.0.1 ${IP:+"$IP"} >/dev/null 2>&1
  else
    SAN="DNS:localhost,IP:127.0.0.1${IP:+,IP:$IP}"
    openssl req -x509 -newkey rsa:2048 -nodes -days 825 -subj "/CN=Rolo local" \
      -addext "subjectAltName=$SAN" -addext "extendedKeyUsage=serverAuth" \
      -keyout "$KEY" -out "$CERT" >/dev/null 2>&1
  fi
  echo "$IP" > certs/.ip
fi
export ROLO_CERT="$PWD/$CERT" ROLO_KEY="$PWD/$KEY"

# --- Start both servers -----------------------------------------------------
pids=()
killtree() { local c; for c in $(pgrep -P "$1"); do killtree "$c"; done; kill "$1" 2>/dev/null || true; }
cleanup() {
  trap - INT TERM EXIT
  local p; for p in ${pids[@]+"${pids[@]}"}; do killtree "$p"; done
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

./backend/run_dev.sh --log-level warning &
pids+=($!)
(cd frontend && exec ./node_modules/.bin/vite --clearScreen false) &
pids+=($!)

# Wait for the backend to answer before printing URLs.
for _ in $(seq 1 60); do
  curl -sf -m 1 http://localhost:8000/api/health >/dev/null && break
  sleep 0.5
done
curl -sf -m 1 http://localhost:8000/api/health >/dev/null || fail "Backend didn't start. See the output above."

echo
bold "Rolo is running."
echo "  Laptop: https://localhost:5173"
if [ -n "$IP" ]; then
  echo "  Phone (same Wi-Fi): https://$IP:5173"
  echo "  First visit on the phone: accept the certificate warning once (needed for the mic)."
else
  warn "Couldn't find this laptop's Wi-Fi IP; the phone URL is unavailable."
fi
echo "  Press Ctrl+C to stop."
echo

wait
