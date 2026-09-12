"""Fast, deterministic demonstration-to-skill compiler."""

from __future__ import annotations

import re
from typing import Any, Iterable, Optional

from cogniagent.skills.skill_schema import SkillDefinition, SkillParameter
from cogniagent.skills.teaching_recorder import DemonstrationEpisode


class TeachingToSkillCompiler:
    """Turn observed intent and actions into semantic, model-agnostic guidance.

    Screen coordinates are deliberately not compiled into the skill. They are
    tied to one resolution and window layout; the visual executor should
    relocate the demonstrated label or control on each fresh screenshot.
    """

    @staticmethod
    def _slugify(text: str) -> str:
        clean = re.sub(r"[^A-Za-z0-9\s_-]", "", str(text)).strip().lower()
        return (re.sub(r"[-\s]+", "_", clean).strip("_")[:48] or "custom_skill")

    @staticmethod
    def _value(action: Any, *names: str, default: Any = None) -> Any:
        for name in names:
            value = getattr(action, name, None)
            if value not in (None, ""):
                return value
        return default

    @staticmethod
    def _parameter_base(goal: str, index: int) -> str:
        lowered = goal.lower()
        if any(word in lowered for word in ("search", "find", "look up")):
            return "search_query"
        if "url" in lowered or "website" in lowered:
            return "url"
        if any(word in lowered for word in ("file", "folder", "path", "document")):
            return "file_path"
        if any(word in lowered for word in ("message", "email", "reply", "send")):
            return "message_text"
        return "input_value" if index == 1 else f"input_value_{index}"

    @staticmethod
    def _domain(apps: list[str]) -> str:
        joined = " ".join(apps).lower()
        if any(app in joined for app in ("chrome", "edge", "firefox", "brave", "browser")):
            return "browser"
        if any(app in joined for app in ("excel", "spreadsheet", "libreoffice calc")):
            return "excel"
        if any(app in joined for app in ("terminal", "powershell", "command prompt", "windows terminal")):
            return "terminal"
        return "desktop"

    def _compile(
        self,
        goal: str,
        actions: Iterable[Any],
        apps: Iterable[str],
        *,
        skill_name: Optional[str],
        parameterize_text: bool,
    ) -> SkillDefinition:
        goal = " ".join(str(goal or "").split()) or "Repeat demonstrated task"
        action_list = list(actions or [])[:100]
        app_list = list(dict.fromkeys(str(app).strip() for app in (apps or []) if str(app).strip()))[:12]
        if not app_list:
            app_list = list(dict.fromkeys(
                str(getattr(action, "window_title", "")).strip()
                for action in action_list
                if str(getattr(action, "window_title", "")).strip()
            ))[:12]

        parameters: list[SkillParameter] = []
        parameter_names: set[str] = set()
        instructions: list[str] = []
        landmarks: list[str] = []
        typed_index = 0

        for action in action_list:
            action_type = str(getattr(action, "action_type", "")).strip().lower()
            window = str(getattr(action, "window_title", "")).strip()[:160]
            cue = str(self._value(action, "target_element_hint", "visual_cue", default="")).strip()[:240]
            location = f" in {window}" if window else ""

            if action_type in {"click", "double_click", "right_click"}:
                target = cue or "the demonstrated control"
                verb = {"click": "click", "double_click": "double-click", "right_click": "right-click"}[action_type]
                instructions.append(f"Visually locate {target}{location} and {verb} it.")
                landmark = f"{target}{location}".strip()
                if landmark and landmark.casefold() not in {item.casefold() for item in landmarks}:
                    landmarks.append(landmark)
                continue

            if action_type == "type":
                typed_text = self._value(action, "text", default="")
                if typed_text in (None, ""):
                    continue
                typed_index += 1
                if parameterize_text:
                    base = self._parameter_base(goal, typed_index)
                    name = base
                    suffix = 2
                    while name in parameter_names:
                        name = f"{base}_{suffix}"
                        suffix += 1
                    parameter_names.add(name)
                    parameters.append(SkillParameter(
                        name=name,
                        description=f"Text to enter during demonstrated input {typed_index}",
                        type="string",
                        default_value=None,
                        required=True,
                    ))
                    value = f"{{{{{name}}}}}"
                else:
                    value = str(typed_text)[:500]
                instructions.append(f"Focus the demonstrated input{location} and type `{value}`.")
                continue

            if action_type in {"key_press", "hotkey"}:
                key = str(getattr(action, "key", "")).strip()[:64]
                if key:
                    instructions.append(f"Press `{key}`{location}.")
                continue

            if action_type == "scroll":
                direction = str(getattr(action, "direction", "down")).lower()
                instructions.append(f"Scroll {direction if direction in {'up', 'down'} else 'down'} and re-scan the visible controls.")

        if not instructions:
            instructions = [
                f"Open or focus the appropriate application for: {goal}.",
                "Use visible labels and controls to complete the goal.",
                "Verify the expected result is visible before finishing.",
            ]
        strategy = "\n".join(f"{index}. {instruction}" for index, instruction in enumerate(instructions, 1))

        if app_list:
            landmarks.insert(0, "Application context: " + ", ".join(app_list))
        visual_landmarks = "\n".join(f"- {item}" for item in landmarks[:16]) or "- Use visible labels from the demonstrated workflow; do not reuse recorded coordinates."

        triggers = [goal.lower()[:300]]
        if parameters and parameters[0].name == "search_query":
            triggers.append("search *")
        tags = [token for token in self._slugify(goal).split("_") if len(token) > 2][:12]
        domain = self._domain(app_list)
        title = goal if len(goal) <= 72 else goal[:69].rstrip() + "…"

        return SkillDefinition(
            name=skill_name or self._slugify(goal),
            title=title,
            description=f"Repeats the demonstrated workflow for {goal}.",
            domain=domain,
            triggers=triggers,
            parameters=parameters,
            author="learned_from_observation",
            tags=[domain, "learned", *tags],
            strategy=strategy,
            visual_landmarks=visual_landmarks,
            failure_recovery=(
                "- If the expected control is not visible, wait briefly, dismiss only non-sensitive blocking UI, and re-scan.\n"
                "- If the layout differs from the demonstration, use labels and roles rather than recorded positions.\n"
                "- Ask the operator when the target is ambiguous or a sensitive step is required."
            ),
        )

    def compile_demonstration(
        self,
        episode: DemonstrationEpisode,
        skill_name: Optional[str] = None,
        parameterize_text: bool = True,
    ) -> SkillDefinition:
        return self._compile(
            episode.task_prompt,
            episode.actions,
            [],
            skill_name=skill_name,
            parameterize_text=parameterize_text,
        )

    def compile_observation(
        self,
        demonstration: Any,
        skill_name: Optional[str] = None,
        parameterize_text: bool = True,
    ) -> SkillDefinition:
        return self._compile(
            getattr(demonstration, "task_goal", ""),
            getattr(demonstration, "actions", []),
            getattr(demonstration, "app_sequence", []),
            skill_name=skill_name,
            parameterize_text=parameterize_text,
        )
