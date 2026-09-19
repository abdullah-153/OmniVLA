"""Unit tests for @skill mention matching and safe polling recorder."""

import time
from cogniagent.skills.skill_registry import SkillRegistry
from cogniagent.skills.skill_schema import SkillDefinition
from cogniagent.skills.teaching_recorder import NativeObservationRecorder
from cogniagent.skills.observation_learner import ObservationLearner


def test_explicit_at_skill_mention_matching():
    registry = SkillRegistry()
    skill = SkillDefinition(
        name="email_check",
        title="Check Email",
        description="Opens inbox and checks unread messages.",
        triggers=["open email", "check inbox"],
    )
    registry._skills_cache["email_check"] = skill

    # 1. Prompt without trigger keywords, but with @email_check
    matched, params = registry.match_skill("Please run @email_check for me right away")
    assert matched is not None
    assert matched.name == "email_check"

    # 2. Case-insensitive and hyphen/underscore normalization
    matched2, _ = registry.match_skill("Can you execute @EMAIL-CHECK?")
    assert matched2 is not None
    assert matched2.name == "email_check"

    # 3. Mentioning non-existent skill falls back to normal matching
    matched3, _ = registry.match_skill("Do something with @nonexistent_skill")
    assert matched3 is None


def test_native_observation_recorder_safe_polling():
    learner = ObservationLearner()
    recorder = NativeObservationRecorder(learner)
    assert not recorder.is_recording

    # Start polling recorder
    started = recorder.start()
    assert started is True
    assert recorder.is_recording is True

    # Let it run safely for 100ms
    time.sleep(0.1)

    # Stop polling recorder
    recorder.stop()
    assert recorder.is_recording is False
    assert recorder._poll_thread is None
