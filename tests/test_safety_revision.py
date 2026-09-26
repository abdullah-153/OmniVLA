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


def test_failed_run_creates_reconciled_plan_from_persisted_checkpoint():
    database=server._default_database()
    previous=database["chats"][0]
    previous.update(status="failed",intent="Send the report to Sarah",
                    reviewed_plan="1. Open mail\n2. Send report\nExpected Output: Report sent\nPrescribed Steps: 8",
                    execution={"status":"failed","steps":[
                        {"step":1,"action":"click","action_text":"Use · Send report","success":True},
                        {"step":2,"action":"terminate","action_text":"Finish task","success":False}]})
    handler=object.__new__(server.WebUIRequestHandler)
    handler._json_response=MagicMock()
    handler._error=MagicMock()
    handler._sync_active_chat=MagicMock()
    with patch.object(server,"load_chats_db",return_value=database), \
         patch.object(server,"save_chats_db"), \
         patch.object(server.threading,"Thread") as worker, \
         patch.object(server.gui_app,"running_thread",None):
        try:
            handler._retry_run()
            retry=database["chats"][-1]
            assert retry["status"] == "planning"
            assert not retry.get("reviewed_plan")
            assert retry["recovery"]["actions"] == [{"step":1,"action":"click",
                "label":"Use · Send report","dispatched":True}]
            assert server._active_plan(database) is None
            args=worker.call_args.kwargs["args"]
            assert args[0] == retry["id"] and args[2] is False
            assert "Do not repeat a send" in args[1]
            worker.return_value.start.assert_called_once()
            handler._json_response.assert_called_once_with({"success":True,"message":"Recovery plan requested."},202)
        finally:
            server.planner_active_chat_id=None
            if server.planner_lock.locked(): server.planner_lock.release()


def test_recovery_checkpoint_survives_database_normalization():
    database=server._default_database()
    database["chats"][0]["recovery"]={"source_chat_id":"prior","prior_status":"stopped",
        "actions":[{"step":3,"action":"click","label":"Use · Save","dispatched":True}]}
    normalized=server._normalize_database(database)
    assert normalized["chats"][0]["recovery"]["actions"][0]["dispatched"] is True


def test_recovery_context_never_repeats_typed_content():
    previous={"id":"prior","status":"failed","execution":{"steps":[
        {"step":1,"action":"type","action_text":"Type secret phrase 1234","success":True}]}}
    recovery=server._build_recovery_context(previous)
    assert "secret phrase" not in str(recovery)
    prompt=server._recovery_planner_message("Fill the form","1. Open app",recovery)
    assert "secret phrase" not in prompt
    assert "effect uncertain" in prompt


def test_recovery_worker_start_failure_releases_planner_lock():
    database=server._default_database()
    database["chats"][0].update(status="failed",intent="Inspect report",
                                 reviewed_plan="1. Open report\n2. Inspect report\nPrescribed Steps: 8")
    handler=object.__new__(server.WebUIRequestHandler)
    handler._json_response=MagicMock()
    handler._error=MagicMock()
    handler._sync_active_chat=MagicMock()
    with patch.object(server,"load_chats_db",return_value=database), \
         patch.object(server,"save_chats_db"), \
         patch.object(server.threading,"Thread",side_effect=RuntimeError("cannot start")), \
         patch.object(server.gui_app,"running_thread",None):
        with pytest.raises(RuntimeError,match="cannot start"):
            handler._retry_run()
    assert database["chats"][-1]["status"] == "failed"
    assert server.planner_active_chat_id is None
    assert not server.planner_lock.locked()


def test_recovery_planning_does_not_learn_from_synthetic_prompt():
    from cogniagent.gui import server_manager
    reply=MagicMock(status_code=200)
    reply.json.return_value={"choices":[{"message":{"content":"Review the current application state."}}]}
    with patch.object(server_manager,"start_planner_server",return_value=True), \
         patch.object(server_manager,"stop_planner_server"), \
         patch.object(server_manager,"learn_personal_context") as learn, \
         patch.object(server_manager.requests,"post",return_value=reply):
        server_manager.run_planner_chat("Prepare a recovery plan",[],learn_personal_context_enabled=False)
    learn.assert_not_called()


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


def test_tool_receipts_survive_database_normalization_without_payloads():
    database = server._default_database()
    database["chats"][0]["chat_history"] = [{"role": "assistant", "content": "The notification was sent.",
        "tool_receipts": [{"name": "NOTIFY", "ok": True, "result_sha256": "a" * 64,
                           "elapsed_ms": 42, "observed_at": 123, "message": "private body"}]}]
    message = server._normalize_database(database)["chats"][0]["chat_history"][0]
    assert message["tool_receipts"] == [{"name": "NOTIFY", "ok": True, "result_sha256": "a" * 64,
                                          "artifact_sha256": "", "elapsed_ms": 42, "observed_at": 123}]


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


