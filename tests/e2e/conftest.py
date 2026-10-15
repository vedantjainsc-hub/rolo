"""Playwright fixtures: mobile viewports, network logging, screenshots."""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

import httpx
import pytest
from playwright.sync_api import sync_playwright

WEB = os.environ.get("ROLO_WEB", "https://localhost:5173").rstrip("/")
API = os.environ.get("ROLO_API", "http://localhost:8000").rstrip("/")
SHOTS = Path(__file__).resolve().parent.parent / "artifacts" / "screenshots"

VIEWPORTS = {
    "iphone-375x812": {"width": 375, "height": 812},
    "android-412x915": {"width": 412, "height": 915},
}

from e2e.helpers import NETWORK_LOG, LOCAL_HOSTS  # noqa: E402


@pytest.fixture(scope="session")
def web_url():
    try:
        httpx.get(WEB, timeout=5, verify=False).raise_for_status()
        httpx.get(f"{API}/api/health", timeout=5).raise_for_status()
    except httpx.HTTPError as e:
        pytest.skip(f"App not reachable ({e}). Start it with ./run.sh first.")
    return WEB


@pytest.fixture(scope="session")
def pw():
    with sync_playwright() as p:
        yield p


@pytest.fixture(scope="session")
def browser(pw):
    b = pw.chromium.launch()
    yield b
    b.close()


@pytest.fixture(params=list(VIEWPORTS), scope="module")
def viewport_name(request):
    return request.param


@pytest.fixture()
def context(browser, viewport_name, web_url):
    ctx = browser.new_context(
        viewport=VIEWPORTS[viewport_name],
        is_mobile=True,
        has_touch=True,
        device_scale_factor=2,
        base_url=web_url,
        accept_downloads=True,
        ignore_https_errors=True,
    )
    ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin=web_url)
    ctx.on("request", lambda r: NETWORK_LOG.append(r.url))
    yield ctx
    ctx.close()


@pytest.fixture()
def page(context):
    p = context.new_page()
    p.set_default_timeout(10_000)
    errors: list[str] = []
    p.on("pageerror", lambda e: errors.append(str(e)))
    p.page_errors = errors  # type: ignore[attr-defined]
    yield p


@pytest.fixture()
def shot(page, viewport_name):
    def _shot(name: str) -> str:
        d = SHOTS / viewport_name
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{name}.png"
        page.screenshot(path=str(path), full_page=True)
        return str(path)

    return _shot


@pytest.fixture()
def api():
    with httpx.Client(base_url=f"{API}/api", timeout=30) as c:
        yield c
