"""
tests/test_skills.py

Unit tests for OmniVLA Intelligent Markdown Skills System, Observation Learner, and Collaborative Holo + Qwen Synthesizer.
"""

import unittest
import time
import os
import shutil
import tempfile
from unittest.mock import Mock, patch

import tests.conftest
tests.conftest.init_mocks()

from cogniagent.skills.skill_schema import (
    SkillParameter,
    SkillDefinition,
)
from cogniagent.skills.skill_registry import SkillRegistry
from cogniagent.skills.observation_learner import ObservationLearner, ObservationDemonstration, ObservedAction
from cogniagent.skills.skill_synthesizer import SkillSynthesizer
from cogniagent.skills.skill_compiler import TeachingToSkillCompiler
from cogniagent.skills.teaching_recorder import DemonstrationAction, DemonstrationEpisode


class TestSkillsSystem(unittest.TestCase):
    def setUp(self):
        tests.conftest.init_mocks()
        self.temp_dir = tempfile.mkdtemp()
        self.registry = SkillRegistry(skills_dir=self.temp_dir)
        self.synthesizer = SkillSynthesizer()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_01_skill_markdown_serialization_and_parsing(self):
        """Verify SkillDefinition parses and formats standard SKILL.md with YAML frontmatter."""
        raw_md = """---
name: web_research
title: Web Research & Synthesis
description: Searches the web and summarizes findings into a document.
domain: browser
triggers:
  - "research *"
  - "find info on *"
parameters:
  - name: topic
    description: Search query topic
    default_value: "OmniVLA"
    required: true
author: system
version: 1.0.0
tags: [web, research]
---

# Web Research & Synthesis

Searches the web and summarizes findings into a document.

## Cognitive Strategy & Workflow
1. Focus browser and enter query `{{topic}}`.
2. Select top organic results.
3. Extract findings into target app.

## Visual Landmarks & Grounding Cues
- Omnibox search input at top center.
- Organic result hyperlinks in blue.

## Failure Modes & Recovery
- If cookie popup appears, click Accept.
"""
        skill = SkillDefinition.from_markdown(raw_md)
        self.assertEqual(skill.name, "web_research")
        self.assertEqual(skill.title, "Web Research & Synthesis")
        self.assertEqual(skill.domain, "browser")
        self.assertEqual(len(skill.parameters), 1)
        self.assertEqual(skill.parameters[0].name, "topic")
        self.assertIn("Focus browser", skill.strategy)
        self.assertIn("Omnibox search input", skill.visual_landmarks)
        self.assertIn("cookie popup", skill.failure_recovery)

        # Verify round-trip serialization
        exported_md = skill.to_markdown()
        self.assertIn("name: web_research", exported_md)
        self.assertIn("## Cognitive Strategy & Workflow", exported_md)

    def test_02_parameter_placeholder_rendering(self):
        """Verify dynamic {{param}} placeholders render correctly."""
        skill = SkillDefinition(
            name="export_report",
            title="Export Report",
            description="Export file",
            strategy="Navigate to portal, click export for `{{date_range}}`, and save to `{{destination}}`.",
            parameters=[
                SkillParameter(name="date_range", default_value="last_30_days"),
                SkillParameter(name="destination", default_value="C:/Reports"),
            ]
        )

        rendered = skill.render_strategy({"date_range": "2026-Q1", "destination": "D:/Finance"})
        self.assertEqual(rendered, "Navigate to portal, click export for `2026-Q1`, and save to `D:/Finance`.")

    def test_03_observation_learner_session(self):
        """Verify ObservationLearner records human demonstration actions."""
        learner = ObservationLearner(screen_dims=(1920, 1080))
        self.assertFalse(learner.is_observing)

        learner.start_observation("Clean spreadsheet data in Excel")
        self.assertTrue(learner.is_observing)

        learner.record_click(x=300, y=400, button="left", window_title="Excel", visual_cue="Table Header A1")
        learner.record_typing("Product Sales Data", window_title="Excel")
        learner.record_key("ctrl+b", window_title="Excel")

        demo = learner.stop_observation()
        self.assertFalse(learner.is_observing)
        self.assertIsNotNone(demo)
        self.assertEqual(demo.task_goal, "Clean spreadsheet data in Excel")
        self.assertEqual(len(demo.actions), 3)
        self.assertIn("Excel", demo.app_sequence)

    def test_04_collaborative_skill_synthesis(self):
        """Verify Holo + Qwen skill synthesizer creates a valid SKILL.md from demonstration."""
        demo = ObservationDemonstration(
            task_goal="Search Python docs for asyncio",
            actions=[],
            key_screenshots=[],
            app_sequence=["Google Chrome"],
            started_at=time.time() - 10,
            finished_at=time.time(),
        )

        skill = self.synthesizer.synthesize_skill(demo)
        self.assertIsNotNone(skill)
        self.assertIn("asyncio", skill.title.lower() + skill.description.lower() + skill.strategy.lower())
        self.assertEqual(skill.author, "learned_from_observation")
        self.assertTrue(bool(skill.strategy))

    def test_05_skill_registry_storage_and_search(self):
        """Verify SkillRegistry saves, discovers, and searches Markdown skills."""
        skill = SkillDefinition(
            name="slack_status",
            title="Update Slack Status",
            description="Sets focus or vacation status on Slack",
            domain="desktop",
            triggers=["set slack status", "update status on slack"],
            parameters=[SkillParameter(name="status_text", default_value="In a meeting")],
            strategy="1. Open Slack.\n2. Click profile picture.\n3. Type `{{status_text}}`.",
            tags=["slack", "chat", "status"]
        )

        fpath = self.registry.save_skill(skill)
        self.assertTrue(os.path.exists(fpath))

        # Search matching
        results = self.registry.search_skills("slack vacation")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "slack_status")

        # Reload registry
        fresh_registry = SkillRegistry(skills_dir=self.temp_dir)
        loaded = fresh_registry.get_skill("slack_status")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.title, "Update Slack Status")

    def test_06_holo_vlm_prompt_guidance_generation(self):
        """Verify formatting procedural knowledge for Holo VLM injection."""
        skill = SkillDefinition(
            name="jira_ticket",
            title="Create Jira Ticket",
            description="Fills out and creates a new bug ticket",
            strategy="1. Click 'Create' button.\n2. Fill summary with `{{summary}}`.",
            visual_landmarks="Blue 'Create' button at top header navigation.",
            failure_recovery="If required field error appears, fill default description.",
            parameters=[SkillParameter(name="summary", default_value="Bug report")]
        )

        guidance = self.registry.format_skill_prompt_for_holo(skill, {"summary": "Fix login crash"})
        self.assertIn("ACTIVE SKILL GUIDANCE: Create Jira Ticket", guidance)
        self.assertIn("Fix login crash", guidance)
        self.assertIn("Blue 'Create' button", guidance)
        self.assertIn("If required field error appears", guidance)

    def test_model_enhancement_generalizes_demo_without_coordinate_replay(self):
        demo = ObservationDemonstration(
            task_goal="Create a reusable note",
            actions=[ObservedAction("click", time.time(), x=947, y=521, visual_cue="New note button")],
            key_screenshots=[],
            app_sequence=["Notes"],
        )
        synthesized = """---
name: reusable_note
title: Create Note
description: Creates a note from a supplied value.
domain: desktop
triggers: [create a note]
parameters: []
tags: [notes]
---
## Cognitive Strategy & Workflow
1. Inspect the current Notes state and activate the visible New note control.
2. Verify that an empty note is ready.
## Visual Landmarks & Grounding Cues
- The labelled New note control in the application chrome.
## Failure Modes & Recovery
- Re-inspect after any layout change.
"""
        response = Mock(status_code=200)
        response.json.return_value = {"choices": [{"message": {"content": synthesized}}]}
        engine = SkillSynthesizer(enhance_with_models=True)
        with patch.object(engine, "analyze_visual_context_with_holo", return_value="New note control"), patch(
            "cogniagent.skills.skill_synthesizer.requests.post", return_value=response
        ) as post:
            skill = engine.synthesize_skill(demo)
        assert skill.name == "reusable_note"
        assert "947" not in skill.to_markdown()
        assert post.call_args.kwargs["json"]["max_tokens"] == 640

    def test_model_failure_fallback_never_serializes_coordinates(self):
        demo = ObservationDemonstration(
            task_goal="Open a report",
            actions=[ObservedAction("click", time.time(), x=811, y=233, visual_cue="Report row")],
            app_sequence=["Reports"],
        )
        engine = SkillSynthesizer(enhance_with_models=True)
        with patch.object(engine, "analyze_visual_context_with_holo", return_value="Report row"), patch(
            "cogniagent.skills.skill_synthesizer.requests.post", side_effect=OSError("offline")
        ):
            skill = engine.synthesize_skill(demo)
        markdown = skill.to_markdown()
        assert "811" not in markdown and "233" not in markdown
        assert "Report row" in markdown

    def test_07_mds_files_and_common_step_headings_are_loaded(self):
        path = os.path.join(self.temp_dir, "browser_search.mds")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("""---
name: browser_search
title: Browser Search
description: Search from the browser address field.
triggers: [\"search *\"]
parameters:
  - name: search_query
    required: true
---
# Browser Search

## Steps
1. Focus the address field.
2. Type `{{search_query}}` and press Enter.
""")

        self.registry.load_all_skills()
        skill = self.registry.get_skill("browser_search")
        self.assertIsNotNone(skill)
        self.assertIn("Focus the address field", skill.strategy)

    def test_08_hot_path_router_can_return_no_match_and_extract_wildcards(self):
        search = SkillDefinition(
            name="browser_search",
            title="Browser Search",
            description="Search in a browser",
            triggers=["search *"],
            parameters=[SkillParameter(name="search_query", required=True)],
            strategy="Search for {{search_query}}.",
        )
        excel = SkillDefinition(
            name="excel_data_clean",
            title="Clean Excel Data",
            description="Clean spreadsheet rows",
            triggers=["clean excel data"],
            strategy="Remove empty rows.",
        )
        self.registry.save_skill(search)
        self.registry.save_skill(excel)

        started = time.perf_counter()
        unmatched, _ = self.registry.match_skill("Play Laufey in Spotify")
        elapsed = time.perf_counter() - started
        matched, params = self.registry.match_skill("Please search Python asyncio documentation")

        self.assertIsNone(unmatched)
        self.assertLess(elapsed, 0.05)
        self.assertEqual(matched.name, "browser_search")
        self.assertEqual(params["search_query"], "Python asyncio documentation")

    def test_09_guidance_is_bounded_for_local_model_context(self):
        skill = SkillDefinition(
            name="large_skill",
            title="Large Skill",
            description="A" * 2_000,
            strategy="Step.\n" * 4_000,
            visual_landmarks="Landmark. " * 2_000,
            failure_recovery="Recover. " * 2_000,
        )
        guidance = self.registry.format_skill_prompt_for_holo(skill)
        self.assertLessEqual(len(guidance), 900)

    def test_10_demonstration_compiler_uses_semantics_and_redacts_typed_defaults(self):
        episode = DemonstrationEpisode(
            task_prompt="Search product documentation",
            actions=[
                DemonstrationAction(
                    action_type="click",
                    timestamp=time.time(),
                    x=845,
                    y=122,
                    window_title="Browser",
                    target_element_hint="address field",
                ),
                DemonstrationAction(
                    action_type="type",
                    timestamp=time.time(),
                    text="private demonstration value",
                    window_title="Browser",
                ),
            ],
        )
        skill = TeachingToSkillCompiler().compile_demonstration(episode)

        self.assertIn("address field", skill.strategy)
        self.assertNotIn("(845", skill.strategy)
        self.assertNotIn("private demonstration value", skill.to_markdown())
        self.assertIn("{{search_query}}", skill.strategy)
        self.assertIsNone(skill.parameters[0].default_value)


if __name__ == "__main__":
    unittest.main()
