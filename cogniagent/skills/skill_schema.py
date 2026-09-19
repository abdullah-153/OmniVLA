"""Validated Markdown schema used by the local desktop skill system."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


MAX_SKILL_BYTES = 128 * 1024
ALLOWED_PARAMETER_TYPES = {"string", "number", "boolean", "choice"}


def _text(value: Any, default: str = "", limit: int = 1_000) -> str:
    if value is None:
        return default
    cleaned = str(value).replace("\x00", "").strip()
    return cleaned[:limit] or default


def _slug(value: Any, default: str = "custom_skill", limit: int = 64) -> str:
    candidate = re.sub(r"[^A-Za-z0-9_-]+", "_", _text(value, default, 200)).strip("_-")
    if not candidate or not candidate[0].isalnum():
        candidate = default
    return candidate[:limit]


def _list(value: Any, *, limit: int = 32, item_limit: int = 300) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            stripped = stripped[1:-1]
        values = stripped.split(",") if "," in stripped else [stripped]
    elif isinstance(value, (list, tuple, set)):
        values = list(value)
    else:
        values = [value]

    result: List[str] = []
    seen = set()
    for item in values:
        cleaned = _text(item, limit=item_limit).strip("\"'")
        key = cleaned.casefold()
        if cleaned and key not in seen:
            result.append(cleaned)
            seen.add(key)
        if len(result) >= limit:
            break
    return result


def _bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "required", "on"}
    return bool(value)


@dataclass
class SkillParameter:
    """A typed value that can be inserted into a reusable skill."""

    name: str
    description: str = ""
    type: str = "string"
    default_value: Any = None
    required: bool = False
    choices: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.name = _slug(self.name, "param", 48).replace("-", "_")
        self.description = _text(self.description, limit=300)
        normalized_type = _text(self.type, "string", 24).lower()
        self.type = normalized_type if normalized_type in ALLOWED_PARAMETER_TYPES else "string"
        self.required = _bool(self.required)
        self.choices = _list(self.choices, limit=20, item_limit=120)
        if isinstance(self.default_value, str):
            self.default_value = self.default_value[:1_000]

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "type": self.type,
            "default_value": self.default_value,
            "required": self.required,
            "choices": self.choices,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SkillParameter":
        if not isinstance(data, dict):
            return cls(name=str(data or "param"))
        return cls(
            name=data.get("name", "param"),
            description=data.get("description", ""),
            type=data.get("type", "string"),
            default_value=data.get("default_value", data.get("default")),
            required=data.get("required", False),
            choices=data.get("choices", []),
        )


@dataclass
class SkillDefinition:
    """A compact, model-agnostic procedure stored as Markdown."""

    name: str
    title: str
    description: str
    domain: str = "general"
    triggers: List[str] = field(default_factory=list)
    parameters: List[SkillParameter] = field(default_factory=list)
    author: str = "user"
    version: str = "1.0.0"
    tags: List[str] = field(default_factory=list)
    strategy: str = ""
    visual_landmarks: str = ""
    failure_recovery: str = ""
    raw_markdown: str = ""
    created_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        self.name = _slug(self.name)
        self.title = _text(self.title, self.name.replace("_", " ").title(), 200)
        self.description = _text(self.description, limit=1_000)
        self.domain = _slug(self.domain, "general", 32).lower()
        self.triggers = _list(self.triggers, limit=32, item_limit=300)
        self.tags = _list(self.tags, limit=32, item_limit=80)
        self.parameters = [
            value if isinstance(value, SkillParameter) else SkillParameter.from_dict(value)
            for value in (self.parameters or [])[:32]
        ]
        self.author = _text(self.author, "user", 80)
        self.version = _text(self.version, "1.0.0", 32)
        self.strategy = _text(self.strategy, limit=16_000)
        self.visual_landmarks = _text(self.visual_landmarks, limit=8_000)
        self.failure_recovery = _text(self.failure_recovery, limit=8_000)
        try:
            self.created_at = float(self.created_at)
        except (TypeError, ValueError):
            self.created_at = time.time()

    def render_strategy(self, params: Dict[str, Any]) -> str:
        """Substitute declared placeholders without evaluating arbitrary templates."""
        text = self.strategy
        params = params or {}
        for parameter in self.parameters:
            value = params.get(parameter.name, parameter.default_value)
            if value is not None:
                text = text.replace(f"{{{{{parameter.name}}}}}", str(value)[:5_000])
        return text

    def to_markdown(self) -> str:
        """Serialize to a portable SKILL.md document."""
        frontmatter = {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "domain": self.domain,
            "triggers": self.triggers,
            "parameters": [parameter.to_dict() for parameter in self.parameters],
            "author": self.author,
            "version": self.version,
            "tags": self.tags,
        }
        fm_str = (
            yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).strip()
            if yaml
            else json.dumps(frontmatter, ensure_ascii=False, indent=2)
        )
        sections = [
            f"---\n{fm_str}\n---",
            f"# {self.title}\n\n{self.description}".strip(),
        ]
        if self.strategy:
            sections.append(f"## Cognitive Strategy & Workflow\n{self.strategy.strip()}")
        if self.visual_landmarks:
            sections.append(f"## Visual Landmarks & Grounding Cues\n{self.visual_landmarks.strip()}")
        if self.failure_recovery:
            sections.append(f"## Failure Modes & Recovery\n{self.failure_recovery.strip()}")
        return "\n\n".join(sections).rstrip() + "\n"

    @staticmethod
    def _section_kind(heading: str) -> str | None:
        normalized = re.sub(r"[^a-z0-9]+", " ", heading.lower()).strip()
        if any(term in normalized for term in ("visual landmark", "visual cue", "grounding cue", "ui landmark")):
            return "visual"
        if any(term in normalized for term in ("failure", "recovery", "troubleshoot", "error handling", "edge case")):
            return "recovery"
        if normalized in {"steps", "instructions", "procedure", "process"} or any(
            term in normalized for term in ("strategy", "workflow", "how to", "execution steps")
        ):
            return "strategy"
        return None

    @classmethod
    def _parse_sections(cls, body: str) -> tuple[str, str, str]:
        matches = list(re.finditer(r"(?m)^#{2,6}\s+(.+?)\s*$", body))
        buckets = {"strategy": [], "visual": [], "recovery": []}
        for index, match in enumerate(matches):
            kind = cls._section_kind(match.group(1))
            if not kind:
                continue
            end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
            content = body[match.end():end].strip()
            if content:
                buckets[kind].append(content)
        strategy = "\n\n".join(buckets["strategy"]).strip()
        visual = "\n\n".join(buckets["visual"]).strip()
        recovery = "\n\n".join(buckets["recovery"]).strip()
        if not strategy:
            preamble = body[:matches[0].start()] if matches else body
            strategy = re.sub(r"(?m)^#\s+.+?\s*$", "", preamble, count=1).strip()
        return strategy, visual, recovery

    @classmethod
    def from_markdown(cls, md_content: str) -> "SkillDefinition":
        """Parse SKILL.md, .md, .markdown, or .mds content safely."""
        if not isinstance(md_content, str):
            raise ValueError("Skill content must be Markdown text.")
        if len(md_content.encode("utf-8", errors="ignore")) > MAX_SKILL_BYTES:
            raise ValueError("Skill Markdown exceeds the 128 KB safety limit.")
        normalized = md_content.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n").strip()
        if not normalized:
            raise ValueError("Skill Markdown is empty.")

        frontmatter: dict = {}
        body = normalized
        fm_match = re.match(r"^---[ \t]*\n([\s\S]*?)\n---[ \t]*(?:\n|$)([\s\S]*)$", normalized)
        if fm_match:
            fm_raw, body = fm_match.group(1), fm_match.group(2).strip()
            if yaml:
                try:
                    parsed = yaml.safe_load(fm_raw)
                    frontmatter = parsed if isinstance(parsed, dict) else {}
                except Exception:
                    frontmatter = {}
            if not frontmatter:
                try:
                    parsed = json.loads(fm_raw)
                    frontmatter = parsed if isinstance(parsed, dict) else {}
                except Exception:
                    frontmatter = cls._parse_simple_yaml(fm_raw)

        h1 = re.search(r"(?m)^#\s+(.+?)\s*$", body)
        inferred_title = _text(h1.group(1), limit=200) if h1 else ""
        strategy, visual_landmarks, failure_recovery = cls._parse_sections(body)
        description = _text(frontmatter.get("description"), limit=1_000)
        if description and strategy.startswith(description):
            strategy = strategy[len(description):].lstrip("\n ")

        raw_parameters = frontmatter.get("parameters", [])
        if isinstance(raw_parameters, dict):
            raw_parameters = [
                {"name": name, **(value if isinstance(value, dict) else {"default_value": value})}
                for name, value in raw_parameters.items()
            ]
        if not isinstance(raw_parameters, list):
            raw_parameters = [raw_parameters]
        parameters = [SkillParameter.from_dict(value) for value in raw_parameters[:32]]

        name = _slug(frontmatter.get("name", "custom_skill"))
        title = _text(frontmatter.get("title"), inferred_title or name.replace("_", " ").title(), 200)
        if not description:
            paragraphs = [
                value.strip()
                for value in re.split(r"\n\s*\n", re.sub(r"(?m)^#\s+.+?\s*$", "", body, count=1))
                if value.strip() and not value.lstrip().startswith("##")
            ]
            description = _text(paragraphs[0] if paragraphs else "", limit=1_000)

        return cls(
            name=name,
            title=title,
            description=description,
            domain=frontmatter.get("domain", "general"),
            triggers=frontmatter.get("triggers", []),
            parameters=parameters,
            author=frontmatter.get("author", "user"),
            version=frontmatter.get("version", "1.0.0"),
            tags=frontmatter.get("tags", []),
            strategy=strategy,
            visual_landmarks=visual_landmarks,
            failure_recovery=failure_recovery,
            raw_markdown=md_content,
            created_at=frontmatter.get("created_at", time.time()),
        )

    @staticmethod
    def _parse_simple_yaml(text: str) -> dict:
        """Small fallback for list-heavy frontmatter when PyYAML is absent."""
        result: dict = {}
        current_list_key = None
        current_dict = None
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("- ") and current_list_key:
                value = stripped[2:].strip().strip("\"'")
                result.setdefault(current_list_key, [])
                if ":" in value:
                    key, raw = value.split(":", 1)
                    current_dict = {key.strip(): raw.strip().strip("\"'")}
                    result[current_list_key].append(current_dict)
                else:
                    result[current_list_key].append(value)
                    current_dict = None
                continue
            if (line.startswith("  ") or line.startswith("\t")) and current_dict is not None and ":" in stripped:
                key, raw = stripped.split(":", 1)
                value: Any = raw.strip().strip("\"'")
                if value.lower() in {"true", "false"}:
                    value = value.lower() == "true"
                current_dict[key.strip()] = value
                continue
            current_dict = None
            if ":" not in stripped:
                continue
            key, raw = stripped.split(":", 1)
            key, raw = key.strip(), raw.strip()
            if not raw:
                result[key] = []
                current_list_key = key
            elif raw.startswith("[") and raw.endswith("]"):
                result[key] = [item.strip().strip("\"'") for item in raw[1:-1].split(",") if item.strip()]
                current_list_key = None
            else:
                value = raw.strip("\"'")
                result[key] = value.lower() == "true" if value.lower() in {"true", "false"} else value
                current_list_key = None
        return result

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "domain": self.domain,
            "triggers": self.triggers,
            "parameters": [parameter.to_dict() for parameter in self.parameters],
            "author": self.author,
            "version": self.version,
            "tags": self.tags,
            "strategy": self.strategy,
            "visual_landmarks": self.visual_landmarks,
            "failure_recovery": self.failure_recovery,
            "raw_markdown": self.to_markdown(),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SkillDefinition":
        if not isinstance(data, dict):
            raise ValueError("Skill data must be an object.")
        return cls(
            name=data.get("name", "custom_skill"),
            title=data.get("title", "Custom Skill"),
            description=data.get("description", ""),
            domain=data.get("domain", "general"),
            triggers=data.get("triggers", []),
            parameters=data.get("parameters", []),
            author=data.get("author", "user"),
            version=data.get("version", "1.0.0"),
            tags=data.get("tags", []),
            strategy=data.get("strategy", ""),
            visual_landmarks=data.get("visual_landmarks", ""),
            failure_recovery=data.get("failure_recovery", ""),
            raw_markdown=data.get("raw_markdown", ""),
            created_at=data.get("created_at", time.time()),
        )
