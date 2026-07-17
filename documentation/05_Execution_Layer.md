# OmniVLA: Execution Layer
## Document 05 — Action-to-System-Input Translation

---

## 1. Execution Philosophy

The Execution Layer is the bridge between the LLM's **semantic intent** and the **physical system input**. It must be:

1. **Deterministic**: Given the same action and state, always produce the same system input
2. **Reliable**: Prefer methods that are resolution-independent and UI-layout-agnostic
3. **Defensive**: Handle edge cases (element moved, window changed, app crashed)
4. **Fast**: Execute within 300ms including all safety checks

---

## 2. Execution Fallback Chain

The Execution Layer tries methods in order of reliability, falling back to the next if the current method fails:

```
┌─────────────────────────────────────────────────────────────────┐
│                 EXECUTION PRIORITY CHAIN                         │
│                                                                   │
│  Priority 1: KEYBOARD SHORTCUT                                  │
│  ┌────────────────────────────────────────────────────────┐     │
│  │ ✓ Resolution independent                               │     │
│  │ ✓ Layout independent                                   │     │
│  │ ✓ Fastest execution (~10ms)                            │     │
│  │ ✓ Works even when element is off-screen                │     │
│  │ ✗ Only available for common operations                 │     │
│  └────────────────────────────────────────────────────────┘     │
│                         │                                        │
│                    Not available?                                │
│                         │                                        │
│  Priority 2: UIA CONTROL INVOCATION                             │
│  ┌────────────────────────────────────────────────────────┐     │
│  │ ✓ Programmatic element interaction (no mouse needed)    │     │
│  │ ✓ Resolution independent                               │     │
│  │ ✓ Works on minimized/overlapped windows                │     │
│  │ ✗ Only works with UIA-compatible apps                  │     │
│  │ ✗ Requires element handle from perception              │     │
│  └────────────────────────────────────────────────────────┘     │
│                         │                                        │
│                    Not available?                                │
│                         │                                        │
│  Priority 3: COORDINATE CLICK (PyAutoGUI)                       │
│  ┌────────────────────────────────────────────────────────┐     │
│  │ ✓ Universal — works on any visible element             │     │
│  │ ✗ Requires accurate coordinates from perception        │     │
│  │ ✗ Resolution dependent                                 │     │
│  │ ✗ Fails if element moves or is obscured                │     │
│  │ ✗ Requires mouse to physically move                    │     │
│  └────────────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. Priority 1: Keyboard Shortcuts

### 3.1 Comprehensive Shortcut Knowledge Base

```python
SHORTCUTS = {
    # ─── Universal Windows Shortcuts ───
    "_global": {
        "copy": ["ctrl", "c"],
        "paste": ["ctrl", "v"],
        "cut": ["ctrl", "x"],
        "undo": ["ctrl", "z"],
        "redo": ["ctrl", "y"],
        "save": ["ctrl", "s"],
        "save_as": ["ctrl", "shift", "s"],
        "select_all": ["ctrl", "a"],
        "find": ["ctrl", "f"],
        "print": ["ctrl", "p"],
        "new": ["ctrl", "n"],
        "open": ["ctrl", "o"],
        "close": ["alt", "f4"],
        "switch_app": ["alt", "tab"],
        "task_manager": ["ctrl", "shift", "escape"],
        "start_menu": ["win"],
        "run": ["win", "r"],
        "lock": ["win", "l"],
        "screenshot": ["win", "shift", "s"],
        "settings": ["win", "i"],
        "file_explorer": ["win", "e"],
        "desktop": ["win", "d"],
    },
    
    # ─── Chrome / Edge ───
    "Chrome": {
        "new_tab": ["ctrl", "t"],
        "close_tab": ["ctrl", "w"],
        "reopen_tab": ["ctrl", "shift", "t"],
        "next_tab": ["ctrl", "tab"],
        "prev_tab": ["ctrl", "shift", "tab"],
        "address_bar": ["ctrl", "l"],
        "refresh": ["f5"],
        "hard_refresh": ["ctrl", "shift", "r"],
        "back": ["alt", "left"],
        "forward": ["alt", "right"],
        "downloads": ["ctrl", "j"],
        "history": ["ctrl", "h"],
        "bookmark": ["ctrl", "d"],
        "dev_tools": ["f12"],
        "zoom_in": ["ctrl", "="],
        "zoom_out": ["ctrl", "-"],
        "zoom_reset": ["ctrl", "0"],
        "page_source": ["ctrl", "u"],
    },
    
    # ─── Microsoft Excel ───
    "Excel": {
        "new_workbook": ["ctrl", "n"],
        "save": ["ctrl", "s"],
        "bold": ["ctrl", "b"],
        "italic": ["ctrl", "i"],
        "underline": ["ctrl", "u"],
        "format_cells": ["ctrl", "1"],
        "insert_function": ["shift", "f3"],
        "autosum": ["alt", "="],
        "find_replace": ["ctrl", "h"],
        "go_to": ["ctrl", "g"],
        "insert_row": ["ctrl", "shift", "="],
        "delete_row": ["ctrl", "-"],
        "select_column": ["ctrl", "space"],
        "select_row": ["shift", "space"],
        "fill_down": ["ctrl", "d"],
        "fill_right": ["ctrl", "r"],
        "name_box": ["ctrl", "f5"],
        "next_sheet": ["ctrl", "pagedown"],
        "prev_sheet": ["ctrl", "pageup"],
        "insert_chart": ["alt", "f1"],
    },
    
    # ─── VS Code ───
    "VS Code": {
        "command_palette": ["ctrl", "shift", "p"],
        "quick_open": ["ctrl", "p"],
        "terminal": ["ctrl", "`"],
        "new_terminal": ["ctrl", "shift", "`"],
        "sidebar": ["ctrl", "b"],
        "explorer": ["ctrl", "shift", "e"],
        "search": ["ctrl", "shift", "f"],
        "git": ["ctrl", "shift", "g"],
        "debug": ["ctrl", "shift", "d"],
        "extensions": ["ctrl", "shift", "x"],
        "go_to_definition": ["f12"],
        "go_back": ["alt", "left"],
        "format_document": ["shift", "alt", "f"],
        "toggle_comment": ["ctrl", "/"],
        "multi_cursor": ["ctrl", "alt", "down"],
        "select_word": ["ctrl", "d"],
    },
    
    # ─── File Explorer ───
    "File Explorer": {
        "new_folder": ["ctrl", "shift", "n"],
        "rename": ["f2"],
        "delete": ["delete"],
        "permanent_delete": ["shift", "delete"],
        "properties": ["alt", "enter"],
        "address_bar": ["ctrl", "l"],
        "search": ["ctrl", "e"],
        "refresh": ["f5"],
        "back": ["alt", "left"],
        "parent": ["alt", "up"],
        "preview_pane": ["alt", "p"],
        "details_pane": ["alt", "shift", "p"],
    },
    
    # ─── Notepad / Text Editors ───
    "Notepad": {
        "new": ["ctrl", "n"],
        "open": ["ctrl", "o"],
        "save": ["ctrl", "s"],
        "save_as": ["ctrl", "shift", "s"],
        "find": ["ctrl", "f"],
        "replace": ["ctrl", "h"],
        "go_to": ["ctrl", "g"],
        "select_all": ["ctrl", "a"],
        "time_date": ["f5"],
        "word_wrap": ["alt", "o", "w"],
    },
    
    # ─── Microsoft Word ───
    "Word": {
        "new": ["ctrl", "n"],
        "save": ["ctrl", "s"],
        "bold": ["ctrl", "b"],
        "italic": ["ctrl", "i"],
        "underline": ["ctrl", "u"],
        "center": ["ctrl", "e"],
        "left_align": ["ctrl", "l"],
        "right_align": ["ctrl", "r"],
        "justify": ["ctrl", "j"],
        "increase_font": ["ctrl", "shift", ">"],
        "decrease_font": ["ctrl", "shift", "<"],
        "line_spacing": ["ctrl", "2"],  # double space
        "page_break": ["ctrl", "enter"],
        "word_count": ["ctrl", "shift", "g"],
    },
}

