import mss
from PIL import Image
import numpy as np
from collections import namedtuple

Size = namedtuple('Size', ['width', 'height'])

class MockMSS:
    def __init__(self):
        self.monitors = [
            {"top": 0, "left": 0, "width": 1920, "height": 1080},
            {"top": 0, "left": 0, "width": 1920, "height": 1080} # Monitor 1 is monitors[1]
        ]
        self.queue = []
        # Create a default blank image (1920x1080, solid blue)
        self.default_image = Image.new("RGB", (1920, 1080), color=(0, 0, 255))
        
    def queue_image(self, img):
        """Queue a PIL Image or NumPy array or path to be returned by grab()."""
        if isinstance(img, np.ndarray):
            img = Image.fromarray(img)
        self.queue.append(img)
        
    def grab(self, monitor):
        if self.queue:
            img = self.queue.pop(0)
        else:
            img = self.default_image
            
        class MockGrabResult:
            def __init__(self, pil_img):
                self.size = Size(pil_img.width, pil_img.height)
                self.bgra = pil_img.convert("RGBA").tobytes("raw", "BGRA")
                
        return MockGrabResult(img)

# Singleton mock instance to share state across imports
mock_mss_instance = MockMSS()

def mock_mss_factory():
    return mock_mss_instance
