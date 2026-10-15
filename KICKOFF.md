# Kickoff prompt — paste this into Claude Code

Open Terminal, `cd` into this `rolo` folder, run `claude`, and paste everything
between the lines below.

---

You are the lead for the Rolo project. Read CLAUDE.md and all of docs/. Then run the
build using the three subagents in .claude/agents/:

Phase 1 — Check the machine. Verify Python 3.11+, Node 20+, and that Ollama is running
with `gemma4:e4b` pulled (`ollama list`). If anything is missing, tell me the exact
command to fix it and wait.

Phase 2 — Build in parallel. Launch backend-engineer and frontend-engineer at the same
time. Each builds its part to the contract and reports back.

Phase 3 — Integrate. Write `run.sh` at the root that starts Ollama check, backend, and
frontend together, prints the laptop's local IP, and shows the phone URL. Run it and
confirm the full flow works end to end.

Phase 4 — QA. Launch qa-engineer to test against docs/ACCEPTANCE.md and write
docs/QA_REPORT.md.

Phase 5 — Fix loop. Send each bug to its owner, then re-run qa-engineer. Repeat until
every item passes or you need my decision. Maximum 3 rounds before checking in with me.

Keep me updated after each phase in 3–5 plain-English lines: what's done, what's next,
anything you need from me. Don't ask me technical questions unless it's truly blocking.

---

## Tips while it runs
- Claude Code will ask permission before running commands. Read each one; approving
  `npm install`, `pip install`, and starting servers is normal.
- If it stalls or goes off-track, press Esc and tell it what you want in plain English.
- To check on a specific agent's work later: "Ask qa-engineer to re-test item C2."
