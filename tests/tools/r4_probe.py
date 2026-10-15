"""Round-4 real-model re-verification of BUG-12/BUG-13 (3 runs each) + Tokyo/Delhi still nulled.
Usage: .venv/bin/python tools/r4_probe.py"""
import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from conftest import wait_until_settled  # noqa: E402

ART = Path(__file__).resolve().parents[1] / "artifacts" / "enrichment" / "r4"
ART.mkdir(parents=True, exist_ok=True)
c = httpx.Client(base_url="http://localhost:8000/api", timeout=30)
CASES = {
    "london_lives": ("Sara Lund", "Met her in London, where she lives. Runs a design studio called Fjord. Wants intros to fintech founders.", "location", "London"),
    "hindi_pune_lives": ("प्रिया वर्मा", "पुणे में रहती है। पुणे में एक मीटअप में मिले। वह एक डॉक्टर है।", "location", "Pune"),
    "partner_title": ("Maya Cohen", "She's a partner at Partner Capital Group. Met at a dinner.", "role", "Partner"),
    "tokyo_venue": ("Kenji Watanabe", "Works at Sony. Chatted in the hotel lobby in Tokyo while waiting for a taxi. Likes jazz records.", "location", None),
    "delhi_venue": ("अमित शर्मा", "दिल्ली में एक शादी में मिले। उन्हें क्रिकेट बहुत पसंद है। अगले महीने फिर मिलने की बात हुई।", "location", None),
    "hindi_mumbai_lives_delhi_met": ("नेहा जैन", "मुंबई में रहती है। दिल्ली में एक शादी में मिले।", "location", "Mumbai"),
}
for key, (name, notes, field, expect) in CASES.items():
    for i in (1, 2, 3):
        r = c.post("/contacts", json={"name": name, "raw_notes": notes}).json()
        d = wait_until_settled(c, r["id"])
        (ART / f"{key}_run{i}.json").write_text(json.dumps(d, ensure_ascii=False, indent=2))
        e = d["enrichment"] or {}
        v = (e.get(field) or {}).get("value")
        if expect is None:
            ok = v is None
        else:
            alts = {"Pune": ("pune", "पुणे"), "Mumbai": ("mumbai", "मुंबई")}.get(expect, (expect.lower(),))
            ok = bool(v) and any(a in v.lower() for a in alts) and (e.get(field) or {}).get("confidence") == "stated"
        print(f"{key} run{i}: {field}={e.get(field)} gaps={e.get('gaps')} -> {'OK' if ok else 'MISMATCH'}", flush=True)
        c.delete(f"/contacts/{r['id']}")
