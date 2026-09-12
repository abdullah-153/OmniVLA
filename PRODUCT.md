# Product

<!-- impeccable:product-schema 1 -->

## Platform

Windows desktop application with a local web/Electron control surface and optional paired PWA viewer.

## Users

AI researchers, automation engineers, accessibility-tool builders, and technical operators who want a supervised computer-use agent without requiring a datacenter GPU or a cloud automation platform.

## Product purpose

OmniVLA plans, visually grounds, executes, and verifies desktop work while keeping the operator in control. The visual model owns the RTX 4050 6 GB GPU path; planning stays on the concurrent CPU/system-memory path.

## Positioning

The primary promise is useful local computer use on ordinary consumer hardware. OmniVLA sits between brittle coordinate macros and expensive hosted generalist agents: it uses reusable procedural skills, fresh visual evidence, native Windows input, and reviewable plans while keeping models and operational data local by default.

## Product principles

1. **Consumer hardware is a hard constraint.** One visual model owns the 6 GB GPU; concurrent planning stays in system RAM.
2. **Evidence before action.** Every native input must originate from a valid current observation and typed action schema.
3. **Supervision is part of reliability.** Plans, high-impact confirmations, pause, stop, and the audit timeline are first-class workflows.
4. **Skills guide; vision grounds.** A skill contributes strategy and parameters but never bypasses current-screen validation.
5. **Failure must be legible.** Invalid output, capture failure, unavailable criticism, and exhausted budgets are distinct states.
6. **Private by default.** Recall is opt-in, typed values are redacted, and remote control is off by default.

## Core capabilities

- Pure screenshot-based desktop grounding with normalized multi-monitor coordinates.
- Click, double-click, right-click, move, drag, typing, keys, scrolling, window switching, and visual termination.
- Draft → review → approve execution lifecycle with task- and action-level risk assessment.
- Separate chats with a per-chat execution panel for current evidence, actions, timing, and intervention state.
- Markdown skill registry, native demonstration recording, synthesis, editing, and reuse.
- Local run history, opt-in redacted recall, and desktop-only recall deletion.
- Configurable local or cloud model selection; provider credentials remain process-only.
- Installable responsive PWA with short-lived trusted-LAN pairing.
- Read-only consumer-hardware readiness report and hermetic regression suite.

## Reference performance profile

- Target: RTX 4050 Laptop GPU with 6 GB VRAM, a modern CPU, and at least 16 GB system memory.
- Visual executor: Holo 3.1 4B quantized GGUF, single llama.cpp slot, bounded 4,096-token context.
- Planner: Qwen3.5 4B quantized GGUF on CPU only, single slot, bounded 2,048-token context; deterministic action review does not call it.
- Candidate latency profile: Qwen3.5 2B, gated by plan-quality, tool-use, safety, and end-to-end task-success evaluation.
- Aligned Holo checkpoint recommended. Abliterated checkpoints are compatibility options and carry an explicit warning.

## Design commitments

The interface follows `DESIGN.md`: a neutral canvas, near-black conversation sidebar, compact native typography, restrained semantic color, visible keyboard focus, touch-safe targets, reduced motion, and mobile drawers. Progress is communicated as evidence and state, never an invented percentage.

## Success criteria

Measure the product by verified task completion, unsafe-action rate, intervention quality, median and p95 action-cycle latency, peak VRAM, planner resident memory, startup time, and operator ability to understand and stop a run. Tokens per second alone are insufficient.

## Explicit boundaries

OmniVLA is an FYP/research system, not unattended production automation. It does not yet guarantee isolation from hostile screen content, arbitrary long-horizon recovery, enterprise identity, or public-internet operation. Consequential workflows require a dedicated low-privilege desktop session and task-specific evaluation.

## Evidence

- Source implementation: `cogniagent/`
- Built-in procedural skills: `skills/`
- Visual source: `DESIGN.md`
- Research and decision records: `documentation/09_*.md` through `documentation/12_*.md`
- Automated verification: `python -m pytest -q`
- Runtime readiness: `python benchmark_runtime.py --json`
