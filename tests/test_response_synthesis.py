import pytest
from unittest.mock import patch
from cogniagent.gui.app import synthesize_task_summary


@patch("requests.post", side_effect=Exception("offline"))
def test_synthesize_task_summary_success(_mock_post):
    steps = [
        {"action": "open_app", "action_text": "Open · Microsoft Edge", "step": 1},
        {"action": "click", "action_text": "Use · Inbox (4,452) - ak1399er@gmail.com", "step": 2},
        {"action": "click", "action_text": "Use · Email from Deepgram Support with subject 'We corrected a Flux STT billing issue'", "step": 3},
    ]
    summary = synthesize_task_summary(
        user_intent="check my emails",
        status="success",
        steps_executed=steps,
        terminal_reason="",
        final_thought="Screen inspected."
    )
    assert "check my emails" in summary
    assert "Email from Deepgram Support with subject 'We corrected a Flux STT billing issue'" in summary
    assert "Screen inspected." not in summary


@patch("requests.post", side_effect=Exception("offline"))
def test_synthesize_task_summary_suppresses_monologue(_mock_post):
    steps = [
        {"action": "open_app", "action_text": "Open · Microsoft Edge", "step": 1},
        {"action": "click", "action_text": "Use · Email from Windows Insider Pro with subject 'An update from the latest Insider meetups'", "step": 2},
    ]
    raw_monologue = "rrently viewing an email from Windows Insider Program about Insider meetups. I need to continue reviewing the latest emails to provide a comprehensive overview. Let me go back to the inbox to see more emails and continue the review process."
    summary = synthesize_task_summary(
        user_intent="check my latest mails in edge and give me an overview",
        status="failed",
        steps_executed=steps,
        terminal_reason=raw_monologue,
        final_thought=raw_monologue
    )
    assert "rrently viewing" not in summary
    assert "Let me go back" not in summary
    assert "Email from Windows Insider Pro with subject 'An update from the latest Insider meetups'" in summary
    assert "Execution progressed across 2 actions" in summary


@patch("requests.post", side_effect=Exception("offline"))
def test_synthesize_task_summary_clean_terminal_reason(_mock_post):
    summary = synthesize_task_summary(
        user_intent="open notepad",
        status="success",
        steps_executed=[{"action": "click", "action_text": "Open · Notepad", "step": 1}],
        terminal_reason="Opened Notepad, typed 'test', and closed without saving.",
        final_thought=""
    )
    assert "Opened Notepad, typed 'test', and closed without saving." in summary


def test_step_model_accepts_long_reasoning():
    from cogniagent.perception.vlm_engine import Step
    long_thought = "Detailed visual reasoning about the inbox. " * 20
    step = Step.model_validate({
        "tool_call": {"tool_name": "wait", "duration": 2},
        "thought": long_thought,
        "note": "Noted 3 unread emails with urgent priority."
    })
    assert len(step.thought) > 500
    assert step.tool_call.tool_name == "wait"


def test_cricket_schedule_search_links_never_parsed_as_plan():
    from cogniagent.gui.server_manager import parse_agentic_plan
    raw = (
        "[Cricbuzz - International Cricket Schedule](https://www.cricbuzz.com/cricket-schedule/upcoming-series/international) - Shows Kenya vs Uganda (19th Match) and Sierra Leone vs Botswana (20th Match) at Gahanga International Cricket Stadium, Kigali City\n"
        "2\n"
        "[Cricinfo - Live Cricket Match Schedule](https://www.cricinfo.com/live-cricket-match-schedule-fixtures) - Provides comprehensive live and upcoming match schedules\n"
        "3\n"
        "[Cricket World - Upcoming International Matches](https://www.cricketworld.com/cricket/upcoming/international) - Lists confirmed international fixtures for the current period --- Note: For real-time updates, scores, and live commentary, I recommend checking the Cricbuzz or Cricinfo websites directly, as match times and conditions can change."
    )
    parsed = parse_agentic_plan(raw)
    assert not parsed["has_plan"]
    assert parsed["steps"] == []


def test_numbered_search_citations_never_parsed_as_plan():
    from cogniagent.gui.server_manager import parse_agentic_plan
    raw = (
        "Here are today's international cricket fixtures:\n\n"
        "1. [Cricbuzz Schedule](https://www.cricbuzz.com/matches) - Kenya vs Uganda at 10:00 AM UTC\n"
        "2. [ICC Fixtures](https://www.icc-cricket.com/matches) - Sierra Leone vs Botswana at 2:00 PM UTC\n\n"
        "Both matches will be played at the Gahanga International Stadium."
    )
    parsed = parse_agentic_plan(raw)
    assert not parsed["has_plan"]
    assert parsed["steps"] == []