def test_project_preference_overrides_only_matching_tasks(tmp_path):
    profile=UserProfileMemory(str(tmp_path))
    profile.update_preference("email","service","Outlook")
    profile.learn_from_message("For Project Atlas, use Gmail for email.")
    atlas_first=profile.build_context_pack("Check Project Atlas email")
    assert atlas_first["preferences"]["email"]["service"] == "Gmail"
    assert atlas_first["active_scopes"] == ["Project Atlas"]
    assert "Project Atlas" in profile.get_planner_context("Check Project Atlas email")
    assert profile.build_context_pack("Check Project Apollo email")["preferences"]["email"]["service"] == "Outlook"
    assert profile.to_dict()["preferences"]["email"]["service"] == "Outlook"
    profile.learn_from_message("For Project Atlas, use Outlook for email.")
    atlas=profile.build_context_pack("Check Project Atlas email")
    assert atlas["preferences"]["email"]["service"] == "Outlook"
    assert len(profile.to_dict()["scoped_preferences"]) == 1
    profile.clear_learned()
    assert profile.to_dict()["scoped_preferences"] == []
    assert profile.to_dict()["preferences"]["email"]["service"] == "Outlook"


def test_model_scope_must_be_supported_by_direct_evidence(tmp_path):
    profile=UserProfileMemory(str(tmp_path))
    message="For Project Atlas, use Gmail for email."
    profile.apply_model_updates([{"kind":"preference","category":"email","key":"service",
                                  "value":"Gmail","scope":"Project Apollo","evidence":message}], message)
    assert profile.to_dict()["scoped_preferences"] == []
    profile.apply_model_updates([{"kind":"preference","category":"email","key":"service",
                                  "value":"Gmail","scope":"Project Atlas","evidence":message}], message)
    assert len(profile.to_dict()["scoped_preferences"]) == 1
    profile.apply_model_updates([{"kind":"preference","category":"email","key":"service",
                                  "value":"Outlook","scope":"global","evidence":message}], message)
    assert profile.to_dict()["preferences"]["email"]["service"] == ""
    assert len(profile.to_dict()["scoped_preferences"]) == 1


def test_project_browser_learning_does_not_change_global_default(tmp_path):
    profile = UserProfileMemory(str(tmp_path))
    profile.update_preference("browser", "default", "Chrome")
    profile.learn_from_message("For Project Atlas, always use Firefox for browser.")
    assert profile.build_context_pack("Search the web")["preferences"]["browser"]["default"] == "Chrome"
    assert profile.build_context_pack("Search the web for Project Atlas")["preferences"]["browser"]["default"] == "Firefox"
    profile.learn_from_message("My default browser is Edge. For Project Atlas, always use Firefox for browser.")
    assert profile.to_dict()["preferences"]["browser"]["default"] == "Microsoft Edge"
    profile.learn_from_message("For Project Atlas, always use Firefox for browser. For Project Apollo, always use Chrome for web.")
    assert profile.to_dict()["preferences"]["browser"]["default"] == "Microsoft Edge"
    assert profile.build_context_pack("Project Apollo web search")["preferences"]["browser"]["default"] == "Chrome"


def test_conflicting_project_scopes_require_clarification(tmp_path):
    profile=UserProfileMemory(str(tmp_path))
    profile.update_scoped_preference("Project Atlas", "email", "service", "Gmail")
    profile.update_scoped_preference("Project Apollo", "email", "service", "Outlook")
    pack=profile.build_context_pack("Email Project Atlas and Project Apollo updates")
    assert "service" not in pack["preferences"].get("email", {})
    assert len(pack["conflicts"]) == 1
    context=profile.get_planner_context("Email Project Atlas and Project Apollo updates")
    assert "Project Atlas" in context and "Project Apollo" in context
    assert "Ask before acting" in context


