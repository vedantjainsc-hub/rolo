"""Round-3 real-model probes: BUG-9/BUG-11 re-verification (3 runs each) + guard break-it cases.
Usage: .venv/bin/python tools/r3_probe.py   (backend must be running with the real model)"""
import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from conftest import wait_until_settled  # noqa: E402

ART = Path(__file__).resolve().parents[1] / "artifacts" / "enrichment" / "r3"
ART.mkdir(parents=True, exist_ok=True)
c = httpx.Client(base_url="http://localhost:8000/api", timeout=30)

CASES = {
    "dates": ("Omar Dates QA", "Met Omar at the co-working space. Call him tomorrow about the lease. Send the contract in 3 days. Lunch next Monday. Check in on Friday about hiring. Review his pitch on 2026-11-02."),
    "tokyo": ("Kenji Watanabe", "Works at Sony. Chatted in the hotel lobby in Tokyo while waiting for a taxi. Likes jazz records."),
    "delhi": ("अमित शर्मा", "दिल्ली में एक शादी में मिले। उन्हें क्रिकेट बहुत पसंद है। अगले महीने फिर मिलने की बात हुई।"),
    "typical_friday": ("Daniel Fri QA", "Head of investments at Sunbridge Capital. Send him the deck by Friday. Maybe invite him to the London roundtable in November."),
    "bk_london_lives": ("Sara Lund", "Met her in London, where she lives. Runs a design studio called Fjord. Wants intros to fintech founders."),
    "bk_hindi_residence": ("प्रिया वर्मा", "पुणे में रहती है। पुणे में एक मीटअप में मिले। वह एक डॉक्टर है।"),
    "bk_role_after_worksat": ("Leo Park", "Works at Google as a product manager on Maps. Met at a friend's barbecue."),
    "bk_based_and_met": ("Ines Costa", "Lisbon-based architect. We met at a Lisbon design week party. Loves surfing."),
    "bk_title_in_company": ("Maya Cohen", "She's a partner at Partner Capital Group. Met at a dinner."),
}
runs = {"dates": 3, "tokyo": 3, "delhi": 3, "typical_friday": 3}
out = {}
for key, (name, notes) in CASES.items():
    for i in range(1, runs.get(key, 2) + 1):
        t0 = time.monotonic()
        r = c.post("/contacts", json={"name": name, "raw_notes": notes}).json()
        d = wait_until_settled(c, r["id"])
        dt = time.monotonic() - t0
        (ART / f"{key}_run{i}.json").write_text(json.dumps({"elapsed_s": round(dt, 1), "contact": d}, ensure_ascii=False, indent=2))
        e = d["enrichment"] or {}
        summ = {
            "s": round(dt, 1), "status": d["enrichment_status"],
            "role": e.get("role"), "company": e.get("company"), "location": e.get("location"),
            "how_we_met": (e.get("how_we_met") or {}).get("value"),
            "follow_ups": [(f["action"], f["when_text"], f["suggested_date"]) for f in e.get("follow_ups", [])],
            "gaps": e.get("gaps"),
        }
        print(key, i, json.dumps(summ, ensure_ascii=False), flush=True)
        c.delete(f"/contacts/{r['id']}")
