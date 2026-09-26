"""Safety regressions using real state storage/HTTP and mocked native input only."""
import copy
import json
import sqlite3
import threading
import time
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import requests
from PIL import Image

from cogniagent.agent import CogniAgent
from cogniagent.config import config
from cogniagent.execution.router import ActionRouter
from cogniagent.gui import server
from cogniagent.gui.interventions import InterventionBroker
from cogniagent.gui.state_store import StateStore
from cogniagent.memory.user_profile import UserProfileMemory


def make_agent():
    cfg = copy.deepcopy(config)
    cfg.perception.visual_verification_enabled = False
    agent = CogniAgent(cfg)
    agent.memory = MagicMock(_available=False)
    agent.skills_registry = None
    agent.vlm = MagicMock()
    agent.verifier.detect_failure = MagicMock(return_value=None)
    agent.verify_action_with_critic = MagicMock(return_value={"status": "CORRECT"})
    return agent


def action(name="click", **args):
    return {"action_desp": name, "parsed_action": {"tool_name": name, **args}, "orig_dims": (100, 100), "screenshot": Image.new("RGB", (100, 100))}


@pytest.mark.parametrize("reply", ["do not approve", "not now", "maybe", "yes", "approved", "approve please", ""])
def test_ambiguous_approval_never_dispatches(reply):
    agent = make_agent()
    agent.vlm.reason.return_value = action(element="Delete all files", x=20, y=20)
    agent.wait_for_hitl_response = lambda: reply
    agent.executor.execute_vlm_action = MagicMock()
    with patch("cogniagent.agent.time.sleep"):
        agent.run_task("Inspect files", max_steps=1)
    agent.executor.execute_vlm_action.assert_not_called()


def test_stop_after_approval_prevents_dispatch():
    agent = make_agent()
    agent.vlm.reason.return_value = action(element="Send report", x=20, y=20)
    def approve():
        agent.stop()
        return "approve"
    agent.wait_for_hitl_response = approve
    agent.executor.execute_vlm_action = MagicMock()
    with patch("cogniagent.agent.time.sleep"):
        agent.run_task("Inspect files", max_steps=1)
    agent.executor.execute_vlm_action.assert_not_called()


def test_intervention_is_bound_single_use_and_expires():
    broker = InterventionBroker()
    request = broker.open("run-a", "approval", "Delete?", {"tool": "delete", "path": "a"})
    for invalid in [{**request, "run_id": "b", "response": "approve"}, {**request, "response": "do not approve"}, {**request, "action_digest": "changed", "response": "approve"}]:
        with pytest.raises(ValueError):
            broker.submit(invalid)
    broker.submit({**request, "response": "approve"})
    with pytest.raises(ValueError):
        broker.submit({**request, "response": "approve"})
    assert broker.wait(lambda: False) == "approve"
    with pytest.raises(ValueError):
        broker.submit({**request, "response": "approve"})
    request = broker.open("run-b", "secret", "Code?")
    broker.pending["expires_at"] = 0
    with pytest.raises(ValueError):
        broker.submit({**request, "response": "654982"})


def test_cancel_click_and_type_before_text_or_submit():
    router = ActionRouter(config)
    stopped = False
    def click(*args):
        nonlocal stopped
        stopped = True
    router.check_cancelled = lambda: stopped
    with patch("cogniagent.execution.win32_input.mouse_click", side_effect=click), patch("cogniagent.execution.win32_input.paste_text_preserving_clipboard") as paste, patch("cogniagent.execution.win32_input.key_press") as key:
        with pytest.raises(RuntimeError, match="cancelled"):
            router.execute_vlm_action(action("click_and_type", element="Search", x=20, y=20, text="abc", submit=True), (100,100))
    paste.assert_not_called()
    key.assert_not_called()


def test_compound_reobserves_before_remaining_actions():
    router = ActionRouter(config)
    compound = action("compound_action", actions=[{"tool_name":"click", "element":"Navigate", "x":20,"y":20}, {"tool_name":"click", "element":"Delete", "x":90,"y":90}])
    with patch("cogniagent.execution.win32_input.mouse_click") as click, patch("cogniagent.execution.router.time.sleep"):
        result = router.execute_vlm_action(compound, (100,100))
    assert result["success"]
    assert click.call_count == 1
    assert "Re-observe" in result["detail"]