def find_shortcut(app_name: str, element_label: str) -> list[str] | None:
    """Look up a keyboard shortcut for an element in the current app."""
    label_lower = element_label.lower().strip()
    
    # Check app-specific shortcuts first
    app_shortcuts = SHORTCUTS.get(app_name, {})
    for intent, keys in app_shortcuts.items():
        if intent.replace("_", " ") in label_lower or label_lower in intent:
            return keys
    
    # Check global shortcuts
    for intent, keys in SHORTCUTS["_global"].items():
        if intent.replace("_", " ") in label_lower or label_lower in intent:
            return keys
    
    return None
```

---

## 4. Priority 2: UIA Control Invocation

### 4.1 Direct Element Invocation

When UIA elements have control patterns, we can invoke them directly without mouse movement:

```python
def invoke_via_uia(element_handle, element_type: str) -> bool:
    """Invoke a UIA element directly via its control pattern."""
    try:
        import pywinauto
        from pywinauto.controls.uiawrapper import UIAWrapper
        
        wrapper = UIAWrapper(element_handle)
        
        if element_type in ("button", "menu_item", "link", "tab"):
            # InvokePattern — equivalent to clicking
            wrapper.invoke()
            return True
            
        elif element_type == "checkbox":
            # TogglePattern — check/uncheck
            wrapper.toggle()
            return True
            
        elif element_type == "text_field":
            # ValuePattern — set text directly
            wrapper.set_focus()
            return True
            
        elif element_type == "dropdown":
            # ExpandCollapsePattern — open dropdown
            wrapper.expand()
            return True
            
    except Exception as e:
        logger.warning("UIA invocation failed: %s", e)
        return False
