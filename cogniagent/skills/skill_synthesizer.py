"""
cogniagent/skills/skill_synthesizer.py

Collaborative Holo (VLM) + Qwen (Planner) Skill Synthesizer for OmniVLA.
Uses Holo for multimodal visual screen analysis and Qwen for procedural reasoning and Markdown SKILL.md generation.
"""

import base64
import json
from io import BytesIO
import logging
import requests
from typing import Dict, Any, Optional, List

from cogniagent.skills.skill_schema import SkillDefinition
from cogniagent.skills.skill_compiler import TeachingToSkillCompiler
from cogniagent.skills.observation_learner import ObservationDemonstration

logger = logging.getLogger(__name__)


class SkillSynthesizer:
    """Synthesizes high-level Markdown skills by combining Holo (Visual) and Qwen (Reasoning)."""

    def __init__(
        self,
        vlm_endpoint: str = "http://127.0.0.1:8089/v1",
        planner_endpoint: str = "http://127.0.0.1:8090/v1",
        enhance_with_models: bool = False,
    ):
        self.vlm_endpoint = vlm_endpoint.rstrip("/")
        self.planner_endpoint = planner_endpoint.rstrip("/")
        self.enhance_with_models = bool(enhance_with_models)
        self.compiler = TeachingToSkillCompiler()

    def analyze_visual_context_with_holo(self, screenshots_b64: List[str], task_goal: str) -> str:
        """Query Holo-3.1 VLM to analyze visual screenshots and identify UI landmarks."""
        if not screenshots_b64:
            return "No visual screenshots captured during demonstration."

        # One start/end contact sheet preserves temporal evidence while using
        # only one vision input and one grounding-token allocation.
        sampled_frames = [screenshots_b64[0]]
        if len(screenshots_b64) > 1:
            try:
                from PIL import Image, ImageOps

                frames = [Image.open(BytesIO(base64.b64decode(value))).convert("RGB") for value in (screenshots_b64[0], screenshots_b64[-1])]
                frames = [ImageOps.contain(frame, (1280, 720)) for frame in frames]
                sheet = Image.new("RGB", (1280, 1440), "white")
                sheet.paste(frames[0], ((1280 - frames[0].width) // 2, 0))
                sheet.paste(frames[1], ((1280 - frames[1].width) // 2, 720))
                buffer = BytesIO()
                sheet.save(buffer, format="JPEG", quality=86, optimize=True)
                sampled_frames = [base64.b64encode(buffer.getvalue()).decode("ascii")]
            except Exception as error:
                logger.debug("Could not build demonstration contact sheet: %s", error)
        
        prompt = (
            f"Analyze the following screenshot(s) from a demonstration for the task: '{task_goal}'.\n"
            "Identify:\n"
            "1. The primary application and visual layout.\n"
            "2. Key interactive visual landmarks (buttons, input fields, menus, tabs, icons) and their visual positions.\n"
            "3. Any visible modal dialogs, status banners, or state changes.\n"
            "Provide a concise, factual bulleted visual breakdown."
        )

        content_payload: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]
        for b64 in sampled_frames:
            content_payload.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}"}
            })

        try:
            resp = requests.post(
                f"{self.vlm_endpoint}/chat/completions",
                json={
                    "model": "Holo-3.1-4B",
                    "messages": [{"role": "user", "content": content_payload}],
                    "max_tokens": 512,
                    "temperature": 0.2,
                },
                timeout=60,
            )
            if resp.status_code == 200:
                data = resp.json()
                return data["choices"][0]["message"]["content"].strip()
            else:
                logger.warning("Holo visual analysis returned status %d", resp.status_code)
        except Exception as e:
            logger.warning("Holo visual analysis unavailable: %s", e)

        return "Standard desktop application interface with navigation controls and input areas."

    def synthesize_skill(
        self,
        demo: ObservationDemonstration,
        skill_name: Optional[str] = None
    ) -> SkillDefinition:
        """Synthesize an intelligent procedural SKILL.md by collaborating with Holo and Qwen."""
        task_goal = demo.task_goal.strip()
        logger.info("Synthesizing skill for demonstration: '%s'", task_goal)

        # Keep an offline path for recovery and tests. Studio enables model
        # enhancement so demonstrations are interpreted visually and then
        # generalized; this branch is not the normal product experience.
        if not self.enhance_with_models:
            skill = self.compiler.compile_observation(demo, skill_name=skill_name)
            logger.info("Compiled SkillDefinition without model inference: '%s'", skill.name)
            return skill

        # Stage 1: Multimodal visual analysis with Holo VLM
        visual_analysis = self.analyze_visual_context_with_holo(demo.key_screenshots, task_goal)

        # Stage 2: Prepare demonstration trace summary
        action_summary = []
        for i, act in enumerate(demo.actions[:40], 1):
            act_str = f"Step {i}: {act.action_type}"
            if act.text:
                act_str += " typed a reusable value"
            if act.key:
                act_str += f" key: '{act.key}'"
            if act.window_title:
                act_str += f" in window: '{act.window_title}'"
            action_summary.append(act_str)
        action_trace = "\n".join(action_summary) if action_summary else "No discrete actions recorded."

        app_context = ", ".join(demo.app_sequence) if demo.app_sequence else "Desktop Application"

        # Stage 3: Query Qwen Planner to synthesize full SKILL.md
        prompt = f"""You are an expert skill architect for a screenshot-grounded desktop agent.
A human operator demonstrated a task on the computer. Your job is to convert this specific demonstration into a reusable, generalized, high-level intelligent skill in standard Markdown format (SKILL.md).

TASK GOAL: {task_goal}
APPLICATIONS INVOLVED: {app_context}

HOLO VLM VISUAL ANALYSIS:
{visual_analysis[:1200]}

RECORDED USER DEMONSTRATION TRACE:
{action_trace[:3000]}

INSTRUCTIONS:
1. Synthesize a clean, parameterized skill in standard SKILL.md format with YAML frontmatter.
2. The frontmatter MUST include:
   - name: lower_snake_case identifier
   - title: Human-readable title
   - description: What this skill accomplishes
   - domain: browser, excel, desktop, terminal, or system
   - triggers: list of user intent trigger phrases
   - parameters: list of parameters with name, description, default_value, required (identify any variable text like search queries, filenames, URLs as {{param_name}})
   - tags: relevant keyword tags
3. The body MUST have:
   - ## Cognitive Strategy & Workflow: Step-by-step reasoning instructions for the VLM, with {{param_name}} placeholders.
   - ## Visual Landmarks & Grounding Cues: What visual icons, labels, and elements the VLM should look for on screen.
   - ## Failure Modes & Recovery: Recovery heuristics for popups, loading spinners, errors.

4. Generalize the demonstrated intent and visible landmarks. Never preserve recorded coordinates, timing, window geometry, or literal typed secrets.
5. Keep the full output below 5,000 characters so it remains compatible with the local model context.

Output ONLY the complete SKILL.md content starting with '---' and ending with markdown sections. No private reasoning or commentary."""

        skill_markdown = ""
        try:
            resp = requests.post(
                f"{self.planner_endpoint}/chat/completions",
                json={
                    "model": "Qwen3.5-4B",
                    "messages": [
                        {"role": "system", "content": "You are a specialized AI skill synthesis compiler."},
                        {"role": "user", "content": prompt}
                    ],
                    "max_tokens": 640,
                    "temperature": 0.2,
                },
                timeout=90,
            )
            if resp.status_code == 200:
                data = resp.json()
                raw_out = data["choices"][0]["message"]["content"].strip()
                # Clean code fences if present
                if raw_out.startswith("```markdown"):
                    raw_out = raw_out[11:].strip()
                elif raw_out.startswith("```"):
                    raw_out = raw_out[3:].strip()
                if raw_out.endswith("```"):
                    raw_out = raw_out[:-3].strip()
                skill_markdown = raw_out
        except Exception as e:
            logger.warning("Qwen planner synthesis call failed: %s. Using heuristic synthesizer.", e)

        # A bounded structural compiler keeps Studio useful when either local
        # model is temporarily unavailable. It learns intent and landmarks,
        # never replay coordinates or recorded timings.
        if not skill_markdown or not skill_markdown.startswith("---"):
            skill_markdown = self._heuristic_synthesis(demo, visual_analysis)

        skill = SkillDefinition.from_markdown(skill_markdown)
        if skill_name:
            skill.name = skill_name
        skill.author = "learned_from_observation"
        logger.info("Successfully synthesized SkillDefinition: '%s' (%s)", skill.name, skill.title)
        return skill

    def _heuristic_synthesis(self, demo: ObservationDemonstration, visual_analysis: str) -> str:
        """Build a coordinate-free recovery skill when model enhancement is unavailable."""
        skill = self.compiler.compile_observation(demo)
        analysis = str(visual_analysis or "").strip()[:1200]
        if analysis and "standard desktop application interface" not in analysis.casefold():
            skill.visual_landmarks = analysis
        if not skill.failure_recovery:
            skill.failure_recovery = (
                "- Re-inspect the current screen after loading or layout changes.\n"
                "- Dismiss unrelated dialogs only after identifying their purpose.\n"
                "- Confirm the expected visible result before finishing."
            )
        skill.author = "learned_from_observation"
        return skill.to_markdown()