def test_real_desktop_action_plan_is_parsed_as_plan():
    from cogniagent.gui.server_manager import parse_agentic_plan
    raw = (
        "I will open Edge and check your Gmail.\n\n"
        "1. Open Microsoft Edge and navigate to https://mail.google.com\n"
        "2. Locate unread messages from ak1399er@gmail.com\n"
        "3. Click on the first message to read the content"
    )
    parsed = parse_agentic_plan(raw)
    assert parsed["has_plan"]
    assert len(parsed["steps"]) == 3


def test_planner_invokes_activity_callback_for_progress():
    from unittest.mock import patch, MagicMock
    from cogniagent.gui.server_manager import run_planner_chat

    activities = []
    def callback(text):
        activities.append(text)

    with patch("cogniagent.gui.server_manager.start_planner_server", return_value=True), \
         patch("cogniagent.gui.server_manager.stop_planner_server"), \
         patch("cogniagent.gui.server_manager.execute_browser_search", return_value="<browser_search_results>fixtures</browser_search_results>"), \
         patch("cogniagent.gui.server_manager.requests.post") as mock_post:
        resp1 = MagicMock(status_code=200)
        resp1.json.return_value = {"choices": [{"message": {"content": "Let me check today's schedule. [BROWSER_SEARCH: cricket match schedule today]"}}]}
        resp2 = MagicMock(status_code=200)
        resp2.json.return_value = {"choices": [{"message": {"content": "Today's fixtures: Kenya vs Uganda."}}]}
        mock_post.side_effect = [resp1, resp2]

        result = run_planner_chat("What is the cricket match schedule today", [], activity_callback=callback)
        assert len(activities) >= 2
        assert any("Searching" in a for a in activities)
        assert any("Thinking" in a for a in activities)
        assert "Kenya vs Uganda" in result


def test_agent_status_contains_planner_activity():
    import cogniagent.gui.app as gui_app
    safe = gui_app.get_safe_status()
    assert "planner_activity" in safe


def test_normalize_database_preserves_conversational_and_numbered_assistant_responses():
    from cogniagent.gui.server import _normalize_database

    sample_response = (
        "Based on the latest search results, here's what's scheduled for today in cricket:\n\n"
        "1. **Zimbabwe vs Australia** - 2nd ODI at Harare Sports Club, Harare\n"
        "2. **Kenya vs Uganda** - 19th Match of the Africa Continental Cup, Kigali\n\n"
        "No other fixtures are scheduled."
    )
    raw_db = {
        "active_chat_id": "test-chat-1",
        "chats": [{
            "id": "test-chat-1",
            "title": "Cricket schedule",
            "status": "idle",
            "intent": "What is the cricket match schedule today",
            "chat_history": [
                {"role": "user", "content": "What is the cricket match schedule today"},
                {"role": "assistant", "content": f"<think>Searching schedule</think>\n{sample_response}"}
            ]
        }]
    }
    normalized = _normalize_database(raw_db)
    chat = normalized["chats"][0]
    assert len(chat["chat_history"]) == 2
    assistant_msg = chat["chat_history"][1]
    assert assistant_msg["role"] == "assistant"
    assert "<think>" not in assistant_msg["content"]
    assert "Zimbabwe vs Australia" in assistant_msg["content"]
    assert "Kenya vs Uganda" in assistant_msg["content"]
    assert "Based on the latest search results" in assistant_msg["content"]


def test_secondary_tool_synthesis_retry_on_failure():
    from unittest.mock import patch, MagicMock
    from cogniagent.gui.server_manager import run_planner_chat

    # First call returns tool call, secondary call returns 400 (context limit), retry returns 200 with answer
    with patch("cogniagent.gui.server_manager.start_planner_server", return_value=True), \
         patch("cogniagent.gui.server_manager.stop_planner_server"), \
         patch("cogniagent.gui.server_manager.execute_browser_search", return_value="<browser_search_results>fixtures</browser_search_results>"), \
         patch("cogniagent.gui.server_manager.requests.post") as mock_post:

        resp_tool_call = MagicMock(status_code=200)
        resp_tool_call.json.return_value = {"choices": [{"message": {"content": "[BROWSER_SEARCH: cricket today]"}}]}

        resp_overflow = MagicMock(status_code=400, text="context exceeded")

        resp_retry = MagicMock(status_code=200)
        resp_retry.json.return_value = {"choices": [{"message": {"content": "Today's matches: Zimbabwe vs Australia."}}]}

        mock_post.side_effect = [resp_tool_call, resp_overflow, resp_retry]

        result = run_planner_chat("check matches", [])
        assert "Zimbabwe vs Australia" in result