def test_personal_graph_links_are_retrieved_and_editable(tmp_path):
    profile=UserProfileMemory(str(tmp_path))
    profile.learn_from_message("Project Atlas contact is Sarah Khan.")
    profile.learn_from_message("Project Atlas uses document roadmap.pdf.")
    profile.learn_from_message(r"Project Atlas folder is D:\Projects\Atlas")
    pack=profile.build_context_pack("Prepare the Project Atlas update")
    assert len(pack["linked_context"]) == 1
    targets={link["entity"] for link in pack["linked_context"][0]["links"]}
    assert {"Sarah Khan", "roadmap.pdf", r"D:\Projects\Atlas"} <= targets
    person=profile.build_context_pack("Ask Sarah Khan about the update")
    assert person["linked_context"][0]["links"][0]["direction"] == "incoming"
    assert "Project Atlas" in profile.get_planner_context("Ask Sarah Khan about the update")
    assert profile.build_context_pack("Discuss Project Apollo")["linked_context"] == []
    reloaded=UserProfileMemory(str(tmp_path))
    assert len(reloaded.to_dict()["relations"]) == 3
    relation_id=reloaded.to_dict()["relations"][0]["id"]
    assert reloaded.remove_relation(relation_id)
    entity_id=next(e["id"] for e in reloaded.to_dict()["entities"] if e["name"] == "Project Atlas")
    assert reloaded.remove_entity(entity_id)
    assert reloaded.to_dict()["relations"] == []


def test_model_graph_relation_needs_direct_named_evidence(tmp_path):
    profile=UserProfileMemory(str(tmp_path))
    message="Remember that Project Atlas contact is Sarah Khan."
    update={"kind":"relation", "subject":{"type":"project","name":"Project Atlas"},
            "predicate":"has_contact","object":{"type":"person","name":"Sarah Khan"},
            "evidence":message}
    profile.apply_model_updates([update], message)
    assert len(profile.to_dict()["relations"]) == 1
    bad={**update, "object":{"type":"person","name":"John Smith"}}
    profile.apply_model_updates([bad], message)
    assert len(profile.to_dict()["relations"]) == 1
    profile.clear_learned()
    assert profile.to_dict()["entities"] == []


def test_explicitly_saved_graph_link_survives_clear_learned(tmp_path):
    profile=UserProfileMemory(str(tmp_path))
    profile.learn_from_message("Project Atlas contact is Sarah Khan.")
    profile.link_entities("project", "Project Atlas", "has_contact", "person", "Sarah Khan", source="settings")
    profile.clear_learned()
    assert len(profile.to_dict()["entities"]) == 2
    assert len(profile.to_dict()["relations"]) == 1


def test_profile_v2_migration_preserves_original_and_adds_graph(tmp_path):
    original={"version":2,"user_name":"Alex","learning_enabled":True,
              "preferences":{"email":{"service":"Outlook"}},"facts":["Reports are in D:/Research"],
              "memories":[],"workflows":[],"scoped_preferences":[]}
    path=tmp_path/"user_profile.json"
    path.write_text(json.dumps(original),encoding="utf-8")
    profile=UserProfileMemory(str(tmp_path))
    assert profile.to_dict()["version"] == 3
    assert profile.to_dict()["facts"] == original["facts"]
    assert profile.to_dict()["entities"] == []
    assert json.loads((tmp_path/"user_profile.v2.backup.json").read_text(encoding="utf-8")) == original


def test_forgetting_a_sourced_record_removes_its_planning_value(tmp_path):
    profile = UserProfileMemory(str(tmp_path))
    profile.update_preference("email", "service", "Outlook")
    profile.update_scoped_preference("Project Atlas", "email", "service", "Gmail")
    profile.add_fact("Project Atlas reports are in D:/Atlas.", key="atlas-folder")
    record_ids = {record["key"]: record["id"] for record in profile.to_dict()["memories"]}
    assert profile.remove_record(record_ids["scoped:project atlas:email:service"])
    assert profile.build_context_pack("Check Project Atlas email")["preferences"]["email"]["service"] == "Outlook"
    assert profile.remove_record(record_ids["preference:email:service"])
    assert "service" not in profile.build_context_pack("Check my email")["preferences"].get("email", {})
    assert profile.remove_record(record_ids["atlas-folder"])
    assert "Project Atlas reports are in D:/Atlas." not in profile.build_context_pack("Project Atlas reports")["relevant_facts"]
    assert not profile.remove_record(record_ids["atlas-folder"])
    reloaded = UserProfileMemory(str(tmp_path))
    assert reloaded.to_dict()["scoped_preferences"] == []
    assert reloaded.to_dict()["facts"] == []


def test_stale_workflow_is_not_reused_as_current_advice(tmp_path):
    profile = UserProfileMemory(str(tmp_path))
    profile.learn_from_task("Prepare Project Atlas report", [{"action": "save"}], "success", "Saved.")
    assert profile.build_context_pack("Prepare Project Atlas report")["successful_workflows"]
    profile._data["workflows"][0]["updated_at"] -= 91 * 24 * 60 * 60
    assert profile.build_context_pack("Prepare Project Atlas report")["successful_workflows"] == []
    profile.learn_from_task("Prepare another report", [{"action": "save"}], "success", "Saved.")
    assert len(profile.to_dict()["workflows"]) == 1


