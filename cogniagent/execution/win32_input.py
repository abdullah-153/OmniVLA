import ctypes
import time
from ctypes import wintypes

# --- Constants ---
# Input Types
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
INPUT_HARDWARE = 2

# Mouse Flags
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_VIRTUALDESK = 0x4000
MOUSEEVENTF_ABSOLUTE = 0x8000

# Keyboard Flags
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_SCANCODE = 0x0008

# MapVirtualKey Mapping Types
MAPVK_VK_TO_VSC = 0

# --- Structure Definitions ---
ULONG_PTR = ctypes.c_size_t

class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ULONG_PTR)
    ]

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ULONG_PTR)
    ]

class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", ctypes.c_ulong),
        ("wParamL", ctypes.c_ushort),
        ("wParamH", ctypes.c_ushort)
    ]

class INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT)
    ]

class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_ulong),
        ("ii", INPUT_UNION)
    ]

# --- Function Signatures ---
user32 = ctypes.windll.user32

# Configure SendInput
user32.SendInput.argtypes = [
    ctypes.c_uint,
    ctypes.c_void_p,
    ctypes.c_int
]
user32.SendInput.restype = ctypes.c_uint

# Configure MapVirtualKeyW
user32.MapVirtualKeyW.argtypes = [ctypes.c_uint, ctypes.c_uint]
user32.MapVirtualKeyW.restype = ctypes.c_uint

# Configure SetCursorPos / GetCursorPos / GetSystemMetrics
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.SetCursorPos.restype = wintypes.BOOL

user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.GetCursorPos.restype = wintypes.BOOL

user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int


# --- Key Mapping Dict ---
VK_MAP = {
    # Control keys
    'backspace': 0x08, 'tab': 0x09, 'clear': 0x0C, 'enter': 0x0D, 'return': 0x0D,
    'shift': 0x10, 'ctrl': 0x11, 'control': 0x11, 'alt': 0x12, 'option': 0x12,
    'pause': 0x13, 'capslock': 0x14, 'escape': 0x1B, 'esc': 0x1B, 'space': 0x20,
    'pageup': 0x21, 'pgup': 0x21, 'pagedown': 0x22, 'pgdn': 0x22, 'end': 0x23,
    'home': 0x24, 'left': 0x25, 'up': 0x26, 'right': 0x27, 'down': 0x28,
    'select': 0x29, 'print': 0x2A, 'execute': 0x2B, 'prtscr': 0x2C, 'prntscrn': 0x2C,
    'insert': 0x2D, 'ins': 0x2D, 'delete': 0x2E, 'del': 0x2E,
    'win': 0x5B, 'winleft': 0x5B, 'winright': 0x5C, 'command': 0x5B, 'apps': 0x5D,
    'num0': 0x60, 'num1': 0x61, 'num2': 0x62, 'num3': 0x63, 'num4': 0x64,
    'num5': 0x65, 'num6': 0x66, 'num7': 0x67, 'num8': 0x68, 'num9': 0x69,
    'f1': 0x70, 'f2': 0x71, 'f3': 0x72, 'f4': 0x73, 'f5': 0x74, 'f6': 0x75,
    'f7': 0x76, 'f8': 0x77, 'f9': 0x78, 'f10': 0x79, 'f11': 0x7A, 'f12': 0x7B,
    'numlock': 0x90, 'scrolllock': 0x91,
    'lshift': 0xA0, 'left_shift': 0xA0, 'rshift': 0xA1, 'right_shift': 0xA1,
    'lctrl': 0xA2, 'left_ctrl': 0xA2, 'rctrl': 0xA3, 'right_ctrl': 0xA3,
    'lalt': 0xA4, 'left_alt': 0xA4, 'ralt': 0xA5, 'right_alt': 0xA5,
}


# --- API Implementations ---

