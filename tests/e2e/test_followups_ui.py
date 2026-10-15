"""v2 follow-up UI (H1, H2-UI, H3-UI, H5-UI, H6) and maybe chip (C9-UI).

H1/H6 use a mocked contact so every date_status is present deterministically; the real
end-to-end path is covered by test_followups_real_flow at the bottom (needs the model).
"""
from __future__ import annotations

import json
import re
import time
import uuid
from datetime import date, timedelta

import httpx
import pytest
from playwright.sync_api import Page, expect

from e2e.audit import audit
from e2e.helpers import API

pytestmark = pytest.mark.e2e

TODAY = date.today()


def _fmt(d: date) -> str:  # "Fri 16 Oct" as in DESIGN.md
    return f"{d.strftime('%a')} {d.day} {d.strftime('%b')}"


def _contact() -> dict:
    cid = str(uuid.uuid4())
    fri = TODAY + timedelta(days=((4 - TODAY.weekday()) % 7) or 7)
    now = "2026-10-14T10:00:00.000000Z"
    fus = [
        {"action": "Send him the deck", "when_text": "by Friday", "suggested_date": fri.isoformat(),
         "date_status": "exact", "confidence": "stated", "confirmed_date": None, "dismissed": False},
        {"action": "Follow up about the lease", "when_text": "after Diwali", "suggested_date": None,
         "date_status": "needs_date", "confidence": "stated", "confirmed_date": None, "dismissed": False},
        {"action": "Get his phone number", "when_text": None, "suggested_date": None,
         "date_status": "none", "confidence": "stated", "confirmed_date": None, "dismissed": False},
        {"action": "Ask how the demo went", "when_text": "last Friday", "suggested_date": None,
         "date_status": "past", "confidence": "stated", "confirmed_date": None, "dismissed": False},
        {"action": "Invite him to the dinner", "when_text": "maybe in November", "suggested_date": None,
         "date_status": "needs_date", "confidence": "maybe", "confirmed_date": None, "dismissed": False},
    ]
    enr = {
        "person_name": None, "headline": "Founder at a lease-tech startup", "summary": "Met at the co-working space.",
        "role": {"value": "Founder", "confidence": "stated"},
        "company": {"value": "A lease-tech startup, possibly Leasely", "confidence": "maybe"},
        "location": {"value": None, "confidence": "stated"},
        "how_we_met": {"value": "Co-working space", "confidence": "stated"},
        "interests": [{"value": "Proptech", "confidence": "inferred"}],
        "what_they_want": [], "how_i_can_help": [], "personal_details": [],
        "follow_ups": fus, "gaps": ["Email or other contact details"], "questions_to_ask": [],
        "suggested_opener": "Great meeting you at the co-working space.", "suggested_tags": [],
        "contact_info": {"email": None, "phone": None, "linkedin": None},
    }
    return {"id": cid, "name": "Omar Haddad", "needs_name": False, "source": "typed", "raw_notes": "notes",
            "tags": [], "enrichment": enr, "enrichment_status": "done", "enrichment_error": None,
            "enriched_at": now, "model_name": "gemma4:e4b", "created_at": now, "updated_at": now}


@pytest.fixture()
def mocked(page: Page):
    c = _contact()
    patches: list[dict] = []

    def contact_route(route):
        req = route.request
        m = re.search(r"/follow-ups/(\d+)$", req.url)
        if req.method == "PATCH" and m:
            body = json.loads(req.post_data or "{}")
            patches.append({"index": int(m.group(1)), **body})
            fu = c["enrichment"]["follow_ups"][int(m.group(1))]
            if "confirmed_date" in body:
                fu["confirmed_date"] = body["confirmed_date"]
                if body["confirmed_date"] and "dismissed" not in body:
                    fu["dismissed"] = False
            if "dismissed" in body:
                fu["dismissed"] = body["dismissed"]
                if body["dismissed"] and "confirmed_date" not in body:
                    fu["confirmed_date"] = None
        return route.fulfill(status=200, content_type="application/json", body=json.dumps(c))

    page.route(re.compile(rf"/api/contacts/{c['id']}(/follow-ups/\d+)?$"), contact_route)
    return c, patches


