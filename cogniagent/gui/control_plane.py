"""Input contracts and safety policy for the OmniVLA command center.

The command center deliberately keeps its policy layer deterministic. It does
not pretend to understand every possible harmful action; instead it makes
high-impact intent visible and requires an explicit, just-in-time approval.
"""

from __future__ import annotations

import ipaddress
import re
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any


MAX_CHAT_CHARACTERS = 8_000
MAX_TASK_CHARACTERS = 12_000
MAX_HITL_CHARACTERS = 2_000
MAX_API_KEY_CHARACTERS = 1_024
MAX_MODEL_PATH_CHARACTERS = 512
MAX_AUDIT_EVENTS = 120

ALLOWED_MODEL_TYPES = {"local", "openai", "anthropic"}
ALLOWED_SAFETY_MODES = {"supervised", "autonomous"}


class RequestValidationError(ValueError):
    """Raised when a control-plane request does not meet its contract."""


def _require_text(value: Any, field_name: str, maximum: int, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise RequestValidationError(f"{field_name} must be text.")

    normalized = value.strip()
    if not normalized and not allow_empty:
        raise RequestValidationError(f"{field_name} cannot be empty.")
    if len(normalized) > maximum:
        raise RequestValidationError(f"{field_name} must be {maximum:,} characters or fewer.")
    if "\x00" in normalized:
        raise RequestValidationError(f"{field_name} contains an invalid character.")
    return normalized


def validate_chat_message(value: Any) -> str:
    return _require_text(value, "message", MAX_CHAT_CHARACTERS)


def validate_task(value: Any) -> str:
    return _require_text(value, "task", MAX_TASK_CHARACTERS)


def validate_hitl_response(value: Any) -> str:
    return _require_text(value, "response", MAX_HITL_CHARACTERS)


def validate_chat_id(value: Any) -> str:
    chat_id = _require_text(value, "chat id", 64)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", chat_id):
        raise RequestValidationError("chat id has an invalid format.")
    return chat_id


def validate_settings(payload: dict[str, Any], current: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    """Return persisted settings and an optional runtime-only provider key."""
    if not isinstance(payload, dict):
        raise RequestValidationError("settings must be an object.")

    settings = {
        "model_path": current.get("model_path", "models/Holo-3.1-4B-abliterated-rdo.Q4_K_M.gguf"),
        "temperature": current.get("temperature", 0.2),
        "max_steps": current.get("max_steps", 15),
        "enable_recording": current.get("enable_recording", False),
        "model_type": current.get("model_type", "local"),
    }

    model_type = settings["model_type"]
    if "model_type" in payload:
        model_type = _require_text(payload["model_type"], "model type", 32).lower()
        if model_type not in ALLOWED_MODEL_TYPES:
            raise RequestValidationError("model type is not supported.")
        settings["model_type"] = model_type

    if "temperature" in payload:
        temperature = payload["temperature"]
        if isinstance(temperature, bool) or not isinstance(temperature, (int, float)):
            raise RequestValidationError("temperature must be a number.")
        if not 0 <= float(temperature) <= 2:
            raise RequestValidationError("temperature must be between 0 and 2.")
        settings["temperature"] = float(temperature)

    if "max_steps" in payload:
        max_steps = payload["max_steps"]
        if isinstance(max_steps, bool) or not isinstance(max_steps, int):
            raise RequestValidationError("max steps must be a whole number.")
        if not 1 <= max_steps <= 100:
            raise RequestValidationError("max steps must be between 1 and 100.")
        settings["max_steps"] = max_steps

    if "enable_recording" in payload:
        recording = payload["enable_recording"]
        if not isinstance(recording, bool):
            raise RequestValidationError("enable recording must be true or false.")
        settings["enable_recording"] = recording

    model_path = _require_text(
        payload.get("model_path", settings["model_path"]),
        "model path" if model_type == "local" else "model identifier",
        MAX_MODEL_PATH_CHARACTERS,
    )
    if model_type == "local" and not model_path.lower().endswith(".gguf"):
        raise RequestValidationError("model path must point to a .gguf file for local execution.")
    if model_type != "local" and model_path.lower().endswith(".gguf"):
        raise RequestValidationError("Cloud providers need a provider model identifier, not a .gguf file.")
    settings["model_path"] = model_path

    runtime_api_key = None
    if "api_key" in payload:
        runtime_api_key = _require_text(
            payload["api_key"], "API key", MAX_API_KEY_CHARACTERS, allow_empty=True
        )

    return settings, runtime_api_key


def default_safety_policy() -> dict[str, Any]:
    return {
        "mode": "supervised",
        "require_plan_approval": True,
        "remote_control_enabled": False,
    }


def normalize_safety_policy(policy: Any) -> dict[str, Any]:
    normalized = default_safety_policy()
    if not isinstance(policy, dict):
        return normalized

    if policy.get("mode") in ALLOWED_SAFETY_MODES:
        normalized["mode"] = policy["mode"]
    for key in ("require_plan_approval", "remote_control_enabled"):
        if isinstance(policy.get(key), bool):
            normalized[key] = policy[key]
    return normalized


def validate_safety_policy(payload: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise RequestValidationError("safety policy must be an object.")

    policy = normalize_safety_policy(current)
    if "mode" in payload:
        mode = _require_text(payload["mode"], "safety mode", 32).lower()
        if mode not in ALLOWED_SAFETY_MODES:
            raise RequestValidationError("safety mode is not supported.")
        policy["mode"] = mode

    for key in ("require_plan_approval", "remote_control_enabled"):
        if key not in payload:
            continue
        value = payload[key]
        if not isinstance(value, bool):
            raise RequestValidationError(f"{key.replace('_', ' ')} must be true or false.")
        policy[key] = value

    return policy


RISK_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("deleting or overwriting data", re.compile(r"\b(delete|erase|remove|wipe|overwrite|format)\b", re.I)),
    ("sharing or sending data externally", re.compile(r"\b(send|post|publish|upload|share|email|message)\b", re.I)),
    ("financial or purchase activity", re.compile(r"\b(buy|purchase|pay|transfer|invoice|bank|checkout)\b", re.I)),
    ("credential or access changes", re.compile(r"\b(password|credential|api key|2fa|mfa|permission|access|login)\b", re.I)),
    ("software or system changes", re.compile(r"\b(install|uninstall|download|vpn|firewall|registry|system setting)\b", re.I)),
)


def assess_task_risk(task: str) -> dict[str, Any]:
    reasons = [label for label, rule in RISK_RULES if rule.search(task)]
    return {
        "requires_explicit_acknowledgement": bool(reasons),
        "reasons": reasons,
    }


def is_loopback_address(address: str) -> bool:
    try:
        return ipaddress.ip_address(address).is_loopback
    except ValueError:
        return False


@dataclass
class PairingSession:
    """Short-lived bearer pairing for an opt-in LAN companion session."""

    ttl_seconds: int = 15 * 60
    _token: str = field(default_factory=lambda: secrets.token_urlsafe(18), init=False, repr=False)
    _expires_at: float = field(init=False, repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)

    def __post_init__(self) -> None:
        self._expires_at = time.time() + self.ttl_seconds

    def rotate(self) -> dict[str, Any]:
        with self._lock:
            self._token = secrets.token_urlsafe(18)
            self._expires_at = time.time() + self.ttl_seconds
            return self.local_payload()

    def verify(self, candidate: Any) -> bool:
        if not isinstance(candidate, str):
            return False
        with self._lock:
            if time.time() >= self._expires_at:
                return False
            return secrets.compare_digest(candidate, self._token)

    def public_payload(self) -> dict[str, Any]:
        with self._lock:
            return {
                "pairing_required": True,
                "expires_at": int(self._expires_at),
                "expires_in_seconds": max(0, int(self._expires_at - time.time())),
            }

    def local_payload(self) -> dict[str, Any]:
        return {**self.public_payload(), "token": self._token}
