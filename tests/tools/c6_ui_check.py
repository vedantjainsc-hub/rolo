"""C6 UI driver. Phase 'down': backend runs with a dead OLLAMA_URL. Phase 'retry': real Ollama is back.
Usage: .venv/bin/python tools/c6_ui_check.py down|retry [contact_id]
"""
import json
import re
import sys
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

WEB = "https://localhost:5173"
SHOTS = Path(__file__).resolve().parent.parent / "artifacts" / "screenshots" / "c6"
SHOTS.mkdir(parents=True, exist_ok=True)
phase = sys.argv[1]

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 375, "height": 812}, is_mobile=True, has_touch=True, ignore_https_errors=True)
    if phase == "down":
        pg.goto(f"{WEB}/settings")
        expect(pg.get_by_text("gemma4:e4b not available")).to_be_visible(timeout=10000)
        pg.screenshot(path=str(SHOTS / "settings-ollama-down.png"), full_page=True)
        pg.goto(f"{WEB}/new")
        pg.fill("#name", "C6 Ollama Down")
        pg.fill("#notes", "Met at a robotics fair. Builds drones at Aerofly. Wants beta testers.")
        pg.get_by_role("button", name="Save & Enrich").click()
        expect(pg).to_have_url(re.compile(r"/c/"))
        cid = pg.url.rsplit("/", 1)[1]
        expect(pg.get_by_text("Couldn't organise these notes")).to_be_visible(timeout=20000)
        msg = pg.locator("[role=alert]").first.inner_text()
        pg.screenshot(path=str(SHOTS / "card-failed.png"), full_page=True)
        body = pg.locator("body").inner_text()
        assert "Traceback" not in body and "httpx" not in body and "Errno" not in body
        print(json.dumps({"cid": cid, "alert": msg}))
    else:
        cid = sys.argv[2]
        pg.goto(f"{WEB}/c/{cid}")
        pg.get_by_role("button", name="Retry").click()
        expect(pg.get_by_text("Organising your notes on this device…")).to_be_visible()
        expect(pg.get_by_role("heading", name="Role & company")).to_be_visible(timeout=120000)
        pg.screenshot(path=str(SHOTS / "card-after-retry.png"), full_page=True)
        print("retry ok:", pg.locator("main").inner_text()[:300].replace("\n", " | "))
    b.close()
