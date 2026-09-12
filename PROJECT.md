# OmniVLA implementation architecture

## What the application does

OmniVLA turns a natural-language desktop intent into a reviewed plan, then executes it through a screenshot → structured action → native input → visual verification loop. The product surface is a chat-first local web/Electron app, a quiet execution overlay, and an optional paired LAN viewer.

Its distinguishing deployment shape is two local models with different hardware owners:

- Holo 3.1 4B performs visual perception and action selection on a 6 GB NVIDIA GPU.
- Qwen3.5 4B performs planning on the CPU/system-memory path. Skill routing and action review are deterministic so they add no model latency.

This separation avoids simultaneous GPU residency and makes the resource policy inspectable in `cogniagent/gui/server_manager.py` and `benchmark_runtime.py`.

## Runtime components

| Component | Responsibility | Primary file |
| --- | --- | --- |
| Desktop app | Separate chats, per-chat execution, Skills, Settings, adaptive polling | `cogniagent/gui/web/` |
| Control plane | Request validation, risk policy, pairing boundary | `cogniagent/gui/control_plane.py` |
| HTTP server | Plan lifecycle, one active run, status/screen split, desktop-only mutations | `cogniagent/gui/server.py` |
| Agent harness | Pause/stop boundaries, action loop, structural review, evidence callbacks | `cogniagent/agent.py` |
| Perception | Screen capture and strict `Step` schema parsing | `cogniagent/perception/vlm_engine.py` |
| Execution | Normalized coordinate mapping, action validation, just-in-time risk check | `cogniagent/execution/router.py` |
| Native input | Win32 `SendInput`, virtual-desktop scaling, failsafes | `cogniagent/execution/win32_input.py` |
| Verification | Bounded pixel-change and stagnation evidence | `cogniagent/perception/verification.py` |
| Model runtime | Serialized llama.cpp startup and CPU/GPU ownership | `cogniagent/gui/server_manager.py` |
| Skills | Markdown schema, registry, native observation, synthesis | `cogniagent/skills/` |
| Local recall | Redacted opt-in episodic and chat retrieval | `cogniagent/memory/` |

## Execution lifecycle

1. The UI submits an intent to the planner endpoint.
2. The server stores a structured candidate plan and a task-level risk assessment.
3. The operator reviews and explicitly approves the plan.
4. The single-active-run lock pins the execution to its originating chat.
5. Holo captures the desktop and must return a valid Pydantic `Step`; empty, malformed, or schema-incomplete output is retried and then fails closed.
6. The router validates the action, coordinates, target description, duration, and duplicate signature.
7. A visible destructive, financial, external, or access-control target can trigger exact just-in-time confirmation even when the original task looked benign.
8. Native input executes only after those checks.
9. The verifier compares before/after frames; deterministic schema, repeat, and stagnation checks review progress without competing with the planner for memory bandwidth.
10. The originating chat receives bounded action, verification, and timing events. Pause and stop are honored at step and action boundaries even when another chat is selected.

Supported visual actions include click, double-click, right-click, pointer move, drag, type, key press, scroll, wait, app switching, minimize-all, terminate, and human intervention.

## Skills and teaching

Skills are parameterized Markdown strategies, not blind coordinate macros. `SkillRegistry` validates a strict slug before any path operation; parses `.md`, `.markdown`, `.mds`, and legacy JSON; selects only a high-confidence match locally; and injects a prompt capped at 900 characters. The agent still visually grounds each resulting action.

Teaching supports both explicit action submission and native low-level mouse/keyboard observation. Hook callbacks enqueue minimal events; screenshot work happens outside the Windows hook thread. Printable text becomes a required placeholder instead of being stored verbatim, and injected model events are ignored. The default compiler is immediate and model-free, removes recorded coordinates, and converts the completed demonstration into a reviewable skill definition.

## Trust boundaries

- Loopback sessions are trusted operator sessions. Optional LAN sessions require a short-lived pairing token.
- Paired clients are read-only unless remote control is explicitly enabled from the desktop.
- Shutdown, memory clearing, skill mutation, and teaching remain desktop-only.
- Provider API keys live only in process memory and are never returned in status payloads.
- Status data is bounded and screenshot-free; `/api/screen` is the only current-frame transport.
- Typed action contents and common credential/token patterns are redacted before local persistence.
- Electron renderers use sandboxing, context isolation, disabled Node integration, navigation limits, and narrow preload APIs.

## Failure semantics

The system distinguishes completion, failure, stopping, and interruption. Capture errors are surfaced instead of replaced by fake frames. Invalid model output produces no native input. A saved active state is recovered as stopped after a restart. The step budget is a safety ceiling, not a completion percentage.

## Deployment constraints

OmniVLA is local research software. It does not provide enterprise identity, hostile-network exposure, durable multi-user policy administration, or guaranteed recovery from arbitrary prompt injection. A consequential deployment should add OS/session isolation, domain and application allowlists, signed audit export, model-specific regression gates, and independent red-team evaluation.
