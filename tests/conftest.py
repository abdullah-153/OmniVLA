import sys

# 1. Mock missing modules and chromadb before they can be imported
import tests.mocks.mock_states as mock_states
sys.modules['cogniagent.perception.state'] = mock_states
sys.modules['cogniagent.reasoning.action_reasoner'] = mock_states

import tests.mocks.mock_chromadb as mock_chromadb
sys.modules['chromadb'] = mock_chromadb

class DummyConfigModule:
    class Settings:
        def __init__(self, *args, **kwargs):
            pass

sys.modules['chromadb.config'] = DummyConfigModule

# 2. Mock ctypes.windll.user32
import tests.mocks.mock_ctypes as mock_ctypes
mock_ctypes.patch_ctypes()

# 3. Mock mss.mss
import mss
import tests.mocks.mock_screen as mock_screen
mss.mss = mock_screen.mock_mss_factory

# 4. Optional: Pytest fixtures
try:
    import pytest
    @pytest.fixture(autouse=True)
    def reset_mocks():
        mock_ctypes.registry.reset()
        mock_screen.mock_mss_instance.queue.clear()
        yield
except ImportError:
    pass

def init_mocks():
    """Explicit initializer for non-pytest runners like unittest."""
    mock_ctypes.registry.reset()
    mock_screen.mock_mss_instance.queue.clear()

def pytest_sessionstart(session):
    from tests.mocks.mock_llama_server import get_shared_server
    get_shared_server()

def pytest_sessionfinish(session, exitstatus):
    from tests.mocks.mock_llama_server import stop_shared_server
    stop_shared_server()
