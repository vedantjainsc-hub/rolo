"""F1: runs after test_app.py (alphabetical) and checks every request the browser made."""
from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page

from e2e.helpers import NETWORK_LOG, non_local_requests

pytestmark = pytest.mark.e2e


def test_no_external_urls_in_page_assets(page: Page):
    page.goto("/")
    page.wait_for_load_state("networkidle")
    srcs = page.evaluate("[...document.scripts].map(s => s.src).filter(Boolean).concat([...document.querySelectorAll('link[href]')].map(l => l.href))")
    for s in srcs:
        assert re.match(r"^https?://(localhost|127\.0\.0\.1)(:\d+)?/", s), s


def test_no_non_local_requests():
    assert NETWORK_LOG, "no requests were captured; run together with test_app.py"
    bad = non_local_requests()
    assert not bad, f"requests to non-local hosts: {bad[:20]}"
    print(f"F1: {len(NETWORK_LOG)} browser requests, all to local hosts")
