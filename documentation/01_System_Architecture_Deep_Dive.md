# OmniVLA: System Architecture Deep Dive
## Document 01 — Complete Technical Specification

---

## 1. Architectural Philosophy

OmniVLA's architecture is built on an end-to-end Vision-Language Model (VLM) paradigm. We leverage **Mano-P** as the singular unified "Brain and Vision" engine for the agent.

This means:
- **Perception** is handled inherently by the VLM's vision encoder (mmproj) which processes raw screenshots.
- **Planning & Reasoning** is done by the VLM parsing the visual layout and user instructions simultaneously.
- **Action selection** is natively output by the VLM via specific tags (e.g., `<action>click(...)`) using normalized spatial coordinates.
- **Execution** maps the VLM's normalized coordinates directly to system UI interactions.

### The Pure VLM Approach

Unlike previous hybrid architectures that compressed screens into text via UIA or OCR, OmniVLA feeds raw screenshots directly to the model. This preserves spatial relationships, visual context, and custom UI elements without the brittleness of heuristic parsing.

---

## 2. Complete Data Flow Specification

### 2.1 Per-Step Pipeline

Every action the agent takes follows this sequence:

```
  Time ──────────────────────────────────────────────────────────────►

  t=0        t=50ms       t=100ms     t=150ms      t=1200ms     t=1300ms
  │          │            │           │            │            │
  ▼          ▼            ▼           ▼            ▼            ▼
  ┌─────┐   ┌───────┐   ┌───────┐   ┌────────┐   ┌───────┐    ┌─────┐
  │Capt-│   │ Resize│   │ Base64│   │ VLM    │   │ Parse │    │Exec │
  │ure  │──►│ &     │──►│ Encode│──►│ Reason │──►│ Coord │───►│ute  │
  │     │   │ Format│   │       │   │        │   │       │    │     │
  └─────┘   └───────┘   └───────┘   └────────┘   └───────┘    └─────┘
```

### 2.2 Full Task Lifecycle

```
USER TASK: "Open Safari and search for 'MLX framework'"

      ┌────────────────────────────────────────────────────────┐
      │                   AGENT MAIN LOOP                       │
      │                                                        │
      │  ┌─────────────────────┐                               │
      │  │ 1. CAPTURE SCREEN   │◄───┐                          │
      │  │    (1280px width)   │    │                          │
      │  └──────────┬──────────┘    │                          │
      │             │               │                          │
      │  ┌──────────▼──────────┐    │                          │
      │  │ 2. RECALL MEMORY    │    │                          │
      │  │    (Action History) │    │                          │
      │  └──────────┬──────────┘    │                          │
      │             │               │                          │
      │  ┌──────────▼──────────┐    │                          │
      │  │ 3. VLM INFERENCE    │    │                          │
      │  │    → <think>        │    │ Loop until task complete │
      │  │    → <action_desp>  │    │                          │
      │  │    → <action>       │    │                          │
      │  └──────────┬──────────┘    │                          │
      │             │               │                          │
      │  ┌──────────▼──────────┐    │                          │
      │  │ 4. EXECUTE ACTION   │    │                          │
      │  │    (Map to PyAutoGUI│    │                          │
      │  └──────────┬──────────┘    │                          │
      │             │               │                          │
      │      Task complete? ────────┴───► Done!                │
      └────────────────────────────────────────────────────────┘
```

---

## 3. Module Interface Specification

### 3.1 VLMEngine
Connects to the `llama-server` via the OpenAI completions API. It captures the screen, resizes it to 1280px to match Mano-P's training distribution, and wraps it in the specific prompt template.

### 3.2 ActionRouter
Parses the VLM's string output into physical mouse and keyboard actions.
Supported actions:
- `click`, `doubleclick`, `right_single`
- `type`, `hotkey`
- `scroll`, `drag`
- `wait`, `finish`, `stop`

---

## 4. Error Handling & Recovery Architecture

If an execution fails (e.g. coordinates couldn't be parsed), the failure is appended to the action history. In the next iteration, the VLM reads its history, realizes the action failed, sees the new screenshot, and attempts a correction.

---

## 5. Security & Privacy Architecture

- Zero network egress: the model runs completely locally via `llama.cpp`.
- Safe Execution: `pyautogui.FAILSAFE` is enabled, allowing users to abort tasks by moving the mouse to a corner.

---

*Document Version: 2.0 | Part 01 of 08*
*See also: [02_Perception_Engine](./02_Perception_Engine.md) for detailed perception implementation*
