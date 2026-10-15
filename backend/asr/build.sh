#!/usr/bin/env bash
# Build the rolo-asr speech helper and make sure its models are downloaded.
# Safe to run every time: the build is incremental and the warm-up is skipped when
# the binary is newer than the sources and a previous warm-up succeeded.
#   ./build.sh            build if needed + warm up once
#   ./build.sh --force    rebuild and warm up again
# Prints the binary path on the last line. Exit code != 0 means voice isn't available.
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v swift >/dev/null 2>&1; then
  echo "swift not found. Install the Command Line Tools: xcode-select --install" >&2
  exit 1
fi

BIN="$(pwd)/.build/release/rolo-asr"
STAMP="$(pwd)/.build/.warmup-ok"
FORCE="${1:-}"

needs_build=0
if [ "$FORCE" = "--force" ] || [ ! -x "$BIN" ]; then
  needs_build=1
elif [ -n "$(find Package.swift Package.resolved Sources -newer "$BIN" 2>/dev/null | head -1)" ]; then
  needs_build=1
fi

if [ "$needs_build" = 1 ]; then
  echo "Building rolo-asr (first time takes ~5 minutes)..." >&2
  swift build -c release --product rolo-asr >&2
  rm -f "$STAMP"
fi

if [ ! -f "$STAMP" ] || [ "$FORCE" = "--force" ]; then
  echo "Warming up speech models (first time downloads ~1.3 GB)..." >&2
  out="$("$BIN" --warmup 2>/dev/null | tail -1)"
  case "$out" in
    *'"ready":true'*) touch "$STAMP" ;;
    *) echo "Speech warm-up failed: $out" >&2; exit 1 ;;
  esac
fi

echo "$BIN"
