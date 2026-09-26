from evaluate_skill_routing import evaluate
from cogniagent.skills.skill_registry import SkillRegistry
from cogniagent.skills.skill_schema import SkillDefinition, SkillParameter
from cogniagent.memory.user_profile import UserProfileMemory


def test_labeled_routing_and_abstention(tmp_path):
    registry = SkillRegistry(str(tmp_path / "skills"))
    registry.save_skill(SkillDefinition(name="search", title="Web search", description="Search",
        triggers=["search *"], parameters=[SkillParameter(name="query", required=True)]))
    cases = [
        {"id": "explicit", "prompt": "Use @search", "expected_skill": "search"},
        {"id": "wildcard", "prompt": "search release notes", "expected_skill": "search",
         "expected_parameters": {"query": "release notes"}},
        {"id": "unrelated", "prompt": "Play music", "expected_skill": None},
    ]
    report = evaluate(registry, cases)
    assert report["passed"] == 3 and report["false_selections"] == 0
    assert len(report["versions"]["search"]) == 64
    registry.save_skill(SkillDefinition(name="other_search", title="Alternative search", description="Search",
                                       triggers=["search *"]))
    ambiguous = evaluate(registry, [{"prompt": "search release notes", "expected_skill": None}])
    assert ambiguous["passed"] == 1


def test_application_bound_skill_uses_task_choice_or_saved_preference(tmp_path):
    registry = SkillRegistry(str(tmp_path / "skills"))
    registry.save_skill(SkillDefinition(
        name="gmail_summary", title="Summarize Gmail", description="Read unread messages in Gmail",
        triggers=["summarize unread emails", "check my inbox"],
        application="Gmail", preference_path="email.service"))
    registry = SkillRegistry(str(tmp_path / "skills"))
    gmail = {"preferences": {"email": {"service": "Gmail"}}}
    outlook = {"preferences": {"email": {"service": "Outlook"}}}
    assert registry.get_skill("gmail_summary").application == "Gmail"
    assert registry.match_skill("Summarize unread emails")[0] is None
    assert registry.match_skill("Summarize unread emails", context_pack=outlook)[0] is None
    assert registry.match_skill("Summarize unread emails", context_pack=gmail)[0].name == "gmail_summary"
    assert registry.match_skill("Summarize unread emails in Outlook", context_pack=gmail)[0] is None
    assert registry.match_skill("Summarize unread emails in Gmail", context_pack=outlook)[0].name == "gmail_summary"
    override = {"preferences": outlook["preferences"], "task_overrides": {"email": {"service": "Gmail"}}}
    assert registry.match_skill("Use Gmail instead of Outlook. Summarize unread emails.", context_pack=override)[0].name == "gmail_summary"
    assert registry.match_skill("Do not use Gmail; summarize unread emails", context_pack=gmail)[0] is None
    assert registry.match_skill("Do not check my inbox; summarize my calendar", context_pack=gmail)[0] is None
    assert registry.match_skill("Use @gmail_summary to summarize unread emails", context_pack=outlook)[0].name == "gmail_summary"
    report = evaluate(registry, [
        {"id": "saved-outlook", "prompt": "Summarize unread emails", "context_pack": outlook, "expected_skill": None},
        {"id": "saved-gmail", "prompt": "Summarize unread emails", "context_pack": gmail, "expected_skill": "gmail_summary"},
    ])
    assert report["passed"] == 2 and report["false_selections"] == 0
    assert report["versions"]["gmail_summary"] == registry.current_revision("gmail_summary")
    assert "context_pack" not in report["cases"][0]
    profile = UserProfileMemory(str(tmp_path / "personal"))
    profile.update_preference("email", "service", "Outlook")
    assert registry.match_skill("Summarize unread emails", context_pack=profile.build_context_pack("Summarize unread emails"))[0] is None
    profile.update_preference("email", "service", "Gmail")
    assert registry.match_skill("Summarize unread emails", context_pack=profile.build_context_pack("Summarize unread emails"))[0].name == "gmail_summary"


def test_negated_trigger_does_not_route_unbound_skill(tmp_path):
    registry = SkillRegistry(str(tmp_path / "skills"))
    registry.save_skill(SkillDefinition(name="clean_excel", title="Clean Excel Data", description="Clean rows",
                                        triggers=["clean excel data"]))
    assert registry.match_skill("Do not clean Excel data; just open the file")[0] is None
    assert registry.match_skill("Please clean Excel data")[0].name == "clean_excel"
    registry.save_skill(SkillDefinition(name="research", title="Web research", description="Research topics",
                                        triggers=["research *"], parameters=[SkillParameter(name="topic", required=True)]))
    matched, params = registry.match_skill("Do not research pricing. Research battery safety.")
    assert matched.name == "research" and params["topic"] == "battery safety"
