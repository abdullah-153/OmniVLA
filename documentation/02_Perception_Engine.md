# OmniVLA: Perception Engine
## Document 02 — VLM-Based Perception

---

## 1. The Perception Problem Solved

Traditional perception engines rely on complex heuristics, UI tree extractions (UIA), and Optical Character Recognition (OCR) to build text-based semantic states. These methods are brittle, fail on custom UI elements, and struggle with visual context.

OmniVLA abandons this approach. By utilizing **Mano-P**, an end-to-end Vision-Language Model, the "Perception Engine" is seamlessly integrated into the model's forward pass.

### Why VLM Perception is Superior

| Feature | Legacy (UIA/OCR) | VLM (Mano-P) |
|----------|-------------|-------------|
| **Coverage** | Fails on games, custom canvases | 100% (sees what the user sees) |
| **Context** | Struggles with visual hierarchy | Inherently understands spatial layouts |
| **Speed** | 100-500ms pipeline | Processed during inference prefill |
| **Codebase** | Thousands of lines of heuristics | < 100 lines of image capture |

---

## 2. VLM Perception Pipeline

The perception pipeline is now responsible only for capturing the screen, formatting it correctly, and passing it to the VLM.

```python
import mss
from PIL import Image

def capture_screen(resize_width=1280):
    """Captures the screen and resizes it for Mano-P."""
    with mss.mss() as sct:
        monitor = sct.monitors[1]  # primary monitor
        sct_img = sct.grab(monitor)
        img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
        
        # Mano-P expects ~1280px width for optimal resolution/token trade-off
        ratio = resize_width / img.width
        new_height = int(img.height * ratio)
        img_resized = img.resize((resize_width, new_height), Image.LANCZOS)
        
        return img_resized, (img.width, img.height)
```

---

## 3. Grounding & Coordinate Mapping

When Mano-P decides to click an element, it outputs a bounding box using normalized coordinates in a `(0, 1000)` range. 

For example:
`<action>click(start_box='<|box_start|>(356,948),(380,992)<|box_end|>')</action>`

The perception/execution layer must map these normalized coordinates back to absolute screen pixels to perform the mouse interaction.

### Coordinate Conversion Math

```python
# Convert from 0-1000 normalized scale to actual image pixels
pixel_x = int((normalized_x / 1000.0) * screen_width)
pixel_y = int((normalized_y / 1000.0) * screen_height)
```

For bounding boxes `(x1, y1), (x2, y2)`, OmniVLA calculates the center point `(cx, cy)` to guarantee the click lands securely within the element.

---

## 4. Prompt Engineering for VLM Grounding

To guarantee the model outputs the correct `<think>` and `<action>` tags, the perception context must be wrapped in a strict system prompt.

```text
You are a GUI agent. You are given a task and your action history, with screenshots. You need to perform the next action to complete the task.

## Output Format
<think>thoughts</think>
<action_desp>action description</action_desp>
<action>action call</action>

## Action Space
click(start_box='<|box_start|>(x1,y1)<|box_end|>')
...

## User Instruction:
### task: {task}
### action history: {history}
Current screenshot: <image>
```

---

*Document Version: 2.0 | Part 02 of 08*
*See also: [04_Action_Reasoning](./04_Action_Reasoning.md) for how the model plans its next steps.*
