import sys
import types

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
import tests.mocks.mock_screen as mock_screen
try:
    import mss
    mss.mss = mock_screen.mock_mss_factory
except ImportError:
    fake_mss = types.ModuleType("mss")
    fake_mss.mss = mock_screen.mock_mss_factory
    sys.modules['mss'] = fake_mss
    sys.modules['mss.tools'] = types.ModuleType("mss.tools")

# 3b. Mock openai
try:
    import openai
except ImportError:
    import tests.mocks.mock_openai as mock_openai
    sys.modules['openai'] = mock_openai

# 3c. Mock cv2
try:
    import cv2
except ImportError:
    fake_cv2 = types.ModuleType("cv2")
    sys.modules['cv2'] = fake_cv2



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



@pytest.fixture(autouse=True)
def isolated_personal_memory(tmp_path, monkeypatch):
    from cogniagent.memory import user_profile
    monkeypatch.setattr(user_profile, "_profile_memory_instance", user_profile.UserProfileMemory(str(tmp_path / "personal")))


@pytest.fixture(autouse=True)
def offline_planner_tokenizer(monkeypatch):
    # Unit tests mock inference; do not contact the user's live model for counting.
    # The real HTTP adapter is tested separately, and opt-in scripts exercise it live.
    from cogniagent.gui import server_manager
    monkeypatch.setattr(server_manager, "count_planner_tokens",
        lambda messages: sum(len(item["content"]) // 4 + 8 for item in messages))