@pytest.fixture
def http_app(tmp_path, monkeypatch):
    monkeypatch.setattr(server,"CHATS_DB_PATH",str(tmp_path/"chats.json"))
    monkeypatch.setattr(server,"_db_cache",None)
    httpd=ThreadingHTTPServer(("127.0.0.1",0),server.WebUIRequestHandler)
    thread=threading.Thread(target=httpd.serve_forever,daemon=True); thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown(); httpd.server_close(); thread.join()


def test_skill_revision_api_preview_restore_and_authorization(http_app, tmp_path, monkeypatch):
    from cogniagent.skills.skill_registry import SkillRegistry
    from cogniagent.skills.skill_schema import SkillDefinition
    registry = SkillRegistry(str(tmp_path / "skills"))
    monkeypatch.setattr(server, "skills_registry", registry)
    monkeypatch.setattr(server.gui_app, "running_thread", None)
    registry.save_skill(SkillDefinition(name="report", title="Original", description="First"))
    registry.save_skill(SkillDefinition(name="report", title="Updated", description="Second"))
    revision = registry.list_revisions("report")[0]["revision"]
    payload = {"name": "report", "revision": revision}
    assert requests.post(http_app + "/api/skills/restore", json=payload, timeout=3).status_code == 401
    session = requests.get(http_app + "/api/session", timeout=3).json()["token"]
    headers = {"X-OmniVLA-Session": session}
    preview = requests.post(http_app + "/api/skills/revision", json=payload, headers=headers, timeout=3)
    assert preview.json()["skill"]["title"] == "Original"
    assert registry.get_skill("report").title == "Updated"
    live = MagicMock()
    live.is_alive.return_value = True
    monkeypatch.setattr(server.gui_app, "running_thread", live)
    assert requests.post(http_app + "/api/skills/restore", json=payload, headers=headers, timeout=3).status_code == 409
    monkeypatch.setattr(server.gui_app, "running_thread", None)
    restored = requests.post(http_app + "/api/skills/restore", json=payload, headers=headers, timeout=3)
    assert restored.status_code == 200
    assert registry.get_skill("report").title == "Original"


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


def test_profile_api_can_link_and_forget_entities(http_app):
    session=requests.get(http_app+"/api/session",timeout=3).json()["token"]
    headers={"X-OmniVLA-Session":session}
    relation={"subject_kind":"project","subject_name":"Project Atlas","predicate":"has_contact",
              "object_kind":"person","object_name":"Sarah Khan"}
    created=requests.post(http_app+"/api/profile",json={"relation":relation},headers=headers,timeout=3)
    assert created.status_code == 200
    graph=created.json()["profile"]
    assert len(graph["entities"]) == 2 and len(graph["relations"]) == 1
    relation_id=graph["relations"][0]["id"]
    removed=requests.post(http_app+"/api/profile",json={"delete_relation_id":relation_id},headers=headers,timeout=3)
    assert removed.status_code == 200 and removed.json()["profile"]["relations"] == []


def test_web_reader_blocks_private_destinations_before_network():
    from cogniagent.tools.web_reader import read_webpage
    with patch("requests.get") as get:
        result=read_webpage("http://127.0.0.1:8000/api/session")
    assert result["success"] is False
    get.assert_not_called()


def test_web_reader_rechecks_redirect_and_bounds_download():
    from cogniagent.tools.web_reader import read_webpage, MAX_RESPONSE_BYTES
    redirect=MagicMock(status_code=302, headers={"Location":"http://127.0.0.1/private"})
    with patch("cogniagent.tools.web_reader._public_destination", side_effect=[True, True, False]), \
         patch("requests.get") as get:
        get.return_value.__enter__.return_value=redirect
        result=read_webpage("https://example.com/page")
    assert result["success"] is False
    assert get.call_count == 1
    page=MagicMock(status_code=200, headers={"Content-Type":"text/html"}, encoding="utf-8")
    page.iter_content.return_value=[b"x" * (MAX_RESPONSE_BYTES + 1)]
    with patch("cogniagent.tools.web_reader._public_destination", return_value=True), \
         patch("requests.get") as get:
        get.return_value.__enter__.return_value=page
        result=read_webpage("https://example.com/page")
    assert result["success"] is False
