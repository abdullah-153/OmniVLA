# OmniVLA project review — 26 September 2026

## Summary

OmniVLA has a coherent foundation for a supervised Windows computer-use research project: separate CPU planning and GPU visual execution, typed action parsing, bounded visual context, procedural skills, native input, local recall, and an operator console. The highest-value next work is strengthening approval, cancellation, verification, and recovery. More autonomy should follow those fixes.

This review covered first-party backend, agent loop, perception/verification, native execution routing, tools, memory, skills, runtime setup, web UI, Electron wrappers, and tests. Bundled model weights and third-party llama.cpp binaries were not audited. UI findings are source-level; no live desktop/mobile visual or assistive-technology audit was performed. No real desktop task or model inference was started.

## Checks performed

- `python -m pytest -q tests`: **225 passed**, one pytest cache permissions warning, reported duration 63 seconds. This suite globally mocks Windows input, capture, ChromaDB, and some internal modules; passing it does not establish real desktop reliability.
- `python benchmark_runtime.py --json`: readiness checks passed; RTX 4050 Laptop GPU, 6,141 MiB total VRAM; model files and CUDA backend present. Both model HTTP services were stopped. This is configuration readiness, not a latency or task-success benchmark.
- Isolated, mocked checks reproduced: negative-text approval executing an action; an untrusted Host passing authorization; corrupt database contents being replaced; and changed email settings retaining an incompatible hard-coded planner instruction. Temporary databases were used and no native input was issued.
- Impeccable detector: 145 candidate findings, mostly design-document/token drift. It ran in degraded regex mode because parser dependencies were missing. These are not 145 confirmed defects or an accessibility certification.

Severity: **P1** significant safety, data integrity, or core workflow defect; **P2** reliability, performance, or usability improvement; **P3** polish. No P0 exploit or live catastrophic failure was demonstrated.

## Significant findings

### 1. P1 — Negative or ambiguous text can approve a high-impact action

**Evidence:** `cogniagent/agent.py:443–478` denies only an empty response or an exact match in a small negative-word set. All other text executes the pending action. A mocked run with **“do not approve”** invoked the executor.

**Impact:** An operator can explicitly refuse an action and still authorize it accidentally. Approval and OTP entry currently share the same free-text mechanism.

**Fix:** Use typed intervention requests: approval, secret input, clarification, or budget extension. Approval must be an explicit enum bound to run ID, action ID, and a digest of the proposed action. Reject expired or mismatched responses. Show dedicated Approve/Deny controls and a separate masked OTP input. Add negative-language, replay, duplicate-submit, and stale-action regression cases.

### 2. P1 — Compound execution weakens Stop and fresh-screen guarantees

**Evidence:** `cogniagent/execution/router.py:326–354` recursively executes up to five sub-actions using the original dimensions/origin, without a cancellation callback or new observation between sub-actions. `click_and_type` also performs click, clear, type, and optional submit without cancellation checks between them.

**Impact:** Stop can be requested while the remaining sequence continues. Navigation or focus changes can invalidate coordinates. Model inference and human approval also create gaps between screenshot capture and actual input; the router has no observation-expiry guard.

**Fix:** Put a cancellation token and observation identity into the router. Check cancellation before every input boundary; re-observe after navigation, focus changes, and long approval waits. Permit compound operations only when their targets and preconditions remain stable. Confirm stopped status only after input dispatch is quiescent.

### 3. P1 — Local authorization trusts arbitrary Host values

**Evidence:** `cogniagent/gui/server.py:734` compares Origin against the request's own Host, then trusts loopback clients. A mocked local request with matching `untrusted.example:8000` Host/Origin was authorized, including for a desktop-only mutation.

**Impact:** The application lacks a server-side Host boundary against DNS-rebinding-style requests. Exploitability depends on browser and network protections; a browser exploit was not attempted.

**Fix:** Validate Host against explicit allowed addresses and ports, validate Origin independently, and require a per-launch session credential for local mutations. Keep pairing authorization separate from local operator authorization.

### 4. P1 — Database recovery can destroy the recoverable original

**Evidence:** `cogniagent/gui/server.py:421–468` replaces the database with a clean schema after a read/parse exception. An isolated malformed JSON file was overwritten. Save errors are logged but not returned to callers.

**Impact:** Corruption can erase all recoverable chat history/settings; a failed write can still lead to a success response and divergent in-memory/on-disk state.