def test_h1_each_status_renders(page: Page, mocked, shot):
    c, _ = mocked
    page.goto(f"/c/{c['id']}")
    sec = page.locator("section", has=page.get_by_role("heading", name="Follow-ups"))
    expect(sec).to_be_visible()
    rows = sec.locator("li")
    expect(rows).to_have_count(5)
    # exact -> date row + Add to Calendar + Change date; calendar expands on tap
    exact = rows.nth(0)
    fri = date.fromisoformat(c["enrichment"]["follow_ups"][0]["suggested_date"])
    expect(exact).to_contain_text("“by Friday”")
    expect(exact.get_by_role("button", name=re.compile(_fmt(fri)))).to_be_visible()
    expect(exact.get_by_role("link", name=re.compile("Add to Calendar"))).to_have_attribute(
        "href", re.compile(rf"/api/contacts/{c['id']}/follow-ups/0\.ics$"))
    expect(exact.get_by_role("button", name="Change date")).to_be_visible()
    exact.get_by_role("button", name=re.compile(_fmt(fri))).click()
    sel = exact.locator("button[aria-pressed=true]")
    expect(sel).to_have_attribute("data-ymd", fri.isoformat())
    assert "rgb(11, 31, 58)" in sel.locator("span").evaluate("e => getComputedStyle(e).backgroundColor")
    expect(exact.locator("button[aria-current=date]")).to_have_count(1 if fri.month == TODAY.month else 0)
    # needs_date -> question + 5 chips
    nd = rows.nth(1)
    expect(nd).to_contain_text("When should you follow up? You said “after Diwali”.")
    for chip in ("Next week", "In 2 weeks", "Next month", "Pick a date", "No date"):
        expect(nd.get_by_role("button", name=chip, exact=True)).to_be_visible()
    # none -> "Add a date" link
    none = rows.nth(2)
    expect(none.get_by_role("button", name="Add a date")).to_be_visible()
    expect(none.get_by_text("When should you follow up?")).to_have_count(0)
    # past -> "(already happened)" and no calendar/chips
    past = rows.nth(3)
    expect(past).to_contain_text("(already happened)")
    expect(past.get_by_role("button")).to_have_count(0)
    # maybe chip on the hedged follow-up and company (C9 UI)
    expect(rows.nth(4).get_by_text("maybe", exact=True)).to_be_visible()
    company = page.locator("dt", has_text="Company").locator("xpath=..")
    m = company.get_by_text("maybe", exact=True)
    expect(m).to_be_visible()
    shot("h1-followups-all-statuses")


def test_maybe_and_inferred_marker_styles(page: Page, mocked):
    c, _ = mocked
    page.goto(f"/c/{c['id']}")
    company = page.locator("dt", has_text="Company").locator("xpath=..")
    chip = company.get_by_role("button", name=re.compile("maybe"))
    style = chip.evaluate("""e => { const el = [...e.querySelectorAll('*')].find(x => x.textContent.trim() === 'maybe'
            && parseFloat(getComputedStyle(x).borderTopWidth) > 0) || e;
        const s = getComputedStyle(el);
        return {border: s.borderTopColor + ' ' + s.borderTopWidth, bg: s.backgroundColor, color: s.color, size: s.fontSize} }""")
    assert style["border"] == "rgb(184, 146, 90) 1px", style
    assert style["bg"] in ("rgba(0, 0, 0, 0)", "transparent"), style
    assert style["color"] == "rgb(30, 58, 95)" and style["size"] == "12px", style
    box = chip.bounding_box()
    assert box["width"] >= 44 - 0.5 and box["height"] >= 44 - 0.5, box
    chip.click()
    expect(page.locator("[role=tooltip]:not(.sr-only)", has_text="You weren't sure about this.")).to_be_visible()
    inferred = page.get_by_role("button", name=re.compile("inferred")).first
    inferred.click()
    expect(page.locator("[role=tooltip]:not(.sr-only)", has_text="Rolo's reading of your notes, not something you said.")).to_be_visible()
    print("maybe chip style:", style)


