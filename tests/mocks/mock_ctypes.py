import ctypes
from ctypes import wintypes

class MockCtypesRegistry:
    def __init__(self):
        self.reset()
        
    def reset(self):
        self.calls = []
        self.send_input_events = []
        self.cursor_x = 100
        self.cursor_y = 100
        self.screen_width = 1920
        self.screen_height = 1080

registry = MockCtypesRegistry()

# Define dummy structures for parsing SendInput if needed
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

# Monkeypatch ctypes.byref to return the object itself so that mock functions
# can inspect and mutate fields directly.
def mock_byref(obj):
    return obj

ctypes.byref = mock_byref

def mock_SetCursorPos(x, y):
    registry.calls.append(("SetCursorPos", (x, y)))
    registry.cursor_x = x
    registry.cursor_y = y
    return True

def mock_GetCursorPos(point):
    registry.calls.append(("GetCursorPos", ()))
    if point:
        point.x = registry.cursor_x
        point.y = registry.cursor_y
    return True

def mock_GetSystemMetrics(index):
    registry.calls.append(("GetSystemMetrics", (index,)))
    if index == 0:
        return registry.screen_width
    elif index == 1:
        return registry.screen_height
    return 0

def mock_MapVirtualKeyW(vk, mapping_type):
    registry.calls.append(("MapVirtualKeyW", (vk, mapping_type)))
    return vk + 0x100 # simple fake mapping

def mock_SendInput(num_inputs, inputs_array, size):
    registry.calls.append(("SendInput", (num_inputs, size)))
    for i in range(num_inputs):
        inp = inputs_array[i]
        inp_type = inp.type
        if inp_type == INPUT_MOUSE:
            mi = inp.ii.mi
            registry.send_input_events.append({
                "type": "mouse",
                "dx": mi.dx,
                "dy": mi.dy,
                "mouseData": mi.mouseData,
                "dwFlags": mi.dwFlags,
            })
        elif inp_type == INPUT_KEYBOARD:
            ki = inp.ii.ki
            registry.send_input_events.append({
                "type": "keyboard",
                "wVk": ki.wVk,
                "wScan": ki.wScan,
                "dwFlags": ki.dwFlags,
            })
    return num_inputs

# Mock Function wrapper
class MockFunc:
    def __init__(self, name, impl):
        self.name = name
        self.impl = impl
        self.argtypes = None
        self.restype = None

    def __call__(self, *args, **kwargs):
        return self.impl(*args, **kwargs)

# Mock DLL classes
class MockUser32:
    def __init__(self):
        self.SetCursorPos = MockFunc("SetCursorPos", mock_SetCursorPos)
        self.GetCursorPos = MockFunc("GetCursorPos", mock_GetCursorPos)
        self.GetSystemMetrics = MockFunc("GetSystemMetrics", mock_GetSystemMetrics)
        self.MapVirtualKeyW = MockFunc("MapVirtualKeyW", mock_MapVirtualKeyW)
        self.SendInput = MockFunc("SendInput", mock_SendInput)

class MockShcore:
    def __init__(self):
        self.SetProcessDpiAwareness = MockFunc("SetProcessDpiAwareness", lambda val: 0)

class MockWindll:
    def __init__(self):
        self.user32 = MockUser32()
        self.shcore = MockShcore()

# Helper to apply the mock
def patch_ctypes():
    if not hasattr(ctypes, 'windll'):
        ctypes.windll = MockWindll()
    else:
        mock_windll = MockWindll()
        ctypes.windll.user32 = mock_windll.user32
        ctypes.windll.shcore = mock_windll.shcore