**Fix:** Quarantine damaged files before recovery, retain a last-known-good backup, and surface persistence failures. Move mutable application data to transactional SQLite with schema migrations, keeping screenshots/videos in separate files. The existing atomic replacement is useful but is not a recovery strategy.

### 5. P1 — Startup and shutdown can kill unrelated programs

**Evidence:** `cogniagent/gui/app.py:941–966` calls `kill_port_owner` for fixed ports, including 8000 and 8082. `gui_telemetry.py:24` finds listeners and force-kills their PIDs without checking ownership. Shutdown has similar calls.

**Impact:** Starting OmniVLA while another development server uses one of these ports can terminate that server and lose its unsaved work.

**Fix:** Terminate only child processes owned by the current runtime, or verify a persisted process identity including executable and creation time. For unrelated listeners, report the conflict or select an available port.

### 6. P1 — “Maximum actions per task” is not consistently enforced

**Evidence:** `cogniagent/gui/web/app.js:868` submits the planner's prescribed step count. `cogniagent/gui/app.py:683` gives that count precedence over the saved setting. `cogniagent/agent.py:216` clamps against a separate config ceiling; continuation at line 749 adds ten without applying that ceiling.

**Impact:** Setting a small maximum in Settings does not reliably limit a run. The displayed “actions” are also model steps, which may contain multiple native actions.

**Fix:** Define distinct initial budget, operator-approved extension, and absolute ceiling. Resolve these once on the backend and return the effective value to the UI. Count compound sub-actions or rename the control accurately.

### 7. P1 — Screen changes are treated as verified task progress

**Evidence:** `cogniagent/perception/verification.py:58` exempts scroll from failure checks and accepts tiny pixel changes for several actions. `cogniagent/agent.py:645` converts non-failed actions into verified progress; later termination primarily relies on this accumulated flag, unresolved failure state, and limited action-type evidence.

**Impact:** A harmless scroll, unrelated animation, or focus change can help satisfy completion gating without establishing that the requested objective was achieved.

**Fix:** Distinguish input dispatch, visible change, subgoal verification, and final outcome verification. Use explicit task postconditions, target-region evidence, and bounded recovery. Preserve pixel diffs as a cheap stagnation signal. Do not label them semantic verification.

### 8. P1 — The Electron overlay has a conflicting origin configuration

**Evidence:** `overlay-app/main.js:30,43` enables web security and loads a local file. `overlay-app/renderer.js:40` fetches the HTTP backend from that file origin. The backend does not provide CORS headers or an OPTIONS route, and rejects an Origin other than its HTTP Host.

**Impact:** This configuration is expected to block overlay polling and JSON control requests, including Stop/HITL, under browser origin enforcement. This is a source-level integration finding, not a reproduced Electron session.

**Fix:** Serve the overlay from the same trusted HTTP origin, or move narrowly scoped backend access into the Electron main process through validated IPC. Add a real Electron smoke test. Do not disable web security to compensate.

### 9. P2 — Personalization contradicts settings and privacy expectations

**Evidence:** `cogniagent/memory/user_profile.py:144` always instructs the planner to use a hard-coded Gmail account even after the configured service/account changes. Defaults contain a developer-specific identity. The default structure is shallow-copied at line 79. `server.py:866` learns profile information even when conversation recall is disabled; clearing recall does not clear the profile.

**Impact:** The agent can choose the wrong account/client. Users lack a clear distinction between conversation recall and persistent profile learning. Multiple fresh profile instances can share nested default objects in one process.

**Fix:** Start with neutral defaults, deep-copy them, derive every instruction from current preferences, and remove stale generated facts when preferences change. Expose separate controls for explicit preferences, learned facts, recall, and deletion. Add a complete “what is stored” view.

### 10. P2 — LAN companion support is incomplete in the client

**Evidence:** The server requires `X-OmniVLA-Pairing`, but `cogniagent/gui/web/app.js:99` has no pairing-token handling and the HTML has no pairing flow. `_lan_url` advertises HTTP. Service-worker registration errors are swallowed.

**Impact:** A remote browser can load the shell but cannot authenticate its API calls using the shipped UI. Service-worker/offline functionality also needs a secure context on a phone; the localhost exception does not extend to another machine's LAN address.

