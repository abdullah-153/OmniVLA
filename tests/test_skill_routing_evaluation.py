from evaluate_skill_routing import evaluate
from cogniagent.skills.skill_registry import SkillRegistry
from cogniagent.skills.skill_schema import SkillDefinition, SkillParameter


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
