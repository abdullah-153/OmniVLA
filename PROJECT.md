# Project: OmniVLA Cognitive Harness Overhaul

## Architecture
- Module/package boundaries, data flow, shared interfaces
- `run_agent_gui.py` -> `cogniagent/agent.py` -> `cogniagent/perception/vlm_engine.py` & `cogniagent/execution/router.py`
- Verification loop: `cogniagent/agent.py` calls `cogniagent/perception/verification.py` after execution and before next step.

## Milestones
| # | Name | Scope | Dependencies | Status | Conv ID |
|---|------|-------|-------------|--------|---------|
| 1 | Model Hosting | Host Holo-3.1-9B GGUF with GPU optimizations | none | IN_PROGRESS | f9c211f1-79b9-4758-9412-a06a1655fab8 |
| 2 | Brain replacement | Structured output, observation tagging, image history budget | none | PLANNED | TBD |
| 3 | Windows native API | Ctypes mouse/keyboard calls in router | none | PLANNED | TBD |
| 4 | Verification & correction | Screenshot comparison & self-correction loop | M2, M3 | PLANNED | TBD |
| 5 | E2E Integration | Final test execution and coverage hardening | M1, M2, M3, M4 | PLANNED | TBD |

## Interface Contracts
### VLM Engine ↔ Agent
- `VLMEngine.reason(task, messages)`: returns a dict with `think`, `action_desp`, `action_call`, `parsed_action`, `screenshot`, `orig_dims`, etc.
### Router ↔ Agent
- `ActionRouter.execute_vlm_action(vlm_result, original_dims)`: returns a dict with `success`, `detail`, `is_done`.
### ScreenVerifier ↔ Agent
- `ScreenVerifier.compute_screen_diff(before_frame, after_frame)`: returns a dict with `changed`, `diff_ratio`, `description`.
- `ScreenVerifier.verify_semantically(...)`
- `ScreenVerifier.detect_failure(...)`

## Code Layout
- `run_agent_gui.py` - Main Tkinter GUI application.
- `cogniagent/config.py` - System configurations.
- `cogniagent/agent.py` - Core agent cognitive loop.
- `cogniagent/perception/vlm_engine.py` - Perception engine interface to VLM.
- `cogniagent/execution/router.py` - Native input execution router.
- `cogniagent/perception/verification.py` - Verification checks.
