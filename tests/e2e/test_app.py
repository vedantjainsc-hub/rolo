"""End-to-end tests at 375x812 and 412x915 (every test runs at both viewports)."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import Page, expect

from e2e.audit import audit
from e2e.helpers import API

pytestmark = pytest.mark.e2e

ART = Path(__file__).resolve().parent.parent / "artifacts"
GOLDEN_NOTES = (
    "Priya Shah. Met at Fintech Forward. Runs partnerships at a payments startup, I think\n"
    "Stripe-adjacent. Wants intros to bank CTOs. Has a dog named Biscuit. Said to follow up after Diwali."
)
AUDITS: dict[str, dict] = {}


def _wait_done(api: httpx.Client, cid: str, timeout=150) -> dict:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        c = api.get(f"/contacts/{cid}").json()
        if c["enrichment_status"] != "pending":
            return c
        time.sleep(1)
    raise AssertionError("still pending")


@pytest.fixture(scope="module")
def enriched_id():
    """One enriched golden contact shared by the read-only card tests."""
    with httpx.Client(base_url=f"{API}/api", timeout=30) as api:
        r = api.post("/contacts", json={"name": "Priya Shah (e2e)", "raw_notes": GOLDEN_NOTES})
        cid = r.json()["id"]
        c = _wait_done(api, cid)
        if c["enrichment_status"] != "done":
            pytest.skip(f"golden enrichment did not finish: {c['enrichment_error']}")
        yield cid
        api.delete(f"/contacts/{cid}")


def record_audit(page: Page, viewport: str, screen: str) -> dict:
    a = audit(page)
    AUDITS[f"{viewport}/{screen}"] = a
    ART.mkdir(parents=True, exist_ok=True)
    (ART / "ui_audit.json").write_text(json.dumps(AUDITS, indent=2, ensure_ascii=False))
    return a


def assert_no_hscroll(a: dict):
    h = a["hscroll"]
    assert h["scrollWidth"] <= h["innerWidth"], f"horizontal scroll: {h}"


# ------------------------------------------------------------------ B1 / core flow / C3 / E5

def test_core_flow_capture_enrich_card(page: Page, api, shot, viewport_name):
    page.goto("/")
    expect(page.get_by_role("heading", name="Contacts")).to_be_visible()
    page.get_by_role("link", name="New contact").click()
    expect(page).to_have_url(re.compile(r"/new$"))
    expect(page.locator("#notes")).to_have_attribute(
        "placeholder",
        "Everything you remember — where you met, what they do, what they want, personal details, follow-ups.",
    )
    name = f"Priya Shah {viewport_name} {time.time_ns() % 100000}"
    page.fill("#name", name)
    page.fill("#notes", GOLDEN_NOTES)
    shot("02-capture-filled")
    t0 = time.monotonic()
    page.get_by_role("button", name="Save & Enrich").click()
    expect(page).to_have_url(re.compile(r"/c/[0-9a-f-]{36}$"))
    expect(page.get_by_text("Organising your notes on this device…")).to_be_visible()
    cid = page.url.rsplit("/", 1)[1]
    shot("03-card-pending")
    # B1: appears in list within 1 s, before enrichment finishes.
    page.get_by_role("button", name="Back").click()
    expect(page.get_by_role("heading", name=name)).to_be_visible(timeout=1000)
    elapsed = time.monotonic() - t0
    assert api.get(f"/contacts/{cid}").json()["enrichment_status"] == "pending", "should still be pending"
    expect(page.get_by_text("Organising notes…").first).to_be_visible()
    shot("04-list-pending")
    print(f"B1: saved and visible in list {elapsed:.2f}s after tapping Save & Enrich")
    # Back to the card; wait for enrichment.
    page.get_by_role("heading", name=name).click()
    expect(page.get_by_role("heading", name="Follow-ups")).to_be_visible(timeout=120_000)
    shot("05-card-done")
    # Section order per DESIGN.md
    headings = page.locator("main h2").all_inner_texts()
    order = ["Follow-ups", "What they want", "How I can help", "Role & company", "How we met", "Interests",
             "Personal", "Gaps & questions to ask", "Suggested opener", "Tags", "Original notes"]
    present = [h.strip() for h in headings if h.strip() in {o.upper() for o in order} | set(order)]
    norm = [p.title() if p.isupper() else p for p in present]
    idx = [next(i for i, o in enumerate(order) if o.lower() == n.lower()) for n in norm]
    assert idx == sorted(idx), f"section order wrong: {present}"
    # E5: Copy suggested opener
    opener = page.locator("blockquote").inner_text()
    page.get_by_role("button", name="Copy").click()
    expect(page.get_by_text("Copied to clipboard.")).to_be_visible()
    clip = page.evaluate("navigator.clipboard.readText()")
    assert clip == opener
    api.delete(f"/contacts/{cid}")
    # C3/C9 (v2), checked last so E5 above still runs: the hedged company carries the "maybe" chip.
    company_row = page.locator("dt", has_text="Company").locator("xpath=..")
    expect(company_row.get_by_text("maybe", exact=True)).to_be_visible()
    expect(company_row.locator("button[title=\"You weren't sure about this.\"]")).to_have_count(1)


# ------------------------------------------------------------------ B2 / B3 validation

def test_capture_validation(page: Page, api, shot):
    page.goto("/new")
    page.get_by_role("button", name="Save & Enrich").click()
    expect(page.locator("#name-error")).to_have_text("Enter a name.")
    page.fill("#name", "    ")
    page.get_by_role("button", name="Save & Enrich").click()
    expect(page.locator("#name-error")).to_have_text("Enter a name.")
    shot("06-capture-name-error")
    page.fill("#name", "Long Notes QA")
    page.fill("#notes", "a" * 10_001)
    expect(page.locator("#notes-error")).to_contain_text("10,001")
    expect(page.locator("#notes-error")).to_contain_text("10,000")
    n_before = len(api.get("/contacts").json()["contacts"])
    page.get_by_role("button", name="Save without enriching").click()
    page.wait_for_timeout(500)
    assert page.url.endswith("/new"), "10,001 chars must not save"
    assert len(api.get("/contacts").json()["contacts"]) == n_before
    shot("07-capture-notes-too-long")
    page.fill("#notes", "a" * 10_000)
    expect(page.locator("#notes-error")).to_have_count(0)
    page.get_by_role("button", name="Save without enriching").click()
    expect(page).to_have_url(re.compile(r"/c/"))
    cid = page.url.rsplit("/", 1)[1]
    c = api.get(f"/contacts/{cid}").json()
    assert len(c["raw_notes"]) == 10_000 and c["enrichment_status"] == "none"
    api.delete(f"/contacts/{cid}")


def test_server_side_validation_message_shown_inline(page: Page):
    """Bypass the client check by mocking a 400 from the server; message must land under the field."""
    page.route("**/api/contacts", lambda r: r.fulfill(status=400, content_type="application/json",
               body=json.dumps({"error": {"code": "validation_error", "message": "name: must be at most 120 characters"}}))
               if r.request.method == "POST" else r.continue_())
    page.goto("/new")
    page.fill("#name", "x")
    page.get_by_role("button", name="Save & Enrich").click()
    expect(page.locator("#name-error")).to_have_text("Name must be at most 120 characters.")


def test_server_required_message_wording(page: Page):
    page.route("**/api/contacts", lambda r: r.fulfill(status=400, content_type="application/json",
               body=json.dumps({"error": {"code": "validation_error", "message": "name: is required"}}))
               if r.request.method == "POST" else r.continue_())
    page.goto("/new")
    page.fill("#name", "x")
    page.get_by_role("button", name="Save & Enrich").click()
    expect(page.locator("#name-error")).to_have_text("Name is required.")


def test_emoji_counted_as_one_character(page: Page, api):
    """BUG-7 regression: contract v1.2 counts code points, so 10,000 emoji are allowed, 10,001 are not."""
    page.goto("/new")
    page.fill("#name", "Emoji Count QA")
    page.fill("#notes", "😀" * 10_001)
    expect(page.locator("#notes-count")).to_have_text("10,001 / 10,000")
    expect(page.locator("#notes-error")).to_contain_text("10,001")
    page.fill("#notes", "😀" * 10_000)
    expect(page.locator("#notes-count")).to_have_text("10,000 / 10,000")
    expect(page.locator("#notes-error")).to_have_count(0)
    page.get_by_role("button", name="Save without enriching").click()
    expect(page).to_have_url(re.compile(r"/c/"))
    cid = page.url.rsplit("/", 1)[1]
    assert len(api.get(f"/contacts/{cid}").json()["raw_notes"]) == 10_000
    api.delete(f"/contacts/{cid}")


# ------------------------------------------------------------------ B4 unicode

def test_unicode_display(page: Page, api, shot):
    name = "Ângela 李 प्रिया 🦄"
    notes = "नमस्ते 🙏 — café ☕, 東京で会った. 👩🏽‍💻"
    page.goto("/new")
    page.fill("#name", name)
    page.fill("#notes", notes)
    page.get_by_role("button", name="Save without enriching").click()
    expect(page.get_by_role("heading", level=1)).to_have_text(name)
    page.get_by_text("Original notes").click()
    expect(page.get_by_text(notes)).to_be_visible()
    shot("08-unicode-card")
    cid = page.url.rsplit("/", 1)[1]
    assert api.get(f"/contacts/{cid}").json()["name"] == name
    page.goto("/?q=" + "प्रिया")
    expect(page.get_by_role("heading", name=name)).to_be_visible()
    api.delete(f"/contacts/{cid}")


# ------------------------------------------------------------------ B6 save without enriching

def test_save_without_enriching(page: Page, api):
    reqs: list[str] = []
    page.on("request", lambda r: reqs.append(f"{r.method} {r.url}"))
    page.goto("/new")
    page.fill("#name", "No Enrich QA")
    page.fill("#notes", "Plays the oboe.")
    page.get_by_role("button", name="Save without enriching").click()
    expect(page.get_by_text("These notes haven't been organised yet.")).to_be_visible()
    cid = page.url.rsplit("/", 1)[1]
    page.wait_for_timeout(2000)
    c = api.get(f"/contacts/{cid}").json()
    assert c["enrichment_status"] == "none" and c["enrichment"] is None and c["model_name"] is None
    assert not any("/enrich" in r for r in reqs)
    api.delete(f"/contacts/{cid}")


# ------------------------------------------------------------------ C8 double tap

def test_double_tap_save_and_enrich_creates_one(page: Page, api):
    posts: list[str] = []
    page.on("request", lambda r: posts.append(r.url) if r.method == "POST" and r.url.endswith("/api/contacts") else None)
    page.goto("/new")
    name = f"DoubleTap {time.time_ns()}"
    page.fill("#name", name)
    page.fill("#notes", "Short note.")
    btn = page.get_by_role("button", name="Save & Enrich")
    btn.dblclick()
    page.wait_for_url(re.compile(r"/c/"))
    page.wait_for_timeout(500)
    assert len(posts) == 1, f"{len(posts)} create requests for a double tap"
    hits = [c for c in api.get("/contacts", params={"q": name}).json()["contacts"]]
    assert len(hits) == 1
    for h in hits:
        api.delete(f"/contacts/{h['id']}")


def test_reenrich_disabled_while_pending(page: Page, api):
    r = api.post("/contacts", json={"name": "Pending Menu QA", "raw_notes": "Collects stamps."})
    cid = r.json()["id"]
    page.goto(f"/c/{cid}")
    expect(page.get_by_text("Organising your notes on this device…")).to_be_visible()
    page.get_by_role("button", name="More actions").click()
    expect(page.get_by_role("menuitem", name="Enriching…")).to_be_disabled()
    page.keyboard.press("Escape")
    api.delete(f"/contacts/{cid}")


# ------------------------------------------------------------------ D1 search (rapid typing)

def test_rapid_search_typing_settles_on_last_query(page: Page, api):
    a = api.post("/contacts", json={"name": "Zanzibar Quill", "raw_notes": "loves kites", "enrich": False}).json()
    b = api.post("/contacts", json={"name": "Zanzibar Orchard", "raw_notes": "loves KITES and tea", "tags": ["Botany"], "enrich": False}).json()
    try:
        page.goto("/")
        s = page.locator("#search")
        s.click()
        page.keyboard.type("zanzibar orc", delay=15)
        for _ in range(3):
            page.keyboard.press("Backspace")
        page.keyboard.type("orch", delay=15)
        expect(page.get_by_role("heading", name="Zanzibar Orchard")).to_be_visible()
        expect(page.get_by_role("heading", name="Zanzibar Quill")).to_have_count(0)
        page.wait_for_timeout(800)
        expect(page.get_by_role("heading", name="Zanzibar Quill")).to_have_count(0)
        s.fill("KITES")
        expect(page.get_by_role("heading", name="Zanzibar Quill")).to_be_visible()
        expect(page.get_by_role("heading", name="Zanzibar Orchard")).to_be_visible()
        s.fill("botany")
        expect(page.get_by_role("heading", name="Zanzibar Orchard")).to_be_visible()
        expect(page.get_by_role("heading", name="Zanzibar Quill")).to_have_count(0)
        s.fill("qqqzzz-no-match")
        expect(page.get_by_text("No contacts match")).to_be_visible()
        page.get_by_role("button", name="Clear search").click()
        expect(page.get_by_role("heading", name="Zanzibar Quill")).to_be_visible()
    finally:
        api.delete(f"/contacts/{a['id']}")
        api.delete(f"/contacts/{b['id']}")


# ------------------------------------------------------------------ D2 edit, D3 delete

def test_edit_name_and_notes(page: Page, api, shot):
    c = api.post("/contacts", json={"name": "Edit Me", "raw_notes": "old notes", "enrich": False}).json()
    page.goto(f"/c/{c['id']}")
    page.get_by_role("button", name="More actions").click()
    page.get_by_role("menuitem", name="Edit").click()
    page.fill("#edit-name", "Edited Name")
    page.fill("#edit-notes", "new notes about sailing")
    shot("09-edit-form")
    page.get_by_role("button", name="Save changes").click()
    expect(page.get_by_role("heading", level=1)).to_have_text("Edited Name")
    got = api.get(f"/contacts/{c['id']}").json()
    assert got["name"] == "Edited Name" and got["raw_notes"] == "new notes about sailing"
    api.delete(f"/contacts/{c['id']}")


def test_delete_requires_confirmation(page: Page, api, shot):
    c = api.post("/contacts", json={"name": "Delete Me QA", "raw_notes": "x", "enrich": False}).json()
    page.goto(f"/c/{c['id']}")
    page.get_by_role("button", name="More actions").click()
    page.get_by_role("menuitem", name="Delete").click()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_be_visible()
    expect(dialog).to_contain_text("Delete Delete Me QA?")
    shot("10-delete-confirm")
    dialog.get_by_role("button", name="Cancel").click()
    expect(dialog).to_be_hidden()
    assert api.get(f"/contacts/{c['id']}").status_code == 200
    page.get_by_role("button", name="More actions").click()
    page.get_by_role("menuitem", name="Delete").click()
    page.get_by_role("dialog").get_by_role("button", name="Delete").click()
    expect(page).to_have_url(re.compile(r"/$"))
    expect(page.get_by_text("Deleted Delete Me QA.")).to_be_visible()
    expect(page.get_by_role("heading", name="Delete Me QA")).to_have_count(0)
    assert api.get(f"/contacts/{c['id']}").status_code == 404


def test_delete_while_enriching(page: Page, api):
    c = api.post("/contacts", json={"name": "Delete Pending QA", "raw_notes": "Enjoys chess."}).json()
    page.goto(f"/c/{c['id']}")
    expect(page.get_by_text("Organising your notes on this device…")).to_be_visible()
    page.get_by_role("button", name="More actions").click()
    page.get_by_role("menuitem", name="Delete").click()
    page.get_by_role("dialog").get_by_role("button", name="Delete").click()
    expect(page).to_have_url(re.compile(r"/$"))
    time.sleep(1)
    assert api.get(f"/contacts/{c['id']}").status_code == 404
    assert not page.page_errors


# ------------------------------------------------------------------ D4 export, F3 settings

def test_settings_and_export(page: Page, api, shot):
    page.goto("/")
    page.get_by_role("link", name="Settings").click()
    expect(page.get_by_text("Your notes never leave this device's network.")).to_be_visible()
    model = api.get("/health").json()["model"]
    if model["available"]:
        expect(page.get_by_text(f"{model['name']} running locally")).to_be_visible()
    shot("11-settings")
    with page.expect_download() as dl:
        page.get_by_role("button", name="Export JSON").click()
    path = dl.value.path()
    data = json.loads(Path(path).read_text())
    assert set(data) == {"exported_at", "contacts"}
    api_ids = {c["id"] for c in api.get("/export").json()["contacts"]}
    assert {c["id"] for c in data["contacts"]} == api_ids
    assert re.match(r"rolo-export-\d{4}-\d{2}-\d{2}\.json", dl.value.suggested_filename)
    expect(page.get_by_text(re.compile(r"Exported \d+ contacts?\."))).to_be_visible()


def test_settings_model_down_shows_fix_steps(page: Page, shot):
    page.route("**/api/health", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(
        {"status": "ok", "model": {"name": "gemma4:e4b", "available": False,
                                   "detail": "Ollama isn't reachable at http://localhost:11434. Start Ollama."}})))
    page.goto("/settings")
    expect(page.get_by_text("gemma4:e4b not available")).to_be_visible()
    expect(page.get_by_text("How to fix")).to_be_visible()
    shot("12-settings-model-down")


def test_settings_backend_down(page: Page):
    page.route(re.compile(r"^https?://[^/]+/api/"), lambda r: r.abort())
    page.goto("/settings")
    expect(page.get_by_text("Rolo server not reachable")).to_be_visible()


# ------------------------------------------------------------------ E4 empty / error / timeout states

def test_empty_state(page: Page, shot):
    page.route("**/api/contacts", lambda r: r.fulfill(status=200, content_type="application/json", body='{"contacts": []}'))
    page.goto("/")
    expect(page.get_by_text("No contacts yet.")).to_be_visible()
    expect(page.get_by_role("link", name="Add your first contact")).to_be_visible()
    shot("01-empty")


def test_list_error_state_and_retry(page: Page, shot):
    calls = {"n": 0}

    def handler(route):
        calls["n"] += 1
        if calls["n"] <= 2:
            return route.fulfill(status=500, content_type="application/json",
                                 body=json.dumps({"error": {"code": "internal_error", "message": "Something went wrong. Please try again."}}))
        return route.continue_()

    page.route("**/api/contacts", handler)
    page.goto("/")
    expect(page.get_by_text("Couldn't load contacts")).to_be_visible()
    shot("13-list-error")
    page.get_by_role("button", name="Try again").click()
    expect(page.get_by_text("Couldn't load contacts")).to_be_hidden()


def test_create_network_failure_keeps_notes(page: Page, shot):
    page.route("**/api/contacts", lambda r: r.abort() if r.request.method == "POST" else r.continue_())
    page.goto("/new")
    page.fill("#name", "Offline QA")
    page.fill("#notes", "Do not lose me")
    page.get_by_role("button", name="Save & Enrich").click()
    expect(page.get_by_text("Not saved")).to_be_visible()
    expect(page.locator("#notes")).to_have_value("Do not lose me")
    shot("14-create-failed")


def test_contact_not_found(page: Page):
    page.goto("/c/00000000-0000-0000-0000-000000000000")
    expect(page.get_by_text("This contact doesn't exist. It may have been deleted.")).to_be_visible()


def test_failed_enrichment_state_ui(page: Page, api, shot):
    c = api.post("/contacts", json={"name": "Failed UI QA", "raw_notes": "x", "enrich": False}).json()
    body = api.get(f"/contacts/{c['id']}").json()
    body.update(enrichment_status="failed",
                enrichment_error="The local model isn't running. Start Ollama and tap Retry.")
    page.route(f"**/api/contacts/{c['id']}", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(body)))
    page.goto(f"/c/{c['id']}")
    expect(page.get_by_text("Couldn't organise these notes")).to_be_visible()
    expect(page.get_by_text("The local model isn't running. Start Ollama and tap Retry.")).to_be_visible()
    expect(page.get_by_role("button", name="Retry")).to_be_visible()
    shot("15-card-failed")
    api.delete(f"/contacts/{c['id']}")


def test_polling_timeout_shows_retry(page: Page, api, shot):
    """Frontend must stop polling after 120 s and show a timeout message with Retry."""
    c = api.post("/contacts", json={"name": "Timeout QA", "raw_notes": "x", "enrich": False}).json()
    body = api.get(f"/contacts/{c['id']}").json()
    body["enrichment_status"] = "pending"
    page.clock.install()
    page.route(f"**/api/contacts/{c['id']}", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(body)))
    page.goto(f"/c/{c['id']}")
    expect(page.get_by_text("Organising your notes on this device…")).to_be_visible()
    for _ in range(85):  # 85 * 1.5 s = 127.5 s
        page.clock.run_for(1500)
    expect(page.get_by_text("Still organising")).to_be_visible()
    expect(page.get_by_role("button", name="Retry")).to_be_visible()
    shot("16-card-timeout")
    api.delete(f"/contacts/{c['id']}")


# ------------------------------------------------------------------ E1/E2/E3 audits on every screen

def _audit_screens(page: Page, api, viewport_name, enriched_id, shot):
    results = {}
    page.goto("/")
    page.wait_for_load_state("networkidle")
    results["contacts"] = record_audit(page, viewport_name, "contacts")
    page.goto("/new")
    results["capture"] = record_audit(page, viewport_name, "capture")
    page.get_by_role("button", name="Save & Enrich").click()
    results["capture-error"] = record_audit(page, viewport_name, "capture-error")
    page.goto(f"/c/{enriched_id}")
    expect(page.get_by_role("heading", name="Follow-ups")).to_be_visible()
    page.get_by_text("Original notes").click()
    results["card"] = record_audit(page, viewport_name, "card")
    shot("17-card-enriched-full")
    page.get_by_role("button", name="More actions").click()
    results["card-menu"] = record_audit(page, viewport_name, "card-menu")
    page.get_by_role("menuitem", name="Delete").click()
    results["delete-dialog"] = record_audit(page, viewport_name, "delete-dialog")
    page.get_by_role("dialog").get_by_role("button", name="Cancel").click()
    page.get_by_role("button", name="More actions").click()
    page.get_by_role("menuitem", name="Edit").click()
    results["edit"] = record_audit(page, viewport_name, "edit")
    page.goto("/settings")
    expect(page.get_by_text("Your notes never leave this device's network.")).to_be_visible()
    page.wait_for_load_state("networkidle")
    results["settings"] = record_audit(page, viewport_name, "settings")
    page.goto("/does-not-exist")
    results["not-found"] = record_audit(page, viewport_name, "not-found")
    return results


def test_ui_audit_no_horizontal_scroll(page: Page, api, viewport_name, enriched_id, shot):
    res = _audit_screens(page, api, viewport_name, enriched_id, shot)
    bad = {k: v["hscroll"] for k, v in res.items() if v["hscroll"]["scrollWidth"] > v["hscroll"]["innerWidth"]}
    assert not bad, f"horizontal scroll on: {bad}"


def test_ui_audit_touch_targets_and_input_fonts(page: Page, api, viewport_name, enriched_id, shot):
    res = _audit_screens(page, api, viewport_name, enriched_id, shot)
    small = {k: v["smallTargets"] for k, v in res.items() if v["smallTargets"]}
    fonts = {k: v["smallInputs"] for k, v in res.items() if v["smallInputs"]}
    assert not fonts, f"inputs under 16px: {fonts}"
    assert not small, f"touch targets under 44px: {json.dumps(small, indent=1, ensure_ascii=False)}"


def test_ui_audit_contrast(page: Page, api, viewport_name, enriched_id, shot):
    res = _audit_screens(page, api, viewport_name, enriched_id, shot)
    low = {k: v["lowContrast"] for k, v in res.items() if v["lowContrast"]}
    assert not low, f"WCAG AA contrast failures: {json.dumps(low, indent=1, ensure_ascii=False)}"


def test_design_tokens(page: Page):
    page.goto("/")
    bar = page.locator("header").first
    assert bar.evaluate("e => getComputedStyle(e).backgroundColor") == "rgb(11, 31, 58)"
    assert round(bar.locator("div").first.bounding_box()["height"]) == 56
    assert page.evaluate("getComputedStyle(document.body).backgroundColor") == "rgb(245, 247, 250)"
    fab = page.get_by_role("link", name="New contact").bounding_box()
    assert round(fab["width"]) == 56 and round(fab["height"]) == 56
    vw = page.viewport_size["width"]
    assert round(vw - (fab["x"] + fab["width"])) == 20
    font = page.evaluate("getComputedStyle(document.body).fontFamily")
    assert "Inter" in font
    title = page.get_by_role("heading", name="Contacts")
    assert title.evaluate("e => getComputedStyle(e).fontSize") == "28px"


# ------------------------------------------------------------------ E6 PWA manifest

def test_pwa_manifest_and_navy_icon(page: Page):
    page.goto("/")
    href = page.locator("link[rel=manifest]").get_attribute("href")
    m = page.evaluate(f"fetch('{href}').then(r => r.json())")
    assert m["name"] == "Rolo" and m["short_name"] == "Rolo"
    assert m["display"] == "standalone"
    assert m["theme_color"].lower() == "#0b1f3a"
    sizes = {i["sizes"] for i in m["icons"]}
    assert {"192x192", "512x512"} <= sizes
    # Sample icon pixels: corner should be navy.
    for icon in m["icons"] + [{"src": page.locator("link[rel=apple-touch-icon]").get_attribute("href")}]:
        px = page.evaluate("""async (src) => {
            const img = new Image(); img.src = src; await img.decode();
            const c = document.createElement('canvas'); c.width = img.width; c.height = img.height;
            const g = c.getContext('2d'); g.drawImage(img, 0, 0);
            return Array.from(g.getImageData(Math.floor(img.width*0.1), Math.floor(img.height*0.1), 1, 1).data);
        }""", icon["src"])
        assert px[:3] == [11, 31, 58], f"icon {icon['src']} sample {px} is not navy #0B1F3A"