def enable_dpi_awareness():
    """Enable DPI awareness so absolute screen coordinates map correctly."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def check_failsafe():
    """Abort if the cursor is at a virtual-desktop corner.

    Windows reports cursor coordinates in the virtual desktop.  Using only the
    primary-monitor dimensions misclassified valid secondary-monitor positions
    (including negative coordinates) and could either abort incorrectly or
    miss a real corner.
    """
    point = wintypes.POINT()
    if user32.GetCursorPos(ctypes.byref(point)):
        x, y = point.x, point.y
        left = user32.GetSystemMetrics(76)   # SM_XVIRTUALSCREEN
        top = user32.GetSystemMetrics(77)    # SM_YVIRTUALSCREEN
        w = user32.GetSystemMetrics(78)      # SM_CXVIRTUALSCREEN
        h = user32.GetSystemMetrics(79)      # SM_CYVIRTUALSCREEN
        if w <= 0 or h <= 0:
            left = top = 0
            w = user32.GetSystemMetrics(0)
            h = user32.GetSystemMetrics(1)
        if w <= 0 or h <= 0:
            return
        right = left + w - 1
        bottom = top + h - 1
        
        # Corners of the full virtual desktop.
        # We check within a small 2-pixel margin
        if (x <= left + 2 and y <= top + 2) or \
           (x <= left + 2 and y >= bottom - 2) or \
           (x >= right - 2 and y <= top + 2) or \
           (x >= right - 2 and y >= bottom - 2):
            raise RuntimeError("FailSafeException: Mouse moved to a corner of the screen. Aborting execution.")


def get_screen_dimensions():
    """Get physical and logical dimensions of the primary screen."""
    try:
        hdc = ctypes.windll.user32.GetDC(0)
        # HORZRES = 8, VERTRES = 10, DESKTOPHORZRES = 118, DESKTOPVERTRES = 117
        logical_w = ctypes.windll.gdi32.GetDeviceCaps(hdc, 8)
        logical_h = ctypes.windll.gdi32.GetDeviceCaps(hdc, 10)
        physical_w = ctypes.windll.gdi32.GetDeviceCaps(hdc, 118)
        physical_h = ctypes.windll.gdi32.GetDeviceCaps(hdc, 117)
        ctypes.windll.user32.ReleaseDC(0, hdc)
        if logical_w > 0 and physical_w > 0:
            return physical_w, physical_h, logical_w, logical_h
    except Exception:
        pass
    w = user32.GetSystemMetrics(0)
    h = user32.GetSystemMetrics(1)
    return w, h, w, h


def get_cursor_pos():
    """Retrieve the current cursor position in logical coordinates."""
    point = wintypes.POINT()
    if user32.GetCursorPos(ctypes.byref(point)):
        return point.x, point.y
    return 0, 0


def smooth_move_to(x: int, y: int, duration: float = 0.35):
    """Move cursor smoothly to absolute virtual-desktop pixel coordinates."""
    check_failsafe()
    target_x = int(x)
    target_y = int(y)
    start_x, start_y = get_cursor_pos()
    
    # Calculate steps at ~60 Hz
    steps = int(duration * 60)
    if steps < 1:
        steps = 1
        
    for i in range(1, steps + 1):
        check_failsafe()
        t = i / steps
        # Smooth step / cubic ease-in-out interpolation
        t_smooth = t * t * (3 - 2 * t)
        curr_x = int(start_x + (target_x - start_x) * t_smooth)
        curr_y = int(start_y + (target_y - start_y) * t_smooth)
        user32.SetCursorPos(curr_x, curr_y)
        time.sleep(duration / steps)
        
    # Ensure final coordinate is exactly reached
    user32.SetCursorPos(target_x, target_y)
    time.sleep(0.05)


def set_cursor_pos(x: int, y: int):
    """Directly position the cursor in virtual-desktop physical pixels.

    The process is per-monitor DPI-aware, so SetCursorPos already expects the
    same physical coordinates returned by mss and UI Automation.  Additional
    primary-monitor scaling caused drift on high-DPI and multi-monitor setups.
    """
    check_failsafe()
    user32.SetCursorPos(int(x), int(y))


def move_to(x: int, y: int):
    """Move the mouse to absolute virtual-desktop coordinates."""
    set_cursor_pos(x, y)


def mouse_click(x: int, y: int, button: str = "left"):
    """Move cursor smoothly and execute click using SendInput."""
    check_failsafe()
    
    from cogniagent.config import config
    pause = getattr(config.execution, "click_pause", 0.3)
    
    if pause == 0.0:
        set_cursor_pos(x, y)
    else:
        # Move smoothly over a fraction of the pause or default 0.25s
        smooth_move_to(x, y, duration=min(0.25, pause))
        time.sleep(0.05)
    
    if button == "left":
        down_flag = MOUSEEVENTF_LEFTDOWN
        up_flag = MOUSEEVENTF_LEFTUP
    elif button == "right":
        down_flag = MOUSEEVENTF_RIGHTDOWN
        up_flag = MOUSEEVENTF_RIGHTUP
    elif button == "middle":
        down_flag = MOUSEEVENTF_MIDDLEDOWN
        up_flag = MOUSEEVENTF_MIDDLEUP
    else:
        raise ValueError(f"Unknown button: {button}")

    inputs = (INPUT * 2)()
    
    # Down event
    inputs[0].type = INPUT_MOUSE
    inputs[0].ii.mi.dx = 0
    inputs[0].ii.mi.dy = 0
    inputs[0].ii.mi.mouseData = 0
    inputs[0].ii.mi.dwFlags = down_flag
    inputs[0].ii.mi.time = 0
    inputs[0].ii.mi.dwExtraInfo = 0
    
    # Up event
    inputs[1].type = INPUT_MOUSE
    inputs[1].ii.mi.dx = 0
    inputs[1].ii.mi.dy = 0
    inputs[1].ii.mi.mouseData = 0
    inputs[1].ii.mi.dwFlags = up_flag
    inputs[1].ii.mi.time = 0
    inputs[1].ii.mi.dwExtraInfo = 0
    
    user32.SendInput(2, inputs, ctypes.sizeof(INPUT))


def mouse_double_click(x: int, y: int):
    """Execute double-click using SetCursorPos and SendInput."""
    check_failsafe()
    mouse_click(x, y, "left")
    time.sleep(0.05)  # 50ms delay between clicks
    mouse_click(x, y, "left")


def mouse_drag(x1: int, y1: int, x2: int, y2: int, duration: float = 0.5):
    """Simulate a smooth mouse drag from (x1, y1) to (x2, y2) using SendInput and interpolation."""
    check_failsafe()
    set_cursor_pos(x1, y1)
    time.sleep(0.05)
    
    # Send LEFTDOWN
    down_input = (INPUT * 1)()
    down_input[0].type = INPUT_MOUSE
    down_input[0].ii.mi.dx = 0
    down_input[0].ii.mi.dy = 0
    down_input[0].ii.mi.mouseData = 0
    down_input[0].ii.mi.dwFlags = MOUSEEVENTF_LEFTDOWN
    down_input[0].ii.mi.time = 0
    down_input[0].ii.mi.dwExtraInfo = 0
    user32.SendInput(1, down_input, ctypes.sizeof(INPUT))
    time.sleep(0.05)
    
    steps = int(duration * 60)  # 60Hz update rate
    if steps < 1:
        steps = 1
        
    for i in range(1, steps + 1):
        check_failsafe()
        t = i / steps
        curr_x = int(x1 + (x2 - x1) * t)
        curr_y = int(y1 + (y2 - y1) * t)
        user32.SetCursorPos(curr_x, curr_y)
        
        time.sleep(duration / steps)
        
    set_cursor_pos(x2, y2)
    time.sleep(0.05)
    
    # Send LEFTUP
    up_input = (INPUT * 1)()
    up_input[0].type = INPUT_MOUSE
    up_input[0].ii.mi.dx = 0
    up_input[0].ii.mi.dy = 0
    up_input[0].ii.mi.mouseData = 0
    up_input[0].ii.mi.dwFlags = MOUSEEVENTF_LEFTUP
    up_input[0].ii.mi.time = 0
    up_input[0].ii.mi.dwExtraInfo = 0
    user32.SendInput(1, up_input, ctypes.sizeof(INPUT))
    time.sleep(0.05)


def mouse_scroll(amount: int):
    """Scroll mouse wheel using SendInput. Positive value scrolls UP, negative DOWN."""
    check_failsafe()
    unsigned_amount = amount & 0xFFFFFFFF
    
    scroll_input = (INPUT * 1)()
    scroll_input[0].type = INPUT_MOUSE
    scroll_input[0].ii.mi.dx = 0
    scroll_input[0].ii.mi.dy = 0
    scroll_input[0].ii.mi.mouseData = unsigned_amount
    scroll_input[0].ii.mi.dwFlags = MOUSEEVENTF_WHEEL
    scroll_input[0].ii.mi.time = 0
    scroll_input[0].ii.mi.dwExtraInfo = 0
    
    user32.SendInput(1, scroll_input, ctypes.sizeof(INPUT))


def resolve_vk(key: str) -> int:
    """Resolve key name (or single character/digit) to its Virtual Keycode."""
    k = key.lower()
    if k in VK_MAP:
        return VK_MAP[k]
    if len(key) == 1:
        val = ord(key.upper())
        if (0x30 <= val <= 0x39) or (0x41 <= val <= 0x5A):  # 0-9, A-Z
            return val
        
        punctuation_vks = {
            ';': 0xBA, '=': 0xBB, ',': 0xBC, '-': 0xBD, '.': 0xBE, '/': 0xBF, '`': 0xC0,
            '[': 0xDB, '\\': 0xDC, ']': 0xDD, "'": 0xDE
        }
        if key in punctuation_vks:
            return punctuation_vks[key]
            
    raise ValueError(f"Unsupported key identifier: {key}")


def key_down(key: str):
    """Send key down event using SendInput."""
    check_failsafe()
    vk = resolve_vk(key)
    scan = user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)
    
    extended = 0
    if vk in [0x14, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x5B, 0x5C]:
        extended = KEYEVENTF_EXTENDEDKEY
        
    inputs = (INPUT * 1)()
    inputs[0].type = INPUT_KEYBOARD
    inputs[0].ii.ki.wVk = vk
    inputs[0].ii.ki.wScan = scan
    inputs[0].ii.ki.dwFlags = extended
    inputs[0].ii.ki.time = 0
    inputs[0].ii.ki.dwExtraInfo = 0
    
    user32.SendInput(1, inputs, ctypes.sizeof(INPUT))


def key_up(key: str):
    """Send key up event using SendInput."""
    check_failsafe()
    vk = resolve_vk(key)
    scan = user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)
    
    extended = 0
    if vk in [0x14, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x5B, 0x5C]:
        extended = KEYEVENTF_EXTENDEDKEY
        
    inputs = (INPUT * 1)()
    inputs[0].type = INPUT_KEYBOARD
    inputs[0].ii.ki.wVk = vk
    inputs[0].ii.ki.wScan = scan
    inputs[0].ii.ki.dwFlags = KEYEVENTF_KEYUP | extended
    inputs[0].ii.ki.time = 0
    inputs[0].ii.ki.dwExtraInfo = 0
    
    user32.SendInput(1, inputs, ctypes.sizeof(INPUT))


def key_press(key: str, delay: float = 0.02):
    """Send a single press and release event using SendInput."""
    check_failsafe()
    key_down(key)
    if delay > 0:
        time.sleep(delay)
    key_up(key)


def hotkey(*keys, delay: float = 0.05):
    """Execute key combinations (e.g. hotkey('ctrl', 'c'))."""
    check_failsafe()
    if len(keys) < 2:
        raise ValueError("A hotkey requires at least one modifier and one key.")

    pressed = []
    try:
        # Press modifiers in sequence.
        for key in keys[:-1]:
            key_down(key)
            pressed.append(key)
            time.sleep(delay)

        # Tap final action key.
        key_press(keys[-1], delay=delay)
    finally:
        # A failed final key must never leave a modifier stuck down.
        for key in reversed(pressed):
            try:
                key_up(key)
                time.sleep(delay)
            except Exception:
                # Preserve the original exception if there was one; the
                # caller will report it as an execution failure.
                pass


def type_text(text: str, interval: float = 0.02):
    """Type text using Unicode input events to ensure layout-agnostic entry."""
    check_failsafe()
    for char in text:
        code = ord(char)
        if code <= 0xFFFF:
            _send_unicode_char(code)
        else:
            lead = 0xD800 + ((code - 0x10000) >> 10)
            trail = 0xDC00 + ((code - 0x10000) & 0x3FF)
            _send_unicode_char(lead)
            _send_unicode_char(trail)
            
        if interval > 0:
            time.sleep(interval)


def _send_unicode_char(code: int):
    """Press and release a single Unicode character unit using SendInput."""
    inputs = (INPUT * 2)()
    
    # Down
    inputs[0].type = INPUT_KEYBOARD
    inputs[0].ii.ki.wVk = 0
    inputs[0].ii.ki.wScan = code
    inputs[0].ii.ki.dwFlags = KEYEVENTF_UNICODE
    inputs[0].ii.ki.time = 0
    inputs[0].ii.ki.dwExtraInfo = 0
    
    # Up
    inputs[1].type = INPUT_KEYBOARD
    inputs[1].ii.ki.wVk = 0
    inputs[1].ii.ki.wScan = code
    inputs[1].ii.ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP
    inputs[1].ii.ki.time = 0
    inputs[1].ii.ki.dwExtraInfo = 0
    
    user32.SendInput(2, inputs, ctypes.sizeof(INPUT))


def get_open_windows():
    """Enumerate all open, visible windows with non-empty titles."""
    EnumWindows = ctypes.windll.user32.EnumWindows
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    GetWindowTextW = ctypes.windll.user32.GetWindowTextW
    GetWindowTextLengthW = ctypes.windll.user32.GetWindowTextLengthW
    IsWindowVisible = ctypes.windll.user32.IsWindowVisible
    
    titles = []
    
    def foreach_window(hwnd, lParam):
        if IsWindowVisible(hwnd):
            length = GetWindowTextLengthW(hwnd)
            if length > 0:
                buff = ctypes.create_unicode_buffer(length + 1)
                GetWindowTextW(hwnd, buff, length + 1)
                title = buff.value
                if title:
                    titles.append(title)
        return True
        
    EnumWindows(EnumWindowsProc(foreach_window), 0)
    return titles


def focus_window(title_substring: str) -> bool:
    """Find a window matching the title substring (case-insensitive) and bring it to the foreground."""
    EnumWindows = ctypes.windll.user32.EnumWindows
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    GetWindowTextW = ctypes.windll.user32.GetWindowTextW
    GetWindowTextLengthW = ctypes.windll.user32.GetWindowTextLengthW
    IsWindowVisible = ctypes.windll.user32.IsWindowVisible
    ShowWindow = ctypes.windll.user32.ShowWindow
    SetForegroundWindow = ctypes.windll.user32.SetForegroundWindow
    
    found_hwnd = []
    
    def foreach_window(hwnd, lParam):
        if IsWindowVisible(hwnd):
            length = GetWindowTextLengthW(hwnd)
            if length > 0:
                buff = ctypes.create_unicode_buffer(length + 1)
                GetWindowTextW(hwnd, buff, length + 1)
                title = buff.value
                if title_substring.lower() in title.lower():
                    found_hwnd.append(hwnd)
                    return False  # Stop enumerating
        return True
        
    EnumWindows(EnumWindowsProc(foreach_window), 0)
    
    if found_hwnd:
        hwnd = found_hwnd[0]
        ShowWindow(hwnd, 9)  # SW_RESTORE (9) restores if minimized, otherwise normal
        SetForegroundWindow(hwnd)
        return True
    return False


def maximize_window(title_substring: str) -> bool:
    """Find a window matching the title substring and maximize it."""
    EnumWindows = ctypes.windll.user32.EnumWindows
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    GetWindowTextW = ctypes.windll.user32.GetWindowTextW
    GetWindowTextLengthW = ctypes.windll.user32.GetWindowTextLengthW
    IsWindowVisible = ctypes.windll.user32.IsWindowVisible
    ShowWindow = ctypes.windll.user32.ShowWindow
    
    found_hwnd = []
    
    def foreach_window(hwnd, lParam):
        if IsWindowVisible(hwnd):
            length = GetWindowTextLengthW(hwnd)
            if length > 0:
                buff = ctypes.create_unicode_buffer(length + 1)
                GetWindowTextW(hwnd, buff, length + 1)
                title = buff.value
                if title_substring.lower() in title.lower():
                    found_hwnd.append(hwnd)
                    return False
        return True
        
    EnumWindows(EnumWindowsProc(foreach_window), 0)
    
    if found_hwnd:
        ShowWindow(found_hwnd[0], 3)  # SW_MAXIMIZE (3)
        return True
    return False


def minimize_all_windows():
    """Minimize all windows to show the desktop."""
    hotkey('win', 'd')
    return True
