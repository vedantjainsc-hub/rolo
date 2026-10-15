# Rolo — QA Report

# v2 — round 4 (final)

Date: 2026-10-15. Model `gemma4:e4b`; speech `parakeet-tdt-0.6b-v3`.
Setup: `./run.sh` on a temp `ROLO_DB_PATH`; G7 used a second stack (`ROLO_ASR_BIN=/nonexistent` on :8011, Vite on :5174). The real Ollama and the real DB were not touched. All servers are stopped and ports 8000/5173/5174/8011 are free.

## Final result

**47 / 50 acceptance items PASS. 0 FAIL. 3 BLOCKED (A2, E6, G2: the user's phone check).**

- V2-BUG-10 and V2-BUG-11 are fixed and verified on the real model. C11 is back to PASS.
- No open P0, P1 or P2 bugs; only the deferred items below.

| Suite | Result |
|---|---|
| Backend unit tests | **320/320** |
| `tests/guards` (backend venv) | **150 pass**, 4 xfail (V2-BUG-9 deferred ×2; "Dinner…" and "Ask…" are not on the spec's action-cue list, so informational). The uncommon-verb scan cases for visit/attend/invite/submit/pay/interview/pick up are now normal tests and pass. |
| `tests/api` (contract, voice, quality incl. C9–C13 and the V2-BUG-10 regression ×3, follow-ups) | **128/128** |
| `tests/e2e`, 375×812 + 412×915 (v1 flows, voice, follow-ups UI, Speak audit) | **82/82**, plus the 5-minute auto-stop test (pass, 302.0 s) |
| F1 network | 4,600 browser requests, all to localhost or this laptop's LAN IP |
| B5 / C6 | PASS (backend restarted twice; the voice contact persisted; Ollama down → friendly failed → Retry → enriched) |
| G8 | 0 leftover `rolo-asr-*.wav`; no transcript words in the backend log |

Timing (C5): golden **18.2 s**, typical_300w **15.2 s**. Voice: G3 max gap 1.58 s; G5 saved 0.22 s after Stop, enriched in 9.1 s, named "Priya Shah".

## Re-verification (real model through the API, 3 runs each)

| Case | Expected | Result |
|---|---|---|
| "Invite him to our offsite on Nov 3." | follow-up `exact` 2026-11-03 | **3/3** |
| "Submit the proposal to her by Nov 30." | `exact` 2026-11-30 | **3/3** |
| "Attend her wedding on Dec 12 in Goa." | `exact` 2026-12-12 | **3/3** |
| "Review his pitch on Nov 2." | `exact` 2026-11-02 | **3/3** |
| "Raised their Series A on Sep 3." | no follow-up | **3/3** |
| "Her birthday is on Nov 12." | no follow-up | **3/3** |
| Past items: "Ask him how the demo went last Friday." / "Ask about the May 5 recap of the launch." / "Joined Leasely on 2024-03-01." | kept as `past`, nothing with a future date | **3/3**: both "Ask…" items kept as `past`; no future-dated item; the "Joined" fact sentence created no follow-up |

Guard-level, lead ruling: a model item from a past-dated fact sentence ("Joined Stripe on 2024-03-01", "Raised their Series A on Sep 3, 2025") is kept as `past`. A to-do inside a sentence with a fact cue ("Need to call her before she's married on Dec 5", "Remember to send flowers for her birthday on Nov 12") is kept as `exact`.

## Known issues (deferred)
| Issue | Severity | Status |
|---|---|---|
| V2-BUG-9: bullet lines are joined into one hedged clause, so a fact next to "Maybe…" isn't upgraded to `stated` (it never makes anything wrongly stated) | P2 | Deferred by the lead (over-cautious only) |
| The scan backstop only restores model-dropped dated to-dos for verbs on the spec cue list. "Dinner with Omar on Nov 8" or "Ask for the contract by Nov 20" are not restored if the model drops them (the model kept them in testing). | P2 / informational | Per spec; the 2 xfail guard cases track it |
| A2, E6, G2: phone checks (HTTPS on the phone, Add to Home Screen, mic on the phone) | — | BLOCKED for the user. Desktop parts pass. |
| G1: the first-run helper build and 1.3 GB model download were not re-run, to avoid deleting the user's models. Later starts take about 1.6 s. | — | Not re-tested by design |

---


# v2 — round 3 (history)

Date: 2026-10-14/15. Model `gemma4:e4b`; speech `parakeet-tdt-0.6b-v3`.
Setup: `./run.sh` on a temp `ROLO_DB_PATH`; G7 used a second stack (`ROLO_ASR_BIN=/nonexistent` on :8011, Vite on :5174). The real Ollama and the real DB were not touched. All servers are stopped.

## Final result

**46 / 50 acceptance items PASS. 1 FAIL (C11). 3 BLOCKED (A2, E6, G2: the user's phone check).**

- V2-BUG-7 and V2-BUG-8 are fixed and verified on the real model (18/18 runs).
- The fix for V2-BUG-7 introduced a **P1 regression (V2-BUG-10)**: real to-dos with an explicit date are deleted when the verb isn't on the action-cue list. The model produces them correctly and the backend removes them. This fails C11.

| Suite | Result |
|---|---|
| Backend unit tests | **289/289** |
| `tests/guards` (backend venv) | 128 pass, 11 xfail (V2-BUG-9 deferred ×2, plus 9 informational "scan restores a dropped to-do with an uncommon verb" cases the spec doesn't promise). **10 fail = V2-BUG-10 (9) + V2-BUG-11 (1).** |
| `tests/api` (contract, voice, quality incl. C9–C13, follow-ups) | **125/125** in the full run. The new `test_c11_dated_todo_with_uncommon_verb_kept` added afterwards is **0/3** (V2-BUG-10). |
| `tests/e2e`, 375×812 + 412×915 (v1 flows, voice, follow-ups UI, Speak audit) | **82/82**, plus the 5-minute auto-stop test (pass, 302.4 s) |
| F1 network | 4,626 browser requests, all to localhost or this laptop's LAN IP |
| B5 / C6 | PASS (backend restarted twice; the voice contact persisted; Ollama down → friendly failed → Retry → enriched) |
| G8 | 0 leftover `rolo-asr-*.wav`; no transcript words in the backend log |

Timing (C5): golden **28.3 s**, typical_300w **24.6 s**, both under 30 s on the first try.

## Re-verification (real model, 3 runs each)

| Bug | Case | Result |
|---|---|---|
| V2-BUG-7 | "Raised their Series A on Sep 3." | **3/3** no follow-up |
| V2-BUG-7 | "Her birthday is on Nov 12." | **3/3** no follow-up |
| V2-BUG-7 (no regression) | "Review his pitch on Nov 2." | **3/3** `exact` 2026-11-02 |
| V2-BUG-8 | "Met on 2026-10-10 … Her number is +1 415 555 0100." | **3/3** phone "+1 415 555 0100" (the date is not taken as a phone) |
| V2-BUG-8 | "+44 20 7946 0958 ext 12" | **3/3** kept, including "ext 12" |
| V2-BUG-8 | "LinkedIn: priya-shah-123" | **3/3** linkedin "priya-shah-123" |

## Break-it: false negatives of the new non-to-do rule

**V2-BUG-10 (P1, new): `drop_non_action_dated` deletes correct model follow-ups.** Owner: **backend-engineer**. Suspect: `backend/app/enrichment/followups.py` `drop_non_action_dated` (and the `_ACTION_CUE` list it relies on).

Real model:

| Notes | Model output | After the guard | Runs |
|---|---|---|---|
| "Invite him to our offsite on Nov 3." | "Invite him to our offsite" / Nov 3 | **no follow-ups** | 0/2 kept |
| "Submit the proposal to her by Nov 30." | "Submit the proposal" / by Nov 30 | **no follow-ups** | 0/2 kept |
| "Attend her wedding on Dec 12 in Goa." | "Attend her wedding" / Dec 12 | **no follow-ups** | 0/2 kept |
| "Visit his office on Nov 5 to see the prototype." | — | kept | 2/2 |

- Raw model vs guarded output was captured for each of the three dropped cases.
- Guard-level (`test_model_todo_with_date_is_kept`): 9/9 correct model to-dos deleted. Verbs: visit, dinner, attend, invite, submit, pay, interview, pick up, ask.
- Fails C11 ("Follow-ups with timing in the notes are never dropped").
- Fix idea: drop only items that match a non-to-do pattern (raised/joined/born/moved/graduated/birthday/anniversary, or past tense), instead of keeping only items that match the cue list. Alternatively, treat an imperative verb at the start of the sentence as an action cue.

**V2-BUG-11 (P2, new): a model follow-up tied to an explicit past date is dropped instead of shown as `past`.** Owner: **backend-engineer**. Suspect: the same function. Its past check uses only cue words, not an explicit past year.
- "Joined Stripe on 2024-03-01." with the model item "Ask how joining Stripe went" / on 2024-03-01 → removed.
- This contradicts the lead's ruling that past-dated model follow-ups are kept and shown as `past`.

## Acceptance changes vs round 2
- **C11: PASS → FAIL** (V2-BUG-10). The C11 example itself ("Send him the deck by Friday") is still present and `exact`.
- Every other item keeps its round-2 PASS, re-run this round:
  - C1 golden company `maybe`
  - C12 classification
  - C13 Hindi residence
  - G3 max gap 1.64 s
  - G5 saved 0.84 s after Stop, named "Priya Shah"
  - G9 302.4 s
  - H1–H6 (UI and API)

## Known issues (deferred)
| Issue | Severity | Status |
|---|---|---|
| V2-BUG-9: bullet lines are joined into one hedged clause, so a fact next to "Maybe…" isn't upgraded to `stated` (it never makes anything wrongly stated) | P2 | Deferred by the lead (over-cautious only) |
| A2, E6, G2: phone checks (HTTPS on the phone, Add to Home Screen, mic on the phone) | — | BLOCKED for the user. Desktop parts pass. |
| G1: the first-run helper build and 1.3 GB model download were not re-run, to avoid deleting the user's models. Later starts take about 1.6 s. | — | Not re-tested by design |

## Open (not deferred)
- **V2-BUG-10 (P1):** blocks C11.
- **V2-BUG-11 (P2).**

## New test assets
- `tests/tools/v2r3_probe.py`
- `test_c11_dated_todo_with_uncommon_verb_kept` in `tests/api/test_enrichment_quality.py`
- Round-3 cases in `tests/guards/test_guard_regressions.py`

---


# v2 — round 2 (history)

Date: 2026-10-14. Model `gemma4:e4b`; speech `parakeet-tdt-0.6b-v3`.
Setup: `./run.sh` on a temp `ROLO_DB_PATH` (the LAN IP is now 192.168.1.252; run.sh regenerated the certificate). G7 used a second stack (`ROLO_ASR_BIN=/nonexistent` on :8011, Vite on :5174). The real Ollama and the real DB were not touched. All servers are stopped.

## Summary

**47 / 50 acceptance items PASS. 0 FAIL. 3 BLOCKED (A2, E6, G2: the user's phone check).**

- All five V2 bugs (V2-BUG-1…5) and V2-NOTE-6 are fixed and verified on the real model.
- The break-it pass found one new **P1**: the explicit-date scan turns biographical dates into follow-ups (V2-BUG-7). It found two new P2 guard edge cases (V2-BUG-8, -9). None of the three breaks an acceptance item.

| Suite | Result |
|---|---|
| Backend unit tests | **265/265** |
| `tests/guards` (deterministic; run with the backend venv) | 110/121. All 11 failures are the new round-2 break-it cases: V2-BUG-7 (6), V2-BUG-8 (3), V2-BUG-9 (2). Every older case passes. |
| `tests/api` (contract 64, voice 17, quality incl. C9–C13, follow-ups ×2 contacts) | **125/125** |
| `tests/e2e` at 375×812 + 412×915 (v1 flows, voice, follow-ups UI, Speak audit, F1) | **82/82**, plus the 5-minute auto-stop test (pass, 302.6 s) |
| F1 network | 4,626 browser requests, all to localhost or this laptop's LAN IP. `rolo-asr` has 0 sockets. |
| B5 / C6 | PASS (backend restarted twice; Ollama down → friendly failed → Retry → enriched) |

Timing (C5): in the full-suite run, golden took **27.3 s** and typical_300w **24.2 s**, both under 30 s, so no re-run was needed. In the probe runs golden took 14.1–15.1 s (8 runs).

## Re-verification (real model)

| Bug | Case | Result |
|---|---|---|
| V2-BUG-1 hedge across a line break | golden notes (with "I think\nStripe-adjacent") | **8/8** company `maybe` ("Payments startup, possibly Stripe-adjacent") |
| V2-BUG-2 "last Friday" hid "by Friday" | deck + "last Friday" note | **3/3** "Send him the deck by Friday" present, `exact` 2026-10-16. Plus `[with_past]` in the API suite. |
| V2-BUG-3 Devanagari location nulled | "वह जयपुर से है…" ("He is from Jaipur…") | **3/3** location kept ("Jaipur" ×2, "जयपुर" ×1; either script accepted, as approved) |
| V2-BUG-4 contact info took any phrase | `contact_info_bait` | **3/3** all null (plus the hallucination suite run) |
| V2-BUG-5 explicit date lost without an action cue | "Review his pitch on Nov 2." | **3/3** `exact` 2026-11-02; also in both C12 runs |
| V2-NOTE-6 "Next week" chip | UI chip title and the real .ics download | next Monday (2026-10-19), computed relative to today |

Acceptance items that changed from round 1: **C1, C3, C4, C9, C11, C13 → PASS** (evidence above plus the `tests/api` and `tests/e2e` runs, including the golden "maybe" chip in the e2e core flow at both viewports). Every other item keeps its round-1 result and was re-run this round: G3 max gap 1.72 s; G5 saved 0.82 s after Stop, named "Priya Shah"; G8 0 leftover WAVs and no transcript text in the log; G9 302.6 s.

Approved test updates applied:
- `test_followups_ui.py`: "Next week" = next Monday, computed from today.
- C13 and r4 probes: Hindi places accepted in either script.

## New bugs (break-it on the new guards)

**V2-BUG-7 (P1): the explicit-date scan turns biographical dates into follow-ups.** Owner: **backend-engineer**. Suspect: the "no action cue → explicit date only" branch in `backend/app/enrichment/followups.py` `scan_follow_ups` (`_SENTENCE_PAST` doesn't know joined/raised/born/moved/graduated, and doesn't exclude "birthday").
- Real model, 2/2 runs. Notes: "Ravi Iyer, CFO at Finlo. Raised their Series A on Sep 3. Her birthday is on Nov 12. …"
- Result:
  - follow-up "Raised their Series A on Sep 3", `exact`, **2027-09-03**
  - follow-up "Her birthday is on Nov 12", `exact`, 2026-11-12
- Both get a calendar and Add to Calendar, and both will reach Upcoming.
- Guard-level: "Joined Stripe on 2024-03-01", "Born on 1990-05-04", "Moved to London on 2025-06-01" and "Graduated … May 20, 2015" each become a follow-up marked "(already happened)" (`test_scan_no_follow_up_from_non_action_dates`, 6/6 fail).
- Why P1: it invents a to-do the user never wrote, with a wrong date (against non-negotiable 2).
- Expected: dates that only describe the past or the person (funding, birthday, joined, born) are not follow-ups. A birthday could go in personal details.
- Real explicit-date follow-ups still work ("Review his pitch on Nov 2", "Demo day is on 2026-11-20, worth attending").

**V2-BUG-8 (P2): contact-info shape rules are too loose in one place and too strict in two.** Owner: **backend-engineer**. Suspect: `service.py` `_PHONE_RE` / `_LINKEDIN_RE`. All guard-level; not seen in real-model runs.
- Too loose: phone `"2026-11-02"` (a date) is accepted.
- Too strict (real contact info dropped): phone `"+44 20 7946 0958 ext 12"`, and a bare LinkedIn handle `"priya-shah-123"` written as "LinkedIn: priya-shah-123".

**V2-BUG-9 (P2, low): line flattening joins bullet lines into one hedged clause.** Owner: **backend-engineer**. Suspect: `service.py` `_hedged_clause_words`.
- With "Works at Acme Robotics\nMaybe moving to Berlin" (or "- " bullets), "Acme Robotics" counts as hedged, so a model `maybe` on it is never upgraded to `stated`.
- This can only keep a value at `maybe` (never wrongly stated). Idea: treat a newline followed by a capital letter or bullet as a clause break.

## Known / unchanged
- A2, E6 and G2 need the user's phone (desktop checks pass: LAN HTTPS → 200, secure context true, recording starts).
- G1 first-run build/download was not re-run (it would delete the user's 1.3 GB of models). Later starts take about 1.6 s.

---


# v2 — round 1 (history)

Date: 2026-10-14. Model `gemma4:e4b` (local Ollama). Speech: `parakeet-tdt-0.6b-v3` via `rolo-asr`.
Specs: ACCEPTANCE (v1 + v2), API_CONTRACT v2.1, ENRICHMENT v2, VOICE.md, DESIGN v2.
Setup:
- The app was started with `./run.sh` (HTTPS at https://localhost:5173) and `ROLO_DB_PATH` set to a temp file.
- G7 used a second stack: a backend on :8011 with `ROLO_ASR_BIN=/nonexistent` and Vite on :5174.
- The real Ollama and the real DB were not touched. All servers I started are stopped.

## Summary

**41 / 50 acceptance items PASS. 6 FAIL (C1, C3, C4, C9, C11, C13). 3 BLOCKED (A2, E6, G2: the user's phone check).**

No P0. Two P1 bugs cause four of the FAILs:
- **V2-BUG-1:** a hedge split across a line break is lost. This fails C1, C3 and C9.
- **V2-BUG-2:** a past "last Friday" follow-up hides a future "by Friday" one. This fails C11.

Voice (G) and calendar (H) all pass.

| Suite | Result |
|---|---|
| Backend unit tests (`backend/tests_unit`) | **233/233** |
| `tests/api/test_contract.py` (v2.1: new keys, health.asr, voice create, follow-up 404s, upcoming validation, transcribe errors) | **64/64** |
| `tests/api/test_voice.py` (real helper) | **17/17** |
| `tests/api/test_enrichment_quality.py` + `test_followups.py` (real model) | 35/42 on the first full run; failures analysed below. Reruns after fixing my 3 test bugs: see the per-item evidence. |
| `tests/guards` (deterministic guards, backend venv) | **90/92**. 2 fail = V2-BUG-1. The 3 BUG-14 cases that were deferred now pass. |
| `tests/e2e` (375×812 + 412×915, voice, follow-ups UI, Speak audit, F1) | **80/82** + the 5-minute auto-stop test run separately (pass). The 2 failures are the golden "maybe" chip at both viewports (V2-BUG-1). |

## Acceptance (v1 A–F + v2)

| Item | Result | Evidence |
|---|---|---|
| A1 | PASS | `./run.sh` reached "Rolo is running" in **1.6 s**. It prints `https://localhost:5173` and `https://192.168.1.245:5173` and stops cleanly. |
| A2 | **BLOCKED** (phone) | `https://192.168.1.245:5173/` → 200, and `/api/health` through the LAN proxy → 200. Note for the lead: A2 still says `http://`, but v2 serves HTTPS only; plain `http://localhost:5173` gets no response. |
| A3 | PASS | `/api/health` → `model.available: true`, `asr.available: true` (v2.1 shape, `test_health_shape`). |
| B1–B4, B6 | PASS | e2e at both viewports. B1: visible in the list 0.17–0.30 s after Save, still pending. |
| B5 | PASS | Backend restarted twice on the same DB: 10 → 10 contacts. The voice contact kept `needs_name: true, source: "voice"`. |
| **C1** | **FAIL** | Golden company `"A payments startup, possibly Stripe-adjacent"` comes back **`stated`** in 8/8 runs (ENRICHMENT expects `maybe`). Every other highlight matches: role "Runs partnerships"/"Partnerships" (stated), Fintech Forward, intros to bank CTOs, Biscuit, "after Diwali" → `needs_date`, gaps company + email, contact_info null. Cause: V2-BUG-1. |
| C2 | PASS | 10/10 hallucination cases: no invented role or company, and no world-knowledge terms. (contact_info is covered under C4.) |
| **C3** | **FAIL** | The golden hedge ("I think Stripe-adjacent") shows **no marker** on the card (e2e core flow at both viewports; the company row has no chip). `hedged_everything` is flagged correctly. Cause: V2-BUG-1. |
| **C4** | **FAIL** (1/5 runs) | `contact_info_bait`: `linkedin: "probably under his full name"`. The phrase is a substring of the notes, so the guard keeps it, and the card shows it as a LinkedIn value. The other 4 runs and every other enrichment had contact_info null. V2-BUG-4. |
| C5 | PASS | 267-word note: **22.2, 23.3, 20.3 s**. Golden: 15.2, 16.2, 16.2 s (one 36.5 s outlier on the first model call after the 5-minute voice test). |
| C6 | PASS | `tools/c6_ui_check.py`: with `OLLAMA_URL=http://localhost:1` the contact saves and shows "The local model isn't running. Start Ollama and tap Retry." After restarting with real Ollama, Retry → enriched card. |
| C7 | PASS | `test_add_note_reenrich_reflects_it`, `test_append_while_pending_supersedes`. |
| C8 | PASS | Atomic 409 (10 rounds × 6 parallel calls); double-tap sends 1 POST; Re-enrich is disabled while pending. |
| **C9** | **FAIL** | `hedged_everything`: company "Google" is `maybe` 5/5 and the maybe chip renders per DESIGN (1 px gold border, transparent fill, 12 px navy-700, 44×44 target, tooltip "You weren't sure about this."). **But the golden hedge is `stated` 8/8** (V2-BUG-1). |
| C10 | PASS | `hedged_everything` 5/5 runs: the opener never mentions Google, London or ads. The opener guard has 4 deterministic cases. |
| **C11** | **FAIL** | The C11 example ("Send him the deck by Friday", Sunbridge note): present and `exact` in 3/3 runs. **But** with "Send him the deck by Friday… Ask him how the demo went last Friday." the deck follow-up is **dropped in 3/3 runs** (`test_shape_and_classification[with_past]` ×2, `test_c12_split_under_cap[0]`). Without the "last Friday" sentence it is present (`[no_past]`). V2-BUG-2. |
| C12 | PASS | Deterministic: by Friday → 2026-10-16, tomorrow → 10-15, in 3 days → 10-17, Nov 2 → 2026-11-02 (`exact`); after Diwali and (maybe) in November → `needs_date`; since last Friday and the May 5 recap → `past`; no timing → `none`: 12/12 cases. Real model: every follow-up that was present got the right status and date (lease 10-15, contract 10-17, pitch 11-02, office/dinner `needs_date`, demo/recap `past`). Caveat: in 1 of 2 real runs "Review his pitch on Nov 2" came back without a date (V2-BUG-5). |
| **C13** | **FAIL** | The BUG-17 case (Mumbai/Delhi), "पुणे में रहती है" and "लखनऊ की रहने वाली" keep the location (real model and guards, 7/7 cue forms). **"वह जयपुर से है" loses it in 2/2 real runs**: when the model writes the place in Devanagari ("जयपुर"), the guard nulls it; when it writes "Jaipur", it's kept. V2-BUG-3. |
| D1–D4 | PASS | e2e search, edit, delete and export at both viewports. |
| E1–E3 | PASS | v1 screen audits plus the new Speak screen (idle and recording) and the follow-up calendar/chips: no horizontal scroll, all targets ≥ 44 px, inputs ≥ 16 px, AA contrast at both viewports. Speak button is full width under search; mic 96 px navy-900. |
| E4 | PASS | v1 state tests, plus the Speak error states (helper missing, permission denied, insecure context) and the follow-up pending note. |
| E5 | PASS | Core flow at both viewports: the clipboard text equals the opener. |
| E6 | **BLOCKED** (device) | Manifest and icons pass `test_pwa_manifest_and_navy_icon`. Needs the user's phone check. |
| F1 | PASS | 4,466 browser requests across the e2e run, all to localhost or this laptop's LAN IP. `rolo-asr` has no network sockets (`lsof -i`); its only files are CoreML caches. |
| F2 | PASS | Error-envelope tests; friendly voice errors (503 "Voice isn't set up. Run ./run.sh once on the laptop."). |
| F3 | PASS | `test_settings_and_export`. |
| G1 | PASS | Later runs: ready in 1.6 s; helper ready after 0.2 s; `asr.available: true`. The first-run build/download was **not** re-run, because it would delete the user's 1.3 GB models. |
| G2 | **BLOCKED** (phone) | Desktop part passes (`test_g2_secure_context_desktop`): `https://192.168.1.245:5173/speak` loads, `window.isSecureContext === true` after accepting the certificate, and recording starts. Needs the user's phone. |
| G3 | PASS | 31 s `say` sample fed through the fake mic: 21 live updates, first at 1.7–2.0 s, **max gap 1.70–1.97 s** (2 runs). `artifacts/g3_live_text.json`. |
| G4 | PASS | Lead sample and my `say` sample: both transcripts contain "Priya Shah", "Fintech Forward", "bank CTOs" and "Friday". 60 s of audio transcribes in 0.35 s. |
| G5 | PASS | Saved **0.83–0.93 s** after Stop, `source: voice`, enriched in 20–21 s; name filled to "Priya Shah" and `needs_name` false (2 runs). |
| G6 | PASS | No name said: the card shows "New contact" and "No name was heard…" with an "Add a name" button. Editing the name clears the prompt, and the list shows the new name. |
| G7 | PASS | `ROLO_ASR_BIN=/nonexistent`: health shows asr false with "Run ./run.sh once to set up voice"; `/api/transcribe` → 503 `asr_unavailable` "Voice isn't set up. Run ./run.sh once on the laptop."; the Speak button is disabled with that reason; /speak shows "Voice isn't ready" plus "Type instead"; typed save still works. |
| G8 | PASS | 367 transcriptions over the session. During 10 back-to-back requests the temp file `rolo-asr-*.wav` was seen in `$TMPDIR` (10×) and deleted every time; 0 left afterwards. The log has only "Transcribed N s of audio -> M chars" lines and no transcript words. |
| G9 | PASS | A denied mic (NotAllowedError) shows "Allow microphone access for this site in your browser settings." The 5-minute limit auto-stopped and saved at **302.7 s** (`source: voice`, 4,914 chars). |
| H1 | PASS | All four statuses render per DESIGN (mocked contact): `exact` = 44 px date row that expands to the calendar (selected day navy-900, today ringed) + Add to Calendar + Change date; `needs_date` = "When should you follow up? You said “after Diwali”." + 5 chips; `none` = "Add a date"; `past` = "(already happened)", no controls. |
| H2 | PASS | API: `confirmed_date` persists, .ics follows it, it shows in Upcoming, and it **survives re-enrichment** (2 contacts). PATCH while pending → 409. UI: chip → "Follow-up set for …" + Undo; Pick a date → calendar with past days disabled. A real chip pick persists across reload. |
| H3 | PASS | `dismissed` persists, is excluded from Upcoming, and .ics → 400 "date: pick a date first"; confirming clears dismissed. UI: "No date" → "No date" plus "Add a date". |
| H4 | PASS | `icalendar` parses it: 1 VEVENT, `DTSTART` is a `date` (all-day), `DTEND` = +1 day, SUMMARY "Follow up: Omar Haddad — {action}", DESCRIPTION has when_text. The UI download is named `rolo-followup.ics`. |
| H5 | PASS | Window: 20-day item excluded at `days=14`, included at 30; sorted soonest first; `days=0` gives only today; validation 61/-1/abc → 400. UI: at most 3 rows "Fri 16 Oct · Omar Haddad — Send him the deck", tapping opens the card, hidden when empty. A real tomorrow follow-up appears in the strip. |
| H6 | PASS | At 375 and 412 with the calendar and chips open: no horizontal scroll, day cells ≥ 44×44, all targets ≥ 44 px, AA contrast. |

## Bugs (v2 round 1)

### P1

**V2-BUG-1: a hedge split across a line break is lost, so `maybe` gets "upgraded" to `stated`.** Owner: **backend-engineer**. Suspect: `backend/app/enrichment/service.py` `_hedged_clause_words` (splits clauses on `\n`).
- Steps: golden notes exactly as in ENRICHMENT.md ("…payments startup, I think\nStripe-adjacent…").
- Expected: company `maybe`, with the maybe chip.
- Actual: `stated`, no chip, in 8/8 runs (API and e2e).
- Isolated: `test_hedge_survives_line_breaks` (2 of 4 cases fail). The same sentence without the line break stays `maybe`; the voice transcript of the same notes (one line) is `maybe`.
- Why it matters: phone notes wrap anywhere, and a hedged fact is shown as fact (violates non-negotiable 2). This fails C1, C3 and C9.
- Fix idea: split clauses on sentence punctuation only, treating newlines inside a sentence as spaces.

**V2-BUG-2: the follow-up scan treats "by Friday" as already covered when another follow-up mentions "last Friday", so "Send him the deck by Friday" is dropped.** Owner: **backend-engineer**. Suspect: `backend/app/enrichment/followups.py` `_same_timing` (strips "by", then finds "friday" inside the past item).
- Steps: notes "Send him the deck by Friday. … Ask him how the demo went last Friday."
- Actual: the deck follow-up is missing in 3/3 real runs. Guard repro: with the past item present the scan adds nothing; without it, it adds "Send him the deck by Friday" (`exact`).
- This fails C11. Fix idea: compare by resolved date/status and ignore `past` items when deciding coverage.

### P2

**V2-BUG-3: a location written in Devanagari is nulled despite a Hindi residence cue.** Owner: **backend-engineer**. Suspect: `service.py` `_lives_there` / `_location_is_meeting_place`. The Devanagari-place path only matches Latin location values.
- "वह जयपुर से है। जयपुर में एक कॉन्फ्रेंस में मिले।" ("He is from Jaipur. Met at a conference in Jaipur."). The raw model said `location "जयपुर"` and the guard nulled it (2/2 runs); "Jaipur" in Latin is kept. This fails C13.

**V2-BUG-4: contact_info accepts any substring of the notes.** Owner: **backend-engineer**. Suspect: the contact_info guard in `service.py` `apply_guards`.
- `contact_info_bait` (1/5 runs): `linkedin: "probably under his full name"` (a hedge, not a profile) was kept and shown as a LinkedIn value. This fails C4.
- Fix idea: also require a plausible shape (email has `@`, phone ≥ 7 digits, linkedin is a URL/handle).

**V2-BUG-5: an explicit date is dropped when the model leaves `when_text` empty and the sentence has no action cue.** Owner: **backend-engineer**. Suspect: `followups.py` `_ACTION_CUE` (no "review/ask/invite…").
- "Review his pitch on Nov 2." → `none` in 1 of 2 real runs (`exact` 2026-11-02 in the other).
- Fix idea: scan explicit dates (ISO / month-day) in any sentence, or attach them to a follow-up whose action words overlap the sentence.

**V2-NOTE-6: "Next week" means different things in the UI and the backend.** Owner: lead to decide → frontend-engineer.
- The chip sets today + 7 (`FollowUps.tsx`), while a spoken/typed "next week" resolves to next Monday (`dates.py`). The same words can give different dates.

**Doc (lead):** ACCEPTANCE A2 still says `http://<laptop-ip>:5173`. In v2 it should be `https://`.

### Fixed since v1 (verified)
- **BUG-14:** past detection now works; the 3 deferred guard tests pass.
- **BUG-16:** opener guard; C10 5/5.
- **BUG-17:** the original Mumbai/Delhi case passes. The new Devanagari-value case is V2-BUG-3.
- **BUG-15:** partly fixed; see V2-BUG-2 and V2-BUG-5.

### Observations (not bugs)
- Parakeet heard `say`'s "Stripe adjacent" as "Striper Jason". G4's four phrases were all correct.
- Headless Chromium reports a refused mic as `NotSupportedError` rather than `NotAllowedError`, so the G9 denial was simulated with the real browser error name.

## New test assets
- `tests/api/test_voice.py`, `tests/api/test_followups.py`
- v2 cases in `tests/api/test_enrichment_quality.py` (C9–C13, split C12)
- `tests/e2e/test_voice_ui.py` (fake mic; `ROLO_SLOW=1` enables the 5-minute test), `tests/e2e/test_followups_ui.py`
- v2 cases in `tests/guards/test_guard_regressions.py`
- `tests/fixtures/golden_sample_16k.wav` (lead's) and `tests/fixtures/voice/*.wav` (`say`: golden, 31 s script, no-name, 44.1 kHz, 48 kHz, stereo)

---

# v1 history

Date: 2026-10-14. Model `gemma4:e4b` (local Ollama). The app was started with `./run.sh` on a temp DB. The real Ollama was not touched. All servers I started are stopped.

## Final result

**28 / 30 acceptance items PASS. 0 FAIL. 2 BLOCKED (A2 and E6 still need the user's phone check).**

- BUG-12 and BUG-13 are fixed and verified on the real model.
- No P0 or P1 bugs are open. The remaining issues are P2 and listed under "Known issues (deferred)" below.

## R4-1. Runs this round

| Suite | Result |
|---|---|
| Backend unit tests | 128/128 |
| `tests/guards` (deterministic guard break-it, backend venv) | 56 pass. 3 xfail = deferred BUG-14. 1 fail = new latent edge, BUG-17. |
| `tests/api` (contract + real-model quality) | 59/60. The 1 failure is `hedged_everything`: the opener stated "your work at Google" as fact (BUG-16, model variance; see R4-3). |
| `tests/e2e` at 375×812 and 412×915, including the F1 network check | **57/57**. F1: 2,753 browser requests, all local. B1: 0.13–0.15 s. |
| Real-model probes (`tests/tools/r4_probe.py`, 3 runs each) | 18/18 as expected. Artifacts: `tests/artifacts/enrichment/r4/` |

## R4-2. Re-verification (real model, 3 runs each)

| Case | Expected | Result |
|---|---|---|
| "Met her in London, where she lives." | location London (stated) | **3/3** London (stated). BUG-12 fixed. |
| "पुणे में रहती है। पुणे में एक मीटअप में मिले।" ("Lives in Pune. Met at a meetup in Pune.") | location Pune (stated) | **3/3** Pune (stated). BUG-12 fixed. |
| "She's a partner at Partner Capital Group." | role Partner (stated), no "Job title" gap | **3/3** "partner" (stated), no bogus gap. BUG-13 fixed. |
| Tokyo hotel-lobby case | location null | **3/3** null (BUG-9 still fixed) |
| Delhi wedding case (Hindi) | location null | **3/3** null (BUG-9 still fixed) |
| "मुंबई में रहती है। दिल्ली में एक शादी में मिले।" ("Lives in Mumbai. Met at a wedding in Delhi.") | location Mumbai | **3/3** Mumbai (stated) |

## R4-3. `hedged_everything`: variance or regression?

I ran it 5 times: **3 passed, 2 failed.**
- In all 5 runs the structured fields were identical and correct: role null, company "Google" (inferred), location "London" (inferred), and the headline kept the hedge ("possibly at Google (Ads?)").
- The 2 failures were only the suggested opener: "Hi Rahul, I hope you're well. Curious about your work at Google."
- It failed once more in the full-suite run (6 of 6 runs had correct fields; 3 of 6 had the bad opener).

**Verdict: model variance, not a regression from the location/role guards.** The guards never read or write `suggested_opener` (checked in `service.py` `apply_guards`), and the fields they do touch were stable and correct in every run. Possibly relevant: the round-3 prompt edit. I can't confirm that, because earlier rounds ran this case only once each (both passed). Filed as BUG-16 (P2). Acceptance is unaffected: C2 (no invented role/company/contact info) and C3 (hedges inferred and flagged in the UI) both pass.

## Known issues (deferred, P2, not blockers)

| Bug | Summary | Owner / suspect |
|---|---|---|
| BUG-14 | The date guard is over-eager: an action without timing ("Send the Friday report") gets a date; the past "May 5 launch recap" becomes 2027-05-05; "since last Friday" becomes a future date. Seen only in direct guard tests (3 xfail), not in real-model runs. **Deferred by user decision.** | backend-engineer, `backend/app/enrichment/dates.py`, `apply_guards` action fallback |
| BUG-15 | The model sometimes drops stated follow-ups or their timing: "Review his pitch on 2026-11-02." loses its date (3/3); "Send him the deck by Friday" is missing from a short note (3/3). **Deferred by user decision.** | backend-engineer, prompt changes via the lead |
| BUG-16 (new) | The suggested opener sometimes states a hedged claim as fact ("Curious about your work at Google", 3 of 6 runs). Possible fix: a deterministic check that swaps in a neutral opener when the text names an inferred company/role/location without a hedge word. | backend-engineer, `service.py` `apply_guards`; prompt via the lead |
| BUG-17 (new, latent) | The Hindi residence cue applies to any location. With "मुंबई में रहती है। दिल्ली में एक शादी में मिले।" ("Lives in Mumbai. Met at a wedding in Delhi."), a model answer of location "Delhi" would be kept as stated. The real model answered "Mumbai" in 3/3 runs, so this is guard-level only (`test_meeting_city_still_nulled_when_residence_is_elsewhere`). | backend-engineer, `service.py` `_HINDI_RESIDENCE` in `_location_is_meeting_place` |

Still BLOCKED: A2 (open the app from a phone on the same Wi-Fi) and E6 (Add to Home Screen shows "Rolo" and the navy icon). The user needs to check both on a real phone.

---

# Round 3 (history)

Date: 2026-10-14. Model `gemma4:e4b` (local Ollama). Contract v1.2 and ENRICHMENT.md with the new deterministic guards (dates, location, role).
The app was started with `./run.sh` on a temp DB. The real Ollama was not touched. All servers I started are stopped.

## R3-0. Result (round 3)

**28 / 30 acceptance items PASS. 0 FAIL. 2 BLOCKED (A2 and E6 still need the user's phone check).** C1–C8 all pass.

- **Fixed:** BUG-9 (meeting venue saved as location).
- **Mostly fixed:** BUG-11 (follow-up dates). Weekday arithmetic is now correct; one residual: an explicit date in the notes is still dropped.
- **New in round 3:** three P2 regressions from the new guards (BUG-12 to BUG-14) and one P2 model omission (BUG-15).
- No P0 or P1 bugs are open.

## R3-1. Runs this round

| Suite | Result |
|---|---|
| Backend unit tests (`backend/tests_unit`) | 106/106 |
| `tests/api` (contract 45 + quality 15: golden, 300-word, 10 hallucination cases, C7, D2, supersede) | **60/60** |
| `tests/e2e` at 375×812 and 412×915, including the F1 network check | **57/57**. F1: 2,754 browser requests, all local. B1: 0.15 s. |
| C6 (Ollama down → failed → Retry) and B5 (2 backend restarts) | PASS, via `tools/c6_ui_check.py` |
| Real-model re-verification and break-it (`tools/r3_probe.py`) | see R3-2. Artifacts: `tests/artifacts/enrichment/r3/` |
| Guard break-it, deterministic (`tests/guards/test_guard_regressions.py`, run with the backend venv) | 46/56. The 10 failures are filed as BUG-12 to BUG-14. |

Timing (C5): golden 13.1 s; 267-word note 12.1 s; other cases 4–9 s.

## R3-2. Re-verification

**BUG-9: fixed.**
- Tokyo hotel-lobby case: location null in 3/3 runs.
- Delhi wedding case (Hindi notes): location null in 3/3 runs.
- `halluc_famous_ceo_unrelated` (Pune): location null.
- Real residences are still kept. "Lisbon-based architect. We met at a Lisbon design week party." keeps location "Lisbon" (stated) in 2/2 runs.

**BUG-11: mostly fixed, one residual (see BUG-15).**

| Timing phrase in notes | Result | Runs |
|---|---|---|
| "tomorrow" | 2026-10-15 ✓ | 3/3 |
| "in 3 days" | 2026-10-17 ✓ | 2/3; in 1 run the model left `when_text` null |
| "next Monday" | 2026-10-19 ✓ | 3/3 |
| "Friday" | 2026-10-16 ✓ | 3/3 |
| 267-word note, "by Friday" | 2026-10-16 ✓ (was 10-17) | — |
| 267-word note, "next week" | 2026-10-19 ✓ | — |
| 267-word note, "maybe in November" | null, hedge kept ✓ | — |
| Golden, "after Diwali" | null ✓ | — |

**Residual:** "Review his pitch on 2026-11-02." still comes back with `when_text: null, suggested_date: null` (3/3). The model drops the date before the backend guard sees it.

## R3-3. Acceptance checklist (round 3)

| Item | Result | Evidence (round 3) |
|---|---|---|
| A1 | PASS | `./run.sh` ready in about 1 s; prints the laptop and phone URLs; stops cleanly. |
| A2 | **BLOCKED** (phone) | `http://192.168.1.245:5173/` gives 200 from this machine. Needs the user's phone check. |
| A3 | PASS | `available:true` with the real Ollama; false with a detail when Ollama is down. |
| B1 | PASS | 0.15 s at both viewports, status still pending. |
| B2 | PASS | e2e validation tests. |
| B3 | PASS | API and UI 10,000 / 10,001 tests, including emoji and Devanagari. |
| B4 | PASS | Unicode API and UI tests. |
| B5 | PASS | A contact persisted across 2 restarts. |
| B6 | PASS | `test_save_without_enriching`. |
| C1 | PASS | Role "Partnerships" (stated), company "A payments startup, possibly Stripe-adjacent" (inferred), Fintech Forward, intros to bank CTOs, Biscuit, "after Diwali" with null date, gaps include company + email, contact_info null. |
| C2 | PASS | 10/10 hallucination cases. No invented role, company or contact_info, and no world-knowledge terms. |
| C3 | PASS | Hedged company "Google, possibly" (inferred). UI inferred marker test passes. |
| C4 | PASS | contact_info null in every enrichment this round. |
| C5 | PASS | 267 words in 12.1 s. |
| C6 | PASS | Friendly failed state, then Retry gives an enriched card. |
| C7 | PASS | `test_add_note_reenrich_reflects_it`, supersede test. |
| C8 | PASS | Atomic 409 (10 rounds × 6 parallel calls); UI double-tap sends 1 POST. |
| D1–D4 | PASS | API and e2e search, edit, delete and export tests. |
| E1–E5 | PASS | Audits (no horizontal scroll, ≥ 44 px targets, ≥ 16 px inputs, AA contrast), tokens, state tests, Copy. |
| E6 | **BLOCKED** (device) | Manifest and navy icons verified. The Add-to-Home-Screen sheet needs the user's phone check. |
| F1 | PASS | 2,754 requests, all local. |
| F2 | PASS | Error envelope tests. The fake garbage/500 model checks passed in round 2; that code is unchanged this round. |
| F3 | PASS | Settings privacy line and model pill. |

## R3-4. Open bugs (all P2)

**BUG-12 (new): the location guard drops real residences.** Owner: **backend-engineer**. Suspect: `backend/app/enrichment/service.py` `_location_is_meeting_place` / `_RESIDENCE_CUE`.
- "Met her in London, where she lives. Runs a design studio called Fjord." gives location **null** (real model 2/2). The residence cue only counts when it comes before the place name.
- Hindi: "पुणे में रहती है। पुणे में एक मीटअप में मिले।" ("Lives in Pune. Met at a meetup in Pune.") gives location **null** (real model 2/2). Hindi residence words (रहती/रहता/रहते, काम करती/करता) are not cues, even though मिले counts as a meeting cue.
- Guard-level only (not seen with the model): "Met at her flat in Brooklyn" and "Met at his office in Zurich. He runs the Zurich team." also null the location.
- Expected: keep the location when the notes say the person lives or works there, before or after the place name, in English or Hindi.

**BUG-13 (new): the role guard nulls a real title when the title word appears in the company name.** Owner: **backend-engineer**. Suspect: `service.py` `_role_is_not_a_title` (the `rw <= cw` subset rule).
- "She's a partner at Partner Capital Group." gives role **null** plus a bogus "Job title" gap (real model 2/2).
- Guard-level: "Owner" at "Owner's Bakery" is also nulled. A role value "Works at Google as a product manager" would be nulled because of its "works at" prefix, though in practice the model returned "Product manager".
- Suggestion: only treat the role as restating the employer when it equals the company, not when it is a subset of it. When the role starts with "works at … as X", keep X.

**BUG-14 (new): the date guard is over-eager on actions and past references.** Owner: **backend-engineer**. Suspect: `backend/app/enrichment/dates.py` and the action fallback in `apply_guards`.
- Guard-level only (not seen in real-model runs):
  - Action "Send the Friday report" with no timing gets 2026-10-16.
  - "Ask about the May 5 launch recap" gets 2027-05-05.
  - when_text "since last Friday" gets a future Friday.
- Suggestion: don't fall back to the action text, or only for an explicit "by/on/next <day>"; and return None for "last <weekday>".

**BUG-15 (new; also the BUG-11 residual): the model drops stated follow-up timing or whole follow-ups.** Owner: **backend-engineer** (prompt changes go through the lead).
- "Review his pitch on 2026-11-02." becomes a follow-up with no `when_text` (3/3), so the user's explicit date is lost.
- Short note "Head of investments at Sunbridge Capital. Send him the deck by Friday. Maybe invite him to the London roundtable in November." The "Send him the deck by Friday" follow-up is **missing entirely** (3/3). The same instruction inside the 267-word note is kept.
- In one run, "Send the contract in 3 days" lost its `when_text`.
- Suggestion:
  - Prompt (via the lead): "include every action the notes ask for, with its timing phrase verbatim".
  - Optional deterministic backstop: if the notes contain an ISO date or "by <weekday>" phrase that no follow-up covers, add it to the follow-up whose action words overlap that sentence.
- Evidence: `tests/artifacts/enrichment/r3/dates_run*.json`, `typical_friday_run*.json`.

### Test changes this round
- New `tests/guards/test_guard_regressions.py`: deterministic break-it for the date, location and role guards. It needs the backend venv: `cd tests && ../backend/.venv/bin/python -m pytest guards -q`.
- New `tests/tools/r3_probe.py`: real-model re-verification and break-it probes.

---

# Round 2 (history)

Date: 2026-10-14. Model: `gemma4:e4b` on local Ollama. API contract v1.2, ENRICHMENT.md (new prompt, `maxItems`, `num_predict`, contact-gap guard, single-worker queue).
The app was started with `./run.sh` and a throwaway DB (`ROLO_DB_PATH` in the scratch dir). The real Ollama was not touched. Every server I started has been stopped.

## R2-1. Summary (round 2)

**28 / 30 acceptance items PASS. 0 FAIL. 2 BLOCKED (A2, E6), both waiting on the user's phone check.**

All 10 round-1 bugs were re-verified. 9 are fixed. BUG-9 is partly fixed: two meeting venues are still saved as stated locations. One new P2 bug (BUG-11): follow-up dates are wrong or dropped.

Test totals:
- Backend unit tests: 58/58.
- `tests/api/test_contract.py`: 45/45. The race test now does 10 rounds of 6 simultaneous calls, and I ran it 4 times: all correct.
- `tests/api/test_enrichment_quality.py`: 13/15. The 2 failures are my stricter round-2 location checks (BUG-9 residual). Every C2 criterion passes.
- `tests/e2e`: 57/57 at both viewports, including the F1 network check.

### Change log: round 1 → round 2

| Item / bug | Round 1 | Round 2 | Evidence |
|---|---|---|---|
| C1 golden | FAIL (no email gap) | **PASS** | 3/3 runs. Gaps `["Exact company name", "Email or other contact details"]`. Role "Partnerships" (stated) counts as a match under the lead's ruling. `artifacts/enrichment/golden_r2_run{1,2,3}.json` |
| C5 < 30 s | FAIL (36–46 s) | **PASS** | 267-word note: 9.1 s, 10.1 s, 9.1 s. Golden note: 7.1 s, 6.0 s, 6.0 s. Hallucination cases: 5–7 s. |
| E2 touch targets | FAIL | **PASS** | `test_ui_audit_touch_targets_and_input_fonts` passes at both viewports. The layout checks out by eye (`17-card-enriched-full.png`). |
| C8 | PASS with caveat | **PASS** | Caveat removed: the 409 check is now atomic (BUG-5 fixed). |
| BUG-1 DB pool exhaustion | P1 open | **Fixed** | Pointed a backend at a hung fake model and queued 40 enrichments. All 40 creates returned 201. List 1.5 ms, create 1 ms, append ×5 about 1 ms each, health 3 ms. No `QueuePool` errors in the log. |
| BUG-2 stuck `pending` after a crash | P1 open | **Fixed** | Backend unit test `test_bug2_crash_marks_failed_and_retry_works` (I ran it) covers it: the crash marks the contact `failed` with a safe message, then Retry ends in `done`. Black box: 5 jobs queued behind a model timing out at 2 s all drained to `failed`, none stuck. The round-1 trigger (pool exhaustion) no longer happens. |
| BUG-3 C5 speed | P1 open | **Fixed** | See C5. |
| BUG-4 C1 email gap | P1 open | **Fixed** | See C1. The guard also fires in every hallucination case. |
| BUG-5 `/enrich` race | P2 open | **Fixed** | `test_concurrent_enrich_calls_only_one_202`: 10 rounds × 6 parallel calls give exactly one 202 and five 409s per round. I ran it 4 times. |
| BUG-6 touch targets | P2 open | **Fixed** | See E2. |
| BUG-7 emoji counting | P2 open | **Fixed** | `test_emoji_counted_as_one_character`: the UI shows 10,001 emoji as "10,001 / 10,000" with an error, and 10,000 emoji save. API: `test_emoji_name_and_notes_limits_in_code_points`. |
| BUG-8 connect timeout wording | P2 open | **Fixed** | `OLLAMA_URL=http://10.255.255.1:11434` (non-routable, so a real connect timeout) gives "The local model isn't running. Start Ollama and tap Retry." |
| BUG-9 enrichment quality | P2 open | **Partly fixed** | Fixed: Pune is no longer used as a location; no invented "Follow up" items; the opener no longer states hedged claims. Still open: Tokyo (`company_no_role`) and Delhi (`hindi_only`) are saved as **stated** locations, but both are just where we met. |
| BUG-10 405 code | P2 open | **Fixed** | `test_method_not_allowed_is_405`: PUT and DELETE on `/contacts` give 405 `method_not_allowed`, which is now in contract v1.2. |
| BUG-11 follow-up dates | — | **New, P2** | See section 3. |

Test changes this round:
- `e2e/test_app.py:156` now expects the new wording, "Name must be at most 120 characters." (approved).
- New tests:
  - "Name is required." wording
  - emoji counting (UI and API)
  - 405
  - the 10-round race
- The hallucination fixtures are stricter for BUG-9:
  - location must not be stated in `hindi_only` and `company_no_role`
  - no follow-ups allowed in `very_short`
  - the hedge check now also covers `suggested_opener`

## R2-2. Acceptance checklist (round 2)

| Item | Result | Evidence |
|---|---|---|
| A1 `./run.sh` one command | PASS | Ready in about 1 s. Prints `✓ Ollama running with gemma4:e4b`, the laptop URL and `Phone (same Wi-Fi): http://192.168.1.245:5173`. Stopped with `pkill -TERM -f "bash ./run.sh"`; ports freed. |
| A2 localhost + phone | **BLOCKED** (phone) | From this machine: `http://192.168.1.245:5173/` gives 200 and `/api/health` through the LAN proxy gives 200. **Needs the user's phone check.** |
| A3 health | PASS | `{"name":"gemma4:e4b","available":true,"detail":null}`. With a dead or unreachable URL: `available:false` and a "isn't reachable" detail. |
| B1 in list < 1 s, before enrichment | PASS | `B1: saved and visible in list 0.15s` at both viewports, status still `pending`. |
| B2 empty / whitespace name | PASS | `test_capture_validation` ("Enter a name."), `test_server_required_message_wording` ("Name is required."), API `name: is required`. |
| B3 10,000 / 10,001 | PASS | UI and API tests for ASCII, Devanagari and emoji (code points). |
| B4 Unicode | PASS | `test_unicode_roundtrip` and `test_unicode_display`. |
| B5 persists across restart | PASS | Two backend restarts on the same DB. All contacts kept, notes intact. Three contacts that were pending at shutdown came back as `failed` with "Enrichment was interrupted. Tap Retry." |
| B6 save without enriching | PASS | `test_save_without_enriching`. |
| C1 golden | PASS | 3/3 runs: role "Partnerships" (stated), company "A payments startup, possibly Stripe-adjacent" (inferred), how_we_met "Fintech Forward" (stated), "Intros to bank CTOs" (stated), "Has a dog named Biscuit" (stated), follow-up "after Diwali" with `suggested_date` null, gaps include exact company name and email, contact_info all null. |
| C2 hallucination, zero invented role/company/contact_info | PASS | 10/10 cases (including Satya Nadella, Elon Musk and Mark Zuckerberg with unrelated notes): no invented role, company or contact_info, and no world-knowledge terms. The 2 stricter location failures are filed under BUG-9. |
| C3 hedges inferred + flagged in UI | PASS | Hedged case: company "Google" (inferred), London only as an inferred personal detail. Headline "Professional possibly at Google (Ads?)". UI shows the gold "inferred" marker on Company (`test_core_flow_capture_enrich_card`). |
| C4 no invented contact info | PASS | Null in every real enrichment this round, including the bait case. |
| C5 < 30 s | PASS | 267 words: 9.1, 10.1, 9.1 s. |
| C6 Ollama down → failed → Retry | PASS | `tools/c6_ui_check.py`: with a dead URL the card shows "The local model isn't running. Start Ollama and tap Retry." After restarting the backend with real Ollama, Retry gives an enriched card. |
| C7 add note → re-enrich | PASS | `test_add_note_reenrich_reflects_it` and the format tests. Supersede test passes. |
| C8 409 + UI double-tap | PASS | Sequential and concurrent 409 (atomic). Double-tap sends 1 POST. Re-enrich is disabled while pending. |
| D1 search | PASS | API test. Golden: `q=PAYMENTS` and the suggested tag match. UI rapid-typing test. |
| D2 edit + re-enrich | PASS | `test_edit_name_and_notes` and `test_edit_then_reenrich_updates_card`. |
| D3 delete with confirmation | PASS | `test_delete_requires_confirmation` and `test_delete_while_enriching`. |
| D4 export | PASS | `test_settings_and_export`: the downloaded JSON ids equal the API ids. |
| E1 no horizontal scroll | PASS | Audit across 9 screens at both viewports. |
| E2 touch ≥ 44, inputs ≥ 16 px | PASS | Audit at both viewports. `artifacts/ui_audit.json`. |
| E3 design + WCAG AA | PASS | `test_design_tokens` and `test_ui_audit_contrast`. |
| E4 loading/empty/error/timeout | PASS | Empty, list error + retry, create failure keeps notes, failed card, 120 s timeout + Retry, pending skeleton, settings down/unreachable, not found. |
| E5 Copy | PASS | Clipboard text equals the opener. |
| E6 PWA | **BLOCKED** (device) | Manifest and navy icons verified (`test_pwa_manifest_and_navy_icon`). **The Add-to-Home-Screen sheet needs the user's phone check.** |
| F1 local-only network | PASS | `test_zz_network.py`: 2,749 browser requests, all to local hosts. |
| F2 no stack traces / raw output | PASS | Fake garbage reply: "The model's reply couldn't be read, even after a retry. Tap Retry." Fake 500: "The local model returned an error. Tap Retry." Plus the API error-envelope tests. |
| F3 settings | PASS | Privacy line and "gemma4:e4b running locally"; red pill and fix steps when down. |

## R2-3. Open bugs (round 2)

### P0 / P1 — none

### P2

**BUG-9 (residual): where we met is saved as the person's location, marked stated.** Owner: **backend-engineer** (prompt changes go through the lead).
- `company_no_role` ("Chatted in the hotel lobby in Tokyo") gives location `Tokyo` (stated).
- `hindi_only` ("दिल्ली में एक शादी में मिले", met at a wedding in Delhi) gives location `Delhi` (stated).
- The `famous_ceo_unrelated` case (Pune) is fixed.
- Suggested deterministic guard in `backend/app/enrichment/service.py` `apply_guards`: if the location value appears in `how_we_met.value` and the notes don't tie it to where the person lives or works, set confidence to `inferred`, or null it.
- Evidence: `tests/artifacts/enrichment/halluc_company_no_role.json`, `halluc_hindi_only.json`.

**BUG-11 (new): follow-up dates are sometimes wrong or dropped.** Owner: **backend-engineer**.
- **Wrong weekday:** in the 267-word note, "send him the deck … by Friday" became `suggested_date: "2026-10-17"` in 3/3 runs. Today is Wednesday 2026-10-14, so Friday is **2026-10-16**; the 17th is a Saturday. The card shows the wrong date to the user.
- **Explicit date lost:** "Review his pitch on 2026-11-02." became a follow-up with `when_text: null, suggested_date: null`, so the date vanished. In the same probe, "Lunch next Monday." was dropped as a follow-up. "tomorrow" (2026-10-15) and "in 3 days" (2026-10-17) were correct.
- **Hedge or timing lost:** "maybe invite him to the London roundtable in November" became "Invite to London roundtable", with `when_text` null in 2 of 3 runs; "maybe" was gone in all three.
- Expected (ENRICHMENT rule 5): explicit dates and weekday offsets computed correctly; relative phrases kept verbatim in `when_text`.
- Suggestion: compute `suggested_date` deterministically in `service.py` from `when_text` (ISO dates, tomorrow, in N days, next week, weekday names) and override the model's arithmetic. If the backend can't resolve the phrase, set it to null.
- Evidence: `tests/artifacts/enrichment/typical_300w_r2_run{1,2,3}.json`, `dates_probe.json`.

### Notes
- The lead ruled that a long queue can outlast the UI's 120 s polling cutoff; that is accepted for the MVP and not filed.
- Garbage/500 model replies, Ollama dying mid-request, delete while queued or enriching, and restart while pending all behave correctly.

## R2-4. How to reproduce
See `tests/README.md`. Artifacts are in `tests/artifacts/`: enrichment JSON (round-2 files have an `_r2` suffix), screenshots per viewport plus `c6/`, and `ui_audit.json`.
