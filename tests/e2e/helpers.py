"""Shared e2e state (kept out of conftest.py to avoid module-name clashes)."""
from __future__ import annotations

import os
from urllib.parse import urlparse

API = os.environ.get("ROLO_API", "http://localhost:8000").rstrip("/")
WEB = os.environ.get("ROLO_WEB", "https://localhost:5173").rstrip("/")
_LAN_IP = os.popen("ipconfig getifaddr en0 2>/dev/null").read().strip()  # this laptop, on the LAN
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]", urlparse(WEB).hostname, urlparse(API).hostname} | ({_LAN_IP} if _LAN_IP else set())

# Every request seen by any page, across the whole e2e session (for F1).
NETWORK_LOG: list[str] = []


def non_local_requests() -> list[str]:
    bad = []
    for u in NETWORK_LOG:
        p = urlparse(u)
        if p.scheme in ("data", "blob", "about", "chrome-extension"):
            continue
        if p.hostname not in LOCAL_HOSTS:
            bad.append(u)
    return bad