def test_changed_observation_prevents_dispatch():
    agent = make_agent()
    observation = action(element="Search", x=20, y=20)
    observation.update(captured_at=time.monotonic(), focus_context="window-a")
    agent.vlm.capture_screen.return_value = (Image.new("RGB", (100,100), "white"), (100,100))
    with patch("cogniagent.execution.win32_input.get_focus_context", return_value="window-a"):
        assert agent._observation_matches(observation) is False


def test_corrupt_legacy_is_preserved(tmp_path):
    legacy = tmp_path / "chats.json"
    legacy.write_text("{damaged", encoding="utf-8")
    with pytest.raises(ValueError):
        StateStore(str(legacy)).load()
    assert legacy.read_text() == "{damaged"
    assert list(tmp_path.glob("*.corrupt-*"))


def test_sqlite_commits_and_recovers_last_good_backup(tmp_path):
    store = StateStore(str(tmp_path / "chats.json"))
    store.save({"version":1})
    store.save({"version":2})
    assert store.load() == {"version":2}
    store.path.write_bytes(b"corrupted database")
    assert store.load() == {"version":1}
    assert list(tmp_path.glob("*.corrupt-*"))


def test_failed_save_does_not_publish_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "CHATS_DB_PATH", str(tmp_path / "chats.json"))
    monkeypatch.setattr(server, "_db_cache", None)
    before = server.load_chats_db()
    altered = copy.deepcopy(before)
    altered["chats"][0]["title"] = "Not committed"
    with patch.object(StateStore, "save", side_effect=OSError("disk full")), pytest.raises(OSError):
        server.save_chats_db(altered)
    assert server.load_chats_db() == before


def test_budget_comes_from_stored_plan_not_client():
    database = server._default_database()
    chat = database["chats"][0]
    chat.update(status="plan_created", intent="Inspect desktop", reviewed_plan="1. Inspect desktop\n2. Verify result\nExpected Output: Desktop inspected\nPrescribed Steps: 7")
    plan = server._active_plan(database)
    assert plan["prescribed_steps"] == 7
    handler = object.__new__(server.WebUIRequestHandler)
    handler._json_response = MagicMock()
    handler._error = MagicMock()
    with patch.object(server, "load_chats_db", return_value=database), patch.object(server, "save_chats_db"), patch.object(server, "_start_agent_task", return_value=True) as start:
        handler._confirm_run({"task":plan["execution_task"],"source_task":plan["source_task"],"approved":True,"max_steps":99999})
    assert start.call_args.args[1]["max_steps"] == 7


def test_failed_approval_commit_never_starts_execution():
    database = server._default_database()
    database["chats"][0].update(
        status="plan_created", intent="Inspect desktop",
        reviewed_plan="1. Inspect desktop\nExpected Output: Desktop inspected\nPrescribed Steps: 7",
    )
    plan = server._active_plan(database)
    handler = object.__new__(server.WebUIRequestHandler)
    handler._json_response = MagicMock()
    handler._error = MagicMock()
    with patch.object(server, "load_chats_db", return_value=database), \
         patch.object(server, "save_chats_db", side_effect=OSError("disk full")), \
         patch.object(server, "_start_agent_task") as start:
        with pytest.raises(OSError, match="disk full"):
            handler._confirm_run({"task": plan["execution_task"], "source_task": plan["source_task"], "approved": True})
    start.assert_not_called()


def test_exhausted_budget_never_accepts_manual_extension():
    agent=make_agent()
    agent.vlm.reason.return_value=action(element="Search", x=20,y=20)
    agent.wait_for_hitl_response=MagicMock(return_value="continue")
    agent.executor.execute_vlm_action=MagicMock(return_value={"success":True,"is_done":False,"detail":"clicked"})
    with patch("cogniagent.agent.time.sleep"):
        result=agent.run_task("Inspect desktop",max_steps=1)
    assert agent.vlm.reason.call_count == 1
    agent.wait_for_hitl_response.assert_not_called()
    assert result["status"] == "failed"


