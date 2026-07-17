# OmniVLA Command Center — Research-Led Overhaul

## Purpose

This release reframes OmniVLA as a supervised desktop-agent control plane rather
than a chat box that can immediately drive a machine. The redesign follows
DESIGNv2.md: a midnight precision instrument with near-black surfaces,
hairline geometry, compact metadata, 6px controls, and a single acid-lime
primary action. Phase color is deliberately reserved for live execution
signals in the overlay, not general UI decoration.

## Market and technical research

| Source | Relevant finding | Product decision |
| --- | --- | --- |
| [OpenAI Computer Use guide](https://developers.openai.com/api/docs/guides/tools-computer-use) | Screen content is untrusted; high-impact actions need human confirmation and computer-use environments should be isolated. | Plans are drafted before execution, risk is surfaced before approval, and the UI treats the screen as an observation rather than an instruction source. |
| [Microsoft Copilot Studio computer-use FAQ](https://learn.microsoft.com/en-us/microsoft-copilot-studio/faqs-computer-use) | Governance, supervision, least privilege, and prompt-injection awareness are core product concerns for desktop automation. | Local-first access, a visible control policy, event journal, stop control, and disabled-by-default remote mutation were added. |
| [Microsoft computer-use run environments](https://learn.microsoft.com/en-us/microsoft-copilot-studio/configure-where-computer-use-runs) | Enterprise computer use separates the orchestration surface from the desktop execution environment. | The command center is a small HTTP control plane and the Electron windows expose only narrow, explicit bridge APIs. |
| [UiPath agentic automation platform](https://www.uipath.com/platform/agentic-automation) | Competitive automation platforms differentiate through governance, auditability, and collaboration between people and agents. | OmniVLA now exposes a plan review, execution trace, human intervention panel, audit journal, and runtime health view. |
| [Gemini Computer Use model announcement](https://blog.google/innovation-and-ai/models-and-research/google-deepmind/gemini-computer-use-model/) | Reliable browser and desktop agents need perception-action loops and deliberate handling of uncertain interactions. | The interface makes the latest capture, current action, critic state, step count, pause, stop, and retry state visible during a run. |
| [OSWorld-2 benchmark](https://arxiv.org/abs/2606.29537) | Long-horizon computer-use tasks remain difficult because interfaces are dynamic, stateful, and only partly observable. | The execution system preserves a short visual memory, bounds action inputs, and makes every run inspectable instead of hiding progress behind a spinner. |
| [MCP authorization specification](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization) | Remote tool access needs explicit, short-lived authorization boundaries. | The optional mobile companion uses expiring pairing codes and remote control remains off until enabled from the desktop. |

## Competitive feature map

The redesign borrows the useful product primitives in the market without
copying a vendor interface:

| Competitor capability | OmniVLA implementation |
| --- | --- |
| Plan-before-act and human supervision | Draft, review, risk acknowledgement, then approve and execute. |
| Runtime observability | Current capture, step trace, model/VRAM health, critic result, pause, stop, and rerun controls. |
| Governance and auditability | Bounded audit journal, chat/run state, local policy, and safe summaries instead of raw secret-bearing settings. |
| Managed mobile access | Installable PWA companion with a matching theme, short-lived pairing, and desktop-controlled remote mutation. |
| Operational resilience | Single active execution lock, planner lock, bounded request bodies, strict payload validation, and explicit error responses. |

## System shape

1. The operator writes an intent in the Workbench.
2. The planner prepares a runbook in the background.
3. The command center presents the scope, actions, and detected risk.
4. The operator explicitly approves the runbook.
5. The executor runs one task at a time while the interface streams the trace,
   latest capture, critic state, health, and human-input requests.
6. The audit record remains available in Activity. Mobile sessions can observe
   status after pairing; they may mutate state only when desktop policy permits
   it.

## Implemented safeguards

- The old direct-run HTTP routes are retired. A run now has to enter through a
  reviewed plan.
- Every JSON mutation has a bounded body size and a typed validator.
- API keys stay in runtime memory and are neither returned by status APIs nor
  persisted in the chat database.
- Risk patterns elevate destructive, sharing, financial, credential, and
  system-setting intents for acknowledgement.
- Remote requests need both a valid pairing token and an explicit desktop
  remote-control toggle. Desktop-only controls cannot be performed remotely.
- Electron renderers no longer receive Node integration. Both desktop shells
  use context isolation, sandboxing, navigation limits, and narrow preload
  bridges.
- Native action input is bounded; logs record typed character counts rather
  than typed contents.
- Screenshot memory is intentionally capped at the three most recent frames.

## Design delivery

The web command center is a file-backed installable PWA at
cogniagent/gui/web. It is a from-scratch Command / Trace / Safety / Runtime
surface rather than a reskin of the earlier flow. The matching phone layout has
its own compact navigation and pairing controls instead of simply shrinking the
desktop UI. The desktop application consumes the same assets, which prevents
the Electron shell and browser surface from drifting apart.

The execution overlay is also rebuilt around live state: animated edge glows
change by phase (teal thinking, lime action, violet verification, coral
intervention/error), an indeterminate progress rail communicates work without
inventing a percentage, and its trace is rendered from actual agent actions.
Reduced-motion preferences are respected.

## Known operational boundary

This project is a local desktop-agent FYP, not a hosted multi-tenant service.
Pairing is intended for a trusted LAN and remains opt-in. Internet exposure,
identity-provider login, durable cloud audit storage, and policy management for
multiple operators would be the appropriate next deployment phase.
