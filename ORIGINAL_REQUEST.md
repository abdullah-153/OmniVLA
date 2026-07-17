# Original User Request

## Initial Request — 2026-06-08T20:30:26+05:00

Overhaul the OmniVLA agent system's cognitive harness to use Holo-3.1-9B models hosted via llama.cpp, transitioning from pyautogui to Windows native API calls, and implementing a hybrid visual/semantic state verification and self-correction loop.

Working directory: `C:\Programming\FYP`
Integrity mode: development

## Requirements

### R1. Host Holo-3.1-9B via llama.cpp
- Host the GGUF text model `C:\Programming\FYP\models\Holo-3.1-9B-abliterated-rdo.i1-IQ4_XS.gguf` using `llama-server.exe` from `C:\Programming\FYP\llama-cpp`.
- Integrate the vision projector model `C:\Programming\FYP\models\Holo-3.1-9B.mmproj-f16.gguf` using the `--mmproj` flag.
- Optimize performance for the RTX 4050 GPU (6GB VRAM):
  - Set GPU offload layers to maximum (offloading all layers, e.g., `-ngl -1` or `-ngl 99`) to ensure both the LLM and the vision projector run entirely in VRAM.
  - Enable KV cache quantization (`-ctk q8_0 -ctv q8_0` or similar).
  - Enable Flash Attention (`-fa on`).
  - Configure appropriate context size (e.g., `-c 4096` or `-c 2048`).
- Update or create a PowerShell startup script (e.g., `start_holo3.1.ps1`) reflecting these optimized settings.

### R2. Replace Brain in OmniVLA System (CogniAgent)
- Update configuration (`cogniagent/config.py`) and VLM engine (`cogniagent/perception/vlm_engine.py`) to target the new model server and endpoint.
- Configure `VLMEngine` to request structured output JSON matching the Holo3.1 format: `{note, thought, tool_call}`.
- Wrap user observation screenshots and logs with `<observation>` and `</observation>` tags.
- Implement the image budget trim mechanism: keep only the latest 3 screenshots in the message history, replacing older ones with a text placeholder `[screenshot evicted]` but keeping the `<observation>` wrapper.

### R3. Windows Native API Automation (Coasty-AI Practice)
- Replace `pyautogui` usage in `cogniagent/execution/router.py` with Windows native DLL calls (using `ctypes` / `win32api` / `win32con`).
- Implement robust mouse control:
  - Clicks and double-clicks using direct cursor positioning and `mouse_event` (or `SendInput`).
  - Dragging/scrolling via mouse events.
- Implement robust keyboard control:
  - Text typing using native Windows inputs (such as `SendKeys` or keyboard event sequences).
  - Advanced modifier key combinations (e.g., Win, Ctrl, Alt, Shift combos) using `keybd_event` or `SendInput` (simulating key down/up sequences) to ensure modifier focus and combinations operate reliably.

### R4. Hybrid Verification & Self-Correction (Coasty-AI Practice)
- Implement a hybrid state validation loop:
  - **Visual Verification**: Compare consecutive screenshots (e.g., via SSIM, structural similarity, or simple pixel differences) to detect absolute stagnation (i.e., when an action had zero effect on the screen).
  - **Semantic Verification**: Check the agent's output thought/note field and feedback messages to determine if a sub-goal was completed successfully.
- Implement self-correction/backtracking: If stagnation is detected or the previous action failed, the harness must trigger an alternative action (e.g., retrying, clicking a fallback element, or backtracking) instead of repeating the same failed action.

## Acceptance Criteria

### Model Hosting & Optimization
- [ ] Llama-server starts successfully with Holo-3.1-9B GGUF and mmproj.
- [ ] Both model weights and vision encoder are fully loaded into GPU VRAM (visible in nvidia-smi).
- [ ] llama-server logs show Flash Attention and KV cache quantization are enabled.

### Harness Brain Integration
- [ ] VLM queries successfully prompt the model and return structured JSON actions.
- [ ] Screen observations are formatted with `<observation>` tags, and the assistant history is properly trimmed to 3 active images.

### Windows Native Input Automation
- [ ] Actions in `router.py` execute without importing or calling `pyautogui`.
- [ ] Clicks, double-clicks, and keyboard inputs function correctly via ctypes/Win32 APIs.
- [ ] Complex key shortcuts (like Win + R, Ctrl + C, Ctrl + V) execute and affect the OS successfully.

### Hybrid Verification & Self-Correction
- [ ] The agent loop compares screenshots between steps and flags step stagnation if the screen did not change after a click or keypress.
- [ ] In the event of stagnation or a failed action, the system backtracks or requests a self-corrected plan from the model rather than repeating the same input.