**Fix:** Add pairing entry/QR flow, expiry/revocation feedback, read-only status, and authenticated requests. Decide whether to support HTTPS installation or describe the feature as a browser companion. [MDN service worker requirements](https://developer.mozilla.org/en-US/docs/Web/API/Service_Worker_API/Using_Service_Workers).

### 11. P2 — Web tools need explicit scope and resource bounds

**Evidence:** `cogniagent/tools/web_reader.py:33–85` fetches supplied URLs without a destination policy, buffers responses before truncating output, and does not pass its requested timeout into the trafilatura branch. Planner-generated tool calls invoke it directly. The Everything file-search path does not apply the fallback's search-root restriction.

**Impact:** A model-selected URL can access local services; large or slow pages can consume memory/time. File-search scope changes depending on whether Everything is installed.

**Fix:** Define allowed destinations and filesystem roots; validate redirects and resolved addresses; stream with byte limits and deadlines; and use one tool-policy layer for direct-intent and model-selected calls. Give external content a distinct untrusted result channel.

### 12. P2 — UI evidence is stale and intervention controls are ambiguous

**Evidence:** `cogniagent/agent.py:689` makes the displayed thumbnail from the pre-action screenshot, while `gui/app.py:644` stores it as the latest frame after the action. The post-action frame used for verification is not what the operator sees. HITL questions appear primarily in the composer placeholder (`web/app.js:505`), and the execution panel is forced open on each active status refresh (`web/app.js:604`).

**Impact:** Operators may inspect the wrong screen state, lose the question while typing, and be unable to keep the execution drawer closed during work, especially on narrow displays.

**Fix:** Show timestamped post-action evidence with an explicit before/after toggle. Render intervention requests as persistent cards. Respect a deliberate panel-close action until a new intervention requires attention.

## Performance priorities

These are code-supported optimization opportunities, not measured speedup claims.

1. **Measure complete action cycles.** Record capture/encoding, prompt construction, model queueing, prefill, generation, native input, settle time, verification, persistence, and UI delivery. Existing timing samples omit some post-verification persistence/callback work. Compare median/p95 latency alongside verified task success and intervention frequency.
2. **Avoid full-database writes on each step.** `on_step_complete` persists a snapshot through full normalization, indented JSON serialization, fsync, and replacement. Use incremental transactions and checkpoint batches, while immediately committing approvals and terminal state.
3. **Send only changed state.** The main window polls full status every 0.9–2.2 seconds and the overlay every 0.45–0.9 seconds. Status includes chat summaries, history, audit events, logs, and profile. Use a compact run-status endpoint first, then versioned deltas or server-sent events. Paginate history.
4. **Version screenshots.** Return a frame ID/timestamp and skip unchanged frames. Stop screenshot requests when the panel is hidden or the document is not visible. Preserve enough resolution for readable evidence.
5. **Replace fixed settling sleeps carefully.** The execution pause and fixed verification delay add overhead every step. Use bounded change/stability detection with cancellation, while retaining app-specific timeout fallbacks.
6. **Keep the hardware split.** Single-slot GPU visual execution and CPU planning suit the 6 GB constraint. Benchmark image-size/token-budget and planner-model alternatives on the same task corpus before changing them. Do not trade grounding accuracy for token throughput alone.

## Backend and engineering improvements

- Introduce a `RunSession` owning status, cancellation, approvals, events, and execution identity. Centralize transitions such as planning → review → running → waiting → stopped/completed/failed. Current state is distributed across mutable globals, threads, cached JSON, and callbacks.
- Bind every mutation to an explicit chat/run ID and version. Active chat selection is currently shared server state, so multiple windows/devices can change each other's selected conversation.
- Add cancellable planner work and request deadlines. Existing planner calls can wait 180 seconds, followed by synthesis/retry requests, while holding the single planner slot.
- Make settings updates atomic. The UI currently issues settings, safety, and three profile mutations separately, allowing partial saves.
- Centralize redaction across logs, profile, episodic metadata, chat storage, and audit exports. The agent logs the full task; typed-action redaction alone does not protect secrets embedded in task text.
- Add pinned, reproducible dependency sets, optional dependency groups, and Windows CI. `winotify` and `trafilatura` are optional imports absent from requirements; the notification fallback logs and returns success without displaying a notification. Distinguish delivered, unavailable, and log-only outcomes.
- Retain fast mocked tests, but add real-schema/real-SQLite integration tests, HTTP authorization tests, browser/Electron smoke tests, and a supervised Windows task corpus. Remove global mocks for modules that now exist where practical.
- Before broader deployment, use a production HTTP stack with bounded request handling and connection timeouts. Python explicitly cautions that `http.server` is not recommended for production. [Python documentation](https://docs.python.org/3/library/http.server.html).

## Frontend/UI audit

**Implementation integrity:** qualified pass for a coherent operator-workbench structure; fails release readiness because safety interaction and companion/overlay integration are incomplete.

Provisional code-only scores, not a visual/accessibility conformance result:

| Dimension | Score / 4 | Main evidence |
|---|---:|---|
| Accessibility | 2 | Many controls are labeled and focus styles exist; mobile sidebar is translated offscreen without making its controls inert; no drawer focus containment/return handling was found. |
| Performance | 2 | Render signatures and split screenshot polling help; full status polling, whole-list replacement, and repeated state serialization remain. |
| Responsive design | 2 | Useful breakpoints exist; auto-reopening execution sheet, hidden focusable sidebar, and compact mobile controls need interaction testing. |
| Theming | 2 | Core tokens exist; many later literals and duplicated styling diverge from the design reference. |
| Implementation integrity | 2 | Product-specific structure is clear, but UI copy, saved preferences, evidence, and runtime policy disagree in places. |
| **Total** | **10/20** | **Acceptable source foundation; significant work before release.** |

Recommended UI work:

- Persistent, unmistakable Stop and distinct stopping/stopped states; typed approval cards with the exact pending effect.
- A live-task banner across all chats so the user can locate the executing conversation immediately.
- First-run setup for models, hardware readiness, preferred browser/account, and a safe sample task. Remove personal defaults.
- Honest service states: stopped, starting, ready, failed, cloud configured. Current readiness labels depend on local VLA telemetry even when a different execution mode is relevant.
- Make closed mobile surfaces inert; manage focus on open/close and support Escape. Use intentional reduced-motion state changes rather than the broad 0.01 ms animation override alone.
- Render clickable, sanitized source citations for research results. The current Markdown renderer supports emphasis/lists but not links, making its own search output difficult to verify.
- Split the large JS file into API/state, conversation, execution, skills, and settings modules. A framework migration is optional; fixing the state contracts is the priority.
- Consolidate token values and the design documentation after agreeing on the current visual baseline. Detector palette/radius warnings alone do not justify redesigning the app.

Impeccable follow-up order: **harden → adapt → clarify → optimize → document → polish**. These can be run individually or together after the backend contracts are fixed; rerun the audit after changes.

## New features ranked by value

| Priority | Feature | Why it fits OmniVLA |
|---|---|---|
| 1 | Task contracts and completion evidence | Turns “the model said done” into reviewable outcomes with explicit success conditions. |
| 2 | Recovery checkpoints and safe resume | Preserves finished subgoals and asks for help at the failed step; avoids blindly replaying external effects. |
| 3 | Run replay and evaluation dashboard | Before/after evidence, action timing, intervention causes, and model/skill comparisons strengthen both the product and FYP evaluation. |
| 4 | Scoped application/domain/folder permissions | Gives each run a concrete operating boundary independent of prompt wording. |
| 5 | Skill versions and regression results | Preview changes, compare success rates, roll back regressions, and reuse validated parameterized workflows. |
| 6 | Inspectable personal memory | Per-fact provenance, edit/delete controls, retention, export, and opt-in learning. |
| 7 | Supervised task queue | Queue reviewed work with visible budgets after cancellation and state isolation are reliable. |

## Suggested implementation order

1. **Safety and data integrity:** explicit approval, cancellation at input boundaries, observation freshness, Host/session validation, corruption recovery, owned-process shutdown, and budget enforcement.
2. **Reliable product flows:** outcome verification, overlay connectivity, preference correctness, memory controls, pairing, and timestamped evidence.
3. **Measured performance:** transactional persistence, lean status transport, frame deduplication, cancellable inference, and representative latency/success baselines.
4. **Expansion:** run replay, recovery checkpoints, permissions, skill evaluation, then task queues.

Design-tool maintenance note: `PRODUCT.md` uses a Platform value unrecognized by the installed Impeccable schema. Align it to the supported value when updating the design documents; it does not require changing the product platform.
