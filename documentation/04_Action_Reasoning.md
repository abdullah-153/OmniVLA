# OmniVLA: Action Reasoning
## Document 04 — VLM Action Generation

---

## 1. Single-Step Reasoning Architecture

OmniVLA relies on **Mano-P** (a Qwen2.5-VL derivative) to bridge the gap between visual perception and system execution.

The legacy architecture separated reasoning (LLM) and perception (CV/UIA) into distinct steps. The new VLM architecture unifies them into a single step:

```
[Screenshot] + [Task + History] ──► Mano-P ──► [Thoughts + Action Coordinates]
```

---

## 2. The Thought Process (`<think>`)

Mano-P generates Chain-of-Thought (CoT) reasoning before committing to an action. This step is critical because it forces the model to visually locate elements and plan the next logical step before outputting exact coordinates.

Example `<think>` block from the model:
```xml
<think>
The user wants me to search for 'MLX framework'.
I see the Safari browser is open. 
The address/search bar is located at the top center of the window.
I need to click it to focus the input field, then type the search query.
</think>
```

---

## 3. Supported Action Space

The reasoning engine outputs specific commands that the ActionRouter parses. All coordinates are normalized to `[0, 1000]`.

| Action | Format | Description |
|--------|--------|-------------|
| **Click** | `click(start_box='<\|box_start\|>(x,y)<\|box_end\|>')` | Standard left-click. Center of box is used. |
| **Double Click**| `doubleclick(...)` | Double left-click. |
| **Right Click** | `right_single(...)` | Context menu invocation. |
| **Type** | `type(content='text')` | Keystroke emulation. |
| **Hotkey** | `hotkey(key='cmd+c')` | Keyboard shortcuts. |
| **Scroll** | `scroll(start_box='...', direction='down', amount='3')` | Wheel scrolling over a specific area. |
| **Drag** | `drag(start_box='...', end_box='...')` | Click and drag operations. |
| **Finish** | `finish()` | Task successfully completed. |
| **Stop** | `stop(reason='...')` | Task is impossible or failed. |

---

## 4. History as Context

To allow the VLM to correct its mistakes or avoid repeating loops, the action history is fed back into the prompt on every turn. 

```text
### action history:
Step 1: Click the search bar to focus it
Step 2: Type 'MLX framework'
Step 3: Press Enter to search
```

If the execution layer fails (e.g., coordinates out of bounds), a failure step is appended to the history so the model knows its previous action did not have the intended effect.

---

*Document Version: 2.0 | Part 04 of 08*
*See also: [05_Execution_Layer](./05_Execution_Layer.md) for how actions are translated to PyAutoGUI.*