```

### 4.2 UIA Advantages

| Feature | UIA Invoke | Mouse Click |
|---------|-----------|------------|
| Works when window is partially covered | ✓ | ✗ |
| Independent of element position | ✓ | ✗ |
| Works at any DPI/scaling | ✓ | ✗ |
| No mouse cursor interference | ✓ | ✗ |
| Speed | ~5ms | ~50ms |
| Works on hidden elements | Sometimes | Never |

---

## 5. Priority 3: Coordinate Click

### 5.1 Implementation

When shortcuts and UIA are unavailable, we fall back to mouse-based clicking:

```python
import pyautogui
import time

pyautogui.FAILSAFE = True   # Move mouse to corner = abort
pyautogui.PAUSE = 0.1       # Minimum pause between actions

def click_at_coordinates(cx: int, cy: int, click_type: str = "left"):
    """Click at specific screen coordinates."""
    # Move mouse smoothly to target
    pyautogui.moveTo(cx, cy, duration=0.15)
    
    # Brief pause for hover effects
    time.sleep(0.05)
    
    # Click
    if click_type == "left":
        pyautogui.click(cx, cy)
    elif click_type == "right":
        pyautogui.rightClick(cx, cy)
    elif click_type == "double":
        pyautogui.doubleClick(cx, cy)
    
    # Post-click pause for UI response
    time.sleep(0.2)

def type_text(text: str, interval: float = 0.02):
    """Type text character by character."""
    # Use pyautogui.write for ASCII text
    if all(ord(c) < 128 for c in text):
        pyautogui.write(text, interval=interval)
    else:
        # For Unicode text, use clipboard paste
        import pyperclip
        pyperclip.copy(text)
        pyautogui.hotkey("ctrl", "v")

def press_key_combo(keys: list[str]):
    """Press a keyboard shortcut."""
    pyautogui.hotkey(*keys)
    time.sleep(0.1)
```

### 5.2 Click Accuracy Enhancement

When using coordinate clicks, we can improve accuracy with a small "micro-snap":

```python
def enhanced_click(element, frame_pixels):
    """Click with micro-snap correction for better accuracy."""
    cx, cy = element.center
    
    # Get a small region around the predicted center
    margin = 15
    x1 = max(0, cx - margin)
    y1 = max(0, cy - margin)
    x2 = min(frame_pixels.shape[1], cx + margin)
    y2 = min(frame_pixels.shape[0], cy + margin)
    
    roi = frame_pixels[y1:y2, x1:x2]
    
    # Find the visual center of the element in the ROI
    # (using edge detection to find the element boundary)
    import cv2
    gray = cv2.cvtColor(roi, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, 50, 150)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, 
                                     cv2.CHAIN_APPROX_SIMPLE)
    
    if contours:
        # Find the largest contour (likely the element)
        largest = max(contours, key=cv2.contourArea)
        M = cv2.moments(largest)
        if M["m00"] > 0:
            # Adjust click to contour center
            snap_cx = int(M["m10"] / M["m00"]) + x1
            snap_cy = int(M["m01"] / M["m00"]) + y1
            cx, cy = snap_cx, snap_cy
    
    click_at_coordinates(cx, cy)
```

---

## 6. Action Router Implementation

```python
class ActionRouter:
    """Routes semantic actions to system inputs using the fallback chain."""
    
    def execute(self, action: AgentAction, state: SemanticState) -> dict:
        """Execute an action with automatic fallback."""
        
        if action.action_type == "click":
            return self._execute_click(action, state)
        elif action.action_type == "type":
            return self._execute_type(action)
        elif action.action_type == "key":
            return self._execute_key(action)
        elif action.action_type == "scroll":
            return self._execute_scroll(action)
        elif action.action_type == "wait":
            return self._execute_wait(action)
        elif action.action_type == "done":
            return {"success": True, "detail": "Sub-goal complete"}
        elif action.action_type == "fail":
            return {"success": False, 
                    "detail": f"Agent: {action.args[0]}"}
    
    def _execute_click(self, action, state) -> dict:
        """Execute click with full fallback chain."""
        element = self._find_element(int(action.args[0]), state)
        if not element:
            return {"success": False, 
                    "detail": f"Element {action.args[0]} not found"}
        
        # PRIORITY 1: Try keyboard shortcut
        shortcut = find_shortcut(state.app, element.label)
        if shortcut:
            press_key_combo(shortcut)
            return {"success": True, 
                    "detail": f"Shortcut {'+'.join(shortcut)}",
                    "method": "shortcut"}
        
        # PRIORITY 2: Try UIA invocation
        if element.source == "uia" and hasattr(element, "uia_handle"):
            if invoke_via_uia(element.uia_handle, element.type):
                return {"success": True, 
                        "detail": f"UIA invoke '{element.label}'",
                        "method": "uia"}
        
        # PRIORITY 3: Coordinate click
        click_at_coordinates(element.center[0], element.center[1])
        return {"success": True, 
                "detail": f"Clicked ({element.center[0]}, {element.center[1]})",
                "method": "coordinate"}
