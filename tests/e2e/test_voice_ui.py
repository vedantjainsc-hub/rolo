"""Voice capture in the browser (G3, G5, G6, G7-UI, G9, G2-desktop), fed with `say` WAVs.

Chromium is launched with a fake microphone that plays a WAV file:
  --use-fake-device-for-media-stream --use-file-for-fake-audio-capture=<ABS path>%noloop
The path must be absolute with no "..", or Chrome records silence.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import Page, expect

from e2e.helpers import API, NETWORK_LOG, WEB

pytestmark = pytest.mark.e2e

VOICE = (Path(__file__).resolve().parent.parent / "fixtures" / "voice").resolve()
ART = Path(__file__).resolve().parent.parent / "artifacts"
SHOTS = ART / "screenshots" / "voice"
VIEW = {"width": 375, "height": 812}


def _launch(pw, wav: str | None, loop=False, extra=()):
    args = ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", *extra]
    if wav:
        p = str((VOICE / wav).resolve())
        assert ".." not in p and os.path.isabs(p)
        args.append(f"--use-file-for-fake-audio-capture={p}{'' if loop else '%noloop'}")
    return pw.chromium.launch(args=args)


def _page(browser, base=WEB, mic=True) -> Page:
    ctx = browser.new_context(viewport=VIEW, is_mobile=True, has_touch=True, device_scale_factor=2,
                              base_url=base, ignore_https_errors=True)
    if mic:
        ctx.grant_permissions(["microphone"], origin=base)
    ctx.on("request", lambda r: NETWORK_LOG.append(r.url))
    p = ctx.new_page()
    p.set_default_timeout(15_000)
    return p


def _shot(page: Page, name: str):
    SHOTS.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(SHOTS / f"{name}.png"), full_page=True)


@pytest.fixture(scope="module")
def asr_ok(web_url):
    h = httpx.get(f"{API}/api/health", timeout=10).json()
    if not h["asr"]["available"]:
        pytest.skip(f"speech helper unavailable: {h['asr']['detail']}")


@pytest.fixture()
def api():
    with httpx.Client(base_url=f"{API}/api", timeout=30) as c:
        yield c


def _wait(api, cid, timeout=150):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        c = api.get(f"/contacts/{cid}").json()
        if c["enrichment_status"] != "pending":
            return c
        time.sleep(1)
    raise AssertionError("still pending")


def _transcript(page: Page) -> str:
    return page.locator("h2:text-is('Transcript') + p").inner_text() if page.locator("h2:text-is('Transcript')").count() else ""


# ------------------------------------------------------------------ G3 live text cadence (30 s sample)

def test_g3_live_text_updates_every_2_5s(pw, asr_ok, api):
    b = _launch(pw, "script30_48k.wav")
    try:
        page = _page(b)
        page.goto("/")
        page.get_by_role("link", name="Speak").click()
        expect(page).to_have_url(re.compile(r"/speak$"))
        expect(page.get_by_text("Say their name, where you met, what they do, and anything to follow up on.")).to_be_visible()
        expect(page.get_by_text("Works in English and major European languages.")).to_be_visible()
        page.get_by_role("button", name="Start recording").click()
        expect(page.get_by_role("button", name="Stop and save")).to_be_visible()
        t0 = time.monotonic()
        changes: list[tuple[float, str]] = []
        last = ""
        while time.monotonic() - t0 < 33:
            txt = _transcript(page)
            if txt and txt != last and txt != "Listening…":
                changes.append((time.monotonic() - t0, txt))
                last = txt
            time.sleep(0.1)
        _shot(page, "g3-recording")
        expect(page.get_by_text(re.compile(r"00:3\d"))).to_be_visible()
        page.get_by_role("button", name="Stop and save").click()
        expect(page).to_have_url(re.compile(r"/c/[0-9a-f-]{36}$"), timeout=20_000)
        cid = page.url.rsplit("/", 1)[1]
        times = [t for t, _ in changes]
        speech_end = 31.3
        in_speech = [t for t in times if t <= speech_end + 2.5]
        gaps = [b2 - a for a, b2 in zip([0.0] + in_speech, in_speech)]
        (ART / "g3_live_text.json").write_text(json.dumps(
            {"updates": [{"t": round(t, 2), "chars": len(x)} for t, x in changes], "gaps": [round(g, 2) for g in gaps]}, indent=1))
        print(f"G3: {len(changes)} updates; first at {times[0]:.1f}s; max gap {max(gaps):.2f}s; final: {changes[-1][1]!r}")
        assert max(gaps) <= 2.5, f"live text gap {max(gaps):.2f}s > 2.5s: {gaps}"
        assert "kinetica" in changes[-1][1].lower() or "kinetica" in api.get(f"/contacts/{cid}").json()["raw_notes"].lower()
        api.delete(f"/contacts/{cid}")
    finally:
        b.close()


# ------------------------------------------------------------------ G5 stop -> saved < 2 s, enriched, name from speech

def test_g5_voice_contact_saved_enriched_named(pw, asr_ok, api):
    b = _launch(pw, "golden_48k.wav")
    try:
        page = _page(b)
        page.goto("/speak")
        page.get_by_role("button", name="Start recording").click()
        expect(page.get_by_role("button", name="Stop and save")).to_be_visible()
        page.wait_for_timeout(13_500)  # sample is 12.0 s
        final_live = _transcript(page)
        t0 = time.monotonic()
        page.get_by_role("button", name="Stop and save").click()
        expect(page).to_have_url(re.compile(r"/c/[0-9a-f-]{36}$"), timeout=10_000)
        saved_s = time.monotonic() - t0
        cid = page.url.rsplit("/", 1)[1]
        c = api.get(f"/contacts/{cid}").json()
        assert c["source"] == "voice"
        assert c["needs_name"] is True and c["name"] == "New contact"
        expect(page.get_by_text("Captured by voice")).to_be_visible()
        _shot(page, "g5-card-pending")
        print(f"G5: saved {saved_s:.2f}s after Stop; live text before stop: {final_live!r}")
        t1 = time.monotonic()
        c = _wait(api, cid)
        enrich_s = time.monotonic() - t1
        assert c["enrichment_status"] == "done", c["enrichment_error"]
        assert c["needs_name"] is False and c["name"].lower() == "priya shah", (c["name"], c["needs_name"])
        expect(page.get_by_role("heading", level=1)).to_have_text(re.compile("Priya Shah", re.I), timeout=10_000)
        expect(page.get_by_role("button", name="Add a name")).to_have_count(0)
        _shot(page, "g5-card-done")
        (ART / "g5_contact.json").write_text(json.dumps(c, indent=1, ensure_ascii=False))
        print(f"G5: enriched in {enrich_s:.1f}s; name={c['name']!r}")
        assert saved_s < 2.0, f"saved {saved_s:.2f}s after Stop"
        api.delete(f"/contacts/{cid}")
    finally:
        b.close()


# ------------------------------------------------------------------ G6 no name said

def test_g6_no_name_prompt_and_edit_clears_it(pw, asr_ok, api):
    b = _launch(pw, "noname_48k.wav")
    try:
        page = _page(b)
        page.goto("/speak")
        page.get_by_role("button", name="Start recording").click()
        page.wait_for_timeout(9_000)
        page.get_by_role("button", name="Stop and save").click()
        expect(page).to_have_url(re.compile(r"/c/[0-9a-f-]{36}$"), timeout=10_000)
        cid = page.url.rsplit("/", 1)[1]
        c = _wait(api, cid)
        assert c["enrichment_status"] == "done", c["enrichment_error"]
        assert c["needs_name"] is True and c["name"] == "New contact", (c["name"], c["needs_name"])
        page.reload()
        expect(page.get_by_role("heading", level=1)).to_have_text("New contact")
        expect(page.get_by_text("No name was heard. Add one so you can find this contact later.")).to_be_visible()
        _shot(page, "g6-add-a-name")
        page.get_by_role("button", name="Add a name").click()
        page.fill("#edit-name", "Hana Ito")
        page.get_by_role("button", name="Save changes").click()
        expect(page.get_by_role("heading", level=1)).to_have_text("Hana Ito")
        expect(page.get_by_role("button", name="Add a name")).to_have_count(0)
        c = api.get(f"/contacts/{cid}").json()
        assert c["needs_name"] is False and c["name"] == "Hana Ito"
        page.goto("/")
        expect(page.get_by_role("heading", name="Hana Ito")).to_be_visible()
        api.delete(f"/contacts/{cid}")
    finally:
        b.close()


# ------------------------------------------------------------------ G7 UI with the helper missing (backend on :8011, vite :5174)

G7_WEB = os.environ.get("ROLO_G7_WEB", "https://localhost:5174")


def test_g7_speak_shows_reason_typing_works(pw):
    try:
        h = httpx.get(f"{G7_WEB}/api/health", verify=False, timeout=5).json()
    except httpx.HTTPError:
        pytest.skip(f"G7 stack not running at {G7_WEB} (backend with ROLO_ASR_BIN=/nonexistent)")
    if h["asr"]["available"]:
        pytest.skip("G7 stack has a working helper")
    b = _launch(pw, None)
    try:
        page = _page(b, base=G7_WEB)
        page.goto("/")
        speak = page.get_by_role("button", name="Speak")
        expect(speak).to_be_disabled()
        expect(page.locator("#speak-reason")).to_contain_text("Run ./run.sh once to set up voice")
        _shot(page, "g7-contacts-speak-disabled")
        page.goto("/speak")
        expect(page.get_by_text("Voice isn't ready")).to_be_visible()
        expect(page.get_by_role("button", name="Start recording")).to_be_disabled()
        expect(page.get_by_role("link", name="Type instead")).to_be_visible()
        _shot(page, "g7-speak-not-ready")
        page.get_by_role("link", name="Type instead").click()
        page.fill("#name", "Typed While Voice Down")
        page.fill("#notes", "Still works.")
        page.get_by_role("button", name="Save without enriching").click()
        expect(page.get_by_role("heading", level=1)).to_have_text("Typed While Voice Down")
    finally:
        b.close()


# ------------------------------------------------------------------ G9 permission denied, 5-minute auto-stop

def test_g9_mic_permission_denied(pw):
    """Real browsers reject getUserMedia with NotAllowedError when the user denies the mic.
    Headless Chromium returns NotSupportedError instead, so the denial is simulated exactly."""
    b = _launch(pw, None)
    try:
        page = _page(b, mic=False)
        page.add_init_script("""
          navigator.mediaDevices.getUserMedia = () =>
            Promise.reject(new DOMException('Permission denied', 'NotAllowedError'));
        """)
        page.goto("/speak")
        page.get_by_role("button", name="Start recording").click()
        expect(page.get_by_text("Allow microphone access for this site in your browser settings.")).to_be_visible()
        expect(page.get_by_role("link", name="Type instead")).to_be_visible()
        _shot(page, "g9-denied")
    finally:
        b.close()


def test_g2_secure_context_desktop(pw):
    """G2 desktop part: the LAN HTTPS address serves the page and is a secure context after accepting the cert."""
    ip = os.popen("ipconfig getifaddr en0").read().strip()
    if not ip:
        pytest.skip("no LAN IP")
    b = _launch(pw, None)
    try:
        page = _page(b, base=f"https://{ip}:5173")
        page.goto("/speak")
        assert page.evaluate("window.isSecureContext") is True
        expect(page.get_by_role("button", name="Start recording")).to_be_enabled()
        page.get_by_role("button", name="Start recording").click()
        expect(page.get_by_role("button", name="Stop and save")).to_be_visible()
        page.get_by_role("link", name="Cancel").or_(page.get_by_role("button", name="Cancel")).first.click()
    finally:
        b.close()


def test_insecure_http_origin_explains(pw):
    """Not a secure context -> "Voice needs the secure address". Simulated via a non-localhost http origin is not
    possible here (Vite serves HTTPS only), so isSecureContext is forced false before load."""
    b = _launch(pw, None)
    try:
        page = _page(b)
        page.add_init_script("Object.defineProperty(window, 'isSecureContext', {get: () => false})")
        page.goto("/speak")
        expect(page.get_by_text(re.compile(r"Voice needs the secure address: https://localhost:5173"))).to_be_visible()
    finally:
        b.close()


@pytest.mark.skipif(not os.environ.get("ROLO_SLOW"), reason="5-minute real-time test; set ROLO_SLOW=1")
def test_g9_auto_stop_at_five_minutes(pw, asr_ok, api):
    b = _launch(pw, "script30_48k.wav", loop=True)
    try:
        page = _page(b)
        page.goto("/speak")
        page.get_by_role("button", name="Start recording").click()
        t0 = time.monotonic()
        expect(page).to_have_url(re.compile(r"/c/[0-9a-f-]{36}$"), timeout=330_000)
        dt = time.monotonic() - t0
        cid = page.url.rsplit("/", 1)[1]
        c = api.get(f"/contacts/{cid}").json()
        print(f"G9: auto-stopped and saved after {dt:.1f}s; notes {len(c['raw_notes'])} chars; source {c['source']}")
        assert 295 <= dt <= 320 and c["source"] == "voice"
        api.delete(f"/contacts/{cid}")
    finally:
        b.close()


@pytest.mark.parametrize("vp", [{"width": 375, "height": 812}, {"width": 412, "height": 915}], ids=["375", "412"])
def test_speak_screen_audit(pw, vp):
    """E1/E2/E3 on the new Speak screen, idle and while recording."""
    from e2e.audit import audit

    b = _launch(pw, "script30_48k.wav")
    try:
        ctx = b.new_context(viewport=vp, is_mobile=True, has_touch=True, device_scale_factor=2,
                            base_url=WEB, ignore_https_errors=True)
        ctx.grant_permissions(["microphone"], origin=WEB)
        ctx.on("request", lambda r: NETWORK_LOG.append(r.url))
        page = ctx.new_page()
        page.goto("/")
        speak = page.get_by_role("link", name="Speak")
        bb = speak.bounding_box()
        assert bb["height"] >= 44 and bb["width"] >= vp["width"] - 41, bb  # full width under search
        search_bb = page.locator("#search").bounding_box()
        assert bb["y"] > search_bb["y"], "Speak must sit under the search field"
        a0 = audit(page)
        page.goto("/speak")
        mic = page.get_by_role("button", name="Start recording")
        mb = mic.bounding_box()
        assert round(mb["width"]) == 96 and round(mb["height"]) == 96, mb
        assert mic.evaluate("e => getComputedStyle(e).backgroundColor") == "rgb(11, 31, 58)"
        a1 = audit(page)
        mic.click()
        page.wait_for_timeout(3500)
        a2 = audit(page)
        _shot(page, f"speak-recording-{vp['width']}")
        page.get_by_role("button", name="Cancel").click()
        for name, a in (("contacts", a0), ("speak-idle", a1), ("speak-recording", a2)):
            assert a["hscroll"]["scrollWidth"] <= a["hscroll"]["innerWidth"], (name, a["hscroll"])
            assert not a["smallTargets"], (name, a["smallTargets"])
            assert not a["smallInputs"], (name, a["smallInputs"])
            assert not a["lowContrast"], (name, a["lowContrast"])
    finally:
        b.close()
