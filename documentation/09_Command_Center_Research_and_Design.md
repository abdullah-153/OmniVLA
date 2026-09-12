# Command Center research and design record

Research date: 20 August 2026

## Design objective

The earlier interface mixed chat, model setup, execution, screenshots, history, and teaching in a single control surface. That made the most important operational questions difficult to answer: what has been authorized, what is happening now, what evidence supports it, and how can it be stopped?

The overhaul makes OmniVLA an operator console for a local computer-use system. Its organizing metaphor is an **activity ledger**: intent becomes a reviewed plan, execution becomes a chronological evidence trail, and settings are separated from active work.

## Source-of-truth interpretation

`DESIGN.md` defines a warm institutional system: `#faf9f5` cream, `#141413` ink, editorial type, 8–24 px radii, sparse shadows, and brisk ease-out motion. The implementation preserves that identity while correcting two source limitations for a control application:

- The 12 px source body size is used only for metadata. Operational prose remains readable at 14–16 px.
- Terracotta is a restrained semantic accent for focus, approval, warning, and consequence; it is not decorative color.

The layout avoids generic dashboard tiles. A strong left rail, oversized workspace title, narrow rules, and a central ledger establish hierarchy. Model topology is shown as a relationship—Holo on GPU, Qwen on DDR5—not as unrelated status cards.

## Product research translated into interface behavior

| Primary source | Finding | Implemented decision |
| --- | --- | --- |
| [OpenAI computer use guide](https://developers.openai.com/api/docs/guides/tools-computer-use) | Computer output is untrusted, consequential actions need confirmation, and isolation/allowlists matter. | Draft-review-approve lifecycle, exact high-impact confirmation, explicit safety workspace, and visible current evidence. |
| [Google Gemini computer use guide](https://ai.google.dev/gemini-api/docs/computer-use) | Computer-use loops span screenshot observation, action execution, function results, and safety acknowledgement. | The Live workspace separates observation, rationale, action, verification, and intervention rather than rendering a single opaque status. |
| [Anthropic Claude Sonnet 4.6 announcement](https://www.anthropic.com/news/claude-sonnet-4-6) | Stronger computer use still requires attention to prompt injection and operator control. | Screen text is treated as evidence, not authority; pause/stop and supervised risk checks stay prominent. |
| [Microsoft MagenticLite](https://www.microsoft.com/en-us/research/blog/magenticlite-magenticbrain-fara1-5-an-agentic-experience-optimized-for-small-models/) | A compact planner can coordinate a specialized computer-use executor. | The UI explains OmniVLA's split Holo executor / Qwen planner topology and exposes their health independently. |
| [Magentic-UI](https://github.com/microsoft/magentic-ui) | Useful agent products expose plans, action progress, approvals, and reusable task state. | Command, Live, History, and Safety have distinct information architectures. |
| [UI-TARS Desktop](https://github.com/bytedance/UI-TARS-desktop) | Local computer-use products need model/runtime management and a desktop-native shell. | Runtime is a first-class workspace; Electron and browser consume one asset source. |

## Workspace architecture

| Workspace | Operator question | Key content |
| --- | --- | --- |
| Command | What do I want, and what will the agent do? | Intent composer, chat context, structured plan, risk summary, review/approve action. |
| Live | What is happening and what evidence supports it? | Current frame, phase, elapsed timing, chronological activity ledger, pause/stop/HITL. |
| History | What happened before? | Stable chat/run selection and bounded audit records. |
| Safety | What can this system retain or control? | Supervision policy, pairing, privacy state, remote-control boundary, memory deletion. |
| Runtime | Which models own which hardware? | Holo GPU path, Qwen DDR5 path, checkpoint paths, cloud option, diagnostics, skills and Teach. |

The server pins an active run to the chat that created it. Switching History views therefore cannot redirect live updates into the wrong record.

## Interaction and state decisions

- **No invented progress.** The UI shows phase, actual action count, last-cycle timing, and elapsed work. A maximum-step budget is not presented as a percentage.
- **Evidence on demand.** `/api/status` excludes screenshot bytes. The Live workspace requests `/api/screen` only while visible, reducing encoding, transfer, and browser decoding work elsewhere.
- **Adaptive polling.** Active execution polls frequently enough for control; idle and background views back off.
- **Consequential actions remain explicit.** Plan approval and high-impact confirmations use direct verbs and name the consequence.
- **State survives view changes.** Workspaces are navigation states, not page reloads. The live run and selected history are different concepts.
- **Errors are actionable.** Empty, unavailable, failed, paused, and awaiting-human states have distinct copy and controls.

## Responsive behavior

Desktop uses a persistent rail and editorial two-column compositions where the relationship is useful. Below 768 px:

- the rail becomes a drawer;
- five primary destinations move to a fixed bottom navigation;
- cards and runtime topology collapse to one column;
- dialogs and inputs remain within the viewport;
- touch targets are at least 44 CSS pixels;
- long paths, model names, and status text wrap without forcing horizontal scrolling.

Desktop was reviewed at 1440×960 and mobile at 390×844. Keyboard focus is visible, landmark labels are present, the navigation has an active state, and `prefers-reduced-motion` disables nonessential transitions.

## Before/after evaluation

| Concern | Earlier state | Current state |
| --- | --- | --- |
| Primary workflow | Chat and execution controls competed | Intent, review, live evidence, and history form a clear sequence |
| Runtime truth | Models looked interchangeable | Hardware ownership and checkpoint risk are explicit |
| Activity | Log-like blocks without strong chronology | Evidence-led operator ledger with semantic event types |
| Mobile | Desktop surface compressed | Purpose-built drawer and bottom navigation |
| Privacy | Recall behavior was implicit | Opt-in toggle, redaction, and desktop-only clear action |
| Performance | Screenshots moved with general status | Media transport is isolated and view-aware |
| Brand | Generic dashboard treatment | Warm editorial institution aligned to `DESIGN.md` |

## Deliberate exclusions

The interface does not show fake confidence scores, token-speed vanity metrics without task outcomes, a public-internet sharing switch, or an unattended-autonomy mode. Those would create certainty or authority the underlying research system does not possess.
