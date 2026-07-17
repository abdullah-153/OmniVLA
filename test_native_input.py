import time
import sys
import ctypes
from ctypes import wintypes

try:
    from cogniagent.execution.win32_input import (
        enable_dpi_awareness,
        check_failsafe,
        set_cursor_pos,
        mouse_click,
        mouse_double_click,
        mouse_drag,
        mouse_scroll,
        type_text,
        key_press,
        hotkey
    )
except ImportError as e:
    print(f"Import failed: {e}")
    sys.exit(1)

def get_current_pos():
    user32 = ctypes.windll.user32
    point = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(point))
    return (point.x, point.y)

IS_NON_INTERACTIVE = False

def test_dpi_and_cursor_movement():
    global IS_NON_INTERACTIVE
    print("Testing DPI awareness enabling...")
    enable_dpi_awareness()
    print("DPI awareness enabled successfully.")
    
    # Check if we can actually set cursor position (interactive session check)
    if ctypes.windll.user32.SetCursorPos(100, 100) == 0:
        print("Non-interactive desktop session detected (SetCursorPos failed). Skipping cursor position assertions.")
        IS_NON_INTERACTIVE = True
        return
        
    print("Testing mouse movement to (100, 100)...")
    set_cursor_pos(100, 100)
    time.sleep(0.1)
    pos = get_current_pos()
    print(f"Current mouse position: {pos}")
    assert pos == (100, 100), f"Expected (100, 100), got {pos}"
    
    print("Testing mouse movement to (200, 300)...")
    set_cursor_pos(200, 300)
    time.sleep(0.1)
    pos = get_current_pos()
    print(f"Current mouse position: {pos}")
    assert pos == (200, 300), f"Expected (200, 300), got {pos}"
    print("Cursor movement test passed!")

def test_clicks():
    print("Testing mouse click...")
    mouse_click(150, 150, button="left")
    pos = get_current_pos()
    print(f"Mouse clicked at position: {pos}")
    if not IS_NON_INTERACTIVE:
        assert pos == (150, 150), f"Expected position to be (150, 150), got {pos}"
    
    print("Testing mouse double-click...")
    mouse_double_click(180, 180)
    pos = get_current_pos()
    print(f"Mouse double-clicked at position: {pos}")
    if not IS_NON_INTERACTIVE:
        assert pos == (180, 180), f"Expected position to be (180, 180), got {pos}"
    print("Clicks test passed!")

def test_scroll():
    print("Testing mouse scroll...")
    mouse_scroll(120)  # Scroll up
    time.sleep(0.05)
    mouse_scroll(-120) # Scroll down
    print("Scroll test passed!")

def test_drag():
    print("Testing smooth mouse drag...")
    start_pos = (100, 100)
    end_pos = (300, 300)
    mouse_drag(start_pos[0], start_pos[1], end_pos[0], end_pos[1], duration=0.2)
    pos = get_current_pos()
    print(f"Mouse dragged to position: {pos}")
    if not IS_NON_INTERACTIVE:
        assert pos == (300, 300), f"Expected drag to end at {end_pos}, got {pos}"
    print("Drag test passed!")

def test_typing_and_keys():
    print("Testing Unicode text typing...")
    type_text("Hello, Windows Native Input! 123", interval=0.01)
    
    print("Testing single key press (Enter)...")
    key_press("enter")
    
    print("Testing hotkey combo (Ctrl+C)...")
    hotkey("ctrl", "c")
    print("Typing and keys test passed!")

def test_failsafe():
    print("Testing fail-safe exception by moving cursor to (0, 0)...")
    if IS_NON_INTERACTIVE:
        print("Skipping failsafe test in non-interactive session.")
        return
    # Set cursor directly bypassing check_failsafe first
    ctypes.windll.user32.SetCursorPos(0, 0)
    time.sleep(0.1)
    
    try:
        check_failsafe()
        print("Error: check_failsafe() did not raise RuntimeError at (0, 0)")
        sys.exit(1)
    except RuntimeError as e:
        print(f"Success: Exception raised correctly: {e}")
        # Reset mouse to a safe position
        ctypes.windll.user32.SetCursorPos(500, 500)
        print("Failsafe test passed!")

def main():
    print("=== STARTING NATIVE WIN32 INPUT VERIFICATION ===")
    try:
        test_dpi_and_cursor_movement()
        test_clicks()
        test_scroll()
        test_drag()
        test_typing_and_keys()
        test_failsafe()
        print("=== ALL TESTS PASSED SUCCESSFULLY! ===")
    except Exception as e:
        print(f"=== TEST RUN FAILURE: {e} ===")
        if not IS_NON_INTERACTIVE:
            ctypes.windll.user32.SetCursorPos(500, 500)
        sys.exit(1)

if __name__ == "__main__":
    main()
