"""v2 follow-ups against the real model: classification (C11/C12), PATCH choices (H2/H3),
.ics (H4), upcoming (H5). One enriched contact is shared by the module."""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest
from icalendar import Calendar

from conftest import assert_api_error, wait_until_settled

pytestmark = pytest.mark.model
ART = Path(__file__).resolve().parent.parent / "artifacts" / "enrichment" / "v2"
NOTES = (
    "Omar Haddad. Met at the co-working space. Send him the deck by Friday. "
    "Follow up after Diwali about the lease. Ask him how the demo went last Friday. "
    "Get his phone number sometime."
)
# Same contact without the past "last Friday" sentence, so H-tests have an exact item even while BUG-V2-2 is open.
NOTES_NO_PAST = (
    "Omar Haddad. Met at the co-working space. Send him the deck by Friday. "
    "Follow up after Diwali about the lease. Get his phone number sometime."
)


@pytest.fixture(scope="module", params=[NOTES, NOTES_NO_PAST], ids=["with_past", "no_past"])
def fu_contact(api_url, request):
    with httpx.Client(base_url=f"{api_url}/api", timeout=30) as c:
        h = c.get("/health").json()
        if not h["model"]["available"]:
            pytest.skip(f"model unavailable: {h['model']['detail']}")
        r = c.post("/contacts", json={"name": "Omar Haddad", "raw_notes": request.param})
        got = wait_until_settled(c, r.json()["id"])
        ART.mkdir(parents=True, exist_ok=True)
        (ART / f"followups_contact_{request.param_index}.json").write_text(json.dumps(got, indent=1, ensure_ascii=False))
        assert got["enrichment_status"] == "done", got["enrichment_error"]
        yield got
        c.delete(f"/contacts/{got['id']}")


def _fus(client, cid):
    return client.get(f"/contacts/{cid}").json()["enrichment"]["follow_ups"]


def _find(fus, word):
    for i, f in enumerate(fus):
        if word in f"{f['action']} {f['when_text'] or ''}".lower():
            return i, f
    raise AssertionError(f"no follow-up mentioning {word!r}: {[(f['action'], f['when_text']) for f in fus]}")


def test_shape_and_classification(client, fu_contact):
    fus = _fus(client, fu_contact["id"])
    for f in fus:
        assert set(f) == {"action", "when_text", "suggested_date", "date_status", "confidence", "confirmed_date", "dismissed"}
        assert f["date_status"] in ("exact", "needs_date", "none", "past")
        assert f["confidence"] in ("stated", "maybe", "inferred")
        if f["date_status"] != "exact":
            assert f["suggested_date"] is None
    _, fri = _find(fus, "deck")  # C11: "Send him the deck by Friday" must not be dropped
    assert fri["date_status"] == "exact" and fri["suggested_date"] == _next_weekday(4).isoformat(), fri
    _, diwali = _find(fus, "diwali")
    assert diwali["date_status"] == "needs_date", diwali
    past = [f for f in fus if "demo" in f["action"].lower()]
    if past:  # the model may or may not list a past event as a follow-up
        assert past[0]["date_status"] == "past", past[0]


def _next_weekday(wd: int) -> date:
    t = date.today()
    return t + timedelta(days=((wd - t.weekday()) % 7) or 7)


def _exact(fus):
    for i, f in enumerate(fus):
        if f["date_status"] == "exact" and not f["dismissed"]:
            return i, f
    pytest.skip(f"no exact follow-up to test with: {[(f['action'], f['date_status']) for f in fus]}")


def test_h4_ics_valid_all_day(client, fu_contact):
    cid = fu_contact["id"]
    i, fri = _exact(_fus(client, cid))
    r = client.get(f"/contacts/{cid}/follow-ups/{i}.ics")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/calendar")
    assert 'filename="rolo-followup.ics"' in r.headers["content-disposition"]
    cal = Calendar.from_ical(r.content)
    ev = [c for c in cal.walk() if c.name == "VEVENT"]
    assert len(ev) == 1
    ev = ev[0]
    start = ev.decoded("DTSTART")
    assert type(start) is date, "must be all-day (VALUE=DATE)"
    assert start.isoformat() == fri["suggested_date"]
    assert ev.decoded("DTEND") == start + timedelta(days=1)
    assert str(ev["SUMMARY"]) == f"Follow up: Omar Haddad — {fri['action']}"
    assert fri["when_text"] in str(ev["DESCRIPTION"])
    (ART / "followup.ics").write_bytes(r.content)


def test_h4_ics_needs_a_date(client, fu_contact):
    cid = fu_contact["id"]
    i, _ = _find(_fus(client, cid), "diwali")
    e = assert_api_error(client.get(f"/contacts/{cid}/follow-ups/{i}.ics"), 400, "validation_error", "date")
    assert e["message"] == "date: pick a date first"