def test_frontend_thinking_contains_skeleton_loader():
    import pathlib
    app_js_path = pathlib.Path(__file__).parent.parent / "cogniagent" / "gui" / "web" / "app.js"
    app_css_path = pathlib.Path(__file__).parent.parent / "cogniagent" / "gui" / "web" / "app.css"

    js_code = app_js_path.read_text(encoding="utf-8")
    css_code = app_css_path.read_text(encoding="utf-8")

    assert "message-skeleton" in js_code
    assert "thinking-progress-pill" in js_code
    assert ".message-body.message-thinking" in css_code
    assert "flex-direction: column" in css_code


def test_whatsapp_overview_never_leaks_scroll_finish_none():
    steps = [
        {"action": "open_app", "action_text": "Open · WhatsApp", "step": 1},
        {"action": "click", "action_text": "Use · WhatsApp icon in taskbar", "step": 2},
        {"action": "click", "action_text": "Use · LAND chat entry", "step": 3, "note": "LAND chat entry showing 'You reacted 🤣'"},
        {"action": "click", "action_text": "Use · nub chat entry", "step": 4, "note": "nub chat entry showing 'dekhungi scene' at 11:58 am"},
        {"action": "scroll", "action_text": "Scroll", "step": 5, "note": None},
        {"action": "terminate", "action_text": "Finish task", "step": 6, "note": "None"},
    ]
    terminal = (
        "Successfully reviewed latest WhatsApp messages. The most recent conversation is with 'nub' "
        "containing a message thread from 11:54-11:57 am, with the last message being 'hmmm' sent at 11:57 am. "
        "Several other conversations are visible in the chat list including 'LAND', 'Sec D Students', 'Study material'."
    )
    summary = synthesize_task_summary(
        user_intent="can you check my latest whatsapp messages and provide me an overview.",
        status="success",
        steps_executed=steps,
        terminal_reason=terminal,
        final_thought="",
    )

    # Must contain the substantive answer
    assert "nub" in summary
    assert ("whatsapp" in summary.lower() or "message" in summary.lower())

    # Must NOT leak low-level actions or 'None'
    assert "Scroll" not in summary
    assert "Finish task" not in summary
    assert "\nNone" not in summary
    assert " None" not in summary
    assert "Key Discovered Items & Interactions" not in summary
    assert "I've completed the task: can you check my latest whatsapp messages" not in summary


def test_action_primitives_filtered_even_without_terminal_reason():
    steps = [
        {"action": "scroll", "action_text": "Scroll", "step": 1, "note": None},
        {"action": "terminate", "action_text": "Finish task", "step": 2, "note": "None"},
        {"action": "wait", "action_text": "Wait · 2s", "step": 3},
        {"action": "click", "action_text": "Use · Unread message from Alex", "step": 4},
    ]
    summary = synthesize_task_summary(
        user_intent="check whatsapp",
        status="success",
        steps_executed=steps,
        terminal_reason="",
        final_thought="",
    )

    assert "Alex" in summary
    assert "Scroll" not in summary
    assert "Finish task" not in summary
    assert "None" not in summary


def test_holo_to_planner_neural_synthesis():
    from unittest.mock import MagicMock, patch

    mock_resp = MagicMock(status_code=200)
    mock_resp.json.return_value = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": (
                        "I've reviewed your latest WhatsApp messages. Your most recent conversation is with 'nub', "
                        "where the last message was 'hmmm' sent at 11:57 am. Other active conversations include "
                        "LAND, Sec D Students, and Ventilator."
                    )
                }
            }
        ]
    }

    with patch("requests.post", return_value=mock_resp) as mock_post:
        summary = synthesize_task_summary(
            user_intent="can you check my latest whatsapp messages and provide me an overview.",
            status="success",
            steps_executed=[
                {"action": "open_app", "action_text": "Open · WhatsApp", "step": 1},
                {"action": "click", "action_text": "Use · nub chat", "step": 2, "note": "nub message thread inspected"}
            ],
            terminal_reason="Reviewed latest messages with nub and LAND.",
            final_thought=""
        )

        mock_post.assert_called_once()
        assert "I've reviewed your latest WhatsApp messages" in summary
        assert "nub" in summary
        assert "LAND" in summary
        assert "Scroll" not in summary





