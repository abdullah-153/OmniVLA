import json
from unittest.mock import patch

import pytest

from cogniagent.runtime.context_receipts import personal_context_receipts
from cogniagent.gui import server_manager
from tests.test_planner_tool_sequence import reply


def context(data):
    return "<personal_context>" + json.dumps(data) + "</personal_context>"


def test_receipts_require_the_actual_personal_context_block_in_system_prompt():
    original = context({"relevant_facts": ["Atlas files are in Research"]})
    assert personal_context_receipts(original, [{"role": "system", "content": "Memory omitted"}]) == []
    assert personal_context_receipts(original, [{"role": "user", "content": original}]) == []
    assert personal_context_receipts("<personal_context>bad json</personal_context>", []) == []
    assert personal_context_receipts(original, [{"role": "system", "content": original}]) == [
        {"kind": "fact", "label": "Atlas files are in Research", "source": "Personal memory"}]


def test_receipts_snapshot_scoped_preferences_relationships_and_conflicts():
    original = context({"preferences": {"email": {"service": "Outlook"}},
        "references": [{"key": "scoped:atlas:email:service", "scope": "Atlas", "source": "settings"}],
        "linked_context": [{"entity": "Atlas", "links": [
            {"direction": "incoming", "entity": "Sarah", "relation": "works_on"}]}],
        "conflicts": [{"category": "browser", "key": "default", "options": [
            {"scope": "Atlas", "value": "Edge"}, {"scope": "Boreal", "value": "Firefox"}]}]})
    receipts = personal_context_receipts(original, [{"role": "system", "content": original}])
    assert receipts[0] == {"kind": "preference", "label": "email service: Outlook (Atlas)", "source": "Settings"}
    assert any(item["label"] == "Sarah → works_on → Atlas" for item in receipts)
    assert any(item["kind"] == "conflict" and "Firefox" in item["label"] for item in receipts)


@pytest.mark.parametrize("prune", [False, True])
def test_planner_receipts_follow_measured_context_fitting(prune):
    personal = context({"relevant_facts": ["Atlas uses the research folder"]})
    receipts = []
    def token_count(messages):
        return 3000 if prune and personal in messages[0]["content"] else 100
    with patch.object(server_manager, "start_planner_server", return_value=True), \
         patch.object(server_manager, "stop_planner_server"), \
         patch.object(server_manager, "count_planner_tokens", side_effect=token_count), \
         patch.object(server_manager.requests, "post", return_value=reply("Ready.")):
        server_manager.run_planner_chat("Check Atlas", [], user_profile_context=personal,
                                       context_receipt_callback=receipts.extend)
    assert bool(receipts) is not prune
    if receipts:
        assert receipts[0]["label"] == "Atlas uses the research folder"


def test_rejected_model_request_does_not_report_supplied_context():
    response = reply("unused")
    response.status_code = 400
    receipts = []
    with patch.object(server_manager, "start_planner_server", return_value=True), \
         patch.object(server_manager, "stop_planner_server"), \
         patch.object(server_manager.requests, "post", return_value=response):
        with pytest.raises(RuntimeError):
            server_manager.run_planner_chat("Check Atlas", [],
                user_profile_context=context({"relevant_facts": ["A fact"]}), context_receipt_callback=receipts.extend)
    assert receipts == []
