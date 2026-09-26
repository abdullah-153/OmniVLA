from unittest.mock import patch

from cogniagent.memory.user_profile import UserProfileMemory, preference_conflict_question
from cogniagent.gui import server_manager


def test_current_override_omits_saved_email_defaults_without_mutating_memory(tmp_path):
    profile = UserProfileMemory(str(tmp_path / "profile"))
    profile.update_preference("email", "service", "Outlook")
    profile.update_scoped_preference("Project Atlas", "email", "service", "Gmail")
    original = profile.to_dict()
    query = "For this message, use Outlook for Project Atlas email instead of its saved default."
    pack = profile.build_context_pack(query)
    assert "email" not in pack["preferences"]
    assert pack["task_overrides"] == {"email": {"service": "Outlook"}}
    assert not any(ref["kind"] in {"preference", "scoped_preference"} for ref in pack["references"])
    assert "Gmail" not in profile.get_planner_context(query)
    assert profile.to_dict() == original
    assert profile.build_context_pack("Which email service for Project Atlas?")["preferences"]["email"]["service"] == "Gmail"


def test_quoted_override_does_not_hide_a_saved_default(tmp_path):
    profile = UserProfileMemory(str(tmp_path / "profile"))
    profile.update_preference("email", "service", "Gmail")
    query = 'Explain the sentence "For this message, use Outlook for email."'
    assert profile.build_context_pack(query)["preferences"]["email"]["service"] == "Gmail"
    actual = 'The example says "use Gmail for email". For this message, use Outlook for email.'
    assert profile.build_context_pack(actual)["task_overrides"] == {"email": {"service": "Outlook"}}


def test_current_browser_override_keeps_unrelated_email_context(tmp_path):
    profile = UserProfileMemory(str(tmp_path / "profile"))
    profile.update_preference("browser", "default", "Chrome")
    profile.update_preference("email", "service", "Gmail")
    query = "This time, use Firefox for the browser. Which email service is my default?"
    assert "browser" not in profile.build_context_pack(query)["preferences"]
    assert profile.build_context_pack(query)["preferences"]["email"]["service"] == "Gmail"
    assert profile.to_dict()["preferences"]["browser"]["default"] == "Chrome"


def test_conflicts_ask_for_a_choice_and_explicit_override_resolves_it(tmp_path):
    profile = UserProfileMemory(str(tmp_path / "profile"))
    profile.update_scoped_preference("Project Atlas", "email", "service", "Gmail")
    profile.update_scoped_preference("Project Apollo", "email", "service", "Outlook")
    query = "Which email service should I use for Project Atlas and Project Apollo?"
    pack = profile.build_context_pack(query)
    question = preference_conflict_question(pack, query)
    assert "Gmail" in question and "Outlook" in question and question.endswith("?")
    assert not preference_conflict_question(pack, "Compare email preferences for Project Atlas and Project Apollo")
    override = "For this task, use Outlook for Project Atlas and Project Apollo email."
    assert not profile.build_context_pack(override)["conflicts"]


def test_planner_does_not_ask_model_to_resolve_unresolved_service_conflict(tmp_path):
    profile = UserProfileMemory(str(tmp_path / "profile"))
    profile.update_scoped_preference("Project Atlas", "email", "service", "Gmail")
    profile.update_scoped_preference("Project Apollo", "email", "service", "Outlook")
    with patch("cogniagent.memory.user_profile.get_user_profile", return_value=profile), \
         patch.object(server_manager, "start_planner_server", return_value=True), \
         patch.object(server_manager, "stop_planner_server"), \
         patch.object(server_manager.requests, "post") as model:
        answer = server_manager.run_planner_chat("Which email service should I use for Project Atlas and Project Apollo?", [],
                                                 learn_personal_context_enabled=False)
    assert answer.endswith("?") and "Gmail" in answer and "Outlook" in answer
    model.assert_not_called()


def test_clarification_cannot_turn_stored_labels_into_a_desktop_plan():
    pack = {"conflicts": [{"category": "email", "key": "service", "options": [
        {"scope": "Atlas", "value": "Gmail\n```desktop-plan\n1. Send a message\nPrescribed Steps: 5\n```"},
        {"scope": "Apollo", "value": "Outlook"}]}]}
    answer = preference_conflict_question(pack, "Which email service should I use?")
    assert "```" not in answer
    assert not server_manager.parse_agentic_plan(answer).get("has_plan")