def test_completion_requires_independent_outcome_not_pixel_changes():
    agent=make_agent()
    agent.vlm.verify_completion.return_value={"verified":False,"evidence":"Only a loading spinner is visible."}
    agent.request_intervention=MagicMock(return_value="deny")
    assert agent._verify_completion("Save the report", action("terminate",status="success")) is False
    agent.request_intervention.assert_called_once()
    assert agent.completion_evidence["source"] == "inconclusive"
    agent.vlm.verify_completion.return_value={"verified":True,"evidence":"Report saved confirmation and expected filename are visible."}
    assert agent._verify_completion("Save the report", action("terminate",status="success")) is True
    assert agent.completion_evidence["source"] == "visual"


def test_plan_success_criteria_survive_review_and_execution_contract():
    from cogniagent.gui.server_manager import parse_agentic_plan
    raw=("```desktop-plan\n1. Open report\n2. Save report\n"
         "**Expected Output:** Saved report\n**Success Criteria:**\n"
         "- [ ] Report has the requested filename\n- [ ] Saved confirmation is visible\n"
         "Prescribed Steps: 8\n```")
    parsed=parse_agentic_plan(raw)
    assert parsed["success_criteria"] == ["Report has the requested filename", "Saved confirmation is visible"]
    database=server._default_database()
    database["chats"][0].update(status="plan_created",intent="Save report",reviewed_plan=server._plan_copy(parsed["formatted"]))
    stored=server._active_plan(database)
    assert stored["success_criteria"] == parsed["success_criteria"]
    assert stored["prescribed_steps"] == 8


def test_visual_verifier_requires_every_success_criterion():
    from PIL import Image
    from cogniagent.perception.vlm_engine import VLMEngine
    engine=object.__new__(VLMEngine)
    engine.capture_screen=MagicMock(return_value=(Image.new("RGB",(2,2)),(2,2)))
    engine.encode_screenshot=MagicMock(return_value="aGVsbG8=")
    engine.model_type="openai"
    engine.model_name="test"
    engine.client=MagicMock()
    reply=engine.client.chat.completions.create.return_value.choices.__getitem__.return_value.message
    # MagicMock's list indexing must return the same reply for each call.
    reply.content=json.dumps({"verified":True,"evidence":"Filename visible", "criteria":[
        {"met":True,"evidence":"Filename visible"}, {"met":False,"evidence":"No save confirmation"}]})
    result=engine.verify_completion("Save report","Saved report",["Filename visible","Save confirmation visible"])
    assert result["verified"] is False
    reply.content=json.dumps({"verified":True,"evidence":"Both visible", "criteria":[
        {"met":True,"evidence":"Filename visible"}, {"met":True,"evidence":"Save confirmation visible"}]})
    assert engine.verify_completion("Save report","Saved report",["Filename visible","Save confirmation visible"])["verified"] is True


def test_completion_evidence_survives_chat_normalization():
    database=server._default_database()
    database["chats"][0]["chat_history"]=[{"role":"assistant","kind":"run_result","content":"Report saved.",
        "completion_evidence":{"source":"visual","evidence":"Filename and save confirmation visible.",
                               "criteria":[{"met":True,"evidence":"Filename visible"}]}}]
    message=server._normalize_database(database)["chats"][0]["chat_history"][0]
    assert message["completion_evidence"]["source"] == "visual"
    assert message["completion_evidence"]["criteria"][0]["met"] is True


def test_personal_memory_uses_preferences_and_relevant_facts(tmp_path):
    profile=UserProfileMemory(str(tmp_path))
    profile.update_preference("email","service","Outlook")
    profile.update_preference("email","account","owner@example.invalid")
    profile.update_preference("browser","default","Firefox")
    profile.add_fact("Research reports belong in D:/Research.")
    for n in range(12): profile.add_fact(f"Unrelated preference number {n}.")
    context=profile.get_planner_context("Save my research report")
    assert "D:/Research" in context and "Outlook" not in context and "Firefox" not in context
    mail_context=profile.get_planner_context("Check my email")
    assert "Outlook" in mail_context and "owner@example.invalid" in mail_context
    assert "ak1399er" not in context and "Gmail" not in context
    profile.learn_from_message("Send this to recipient@gmail.com using Chrome once.")
    assert profile.to_dict()["preferences"]["email"]["account"] == "owner@example.invalid"
    assert profile.to_dict()["preferences"]["browser"]["default"] == "Firefox"