def test_h2_chip_pick_patches_and_toasts_with_undo(page: Page, mocked):
    c, patches = mocked
    page.goto(f"/c/{c['id']}")
    nd = page.locator("section", has=page.get_by_role("heading", name="Follow-ups")).locator("li").nth(1)
    nm = TODAY + timedelta(days=7 - TODAY.weekday())
    expect(nd.get_by_role("button", name="Next week")).to_have_attribute("title", _fmt(nm))
    nd.get_by_role("button", name="In 2 weeks").click()
    want = (TODAY + timedelta(days=14))
    expect(page.get_by_text(f"Follow-up set for {_fmt(want)}")).to_be_visible()
    assert patches[-1] == {"index": 1, "confirmed_date": want.isoformat(), "dismissed": False}
    page.get_by_role("button", name="Undo").click()
    expect(page.get_by_text("Undone.", exact=True)).to_be_visible()
    assert patches[-1] == {"index": 1, "confirmed_date": None, "dismissed": False}
    # Pick a date -> calendar -> choose a day
    nd.get_by_role("button", name="Pick a date").click()
    target = TODAY + timedelta(days=5)
    if target.month != TODAY.month:
        nd.get_by_role("button", name="Next month").click()
    nd.locator(f"button[data-ymd='{target.isoformat()}']").click()
    expect(page.get_by_text(f"Follow-up set for {_fmt(target)}")).to_be_visible()
    assert patches[-1]["confirmed_date"] == target.isoformat()
    # past days are disabled
    if TODAY.day > 1:
        nd2 = page.locator("section", has=page.get_by_role("heading", name="Follow-ups")).locator("li").nth(4)
        nd2.get_by_role("button", name="Pick a date").click()
        expect(nd2.locator(f"button[data-ymd='{(TODAY - timedelta(days=1)).isoformat()}']")).to_be_disabled()


def test_h3_no_date_dismisses(page: Page, mocked):
    c, patches = mocked
    page.goto(f"/c/{c['id']}")
    nd = page.locator("section", has=page.get_by_role("heading", name="Follow-ups")).locator("li").nth(1)
    nd.get_by_role("button", name="No date").click()
    expect(page.get_by_text("No date for this follow-up.")).to_be_visible()
    assert patches[-1] == {"index": 1, "confirmed_date": None, "dismissed": True}
    expect(nd.get_by_text("No date", exact=True)).to_be_visible()
    expect(nd.get_by_role("button", name="Add a date")).to_be_visible()


def test_h5_upcoming_strip(page: Page, mocked):
    c, _ = mocked
    d1, d2, d3, d4 = (TODAY + timedelta(days=n) for n in (1, 2, 5, 9))
    items = [
        {"contact_id": c["id"], "contact_name": "Omar Haddad", "index": 0, "action": "Send him the deck", "date": d1.isoformat()},
        {"contact_id": c["id"], "contact_name": "Omar Haddad", "index": 1, "action": "Follow up about the lease", "date": d2.isoformat()},
        {"contact_id": c["id"], "contact_name": "Ana Lopez", "index": 0, "action": "Call", "date": d3.isoformat()},
        {"contact_id": c["id"], "contact_name": "Zed", "index": 0, "action": "Fourth", "date": d4.isoformat()},
    ]
    page.route("**/api/follow-ups/upcoming*", lambda r: r.fulfill(status=200, content_type="application/json",
                                                                   body=json.dumps({"items": items})))
    page.goto("/")
    strip = page.locator("section", has=page.get_by_role("heading", name="Upcoming"))
    expect(strip).to_be_visible()
    links = strip.get_by_role("link")
    expect(links).to_have_count(3)
    expect(links.nth(0)).to_contain_text(f"{_fmt(d1)}")
    expect(links.nth(0)).to_contain_text("Omar Haddad — Send him the deck")
    expect(strip).not_to_contain_text("Fourth")
    links.nth(0).click()
    expect(page).to_have_url(re.compile(rf"/c/{c['id']}$"))


