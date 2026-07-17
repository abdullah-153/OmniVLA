# OmniVLA: Cognitive Agent Harness

This project contains the **OmniVLA** cognitive agent harness and its supervised Command Center. The configured local profile uses Holo-3.1 4B GGUF plus a vision projector through `llama-server`. The startup scripts retain compatibility notes for the original Holo-3.1-9B target.

## Prerequisites

1. **System & GPU**: Windows OS with an NVIDIA GPU (recommended: RTX 4050 6GB VRAM or better) with CUDA drivers installed.
2. **Python**: Python 3.10+ (tested with Python 3.12).
3. **Model Files**: The default local profile expects these files in `models/`:
   - `models/Holo-3.1-4B-abliterated-rdo.Q4_K_M.gguf` (main VLM)
   - `models/Holo-3.1-4B.mmproj-f16.gguf` (vision projector)
   - `models/Qwen3.5-4B.Q4_K_M.gguf` (planner)
4. **Llama-server executable**: Ensure `llama-server.exe` exists under the `llama-cpp/` directory.

> Model weights, llama.cpp binaries, chats, recordings, and local memory are deliberately excluded from Git. They remain local to the machine that runs the agent; only source, tests, documentation, and configuration are published.

---

## 1. Setup

First, install the required Python dependencies. Open a terminal (PowerShell or Command Prompt) in the project root directory `C:\Programming\FYP` and run:

```bash
pip install -r requirements.txt
```

---

## 2. Running the Agent (with GUI)

You can launch and manage the agent via the provided Tkinter-based control panel:

```bash
python run_agent_gui.py
```

### Command Center features:
- **Reviewable execution**: draft a runbook, inspect it, then approve it before desktop input begins.
- **Live trace**: inspect current action, steps, screen capture, runtime health, and an operator audit journal.
- **Guardrails**: validate control-plane requests, keep provider API keys in process memory only, and require an extra acknowledgement for high-impact intent.
- **Mobile companion**: install the responsive PWA on a phone. LAN mode is opt-in (set `OMNIVLA_HOST` to `0.0.0.0` before launch), protected by a short-lived pairing code and a desktop-controlled remote-control toggle.
- **Secure desktop shell**: Electron runs with context isolation, sandboxing, and a narrow preload bridge instead of exposing Node.js to page content.

The command center starts at `http://127.0.0.1:8000`. For a mobile companion, enable LAN mode before launching:

    $env:OMNIVLA_HOST = "0.0.0.0"
    python run_agent_gui.py

Open the LAN address shown under **Safety → Pair a second screen**, then enter the short-lived pairing code. Remote controls remain disabled until explicitly enabled from the desktop.

### 6 GB local performance profile

The default configuration is intentionally tuned for a consumer GPU with 6 GB VRAM:

- The Holo VLA is the only model allocated GPU layers. The planner/critic is explicitly CPU-only, avoiding VRAM and KV-cache contention.
- Each llama.cpp server uses one execution slot, bounded context (4,096 tokens for VLA; 2,048 for critic), compact KV cache types, Flash Attention, prompt caching, and an 8-thread CPU prompt path.
- The VLA receives a compact action contract and short rolling history instead of a generated Pydantic schema and unbounded screenshot checkpoints. This reduces prompt prefill work without weakening the existing action verifier or human-in-the-loop checks.
- The Command Center and execution overlay show real phase and timing data (thinking, input, verification, and full cycle), plus the actual trace length. The visible action count is not a fabricated step-progress meter; the step budget remains a safety limit only.

Use the first two runs as warm-up, then compare the **Last cycle** value in the Command Center across three representative tasks. See [the local performance profile](documentation/10_Local_Performance_Profile.md) for the rationale and a repeatable measurement procedure.

---

## 3. Running the Test Suite

To run all automated unit and integration tests, execute the following command in the project root:

```bash
python -m pytest tests/ -v
```

This runs:
- **F1 Hosting Tests**: Validates startup command construction, log parsing, and VRAM monitoring.
- **F2 Brain (VLM) Tests**: Verifies connection, retry logic, image eviction (context window management), and JSON parsing.
- **F3 Input Tests**: Validates the Windows native input controls (mouse clicks, drags, keyboard keystrokes, and banned inputs/fail-safes).
- **F4 Verification Tests**: Validates visual change detection (using SSIM) and semantic state verification.
- **End-to-End Scenarios**: Simulates full multi-step tasks such as logging in, filling out forms, handling error dialogs, and database sync.