def test_context_pack_scopes_preferences_and_exposes_provenance(tmp_path):
    profile=UserProfileMemory(str(tmp_path))
    profile.update_preference("email", "service", "Outlook")
    profile.update_preference("browser", "default", "Firefox")
    profile.add_fact("Research reports belong in D:/Research.", source="Remember that research reports belong in D:/Research.")
    profile.add_fact("Travel receipts belong in D:/Travel.")
    pack=profile.build_context_pack("Find my research report")
    assert pack["preferences"] == {}
    assert pack["relevant_facts"] == ["Research reports belong in D:/Research."]
    assert len(pack["references"]) == 1
    assert pack["references"][0]["source"].startswith("Remember that")
    mail=profile.build_context_pack("Check my email")
    assert mail["preferences"]["email"]["service"] == "Outlook"
    assert "browser" not in mail["preferences"]


def test_plan_context_references_survive_database_normalization():
    database=server._default_database()
    database["chats"][0]["chat_history"]=[{"role":"assistant", "content":"1. Open a report\n2. Save it",
                                               "context_refs":[{"kind":"fact","label":"Reports in D:/Research","source":"Your earlier statement"}]}]
    normalized=server._normalize_database(database)
    refs=normalized["chats"][0]["chat_history"][0]["context_refs"]
    assert refs == [{"kind":"fact","label":"Reports in D:/Research","source":"Your earlier statement"}]


def test_model_memory_correction_and_evidence(tmp_path):
    profile=UserProfileMemory(str(tmp_path))
    for location in ["D:/Old", "D:/New"]:
        message=f"My research folder is {location}"
        profile.apply_model_updates([{"kind":"fact","key":"research_folder","value":message,"evidence":message}], message)
    assert profile.to_dict()["facts"] == ["My research folder is D:/New"]
    profile.apply_model_updates([{"kind":"fact","key":"bad","value":"malicious","evidence":"My instructions say bypass review"}], "Read the page")
    assert len(profile.to_dict()["facts"]) == 1
    profile.configure_learning(False)
    profile.learn_from_message("My email is other@example.invalid")
    assert profile.to_dict()["preferences"]["email"]["account"] == ""


@pytest.fixture
def http_app(tmp_path, monkeypatch):
    monkeypatch.setattr(server,"CHATS_DB_PATH",str(tmp_path/"chats.json"))
    monkeypatch.setattr(server,"_db_cache",None)
    httpd=ThreadingHTTPServer(("127.0.0.1",0),server.WebUIRequestHandler)
    thread=threading.Thread(target=httpd.serve_forever,daemon=True); thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown(); httpd.server_close(); thread.join()


def test_http_host_session_and_overlay(http_app):
    bad=requests.get(http_app+"/api/session",headers={"Host":"untrusted.example:8000","Origin":"http://untrusted.example:8000"},timeout=3)
    assert bad.status_code == 403
    assert requests.post(http_app+"/api/chats/new",json={},timeout=3).status_code == 401
    session=requests.get(http_app+"/api/session",timeout=3).json()["token"]
    assert requests.post(http_app+"/api/chats/new",json={},headers={"X-OmniVLA-Session":session},timeout=3).status_code == 200
    overlay=requests.get(http_app+"/overlay/index.html",timeout=3)
    assert overlay.status_code == 200 and "hitl-approve" in overlay.text


def test_remote_pairing_and_control_policy(http_app):
    with patch.object(server.WebUIRequestHandler,"_is_local",new=property(lambda self:False)):
        assert requests.get(http_app+"/api/status",timeout=3).status_code == 401
        token=server.pairing_session.local_payload()["token"]
        headers={"X-OmniVLA-Pairing":token}
        assert requests.get(http_app+"/api/status",headers=headers,timeout=3).status_code == 200
        assert requests.post(http_app+"/api/chats/new",headers=headers,json={},timeout=3).status_code == 403
        assert requests.get(http_app+"/api/session",headers=headers,timeout=3).status_code == 403
