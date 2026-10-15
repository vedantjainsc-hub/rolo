"""Shared fixtures for Rolo QA tests. Tests run against a live backend (ROLO_API)."""
from __future__ import annotations

import os
import time
import uuid

import httpx
import pytest

API = os.environ.get("ROLO_API", "http://localhost:8000").rstrip("/")
WEB = os.environ.get("ROLO_WEB", "https://localhost:5173").rstrip("/")


def _backend_up() -> bool:
    try:
        return httpx.get(f"{API}/api/health", timeout=5).status_code == 200
    except httpx.HTTPError:
        return False


@pytest.fixture(scope="session")
def api_url() -> str:
    if not _backend_up():
        pytest.skip(f"Backend not reachable at {API}. Start it with ./run.sh (or set ROLO_API).")
    return API


@pytest.fixture()
def client(api_url):
    with httpx.Client(base_url=f"{api_url}/api", timeout=30) as c:
        yield c


@pytest.fixture()
def make_contact(client):
    """Create contacts (enrich=False by default) and delete them after the test."""
    created: list[str] = []

    def _make(name: str | None = None, raw_notes: str = "QA notes", **extra):
        body = {"name": name or f"QA {uuid.uuid4().hex[:8]}", "raw_notes": raw_notes, "enrich": False}
        body.update(extra)
        r = client.post("/contacts", json=body)
        assert r.status_code == 201, r.text
        created.append(r.json()["id"])
        return r.json()

    yield _make
    for cid in created:
        client.delete(f"/contacts/{cid}")


def wait_until_settled(client: httpx.Client, cid: str, timeout: float = 150.0) -> dict:
    """Poll a contact until enrichment_status is no longer pending."""
    deadline = time.monotonic() + timeout
    while True:
        c = client.get(f"/contacts/{cid}").json()
        if c["enrichment_status"] != "pending":
            return c
        if time.monotonic() > deadline:
            raise AssertionError(f"contact {cid} still pending after {timeout}s")
        time.sleep(1.0)


def assert_api_error(r: httpx.Response, status: int, code: str, field: str | None = None) -> dict:
    assert r.status_code == status, f"expected {status}, got {r.status_code}: {r.text}"
    body = r.json()
    assert set(body) == {"error"}, body
    assert body["error"]["code"] == code, body
    assert isinstance(body["error"]["message"], str) and body["error"]["message"], body
    if field is not None:
        assert body["error"]["message"].startswith(f"{field}:"), body
    assert "Traceback" not in r.text
    return body["error"]
