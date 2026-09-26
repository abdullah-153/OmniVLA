import pytest
import json

from cogniagent.skills.skill_registry import SkillRegistry
from cogniagent.skills.skill_schema import SkillDefinition


def test_skill_update_can_be_restored_without_loading_history(tmp_path):
    registry = SkillRegistry(str(tmp_path / "skills"))
    registry.save_skill(SkillDefinition(name="report", title="Original", description="First procedure"))
    original_revision = registry.current_revision("report")
    registry.save_skill(SkillDefinition(name="report", title="Updated", description="Second procedure"))
    revisions = registry.list_revisions("report")
    assert len(revisions) == 1
    assert revisions[0]["revision"] == original_revision
    reloaded = SkillRegistry(str(tmp_path / "skills"))
    assert len(reloaded.list_skills()) == 1
    assert reloaded.get_skill("report").title == "Updated"
    reloaded.restore_revision("report", revisions[0]["revision"])
    assert reloaded.get_skill("report").title == "Original"
    assert len(reloaded.list_revisions("report")) == 2


def test_damaged_skill_revision_cannot_be_restored(tmp_path):
    registry = SkillRegistry(str(tmp_path / "skills"))
    registry.save_skill(SkillDefinition(name="report", title="Original", description="First"))
    registry.save_skill(SkillDefinition(name="report", title="Updated", description="Second"))
    revision = registry.list_revisions("report")[0]["revision"]
    (tmp_path / "skills" / "report" / ".history" / (revision + ".md")).write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="damaged"):
        registry.restore_revision("report", revision)
    assert registry.get_skill("report").title == "Updated"


@pytest.mark.parametrize("suffix", [".json", ".md", ".markdown", ".mds"])
def test_imported_skill_updates_survive_restart_and_restore(tmp_path, suffix):
    directory = tmp_path / "skills"
    directory.mkdir()
    original = SkillDefinition(name="report", title="Original", description="Imported procedure")
    path = directory / ("imported" + suffix)
    path.write_text(json.dumps(original.to_dict()) if suffix == ".json" else original.to_markdown(), encoding="utf-8")
    registry = SkillRegistry(str(directory))
    original_revision = registry.current_revision("report")
    updated = SkillDefinition(name="report", title="Updated", description="Improved procedure")
    assert registry.save_skill(updated) == str(path)
    reloaded = SkillRegistry(str(directory))
    assert len(reloaded.list_skills()) == 1
    assert reloaded.get_skill("report").title == "Updated"
    revision = reloaded.list_revisions("report")[0]["revision"]
    assert revision == original_revision
    reloaded.restore_revision("report", revision)
    assert SkillRegistry(str(directory)).get_skill("report").title == "Original"
    assert SkillRegistry(str(directory)).current_revision("report") == original_revision


def test_identical_save_does_not_create_revision(tmp_path):
    registry = SkillRegistry(str(tmp_path / "skills"))
    skill = SkillDefinition(name="report", title="Report", description="Procedure")
    registry.save_skill(skill)
    registry.save_skill(skill)
    assert registry.list_revisions("report") == []


def test_outcome_metrics_persist_and_deduplicate_runs(tmp_path):
    directory = tmp_path / "skills"
    registry = SkillRegistry(str(directory))
    assert registry.outcome_summary("report") == []
    registry.record_outcome("report", "a" * 64, "run-1", True, 1000, 3, "visual")
    registry.record_outcome("report", "a" * 64, "run-1", True, 1000, 3, "visual")
    registry.record_outcome("report", "a" * 64, "run-2", False, 3000, 8, "inconclusive")
    registry.record_outcome("report", "b" * 64, "run-3", True, 500, 2, "operator")
    summaries = {row["revision"]: row for row in SkillRegistry(str(directory)).outcome_summary("report")}
    assert summaries["a" * 64]["runs"] == 2
    assert summaries["a" * 64]["successful_runs"] == 1
    assert summaries["a" * 64]["average_duration_ms"] == 2000
    assert summaries["a" * 64]["visual_runs"] == 1
    assert summaries["a" * 64]["operator_runs"] == 0
    assert summaries["a" * 64]["inconclusive_runs"] == 1
    assert summaries["b" * 64]["runs"] == 1
    assert summaries["b" * 64]["operator_runs"] == 1
