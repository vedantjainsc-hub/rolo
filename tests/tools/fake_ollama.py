"""A fake Ollama for break-it tests (never used for acceptance of model quality).

Usage: .venv/bin/python tools/fake_ollama.py PORT MODE
MODE:
  hang    - /api/tags lists gemma4:e4b; /api/chat never answers
  garbage - /api/chat answers 200 with non-JSON message content
  error   - /api/chat answers 500 with an internal-looking error string
"""
import asyncio
import sys

import uvicorn
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

PORT, MODE = int(sys.argv[1]), sys.argv[2]


async def tags(_):
    return JSONResponse({"models": [{"name": "gemma4:e4b", "model": "gemma4:e4b"}]})


async def chat(_):
    if MODE == "hang":
        await asyncio.sleep(3600)
    if MODE == "garbage":
        return JSONResponse({"message": {"role": "assistant", "content": "Sure! Here is the card: <<not json>>"}})
    return JSONResponse({"error": "boom: internal stack at llama.cpp:123"}, status_code=500)


app = Starlette(routes=[Route("/api/tags", tags), Route("/api/chat", chat, methods=["POST"])])
uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
