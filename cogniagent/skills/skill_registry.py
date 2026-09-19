"""
cogniagent/skills/skill_registry.py

Intelligent Skill Registry for OmniVLA.
Discovers, loads, searches, and manages Markdown SKILL.md blueprints, and routes selected skills to Holo VLM for visual execution.
"""

import os
import re
import json
import logging
from typing import List, Dict, Any, Optional

from cogniagent.skills.skill_schema import SkillDefinition

logger = logging.getLogger(__name__)


class SkillRegistry:
    """Manages discovery, storage, search, and dynamic prompt injection of intelligent Markdown skills."""

    def __init__(self, skills_dir: str = "./skills"):
        self.skills_dir = os.path.abspath(skills_dir)
        os.makedirs(self.skills_dir, exist_ok=True)
        self._skills_cache: Dict[str, SkillDefinition] = {}
        self._skill_paths: Dict[str, str] = {}
        self.load_all_skills()

    @staticmethod
    def validate_skill_name(name: str) -> str:
        """Accept a portable slug and reject every path-bearing name."""
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", name):
            raise ValueError("Skill name must be a 1–64 character letter/number slug using '-' or '_'.")
        return name

    def load_all_skills(self) -> Dict[str, SkillDefinition]:
        """Scan recursively for portable Markdown and JSON skill definitions."""
        self._skills_cache.clear()
        self._skill_paths.clear()
        if not os.path.exists(self.skills_dir):
            return self._skills_cache

        for root, dirs, files in os.walk(self.skills_dir):
            dirs.sort()
            for fname in sorted(files):
                fpath = os.path.join(root, fname)
                lower_name = fname.lower()
                is_markdown = lower_name == "skill.md" or (
                    lower_name.endswith((".md", ".markdown", ".mds")) and not fname.startswith(".")
                )
                if is_markdown:
                    try:
                        with open(fpath, "r", encoding="utf-8") as f:
                            content = f.read()
                        skill = SkillDefinition.from_markdown(content)
                        # If name not explicitly set, use parent folder name or file stem
                        if skill.name in {"custom_skill", ""}:
                            skill.name = os.path.basename(root) if fname.lower() == "skill.md" else os.path.splitext(fname)[0]
                        if skill.name in self._skills_cache:
                            logger.warning("Ignoring duplicate skill name '%s' from %s", skill.name, fpath)
                            continue
                        self._skills_cache[skill.name] = skill
                        self._skill_paths[skill.name] = os.path.abspath(fpath)
                        logger.debug("Loaded Markdown skill '%s' from %s", skill.name, fpath)
                    except Exception as e:
                        logger.warning("Failed to parse SKILL.md at %s: %s", fpath, e)
                elif lower_name.endswith(".json") and not fname.startswith("."):
                    try:
                        with open(fpath, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        skill = SkillDefinition.from_dict(data)
                        if skill.name in self._skills_cache:
                            logger.warning("Ignoring duplicate skill name '%s' from %s", skill.name, fpath)
                            continue
                        self._skills_cache[skill.name] = skill
                        self._skill_paths[skill.name] = os.path.abspath(fpath)
                    except Exception as e:
                        logger.warning("Failed to parse JSON skill at %s: %s", fpath, e)

        logger.info("SkillRegistry: Loaded %d intelligent skills from %s", len(self._skills_cache), self.skills_dir)
        return self._skills_cache

    def get_skill(self, name: str) -> Optional[SkillDefinition]:
        """Get a skill definition by name."""
        try:
            return self._skills_cache.get(self.validate_skill_name(name))
        except ValueError:
            return None

    def list_skills(self) -> List[SkillDefinition]:
        """Return list of all registered skills."""
        return list(self._skills_cache.values())

    def save_skill(self, skill: SkillDefinition) -> str:
        """Save a SkillDefinition to skills/<skill_name>/SKILL.md."""
        skill.name = self.validate_skill_name(skill.name)
        target_dir = os.path.join(self.skills_dir, skill.name)
        os.makedirs(target_dir, exist_ok=True)
        fpath = os.path.join(target_dir, "SKILL.md")

        temp_path = f"{fpath}.tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            f.write(skill.to_markdown())
        os.replace(temp_path, fpath)

        self._skills_cache[skill.name] = skill
        self._skill_paths[skill.name] = os.path.abspath(fpath)
        logger.info("Saved intelligent skill '%s' to %s", skill.name, fpath)
        return fpath

    def delete_skill(self, name: str) -> bool:
        """Delete a skill from disk and memory."""
        name = self.validate_skill_name(name)
        skill = self._skills_cache.pop(name, None)
        source_path = self._skill_paths.pop(name, None)
        if not skill:
            return False

        deleted = False
        if source_path and os.path.exists(source_path):
            try:
                if os.path.commonpath([self.skills_dir, source_path]) != self.skills_dir:
                    raise ValueError("Skill source is outside the skills directory.")
                os.remove(source_path)
                target_dir = os.path.dirname(source_path)
                if target_dir != self.skills_dir and not os.listdir(target_dir):
                    os.rmdir(target_dir)
                deleted = True
            except (OSError, ValueError) as e:
                logger.error("Failed to delete skill source %s: %s", source_path, e)

        return deleted

    def search_skills(self, query: str, max_results: int = 5) -> List[SkillDefinition]:
        """Rank skills based on token relevance across title, triggers, description, and tags."""
        q_clean = query.lower()
        q_tokens = set(re.findall(r"\w+", q_clean))
        scored = []

        for skill in self._skills_cache.values():
            score = 0
            # Direct trigger matching
            for trig in skill.triggers:
                if trig.lower() in q_clean or q_clean in trig.lower():
                    score += 15
                elif any(t in trig.lower() for t in q_tokens):
                    score += 5

            # Name / Title match
            if skill.name in q_clean or skill.title.lower() in q_clean:
                score += 10
            for token in q_tokens:
                if token in skill.name.lower():
                    score += 4
                if token in skill.title.lower():
                    score += 3
                if token in skill.description.lower():
                    score += 2
                if any(token in t.lower() for t in skill.tags):
                    score += 3

            if score > 0:
                scored.append((score, skill))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [s for _, s in scored[:max_results]]

    _STOP_WORDS = {
        "a", "an", "and", "app", "for", "from", "in", "into", "my", "of", "on",
        "open", "please", "the", "to", "with", "using", "do", "make", "set",
    }

    @classmethod
    def _tokens(cls, text: str) -> set[str]:
        return {
            token for token in re.findall(r"[a-z0-9]+", str(text).lower())
            if len(token) > 1 and token not in cls._STOP_WORDS
        }

    @staticmethod
    def _wildcard_match(trigger: str, task_prompt: str) -> Optional[str]:
        pieces = [re.escape(piece.strip()) for piece in trigger.split("*")]
        pattern = r"(?<!\w)" + r"\s*(.+?)\s*".join(pieces) + r"(?:$|[.!?])"
        match = re.search(pattern, task_prompt, flags=re.IGNORECASE)
        if not match:
            return None
        captures = [value.strip(" \t\"'") for value in match.groups() if value.strip()]
        return captures[0][:1_000] if captures else ""

    def match_skill(self, task_prompt: str) -> tuple[Optional[SkillDefinition], Dict[str, Any]]:
        """Select only a high-confidence skill without calling either model.

        Skill routing sits on the first-action hot path, so it must be
        deterministic, effectively instant, and able to return no match. The
        previous implementation waited up to 15 seconds and then selected an
        arbitrary first candidate when routing failed.
        """
        raw_query = " ".join(str(task_prompt or "").split())
        query = raw_query.lower()
        if not query:
            return None, {}

        # Check for explicit @skill_name mention in task prompt
        mentions = re.findall(r"@([A-Za-z0-9_-]+)", raw_query)
        for mention in mentions:
            mention_clean = mention.lower().replace("-", "_")
            for sname, sdef in self._skills_cache.items():
                if sname.lower().replace("-", "_") == mention_clean:
                    logger.info("Explicit @%s skill mention detected. Forcing skill match.", sname)
                    return sdef, {}

        query_tokens = self._tokens(query)
        ranked = []

        for skill in self._skills_cache.values():
            score = 0
            capture = None
            for trigger in skill.triggers:
                normalized_trigger = " ".join(trigger.lower().split())
                if not normalized_trigger:
                    continue
                if "*" in normalized_trigger:
                    wildcard_value = self._wildcard_match(normalized_trigger, raw_query)
                    if wildcard_value is not None:
                        score = max(score, 100 + len(self._tokens(normalized_trigger)))
                        capture = wildcard_value
                elif re.search(rf"(?<!\w){re.escape(normalized_trigger)}(?!\w)", query):
                    score = max(score, 90 + min(8, len(self._tokens(normalized_trigger))))

            title_tokens = self._tokens(f"{skill.name} {skill.title}")
            metadata_tokens = title_tokens | self._tokens(" ".join(skill.tags))
            overlap = query_tokens & metadata_tokens
            if len(overlap) >= 2 and title_tokens and len(overlap & title_tokens) / len(title_tokens) >= 0.5:
                score = max(score, 70 + len(overlap))
            if score >= 70:
                ranked.append((score, skill.name, skill, capture))

        if not ranked:
            return None, {}
        _, _, skill, capture = max(ranked, key=lambda item: (item[0], item[1]))
        params: Dict[str, Any] = {}
        if capture:
            candidates = [parameter for parameter in skill.parameters if parameter.required and parameter.type == "string"]
            if not candidates:
                candidates = [parameter for parameter in skill.parameters if parameter.type == "string"]
            if candidates:
                params[candidates[0].name] = capture
        return skill, params

    def select_skill_with_qwen(
        self,
        task_prompt: str,
        planner_endpoint: str = "http://127.0.0.1:8090/v1"
    ) -> tuple[Optional[SkillDefinition], Dict[str, Any]]:
        """Backward-compatible alias for the zero-model deterministic router."""
        return self.match_skill(task_prompt)

    def format_skill_prompt_for_holo(self, skill: SkillDefinition, params: Dict[str, Any] = None) -> str:
        """Format the selected skill into cognitive visual guidance for Holo VLM."""
        params = params or {}
        rendered_strategy = skill.render_strategy(params)

        def clip(value: str, limit: int) -> str:
            value = " ".join(value.split()) if "\n" not in value else value.strip()
            return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"

        prompt_block = (
            f"=== ACTIVE SKILL GUIDANCE: {skill.title} ===\n"
            f"GOAL: {clip(skill.description, 140)}\n"
            f"STEPS:\n{clip(rendered_strategy, 430)}\n"
        )
        if skill.visual_landmarks:
            prompt_block += f"VISUAL CUES:\n{clip(skill.visual_landmarks, 150)}\n"
        if skill.failure_recovery:
            prompt_block += f"RECOVERY:\n{clip(skill.failure_recovery, 90)}\n"
        prompt_block += "Use the newest screenshot as the source of truth.\n=== END SKILL GUIDANCE ==="

        return prompt_block[:900]