def test_h2_confirm_date_persists_and_survives_reenrichment(client, fu_contact):
    cid = fu_contact["id"]
    i, _ = _find(_fus(client, cid), "diwali")
    pick = (date.today() + timedelta(days=10)).isoformat()
    r = client.patch(f"/contacts/{cid}/follow-ups/{i}", json={"confirmed_date": pick})
    assert r.status_code == 200, r.text
    f = r.json()["enrichment"]["follow_ups"][i]
    assert f["confirmed_date"] == pick and f["dismissed"] is False
    assert _fus(client, cid)[i]["confirmed_date"] == pick
    ics = client.get(f"/contacts/{cid}/follow-ups/{i}.ics")
    assert ics.status_code == 200 and Calendar.from_ical(ics.content).walk("VEVENT")[0].decoded("DTSTART").isoformat() == pick
    # upcoming includes it
    items = client.get("/follow-ups/upcoming").json()["items"]
    assert any(x["contact_id"] == cid and x["index"] == i and x["date"] == pick for x in items)
    # re-enrich the same notes
    assert client.post(f"/contacts/{cid}/enrich").status_code == 202
    assert_api_error(client.patch(f"/contacts/{cid}/follow-ups/{i}", json={"dismissed": True}), 409, "enrichment_in_progress")
    after = wait_until_settled(client, cid)
    (ART / "followups_after_reenrich.json").write_text(json.dumps(after, indent=1, ensure_ascii=False))
    j, f2 = _find(after["enrichment"]["follow_ups"], "diwali")
    assert f2["confirmed_date"] == pick, f"choice lost after re-enrichment: {f2}"


def test_h3_dismiss_persists_and_excluded_from_upcoming(client, fu_contact):
    cid = fu_contact["id"]
    i, fri = _find(_fus(client, cid), "diwali")
    r = client.patch(f"/contacts/{cid}/follow-ups/{i}", json={"dismissed": True})
    assert r.status_code == 200
    f = r.json()["enrichment"]["follow_ups"][i]
    assert f["dismissed"] is True and f["confirmed_date"] is None
    items = client.get("/follow-ups/upcoming").json()["items"]
    assert not any(x["contact_id"] == cid and x["index"] == i for x in items)
    assert_api_error(client.get(f"/contacts/{cid}/follow-ups/{i}.ics"), 400, "validation_error", "date")
    # confirming clears dismissed
    pick = (date.today() + timedelta(days=3)).isoformat()
    f = client.patch(f"/contacts/{cid}/follow-ups/{i}", json={"confirmed_date": pick}).json()["enrichment"]["follow_ups"][i]
    assert f["confirmed_date"] == pick and f["dismissed"] is False
    # both sent
    f = client.patch(f"/contacts/{cid}/follow-ups/{i}", json={"confirmed_date": pick, "dismissed": True}).json()["enrichment"]["follow_ups"][i]
    assert f["confirmed_date"] == pick and f["dismissed"] is True
    # reset to model suggestion
    f = client.patch(f"/contacts/{cid}/follow-ups/{i}", json={"confirmed_date": None, "dismissed": False}).json()["enrichment"]["follow_ups"][i]
    assert f["confirmed_date"] is None and f["dismissed"] is False


def test_h5_upcoming_window_and_order(client, fu_contact):
    cid = fu_contact["id"]
    fus = _fus(client, cid)
    i, _ = _find(fus, "diwali")
    far = (date.today() + timedelta(days=20)).isoformat()
    client.patch(f"/contacts/{cid}/follow-ups/{i}", json={"confirmed_date": far})
    in14 = client.get("/follow-ups/upcoming").json()["items"]
    in30 = client.get("/follow-ups/upcoming", params={"days": 30}).json()["items"]
    assert not any(x["contact_id"] == cid and x["date"] == far for x in in14)
    assert any(x["contact_id"] == cid and x["date"] == far for x in in30)
    for items in (in14, in30):
        assert [x["date"] for x in items] == sorted(x["date"] for x in items)
        for x in items:
            assert set(x) == {"contact_id", "contact_name", "index", "action", "date"}
            assert date.today().isoformat() <= x["date"]
    today_items = client.get("/follow-ups/upcoming", params={"days": 0}).json()["items"]
    assert all(x["date"] == date.today().isoformat() for x in today_items)


def test_patch_validation(client, fu_contact):
    cid = fu_contact["id"]
    n = len(_fus(client, cid))
    assert_api_error(client.patch(f"/contacts/{cid}/follow-ups/{n}", json={"dismissed": True}), 404, "not_found")
    assert_api_error(client.patch(f"/contacts/{cid}/follow-ups/-1", json={"dismissed": True}), 404, "not_found")
    for body in ({"confirmed_date": "2026-13-01"}, {"confirmed_date": "next friday"}, {"dismissed": "maybe"}):
        r = client.patch(f"/contacts/{cid}/follow-ups/0", json=body)
        assert r.status_code == 400 and r.json()["error"]["code"] == "validation_error", (body, r.text)
