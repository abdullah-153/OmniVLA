"""Unit tests for Intelligent Skill Synthesis in OmniVLA."""

import pytest
from cogniagent.skills.skill_synthesizer import SkillSynthesizer
from cogniagent.skills.skill_schema import SkillDefinition
from cogniagent.skills.skill_registry import SkillRegistry


def test_heuristic_intelligent_synthesis():
    synthesizer = SkillSynthesizer(enhance_with_models=False)
    skill = synthesizer.synthesize_intelligent_skill(
        goal="Check unread emails in Gmail and summarize the latest 3",
        domain="productivity",
        context_notes="Look for the unread tab and search bar",
        skill_name="check_gmail_inbox",
    )

    assert isinstance(skill, SkillDefinition)
    assert skill.name == "check_gmail_inbox"
    assert "Check Unread Emails In Gmail" in skill.title or "Check" in skill.title
    assert skill.domain == "productivity"
    assert len(skill.triggers) >= 1
    assert any("check" in t.lower() for t in skill.triggers)
    assert skill.parameters is not None
    assert len(skill.strategy) > 0
    assert "focus" in skill.strategy.lower() or "verify" in skill.strategy.lower()
    assert "visual" in skill.visual_landmarks.lower() or "controls" in skill.visual_landmarks.lower()
    assert len(skill.failure_recovery) > 0
    assert skill.author == "intelligent_synthesis"


def test_intelligent_skill_markdown_roundtrip_and_registry():
    synthesizer = SkillSynthesizer(enhance_with_models=False)
    skill = synthesizer.synthesize_intelligent_skill(
        goal="Export monthly invoice to PDF",
        domain="finance",
        context_notes="Click Print, select Save as PDF, specify directory",
    )

    markdown = skill.to_markdown()
    assert markdown.startswith("---")
    assert "name: " in markdown
    assert "domain: finance" in markdown
    assert "## Cognitive Strategy" in markdown

    # Re-parse from Markdown
    reparsed = SkillDefinition.from_markdown(markdown)
    assert reparsed.name == skill.name
    assert reparsed.domain == "finance"

    # Match in registry with @mention
    registry = SkillRegistry()
    registry._skills_cache[skill.name] = reparsed

    matched, _ = registry.match_skill(f"Please run @{skill.name} for October")
    assert matched is not None
    assert matched.name == skill.name