```

---

## 7. Safety Mechanisms

### 7.1 Destructive Action Detection

```python
DESTRUCTIVE_PATTERNS = {
    "delete", "remove", "erase", "clear all", "format drive",
    "uninstall", "drop table", "rm -rf", "shutdown", "restart",
    "factory reset", "permanent", "overwrite"
}

def is_destructive(action: AgentAction, state: SemanticState) -> bool:
    """Check if an action might be destructive."""
    if action.action_type == "click":
        element = find_element(int(action.args[0]), state)
        if element:
            return any(p in element.label.lower() 
                      for p in DESTRUCTIVE_PATTERNS)
    
    if action.action_type == "key":
        combo = action.args[0].lower()
        dangerous = ["alt+f4", "ctrl+shift+delete", "delete"]
        return combo in dangerous
    
    return False
```

### 7.2 User Confirmation for Destructive Actions

```python
def execute_with_safety(self, action, state):
    """Execute action with safety checks."""
    if is_destructive(action, state):
        if self.config.confirm_destructive:
            # Pause and ask user
            console.print(
                f"[yellow]⚠ Destructive action detected: "
                f"{action.action_type}({action.args})[/yellow]"
            )
            response = console.input("[yellow]Proceed? (y/n): [/yellow]")
            if response.lower() != "y":
                return {"success": False, 
                        "detail": "User cancelled destructive action"}
    
    return self.execute(action, state)
```

### 7.3 PyAutoGUI Failsafe

PyAutoGUI has a built-in failsafe: if the mouse cursor is moved to any corner of the screen, all PyAutoGUI functions will raise `FailSafeException`. This provides an emergency stop mechanism.

```python
pyautogui.FAILSAFE = True  # Always enabled
```

---

## 8. Execution Timing

### 8.1 Action Timing Budget

```
Shortcut execution:        10-30ms
UIA invocation:             5-20ms
Coordinate click:          50-200ms (includes mouse movement)
Text typing:               20ms × (number of characters)
Post-action pause:          200-500ms (wait for UI response)
─────────────────────────────────────
Total per action:           250-700ms
```

### 8.2 Adaptive Pausing

Some actions need longer pauses than others:

```python
POST_ACTION_PAUSES = {
    "click": {
        "button": 0.3,      # Normal button click
        "menu_item": 0.5,   # Menu items need time to expand
        "tab": 0.3,         # Tab switching
        "link": 1.0,        # Page navigation (may load)
        "dropdown": 0.3,    # Dropdown expansion
    },
    "key": {
        "default": 0.2,
        "alt+f4": 1.0,      # App closing
        "ctrl+n": 1.0,      # New window/document
        "ctrl+s": 0.5,      # Save operation
    },
    "type": 0.1,             # Minimal pause after typing
    "scroll": 0.3,           # Scroll animation
}
```

---

## 9. Cross-Application Execution

### 9.1 App Switching

When a task requires moving between applications:

```python
def switch_to_app(target_app: str) -> bool:
    """Switch to a target application."""
    
    # Try Alt+Tab cycling
    import pywinauto
    app = pywinauto.Desktop(backend="uia")
    
    for window in app.windows():
        if target_app.lower() in window.window_text().lower():
            window.set_focus()
            time.sleep(0.5)
            return True
    
    # App not found — try starting it
    return start_app(target_app)

def start_app(app_name: str) -> bool:
    """Start an application via Start Menu search."""
    pyautogui.press("win")
    time.sleep(0.5)
    pyautogui.write(app_name, interval=0.05)
    time.sleep(1.0)  # Wait for search results
    pyautogui.press("enter")
    time.sleep(2.0)  # Wait for app to start
    return True
```

### 9.2 Handling App Launch Delays

```python
def wait_for_app(app_name: str, timeout: float = 10.0) -> bool:
    """Wait for an application to become ready."""
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        try:
            title = get_active_window_title()
            if app_name.lower() in title.lower():
                return True
        except:
            pass
        time.sleep(0.5)
    
    return False  # Timeout
```

---

*Document Version: 1.0 | Part 05 of 08*
*See also: [06_Memory_And_Verification](./06_Memory_And_Verification.md) for post-execution verification*
