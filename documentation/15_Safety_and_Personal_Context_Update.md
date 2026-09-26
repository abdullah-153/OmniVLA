# Safety and personal context update

Implemented September 26, 2026. This addresses the safety and integration findings in [the project review](14_Project_Review_2026-09-26.md).

## Execution and approvals

- Approval and completion confirmation use explicit Approve/Deny controls. Every response must match the pending request, run, and action digest. Requests expire and cannot be replayed. Free-text clarification and masked OTP entry are separate paths.
- Stop cancels pending interventions and is checked between native inputs and during waits. Input cleanup still releases held buttons/keys and restores the clipboard. Stop cannot undo an input already sent or instantly interrupt a model request already in flight.
- Compound actions execute only their first sub-action, then require a new observation. This trades some throughput for current coordinates and focus. After approval, the exact observed window is restored only if its process still matches; a fresh screen comparison is required before dispatch.
- Manual budget settings and chat controls are removed. The stored planner budget determines execution, capped by the internal safety ceiling. Client budget overrides and manual extensions are ignored; continuing an exhausted run requires another reviewed plan.
- Completion requires a fresh, separate visual assessment of the objective and expected output. Inconclusive evidence requires operator confirmation. A screen change or scroll alone does not establish success. Visual verification remains model-dependent; application APIs or durable receipts would give stronger evidence for future integrations.

## Storage and local access

- Chat state uses transactional SQLite snapshots, retaining five revisions and a last-good database backup. The existing JSON file is imported without being removed or overwritten.
- Corrupt inputs are preserved with a `.corrupt-<timestamp>` suffix. SQLite recovery uses a verified backup where available; otherwise loading fails explicitly instead of replacing history with an empty database.
- Write errors propagate and do not publish an uncommitted cache. Run approval is committed before starting execution.
- Startup reports occupied backend ports. Port-based process termination is disabled; shutdown only manages owned processes.
- Requests validate Host independently of Origin. Local mutations require a random per-launch session credential. Remote requests require an expiring pairing credential and remain read-only unless remote control is enabled locally.
- The Electron overlay is served from the backend origin with browser security enabled. The companion UI supports pairing, retry, expiry, and local code rotation.

## Personal agent context

- Neutral defaults replace the seeded account and provider. Configured email/browser preferences are used by the planner, with current task instructions taking precedence.
- Personal context includes explicit preferences, relevant facts, constraints, and successful-workflow hints. Retrieval is query-aware and bounded for the local planner.
- Explicit personal statements can be extracted with the planner model, with direct-message evidence required for each update and a deterministic fallback when inference is unavailable. Stable memory keys support corrections rather than accumulating contradictory copies.
- A mentioned email recipient or one-off browser choice does not become the user's default. Memory is advisory context, never permission to execute an action.
- Settings exposes learning enable/disable, memory provenance, and clearing learned context while retaining configured preferences.
- This improves personal context handling; it does not establish OpenClaw/Hermes feature parity. Broader tool integrations, long-running task orchestration, and measured real-world task quality remain future work.

## Validation

- Final full Python regression suite: **254 passed** in 60.28 seconds. The focused safety test file also passes all 23 tests, including failure to commit approval preventing execution.
- Hidden Electron smoke checks exercised desktop Deny, overlay Approve, mobile layout, session bootstrap, and removal of the manual budget control with web security enabled. No renderer JavaScript or CORS errors were observed.
- A browser loaded the fixture through the machine's LAN address, paired through the shipped UI, and verified the default remote read-only policy.
- Tests used temporary state and mocked executors/models; no real native task actions or model inference benchmarks were performed.

Reusable smoke harnesses are `tests/ui_fixture_server.py`, `tests/electron_safety_smoke.cjs`, and `tests/electron_lan_smoke.cjs`. They require installed Python test dependencies and Electron. Run the fixture on loopback port 8000 for the safety harness. For LAN testing, set `OMNIVLA_UI_BIND=0.0.0.0` and `OMNIVLA_UI_PORT=8001`; use a trusted network. These are test-only servers with synthetic approval endpoints and must not be used as the production entry point. Stop the fixture when finished.
