# Repository architecture and security audit

Audit date: 20 August 2026

## Repository conclusion

OmniVLA is a coherent local computer-use research stack rather than a conventional chatbot. Its essential loop is already well chosen for the 6 GB constraint: specialized visual execution, CPU planning, native input, visual verification, and human supervision. The main risks found were not the high-level architecture; they were permissive failure fallbacks, control-plane bypasses, privacy-heavy status payloads, inconsistent desktop action coverage, and an interface that obscured operating state.

## Findings and implemented remediations

| Severity | Finding | Consequence | Remediation |
| --- | --- | --- | --- |
| Critical | Invalid/empty VLM output could fall back to fabricated actions or success | Native input could occur without model evidence | Strict Pydantic schema validation, bounded retries, then fail closed with no action |
| High | A direct run route bypassed plan review | Network/control-plane caller could skip supervision | Removed direct execution; every task enters draft/review/approve lifecycle |
| High | Risk was assessed mainly from initial intent | A benign task could later encounter Delete/Send/Pay/Admin UI | Added just-in-time visible-target risk assessment before input |
| High | Status transported screenshot history | Excess bandwidth, memory pressure, and privacy exposure | Screenshot-free bounded status plus on-demand current-frame endpoint |
| High | Skill paths accepted insufficiently constrained names | Potential traversal or unintended file mutation | Strict slug validation in validator and registry; bounded Markdown payloads |
| High | Mutating controls were available to paired sessions | A LAN viewer could reach sensitive local operations | Memory clear, shutdown, skill changes, and teaching are loopback-only; other mutation needs desktop opt-in |
| Medium | Empty capture could become a synthetic image | Downstream components could act on false evidence | Capture errors now surface and terminate the step |
| Medium | Critic failure could look successful | Operator and agent could over-trust an unavailable check | Explicit `UNAVAILABLE` state distinct from `CORRECT` and `FAILED` |
| Medium | Pause applied mainly through UI callback state | Input could proceed across a pause edge | Pause/stop checks at step and action boundaries |
| Medium | Typed data appeared in logs/memory | Secrets and personal data could persist locally | Character-count action logs, typed placeholder serialization, common-secret redaction, recall opt-in |
| Medium | Teaching UI did not capture native activity end to end | Claimed feature did not match operator behavior | Native Windows hooks, queued processing, injected-event suppression, and parameterized text |
| Medium | Action schema omitted ordinary desktop gestures | Model had to approximate or fail on common interactions | Added double-click, right-click, move, and drag with validation and tests |
| Medium | Planner could theoretically request GPU offload | Resource contention could violate core 6 GB positioning | Planner launcher now hard-forces `-ngl 0` |
| Low | Duplicate handlers and lifecycle blocks existed | Confusing state ownership and maintenance risk | Consolidated app globals, log handler, recording, overlay, and server mutations |
| Low | Electron shutdown used a state-changing GET | Semantically unsafe and easier to trigger unintentionally | POST-only shutdown through narrow preload bridge |
| High | The overlay accepted unauthenticated state-changing GET requests on loopback | A malicious web page could attempt to hide execution evidence through localhost CSRF | POST-only overlay control with a non-simple request header; cross-origin browser requests cannot issue it without rejected preflight |

## Current security properties

### Model-to-input boundary

All native actions must match a closed action schema. Coordinates use normalized 0–1000 values and are mapped across the Win32 virtual desktop, including negative monitor origins. Durations, key names, descriptions, endpoints, and repeated signatures are bounded. Typed text content is not copied into routine telemetry.

### Network boundary

Services bind to loopback by default. LAN mode is opt-in. Pairing codes expire and are compared in constant time; paired clients remain read-only until the desktop permits remote mutation. Request bodies are bounded and JSON fields have type, length, and path rules. Provider secrets are write-only process state.

### Persistence boundary

Run history and optional recall are separate. Recall is disabled by default and can be cleared locally. Screen captures are operational evidence, not general status fields. Local runtime artifacts are Git-ignored.

### Desktop shell boundary

Electron uses context isolation, sandboxed renderers, disabled Node integration, navigation restrictions, and explicit preload APIs. The overlay follows the same pattern.

## Performance architecture findings

- Keeping Qwen on CPU/DDR5 is more valuable to the product constraint than maximizing isolated planner tokens per second.
- The former 9B files are outside the target profile. Holo 4B plus projector is the practical visual path for 6 GB.
- Context, parallel slots, image history, and media polling were controllable sources of memory and prefill cost and are now bounded.
- A smaller planner is the safest next latency experiment because it does not change visual grounding or GPU allocation. Qwen3.5 2B should be compared against 4B with the same plan/evaluation set.

## Residual risks

1. Pure-vision models can still be deceived by malicious or ambiguous screen content.
2. Pixel-change verification proves that something changed, not that the desired semantic outcome occurred.
3. The app shares the operator's Windows session; process-level controls do not equal OS isolation.
4. LAN pairing is suitable for a trusted network, not public exposure.
5. Local model quality varies by checkpoint and quantization; aligned and abliterated weights must never be treated as behaviorally identical.
6. Native observation hooks capture system-wide input metadata while active; the UI must keep start/stop state obvious and the recording duration narrow.

## Recommended next assurance layer

- Run OSWorld-V2/WindowsAgentArena-compatible evaluation on every default-model change.
- Add a dedicated low-privilege Windows VM or sandbox profile with network/domain allowlists.
- Sign/export audit events for experiments that need reproducibility.
- Add adversarial prompt-injection screens and application-specific destructive-action fixtures to the local task pack.
- Calibrate semantic verification per workflow instead of treating raw pixel delta as final truth.
