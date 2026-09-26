import pytest
import json

from cogniagent.skills.skill_registry import SkillRegistry
from cogniagent.skills.skill_schema import SkillDefinition


def test_skill_update_can_be_restored_without_loading_history(tmp_path):
    registry = SkillRegistry(str(tmp_path / "skills"))
    registry.save_skill(SkillDefinition(name="report", title="Original", description="First procedure"))
    registry.save_skill(SkillDefinition(name="report", title="Updated", description="Second procedure"))
    revisions = registry.list_revisions("report")
    assert len(revisions) == 1
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


@pytest.mark.parametrize("suffix", [".json", ".md"])
def test_imported_skill_updates_survive_restart_and_restore(tmp_path, suffix):
    directory = tmp_path / "skills"
    directory.mkdir()
    original = SkillDefinition(name="report", title="Original", description="Imported procedure")
    path = directory / ("imported" + suffix)
    path.write_text(json.dumps(original.to_dict()) if suffix == ".json" else original.to_markdown(), encoding="utf-8")
    registry = SkillRegistry(str(directory))
    updated = SkillDefinition(name="report", title="Updated", description="Improved procedure")
    assert registry.save_skill(updated) == str(path)
    reloaded = SkillRegistry(str(directory))
    assert len(reloaded.list_skills()) == 1
    assert reloaded.get_skill("report").title == "Updated"
    revision = reloaded.list_revisions("report")[0]["revision"]
    reloaded.restore_revision("report", revision)
    assert SkillRegistry(str(directory)).get_skill("report").title == "Original"


def test_identical_save_does_not_create_revision(tmp_path):
    registry = SkillRegistry(str(tmp_path / "skills"))
    skill = SkillDefinition(name="report", title="Report", description="Procedure")
    registry.save_skill(skill)
    registry.save_skill(skill)
    assert registry.list_revisions("report") == []