def test_h5_upcoming_hidden_when_empty(page: Page):
    page.route("**/api/follow-ups/upcoming*", lambda r: r.fulfill(status=200, content_type="application/json", body='{"items": []}'))
    page.goto("/")
    expect(page.get_by_role("heading", name="Contacts")).to_be_visible()
    page.wait_for_timeout(500)
    expect(page.get_by_role("heading", name="Upcoming")).to_have_count(0)


def test_h6_calendar_and_chips_audit(page: Page, mocked, viewport_name, shot):
    c, _ = mocked
    page.goto(f"/c/{c['id']}")
    sec = page.locator("section", has=page.get_by_role("heading", name="Follow-ups"))
    fri = date.fromisoformat(c["enrichment"]["follow_ups"][0]["suggested_date"])
    sec.locator("li").nth(0).get_by_role("button", name=re.compile(_fmt(fri))).click()
    sec.locator("li").nth(1).get_by_role("button", name="Pick a date").click()
    a = audit(page)
    shot("h6-calendar-open")
    assert a["hscroll"]["scrollWidth"] <= a["hscroll"]["innerWidth"], a["hscroll"]
    assert not a["smallTargets"], a["smallTargets"]
    assert not a["lowContrast"], a["lowContrast"]
    cells = sec.locator("button[data-ymd]").all()
    for cell in cells[:10]:
        bb = cell.bounding_box()
        assert bb["height"] >= 44 - 0.5 and bb["width"] >= 44 - 0.5, bb


# ------------------------------------------------------------------ real end-to-end (needs the model)

def test_followups_real_flow(page: Page, api):
    h = api.get("/health").json()
    if not h["model"]["available"]:
        pytest.skip("model unavailable")
    notes = "Met Lena at a meetup. Send her the deck tomorrow. Follow up after the conference about hiring."
    r = api.post("/contacts", json={"name": "Lena Upcoming QA", "raw_notes": notes}).json()
    cid = r["id"]
    try:
        end = time.monotonic() + 150
        while api.get(f"/contacts/{cid}").json()["enrichment_status"] == "pending" and time.monotonic() < end:
            time.sleep(1)
        page.goto("/")
        strip = page.locator("section", has=page.get_by_role("heading", name="Upcoming"))
        row = strip.get_by_role("link", name=re.compile("Lena Upcoming QA"))
        expect(row).to_be_visible()
        expect(row).to_contain_text(_fmt(TODAY + timedelta(days=1)))
        row.click()
        expect(page).to_have_url(re.compile(rf"/c/{cid}$"))
        conf = page.locator("section", has=page.get_by_role("heading", name="Follow-ups")).locator("li", has_text="conference")
        conf.get_by_role("button", name="Next week").click()
        expect(page.get_by_text(re.compile("Follow-up set for"))).to_be_visible()
        page.reload()
        expect(conf.get_by_role("link", name=re.compile("Add to Calendar"))).to_be_visible()
        with page.expect_download() as dl:
            conf.get_by_role("link", name=re.compile("Add to Calendar")).click()
        assert dl.value.suggested_filename == "rolo-followup.ics"
        from icalendar import Calendar
        ev = Calendar.from_ical(open(dl.value.path(), "rb").read()).walk("VEVENT")[0]
        next_monday = TODAY + timedelta(days=7 - TODAY.weekday())  # DESIGN v2: "Next week" = next Monday
        assert ev.decoded("DTSTART").isoformat() == next_monday.isoformat()
    finally:
        api.delete(f"/contacts/{cid}")
