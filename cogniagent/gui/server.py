"""HTTP control plane for the OmniVLA command center.

The web application intentionally talks only to this local control plane.  The
handler validates every mutation, keeps provider secrets out of persisted state,
and requires a short-lived pairing token for optional LAN companion sessions.
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler
from typing import Any
from urllib.parse import urlsplit

import cogniagent.gui.app as gui_app

from cogniagent.skills.skill_registry import SkillRegistry
from cogniagent.skills.skill_schema import SkillDefinition
from cogniagent.skills.observation_learner import ObservationLearner
from cogniagent.skills.teaching_recorder import NativeObservationRecorder
from cogniagent.skills.skill_synthesizer import SkillSynthesizer

from cogniagent.gui.control_plane import (
    MAX_AUDIT_EVENTS,
    PairingSession,
    RequestValidationError,
    assess_task_risk,
    default_safety_policy,
    is_loopback_address,
    normalize_safety_policy,
    validate_chat_id,
    validate_chat_message,
    validate_hitl_response,
    validate_safety_policy,
    validate_skill_markdown,
    validate_skill_name,
    validate_settings,
    validate_task,
    validate_observation_goal,
    validate_observed_action,
)
from cogniagent.gui.web_assets import get_asset


logger = logging.getLogger(__name__)

MAX_REQUEST_BYTES = 64 * 1024
CHATS_DB_PATH = "chats_db.json"

DEFAULT_SETTINGS = {
    "model_path": "models/Holo-3.1-4B-abliterated-rdo.Q4_K_M.gguf",
    "planner_model_path": "models/Qwen3.5-4B.Q4_K_M.gguf",
    "temperature": 0.2,
    "max_steps": 60,
    "enable_recording": False,
    "memory_enabled": False,
    "model_type": "local",
}

telemetry_data = {
    "free_vram": None,
    "optimal_ngl": 28,
    "vla_gpu": None,
    "planner_gpu": None,
    "planner_active": None,
    "planner_uses_gpu": False,
    "planner_ngl": 0,
}

db_lock = threading.RLock()
planner_lock = threading.Lock()
planner_active_chat_id = None
_db_cache: dict[str, Any] | None = None
telemetry_thread: threading.Thread | None = None
pairing_session = PairingSession()
skills_registry = SkillRegistry()
observation_learner = ObservationLearner()
native_observation_recorder = NativeObservationRecorder(observation_learner)
skill_synthesizer = SkillSynthesizer(enhance_with_models=True)
chat_retrieval = None
last_recorded_demo = None


def _new_chat() -> dict[str, Any]:
    now = int(time.time())
    return {
        "id": secrets.token_hex(10),
        "title": "New chat",
        "status": "draft",
        "intent": "",
        "chat_history": [],
        "current_task": "",
        "run_metrics": None,
        "execution": _empty_execution_snapshot(),
        "created_at": now,
        "updated_at": now,
    }


def _empty_execution_snapshot() -> dict[str, Any]:
    return {
        "status": "idle",
        "phase": "idle",
        "phase_started_at": None,
        "step": 0,
        "total_time_ms": 0,
        "current_action": "Ready",
        "current_thought": "",
        "paused": False,
        "steps": [],
        "timing": {
            "last_model_ms": None,
            "last_action_ms": None,
            "last_verification_ms": None,
            "last_step_ms": None,
            "updated_at": None,
        },
    }


def _normalize_execution_snapshot(value: Any) -> dict[str, Any]:
    snapshot = _empty_execution_snapshot()
    if not isinstance(value, dict):
        return snapshot

    snapshot["status"] = str(value.get("status") or "idle")[:32]
    snapshot["phase"] = str(value.get("phase") or snapshot["status"])[:32]
    snapshot["current_action"] = str(value.get("current_action") or "Ready")[:500]
    snapshot["current_thought"] = ""
    snapshot["paused"] = bool(value.get("paused", False))
    for key, maximum in (("step", 10_000), ("total_time_ms", 24 * 60 * 60 * 1_000)):
        candidate = value.get(key)
        snapshot[key] = max(0, min(int(candidate), maximum)) if isinstance(candidate, (int, float)) and not isinstance(candidate, bool) else 0
    started = value.get("phase_started_at")
    snapshot["phase_started_at"] = float(started) if isinstance(started, (int, float)) else None

    timing = value.get("timing") if isinstance(value.get("timing"), dict) else {}
    for key in ("last_model_ms", "last_action_ms", "last_verification_ms", "last_step_ms"):
        candidate = timing.get(key)
        snapshot["timing"][key] = max(0, min(int(candidate), 24 * 60 * 60 * 1_000)) if isinstance(candidate, (int, float)) and not isinstance(candidate, bool) else None
    updated = timing.get("updated_at")
    snapshot["timing"]["updated_at"] = float(updated) if isinstance(updated, (int, float)) else None

    steps = value.get("steps") if isinstance(value.get("steps"), list) else []
    safe_steps = []
    for raw in steps[-60:]:
        if not isinstance(raw, dict):
            continue
        succeeded = bool(raw.get("success", False))
        raw_action = str(raw.get("action") or "")[:80]
        action_text = str(raw.get("action_text") or raw_action)[:300]
        public_prefixes = {
            "Click · ": "Use · ",
            "Double Click · ": "Open · ",
            "Right Click · ": "Options for · ",
            "Move · ": "Point to · ",
            "Type ": "Enter ",
            "Press · ": "Use key · ",
            "Switch app · ": "Bring forward · ",
            "Open app · ": "Open · ",
        }
        for legacy, public in public_prefixes.items():
            if action_text.startswith(legacy):
                action_text = public + action_text[len(legacy):]
                break
        search_result = re.fullmatch(
            r"(?:Use|Open) · Open button for (.+?) app in (?:the )?search results?",
            action_text,
            flags=re.IGNORECASE,
        )
        if search_result:
            action_text = f"Open {search_result.group(1).strip()} from search results"
        if raw_action == "terminate" or action_text == "Terminate":
            action_text = "Finish task"
        safe_steps.append({
            "step": max(0, min(int(raw.get("step", 0)), 10_000)) if isinstance(raw.get("step"), (int, float)) else 0,
            "action": raw_action,
            "action_text": action_text,
            "thought": "",
            "output": "Completed" if succeeded else ("Action did not complete" if raw.get("output") else ""),
            "success": succeeded,
            "eval_state": str(raw.get("eval_state") or "")[:32],
        })
    snapshot["steps"] = safe_steps
    return snapshot


def _default_database() -> dict[str, Any]:
    chat = _new_chat()
    return {
        "active_chat_id": chat["id"],
        "chats": [chat],
        "settings": dict(DEFAULT_SETTINGS),
        "safety": default_safety_policy(),
        "audit_events": [],
    }


def _is_internal_assistant_message(content: str) -> bool:
    """Identify legacy planner scratch text that should never be rendered as chat."""
    normalized = " ".join(content.strip().lower().split())
    if not normalized:
        return False
    if normalized.startswith("hello — i am omnivla. describe a desktop task"):
        return True
    if "<think>" in normalized or "</think>" in normalized:
        return True
    internal_prefixes = (
        "let me analyze",
        "the user is asking",
        "i need to:",
        "key observations:",
        "since the user is asking",
        "the failure message indicates",
        "we need to analyze",
        "we need to respond",
    )
    return normalized.startswith(internal_prefixes)


def _is_terminal_summary(content: str) -> bool:
    normalized = " ".join(str(content or "").strip().casefold().split())
    return normalized.startswith(("task completed", "completed the task", "the task could not", "task failed"))


def _plan_copy(content: Any, limit: int = 24_000) -> str:
    """Migrate legacy planner output into safe, plain-language plan copy."""
    value = str(content or "")[:limit]
    if re.search(r"(?:^|\n)\s*(?:[-*]\s*)?(?:step\s*)?\d+[.):]", value, re.IGNORECASE):
        try:
            from cogniagent.gui.server_manager import extract_planner_output

            value = extract_planner_output(value)
        except (RuntimeError, ValueError):
            pass
    return re.sub(
        r"\brunbook\b",
        lambda match: "Plan" if match.group(0)[:1].isupper() else "plan",
        value,
        flags=re.IGNORECASE,
    )


def _chat_title(message: str) -> str:
    """Create a stable, scannable title without another model request."""
    words = " ".join(message.split()).strip().split(" ")
    if words and words[0].lower() in {"please", "could", "can", "would"}:
        words = words[1:]
    selected = words[:7]
    while selected and selected[-1].lower().strip(".,:;!?") in {"a", "an", "and", "for", "from", "the", "to", "with"}:
        selected.pop()
    title = " ".join(selected).strip(" .,:;!?-")
    if not title:
        return "New chat"
    return title[:52]


def _recover_interrupted_chats(database: dict[str, Any]) -> dict[str, Any]:
    """Turn states left live by a previous process into honest terminal states."""
    for chat in database.get("chats", []):
        if chat.get("status") not in {"running", "planning", "thinking"}:
            continue
        chat["status"] = "stopped"
        execution = _normalize_execution_snapshot(chat.get("execution"))
        execution.update(
            {
                "status": "stopped",
                "phase": "stopped",
                "current_action": "Interrupted before the app restarted.",
                "paused": False,
            }
        )
        chat["execution"] = execution
    return database


def _normalize_database(database: Any) -> dict[str, Any]:
    if not isinstance(database, dict):
        return _default_database()

    chats = database.get("chats")
    if not isinstance(chats, list) or not chats:
        return _default_database()

    normalized_chats = []
    for chat in chats:
        if not isinstance(chat, dict):
            continue
        chat_id = chat.get("id")
        if not isinstance(chat_id, str) or not chat_id:
            chat_id = secrets.token_hex(10)
        history = chat.get("chat_history")
        if not isinstance(history, list):
            history = []
        safe_history = []
        for message in history[-200:]:
            if not isinstance(message, dict) or message.get("role") not in {"user", "assistant"}:
                continue
            content = message.get("content")
            if isinstance(content, str):
                if message["role"] == "assistant":
                    content = _plan_copy(content)
                    if _is_internal_assistant_message(content):
                        continue
                normalized_message = {"role": message["role"], "content": content[:24_000]}
                if message["role"] == "assistant" and (message.get("kind") == "run_result" or _is_terminal_summary(content)):
                    normalized_message["kind"] = "run_result"
                    safe_history = [
                        item for item in safe_history
                        if not (item.get("role") == "assistant" and item.get("kind") == "run_result")
                    ]
                safe_history.append(normalized_message)
        now = int(time.time())
        raw_title = str(chat.get("title") or "New chat")
        if len(raw_title) > 52 or raw_title.endswith("…") or raw_title in {"Untitled run", "New run"}:
            raw_title = _chat_title(str(chat.get("intent") or raw_title))
        normalized_chats.append(
            {
                "id": chat_id,
                "title": raw_title[:52],
                "status": str(chat.get("status") or "draft")[:32],
                "intent": str(chat.get("intent") or "")[:12_000],
                "chat_history": safe_history,
                "current_task": _plan_copy(chat.get("current_task"), 12_000),
                "reviewed_plan": _plan_copy(chat.get("reviewed_plan"), 12_000),
                "run_metrics": _normalize_run_metrics(chat.get("run_metrics")),
                "execution": _normalize_execution_snapshot(chat.get("execution")),
                "created_at": int(chat.get("created_at")) if isinstance(chat.get("created_at"), (int, float)) else now,
                "updated_at": int(chat.get("updated_at")) if isinstance(chat.get("updated_at"), (int, float)) else now,
            }
        )

    if not normalized_chats:
        return _default_database()

    settings = database.get("settings")
    if not isinstance(settings, dict):
        settings = {}
    # Legacy files may contain an API key. It is intentionally discarded during

    settings.pop("api_key", None)
    try:
        normalized_settings, _ = validate_settings(
            {key: settings.get(key, default) for key, default in DEFAULT_SETTINGS.items()},
            DEFAULT_SETTINGS,
        )
    except RequestValidationError:
        logger.warning("Ignoring invalid persisted execution settings and restoring safe defaults.")
        normalized_settings = dict(DEFAULT_SETTINGS)

    active_id = database.get("active_chat_id")
    valid_ids = {chat["id"] for chat in normalized_chats}
    if active_id not in valid_ids:
        active_id = normalized_chats[0]["id"]

    audit_events = database.get("audit_events")
    if not isinstance(audit_events, list):
        audit_events = []
    safe_events = [event for event in audit_events if isinstance(event, dict)][-MAX_AUDIT_EVENTS:]

    return {
        "active_chat_id": active_id,
        "chats": normalized_chats,
        "settings": normalized_settings,
        "safety": normalize_safety_policy(database.get("safety")),
        "audit_events": safe_events,
    }


def _normalize_run_metrics(value: Any) -> dict[str, Any] | None:
    """Keep only bounded, content-free measurements in persisted run history."""
    if not isinstance(value, dict):
        return None

    def bounded_int(candidate: Any, maximum: int) -> int | None:
        if isinstance(candidate, bool) or not isinstance(candidate, (int, float)):
            return None
        return max(0, min(int(candidate), maximum))

    phase_metrics: dict[str, dict[str, int]] = {}
    raw_phases = value.get("phases")
    if isinstance(raw_phases, dict):
        for phase in ("model", "action", "verification", "step"):
            raw = raw_phases.get(phase)
            if not isinstance(raw, dict):
                continue
            normalized = {
                key: bounded_int(raw.get(key), 24 * 60 * 60 * 1000)
                for key in ("count", "median_ms", "p95_ms")
            }
            if all(item is not None for item in normalized.values()):
                phase_metrics[phase] = normalized

    profile = value.get("profile") if isinstance(value.get("profile"), dict) else {}
    return {
        "status": str(value.get("status") or "unknown")[:24],
        "finished_at": bounded_int(value.get("finished_at"), 9_999_999_999),
        "duration_ms": bounded_int(value.get("duration_ms"), 24 * 60 * 60 * 1000),
        "steps": bounded_int(value.get("steps"), 10_000),
        "phases": phase_metrics,
        "profile": {
            "engine": str(profile.get("engine") or "unknown")[:32],
            "vla": str(profile.get("vla") or "unknown")[:160],
            "planner": str(profile.get("planner") or "unknown")[:160],
        },
    }


def load_chats_db() -> dict[str, Any]:
    global _db_cache
    with db_lock:
        if _db_cache is not None:
            return _db_cache

        if not os.path.exists(CHATS_DB_PATH) or os.path.getsize(CHATS_DB_PATH) == 0:
            _db_cache = _default_database()
            save_chats_db(_db_cache)
            return _db_cache

        try:
            with open(CHATS_DB_PATH, "r", encoding="utf-8") as database_file:
                raw_database = json.load(database_file)
            _db_cache = _recover_interrupted_chats(_normalize_database(raw_database))
            # Persist schema/security migrations immediately. In particular,
            # legacy API keys must not remain on disk simply because the user
            # has not changed another setting yet.
            if raw_database != _db_cache:
                save_chats_db(_db_cache)
            return _db_cache
        except (OSError, ValueError, json.JSONDecodeError) as error:
            logger.error("Unable to read chat database; restoring a clean schema: %s", error)
            _db_cache = _default_database()
            save_chats_db(_db_cache)
            return _db_cache


def save_chats_db(database: dict[str, Any]) -> None:
    """Atomically persist settings, conversations, policy, and the audit journal."""
    global _db_cache
    with db_lock:
        normalized = _normalize_database(database)
        temporary_path = CHATS_DB_PATH + ".tmp"
        try:
            with open(temporary_path, "w", encoding="utf-8") as database_file:
                json.dump(normalized, database_file, ensure_ascii=False, indent=2)
                database_file.flush()
                os.fsync(database_file.fileno())
            os.replace(temporary_path, CHATS_DB_PATH)
            _db_cache = normalized
        except OSError as error:
            logger.error("Unable to persist chat database: %s", error)
            try:
                if os.path.exists(temporary_path):
                    os.remove(temporary_path)
            except OSError:
                pass


def _find_chat(database: dict[str, Any], chat_id: str) -> dict[str, Any] | None:
    return next((chat for chat in database["chats"] if chat["id"] == chat_id), None)


def _active_chat(database: dict[str, Any]) -> dict[str, Any]:
    chat = _find_chat(database, database["active_chat_id"])
    if chat:
        return chat
    database["active_chat_id"] = database["chats"][0]["id"]
    return database["chats"][0]


def _record_audit(database: dict[str, Any], kind: str, message: str) -> None:
    events = database.setdefault("audit_events", [])
    events.append(
        {
            "id": secrets.token_hex(6),
            "timestamp": int(time.time()),
            "kind": kind[:40],
            "message": message[:500],
        }
    )
    database["audit_events"] = events[-MAX_AUDIT_EVENTS:]


def _public_settings() -> dict[str, Any]:
    with gui_app.status_lock:
        settings = dict(gui_app.agent_status.get("settings", {}))
        api_key_configured = bool(settings.get("api_key"))
    settings.pop("api_key", None)
    return {
        **settings,
        "api_key_configured": api_key_configured,
    }


def _chat_summaries(database: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "id": chat["id"],
            "title": chat["title"],
            "status": chat.get("status", "draft"),
            "intent": chat.get("intent", ""),
            "current_task": chat.get("current_task", ""),
            "run_metrics": chat.get("run_metrics"),
            "phase": chat.get("execution", {}).get("phase", "idle"),
            "updated_at": chat.get("updated_at"),
        }
        for chat in database["chats"]
    ]


def persist_chat_execution(chat_id: str | None, state: dict[str, Any]) -> None:
    """Persist a bounded execution inspector snapshot for one conversation."""
    if not chat_id:
        return
    with db_lock:
        database = load_chats_db()
        chat = _find_chat(database, chat_id)
        if not chat:
            return
        chat["execution"] = _normalize_execution_snapshot(state)
        chat["updated_at"] = int(time.time())
        save_chats_db(database)


def _active_plan(database: dict[str, Any]) -> dict[str, Any] | None:
    chat = _active_chat(database)
    if chat.get("status") != "plan_created":
        return None

    plan = str(chat.get("reviewed_plan") or "")
    if not plan:
        plan = next(
            (
                message.get("content", "")
                for message in reversed(chat.get("chat_history", []))
                if message.get("role") == "assistant" and isinstance(message.get("content"), str)
            ),
            "",
        )
    if not plan:
        return None

    source_task = chat.get("intent") or next(
        (
            message.get("content", "")
            for message in reversed(chat.get("chat_history", []))
            if message.get("role") == "user" and isinstance(message.get("content"), str)
        ),
        "",
    )
    return {
        "plan": plan,
        "execution_task": plan,
        "source_task": source_task,
        "risk": assess_task_risk(source_task + "\n" + plan),
    }


def _lan_url(port: int) -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("10.255.255.255", 1))
            address = probe.getsockname()[0]
        return f"http://{address}:{port}"
    except OSError:
        return None


def _mobile_status(server_address: tuple[str, int]) -> dict[str, Any]:
    host, port = server_address
    network_enabled = host not in {"127.0.0.1", "::1", "localhost"}
    return {
        "network_enabled": network_enabled,
        "lan_url": _lan_url(port) if network_enabled else None,
        **pairing_session.public_payload(),
    }


def _update_telemetry_loop() -> None:
    import gui_telemetry
    import cogniagent.gui.server_manager as server_manager
    import requests

    while True:
        try:
            free_vram = gui_telemetry.get_free_vram()
            telemetry_data["free_vram"] = free_vram
            telemetry_data["optimal_ngl"] = gui_telemetry.calculate_gpu_layers(free_vram)

            try:
                vla_healthy = requests.get("http://127.0.0.1:8089/health", timeout=0.5).status_code == 200
            except requests.RequestException:
                vla_healthy = False
            telemetry_data["vla_gpu"] = bool(vla_healthy and server_manager.active_vla_cuda)

            try:
                planner_active = requests.get("http://127.0.0.1:8090/health", timeout=0.5).status_code == 200
            except requests.RequestException:
                planner_active = False
            planner_uses_gpu = bool(server_manager.active_planner_gpu)
            telemetry_data["planner_active"] = planner_active
            # Retain this legacy field as a health signal for older clients.
            telemetry_data["planner_gpu"] = planner_active
            telemetry_data["planner_uses_gpu"] = planner_uses_gpu
            telemetry_data["planner_ngl"] = min(28, max(0, int(free_vram / 80))) if planner_uses_gpu and free_vram else 0
        except Exception as error:
            logger.debug("Telemetry refresh failed: %s", error)
        time.sleep(20)


def start_telemetry_thread() -> None:
    global telemetry_thread
    if telemetry_thread and telemetry_thread.is_alive():
        return
    telemetry_thread = threading.Thread(target=_update_telemetry_loop, name="omnivla-telemetry", daemon=True)
    telemetry_thread.start()


def _start_agent_task(task: str, run_policy: dict[str, Any] | None = None) -> bool:
    starter = getattr(gui_app, "start_agent_task", None)
    if callable(starter):
        return bool(starter(task, run_policy))

    if gui_app.running_thread and gui_app.running_thread.is_alive():
        return False
    worker = threading.Thread(target=gui_app.execute_agent_task, args=(task, run_policy), daemon=True)
    gui_app.running_thread = worker
    worker.start()
    return True


class WebUIRequestHandler(BaseHTTPRequestHandler):
    """Serve the PWA and its guarded, same-origin control-plane API."""

    server_version = "OmniVLA/2.0"

    def log_message(self, format: str, *args: Any) -> None:
        logger.info("%s - %s", self.address_string(), format % args)

    @property
    def _path(self) -> str:
        return urlsplit(self.path).path

    @property
    def _is_local(self) -> bool:
        return is_loopback_address(self.client_address[0])

    def _send_headers(self, content_type: str, *, cache_control: str) -> None:
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", cache_control)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
        )

    def _json_response(self, payload: dict[str, Any], status: int = 200) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._send_headers("application/json; charset=utf-8", cache_control="no-store")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _error(self, status: int, message: str) -> None:
        self._json_response({"error": message}, status)

    def _asset_response(self, relative_path: str) -> None:
        asset = get_asset(relative_path)
        if asset is None:
            self._error(404, "Asset not found.")
            return
        content, content_type = asset
        self.send_response(200)
        self._send_headers(content_type, cache_control="no-cache")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _read_json(self) -> dict[str, Any]:
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            raise RequestValidationError("Content-Type must be application/json.")
        header = self.headers.get("Content-Length", "0")
        try:
            content_length = int(header)
        except ValueError as error:
            raise RequestValidationError("Invalid request length.") from error
        if content_length < 0 or content_length > MAX_REQUEST_BYTES:
            raise RequestValidationError("Request body is too large.")
        if content_length == 0:
            return {}

        try:
            decoded = self.rfile.read(content_length).decode("utf-8")
            payload = json.loads(decoded)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RequestValidationError("Request body must be valid JSON.") from error
        if not isinstance(payload, dict):
            raise RequestValidationError("Request body must be a JSON object.")
        return payload

    def _authorize(self, *, mutating: bool = False, local_only: bool = False) -> bool:
        origin = self.headers.get("Origin")
        host = self.headers.get("Host")
        if origin and (not host or origin != f"http://{host}"):
            self._error(403, "Cross-origin control requests are not allowed.")
            return False

        if self._is_local:
            return True

        candidate = self.headers.get("X-OmniVLA-Pairing")
        if not pairing_session.verify(candidate):
            self._error(401, "A valid, unexpired pairing code is required for remote access.")
            return False
        if local_only:
            self._error(403, "This control is only available on the paired desktop.")
            return False

        policy = load_chats_db()["safety"]
        if mutating and not policy.get("remote_control_enabled", False):
            self._error(403, "Remote control is disabled by the desktop safety policy.")
            return False

        return True

    def _status_payload(self) -> dict[str, Any]:
        database = load_chats_db()
        active = _active_chat(database)
        with gui_app.status_lock:
            live_state = gui_app.get_safe_status(include_media=False)
        execution_chat_id = live_state.get("execution_chat_id")
        safe_live_state = _normalize_execution_snapshot(live_state)
        safe_live_state["execution_chat_id"] = execution_chat_id
        selected_is_execution = bool(execution_chat_id and active["id"] == execution_chat_id)
        if selected_is_execution:
            agent_state = dict(safe_live_state)
        else:
            agent_state = _normalize_execution_snapshot(active.get("execution"))
            if planner_active_chat_id == active["id"]:
                agent_state.update({
                    "status": "planning",
                    "phase": "planning",
                    "current_action": "Preparing a plan",
                    "phase_started_at": None,
                })
            elif active.get("status") == "plan_created":
                agent_state.update({"status": "ready", "phase": "ready", "current_action": "Plan ready"})
            agent_state["execution_chat_id"] = execution_chat_id
        agent_state["execution_live"] = {
            key: safe_live_state.get(key)
            for key in (
                "execution_chat_id", "status", "phase", "phase_started_at", "step",
                "total_time_ms", "current_action", "current_thought", "paused", "steps", "timing",
            )
        }
        agent_state["chat_history"] = list(active.get("chat_history", []))
        agent_state["current_task"] = active.get("current_task", "")
        agent_state["active_intent"] = active.get("intent", "")
        agent_state["active_title"] = active.get("title", "Untitled run")
        agent_state["active_plan"] = _active_plan(database)
        agent_state["settings"] = _public_settings()
        agent_state["chats"] = _chat_summaries(database)
        agent_state["active_chat_id"] = database["active_chat_id"]
        agent_state["planning_chat_id"] = planner_active_chat_id
        agent_state["safety"] = database["safety"]

        agent_state["audit_events"] = list(database["audit_events"])
        agent_state["logs"] = list(gui_app.web_log_handler.logs[-80:])
        agent_state["telemetry"] = dict(telemetry_data)
        agent_state["mobile"] = _mobile_status(self.server.server_address)
        agent_state["access"] = {
            "is_local": self._is_local,
            "remote_control_enabled": database["safety"].get("remote_control_enabled", False),
        }
        return agent_state

    def _screen_payload(self) -> dict[str, Any]:
        """Return the current compressed frame separately from the status poll."""
        database = load_chats_db()
        active = _active_chat(database)
        with gui_app.status_lock:
            execution_chat_id = gui_app.agent_status.get("execution_chat_id")
            if not execution_chat_id or execution_chat_id != active["id"]:
                snapshot = _normalize_execution_snapshot(active.get("execution"))
                return {"screenshot_b64": "", "step": snapshot["step"], "phase": snapshot["phase"]}
            return {
                "screenshot_b64": str(gui_app.agent_status.get("latest_screenshot_b64") or ""),
                "step": int(gui_app.agent_status.get("step") or 0),
                "phase": str(gui_app.agent_status.get("phase") or "idle"),
            }

    def _sync_active_chat(self, chat: dict[str, Any]) -> None:
        with gui_app.status_lock:
            execution_chat_id = gui_app.agent_status.get("execution_chat_id")
            if gui_app.running_thread and gui_app.running_thread.is_alive() and execution_chat_id != chat.get("id"):
                return
            gui_app.agent_status["chat_history"] = list(chat.get("chat_history", []))
            gui_app.agent_status["current_task"] = chat.get("current_task", "")

    def _plan_in_background(self, chat_id: str, message: str) -> None:
        try:
            chat_history = []
            memory_enabled = False
            with db_lock:
                database = load_chats_db()
                chat = _find_chat(database, chat_id)
                if chat:
                    chat_history = list(chat.get("chat_history", []))
                memory_enabled = bool(database.get("settings", {}).get("memory_enabled", False))

            rag_context = ""
            chats_rag = None
            if memory_enabled:
                from cogniagent.memory.chats_rag import ChatsRAG
                global chat_retrieval
                if chat_retrieval is None:
                    chat_retrieval = ChatsRAG()
                chats_rag = chat_retrieval
                chats_rag.index_message(chat_id, "user", message)
                rag_context = chats_rag.search_context(message, chat_id)

            response = gui_app.run_planner_chat(message, chat_history=chat_history, rag_context=rag_context)
            if chats_rag is not None:
                chats_rag.index_message(chat_id, "assistant", response)

            with db_lock:
                database = load_chats_db()
                chat = _find_chat(database, chat_id)
                if chat:
                    chat["chat_history"].append({"role": "assistant", "content": response})
                    chat["reviewed_plan"] = response
                    chat["status"] = "plan_created"
                    chat["updated_at"] = int(time.time())
                    _record_audit(database, "plan.ready", "Plan prepared and waiting for approval.")
                    save_chats_db(database)
                    if database["active_chat_id"] == chat_id:
                        self._sync_active_chat(chat)
        except Exception as error:
            logger.exception("Planner request failed: %s", error)
            with db_lock:
                database = load_chats_db()
                chat = _find_chat(database, chat_id)
                if chat:
                    chat["status"] = "failed"
                    chat["chat_history"].append(
                        {"role": "assistant", "content": "I couldn't prepare the plan. Please try again."}
                    )
                    chat["execution"] = _normalize_execution_snapshot(
                        {
                            "status": "failed",
                            "phase": "failed",
                            "current_action": "The plan could not be prepared.",
                        }
                    )
                    chat["updated_at"] = int(time.time())
                    _record_audit(database, "plan.failed", "Plan preparation failed.")
                    save_chats_db(database)
        finally:
            global planner_active_chat_id
            planner_active_chat_id = None
            with gui_app.status_lock:
                if gui_app.agent_status.get("status") in ("planning", "thinking"):
                    gui_app.agent_status["status"] = "idle"
                    gui_app.agent_status["phase"] = "idle"
                    gui_app.agent_status["phase_started_at"] = time.time()
                    gui_app.agent_status["current_action"] = "Ready for a reviewed task."
            planner_lock.release()


    def _create_plan(self, payload: dict[str, Any]) -> None:
        global planner_active_chat_id
        message = validate_chat_message(payload.get("message"))
        chat_id = payload.get("chat_id")
        if gui_app.running_thread and gui_app.running_thread.is_alive():
            self._error(409, "Finish or stop the active task before preparing another plan on this hardware.")
            return
        if not planner_lock.acquire(blocking=False):
            self._error(409, "Another plan is already being prepared.")
            return

        try:
            with db_lock:
                database = load_chats_db()
                if chat_id and any(c["id"] == chat_id for c in database.get("chats", [])):
                    database["active_chat_id"] = chat_id
                chat = _active_chat(database)

                if chat["title"] in {"New run", "New Chat", "New chat"}:
                    chat["title"] = _chat_title(message)
                chat["intent"] = message

                chat["status"] = "planning"
                chat["current_task"] = ""
                chat["chat_history"].append({"role": "user", "content": message})
                chat["updated_at"] = int(time.time())
                _record_audit(database, "plan.requested", "New plan requested.")
                save_chats_db(database)
                self._sync_active_chat(chat)

            planner_active_chat_id = chat["id"]

            with gui_app.status_lock:
                gui_app.agent_status["status"] = "planning"
                gui_app.agent_status["phase"] = "planning"
                gui_app.agent_status["phase_started_at"] = time.time()
                gui_app.agent_status["current_action"] = "Preparing a plan"


            worker = threading.Thread(
                target=self._plan_in_background,
                args=(chat["id"], message),

                name="omnivla-planner",
                daemon=True,
            )
            worker.start()
            self._json_response({"success": True, "message": "Planner started."}, 202)
        except Exception:
            planner_lock.release()
            raise

    def _confirm_run(self, payload: dict[str, Any]) -> None:
        submitted_task = validate_task(payload.get("task"))
        submitted_source_task = validate_task(payload.get("source_task", submitted_task))
        approved = payload.get("approved") is True
        risk_acknowledged = payload.get("risk_acknowledged") is True

        with db_lock:
            database = load_chats_db()
            chat_id = payload.get("chat_id")
            if chat_id and any(c["id"] == chat_id for c in database.get("chats", [])):
                database["active_chat_id"] = chat_id
            
            chat = _active_chat(database)
            stored_plan = _active_plan(database)
            if not stored_plan:
                self._error(409, "Create a plan before starting the task.")
                return
            if (
                submitted_task != stored_plan["execution_task"]
                or submitted_source_task != stored_plan["source_task"]
            ):
                self._error(409, "The reviewed plan changed. Refresh it before approval.")
                return
            task = stored_plan["execution_task"]
            source_task = stored_plan["source_task"]
            policy = dict(database["safety"])
            run_chat_id = chat["id"]

        risk = assess_task_risk(source_task + "\n" + task)

        if policy.get("require_plan_approval", True) and not approved:
            self._error(428, "This policy requires a reviewed plan approval before execution.")
            return
        if risk["requires_explicit_acknowledgement"] and not risk_acknowledged:
            self._json_response(
                {
                    "error": "This task has high-impact intent and needs an explicit acknowledgement.",
                    "risk": risk,
                },
                428,
            )
            return


        with gui_app.status_lock:
            active_settings = dict(gui_app.agent_status.get("settings", {}))
        if active_settings.get("model_type") != "local" and not active_settings.get("api_key"):
            self._error(428, "Configure a runtime-only provider API key before starting a cloud run.")
            return

        # The reviewed plan is useful guidance, but the original objective is
        # authoritative. Giving both to the visual reasoner prevents a planner
        # paraphrase from silently adding or dropping user constraints.
        execution_prompt = f"User objective:\n{source_task}\n\nReviewed plan:\n{task}"
        if not _start_agent_task(
            execution_prompt,
            {"mode": policy.get("mode", "supervised"), "chat_id": run_chat_id},
        ):
            self._error(409, "An agent run is already active. Stop or finish it before starting another.")
            return

        with db_lock:
            database = load_chats_db()
            chat = _find_chat(database, run_chat_id)
            if chat is None:
                self._error(409, "The approved run no longer exists.")
                return
            chat["current_task"] = task
            chat["status"] = "running"
            chat["execution"] = _normalize_execution_snapshot({
                "status": "thinking",
                "phase": "thinking",
                "phase_started_at": time.time(),
                "current_action": "Reading the screen",
            })
            chat["updated_at"] = int(time.time())
            _record_audit(database, "run.approved", "Reviewed run approved and started.")
            save_chats_db(database)
            self._sync_active_chat(chat)

        with gui_app.status_lock:
            gui_app.agent_status["ui_mode"] = "executor"
            gui_app.agent_status["planner_synthesis"] = ""

        self._json_response({"success": True, "risk": risk}, 202)

    def _select_plan(self, payload: dict[str, Any]) -> None:
        """Select any model-authored plan in the active conversation for review."""
        selected = validate_task(payload.get("plan"))
        chat_id = validate_chat_id(payload.get("chat_id"))
        if gui_app.running_thread and gui_app.running_thread.is_alive():
            self._error(409, "Stop the active task before selecting another plan.")
            return
        with db_lock:
            database = load_chats_db()
            chat = _find_chat(database, chat_id)
            if chat is None:
                self._error(404, "Chat not found.")
                return
            authored_plans = {
                _plan_copy(message.get("content"))
                for message in chat.get("chat_history", [])
                if message.get("role") == "assistant"
                and isinstance(message.get("content"), str)
                and len(re.findall(r"(?m)^\s*\d+[.)]\s+", _plan_copy(message.get("content")))) >= 2
            }
            if selected not in authored_plans:
                self._error(409, "That plan is no longer available in this chat.")
                return
            database["active_chat_id"] = chat_id
            chat["reviewed_plan"] = selected
            chat["status"] = "plan_created"
            chat["current_task"] = ""
            chat["updated_at"] = int(time.time())
            _record_audit(database, "plan.selected", "A previous plan was selected for review.")
            save_chats_db(database)
            self._sync_active_chat(chat)
        self._json_response({"success": True})

    def _new_chat(self) -> None:
        with db_lock:
            database = load_chats_db()
            chat = _new_chat()
            database["chats"].append(chat)
            database["active_chat_id"] = chat["id"]
            _record_audit(database, "run.created", "Created a new draft run.")
            save_chats_db(database)
            self._sync_active_chat(chat)

        if not (gui_app.running_thread and gui_app.running_thread.is_alive()):
            with gui_app.status_lock:
                gui_app.agent_status["steps"] = []
                gui_app.agent_status["status"] = "idle"
                gui_app.agent_status["phase"] = "idle"
                gui_app.agent_status["phase_started_at"] = time.time()
                gui_app.agent_status["current_action"] = "Ready for a reviewed task."
        self._json_response({"success": True})

    def _retry_run(self) -> None:
        """Clone a completed run into a fresh, reviewable plan.

        Retrying must not reuse the confirmation granted to the prior run. A
        new chat preserves the original intent and plan, then returns the
        operator to the same approval gate.
        """
        if gui_app.running_thread and gui_app.running_thread.is_alive():
            self._error(409, "Wait for the active run to finish before preparing a retry.")
            return

        with db_lock:
            database = load_chats_db()
            previous = _active_chat(database)
            source_task = str(previous.get("intent") or "").strip()
            reviewed_plan = str(previous.get("reviewed_plan") or previous.get("current_task") or "").strip()

            if not source_task:
                source_task = next(
                    (
                        message.get("content", "")
                        for message in reversed(previous.get("chat_history", []))
                        if message.get("role") == "user" and isinstance(message.get("content"), str)
                    ),
                    "",
                ).strip()
            if not reviewed_plan:
                reviewed_plan = next(
                    (
                        message.get("content", "")
                        for message in reversed(previous.get("chat_history", []))
                        if message.get("role") == "assistant" and isinstance(message.get("content"), str)
                    ),
                    "",
                ).strip()

            if not source_task or not reviewed_plan:
                self._error(409, "This run has no reviewed plan to retry.")
                return

            retry = _new_chat()
            retry["title"] = ("Retry: " + previous.get("title", "run"))[:120]
            retry["intent"] = source_task
            retry["reviewed_plan"] = reviewed_plan
            retry["status"] = "plan_created"
            retry["updated_at"] = int(time.time())
            retry["chat_history"].extend(
                [
                    {"role": "user", "content": source_task},
                    {"role": "assistant", "content": reviewed_plan},
                ]
            )
            database["chats"].append(retry)
            database["active_chat_id"] = retry["id"]
            _record_audit(database, "run.retry_prepared", "Prepared a fresh reviewed retry run.")
            save_chats_db(database)
            self._sync_active_chat(retry)

        with gui_app.status_lock:
            gui_app.agent_status["steps"] = []
            gui_app.agent_status["status"] = "idle"
            gui_app.agent_status["phase"] = "idle"
            gui_app.agent_status["phase_started_at"] = time.time()
            gui_app.agent_status["current_action"] = "Reviewed retry run is ready for approval."
        self._json_response({"success": True}, 201)

    def _switch_chat(self, payload: dict[str, Any]) -> None:
        chat_id = validate_chat_id(payload.get("id"))
        with db_lock:
            database = load_chats_db()
            chat = _find_chat(database, chat_id)
            if not chat:
                self._error(404, "Run not found.")
                return
            database["active_chat_id"] = chat_id
            _record_audit(database, "run.opened", "Opened a saved run.")
            save_chats_db(database)
            self._sync_active_chat(chat)
        self._json_response({"success": True})

    def _delete_chat(self, payload: dict[str, Any]) -> None:
        chat_id = validate_chat_id(payload.get("id"))
        with db_lock:
            database = load_chats_db()
            target = _find_chat(database, chat_id)
            if target is None:
                self._error(404, "Run not found.")
                return
            if target.get("status") == "running":
                self._error(409, "Stop the active run before deleting its history.")
                return
            if len(database["chats"]) == 1:
                self._error(409, "Keep at least one draft run available.")
                return
            database["chats"] = [chat for chat in database["chats"] if chat["id"] != chat_id]
            if len(database["chats"]) == 0:
                self._error(404, "Run not found.")
                return
            if database["active_chat_id"] == chat_id:
                database["active_chat_id"] = database["chats"][0]["id"]
            _record_audit(database, "run.deleted", "Deleted a saved run.")
            save_chats_db(database)
            self._sync_active_chat(_active_chat(database))
        self._json_response({"success": True})

    def _save_settings(self, payload: dict[str, Any]) -> None:
        with gui_app.status_lock:
            current = dict(gui_app.agent_status.get("settings", {}))
        settings, runtime_api_key = validate_settings(payload, current)

        with gui_app.status_lock:
            gui_app.agent_status["settings"].update(settings)
            if runtime_api_key is not None:
                gui_app.agent_status["settings"]["api_key"] = runtime_api_key

        with db_lock:
            database = load_chats_db()
            database["settings"] = settings
            _record_audit(database, "environment.saved", "Execution environment updated; provider keys were kept out of storage.")
            save_chats_db(database)
        self._json_response({"success": True, "settings": _public_settings()})

    def _save_safety(self, payload: dict[str, Any]) -> None:
        with db_lock:
            database = load_chats_db()
            database["safety"] = validate_safety_policy(payload, database["safety"])
            _record_audit(database, "safety.updated", "Desktop execution policy updated.")
            save_chats_db(database)
        self._json_response({"success": True, "safety": database["safety"]})

    def _stop_run(self) -> None:
        gui_app.stop_agent()
        with gui_app.status_lock:
            gui_app.hitl_response.append("stop")
            gui_app.hitl_event.set()
            gui_app.agent_status["status"] = "stopped"
            gui_app.agent_status["current_action"] = "Execution stopped by operator."
            gui_app.agent_status["phase"] = "stopped"
            gui_app.agent_status["phase_started_at"] = time.time()
            gui_app.agent_status["ui_mode"] = "chat"
            execution_chat_id = gui_app.agent_status.get("execution_chat_id")
            state = gui_app.get_safe_status(include_media=False)
        persist_chat_execution(execution_chat_id, state)
        with db_lock:
            database = load_chats_db()
            execution_chat = _find_chat(database, execution_chat_id) if execution_chat_id else None
            if execution_chat:
                execution_chat["status"] = "stopped"
                execution_chat["updated_at"] = int(time.time())
            _record_audit(database, "run.stop_requested", "Operator requested the active run to stop.")
            save_chats_db(database)
        self._json_response({"success": True})


    def _pause_run(self, paused: bool) -> None:
        with gui_app.status_lock:
            gui_app.agent_status["paused"] = paused
            gui_app.agent_status["current_action"] = "Run paused by operator." if paused else "Run resumed by operator."
            gui_app.agent_status["phase"] = "paused" if paused else "thinking"
            gui_app.agent_status["phase_started_at"] = time.time()
            execution_chat_id = gui_app.agent_status.get("execution_chat_id")
            state = gui_app.get_safe_status(include_media=False)
        persist_chat_execution(execution_chat_id, state)
        with db_lock:
            database = load_chats_db()
            _record_audit(database, "run.paused" if paused else "run.resumed", "Operator updated the run state.")
            save_chats_db(database)
        self._json_response({"success": True, "paused": paused})

    def _submit_hitl(self, payload: dict[str, Any]) -> None:
        response = validate_hitl_response(payload.get("response"))
        with gui_app.status_lock:
            gui_app.hitl_response.append(response)
            gui_app.hitl_event.set()
        with db_lock:
            database = load_chats_db()
            _record_audit(database, "hitl.responded", "Human intervention response submitted.")
            save_chats_db(database)
        self._json_response({"success": True})

    def _clear_vram(self) -> None:
        if gui_app.running_thread and gui_app.running_thread.is_alive():
            self._error(409, "Stop the active run before recycling model memory.")
            return

        def restart_model() -> None:
            process = gui_app.server_process
            if process:
                try:
                    process.terminate()
                    process.wait(timeout=5)
                except Exception as error:
                    logger.warning("Unable to stop the current VLA process cleanly: %s", error)
                finally:
                    gui_app.server_process = None
            gui_app.start_llama_server(max_gpu=True)

        threading.Thread(target=restart_model, name="omnivla-vram-restart", daemon=True).start()
        with db_lock:
            database = load_chats_db()
            _record_audit(database, "runtime.recycle_requested", "Local VLA model memory recycling started.")
            save_chats_db(database)
        self._json_response({"success": True}, 202)

    def _clear_memory(self) -> None:
        if gui_app.running_thread and gui_app.running_thread.is_alive():
            self._error(409, "Stop the active run before clearing local recall.")
            return
        from cogniagent.config import config
        from cogniagent.memory.episodic_memory import clear_local_memory

        global chat_retrieval
        if chat_retrieval is not None:
            try:
                chat_retrieval.close()
            finally:
                chat_retrieval = None
        removed = clear_local_memory(config.memory.db_path)
        with db_lock:
            database = load_chats_db()
            _record_audit(database, "memory.cleared", "Operator cleared local episodic recall.")
            save_chats_db(database)
        self._json_response({"success": True, "stores_cleared": removed})

    def _list_skills(self) -> None:
        skills = skills_registry.list_skills()
        self._json_response({"skills": [s.to_dict() for s in skills]})

    def _get_skill_detail(self, name: str) -> None:
        skill = skills_registry.get_skill(name)
        if not skill:
            self._error(404, "Skill not found.")
            return
        self._json_response({"skill": skill.to_dict()})

    def _save_skill_definition(self, payload: dict[str, Any]) -> None:
        try:
            if "markdown" in payload:
                skill = SkillDefinition.from_markdown(validate_skill_markdown(payload["markdown"]))
            else:
                if not isinstance(payload.get("name"), str):
                    raise RequestValidationError("skill name is required.")
                skill = SkillDefinition.from_dict(payload)
            skill.name = validate_skill_name(skill.name)
            for field_name, maximum in (("title", 160), ("description", 2_000), ("strategy", 24_000), ("visual_landmarks", 8_000), ("failure_recovery", 8_000)):
                value = getattr(skill, field_name)
                if not isinstance(value, str) or len(value) > maximum:
                    raise RequestValidationError(f"skill {field_name.replace('_', ' ')} is invalid or too long.")
            if len(skill.parameters) > 24 or len(skill.triggers) > 64 or len(skill.tags) > 64:
                raise RequestValidationError("skill has too many parameters, triggers, or tags.")
            skills_registry.save_skill(skill)
            self._json_response({"success": True, "skill": skill.to_dict()}, 201)
        except (RequestValidationError, ValueError, TypeError) as e:
            self._error(400, f"Invalid skill definition: {e}")

    def _delete_skill_definition(self, payload: dict[str, Any]) -> None:
        name = validate_skill_name(payload.get("name"))
        deleted = skills_registry.delete_skill(name)
        self._json_response({"success": deleted})

    def _start_observation_session(self, payload: dict[str, Any]) -> None:
        goal = validate_observation_goal(payload.get("task_goal", "Human demonstration"))
        if gui_app.running_thread and gui_app.running_thread.is_alive():
            self._error(409, "Stop the agent before recording a human demonstration.")
            return
        native_observation_recorder.stop()
        observation_learner.start_observation(goal)
        native_capture = native_observation_recorder.start()
        if not native_capture:
            observation_learner.stop_observation()
            self._error(503, "Windows input observation could not start. Check desktop-session permissions.")
            return
        self._json_response({"success": True, "is_observing": True, "native_capture": True, "text_privacy": "redacted", "task_goal": goal})

    def _record_observed_action(self, payload: dict[str, Any]) -> None:
        observed = validate_observed_action(payload)
        act_type = observed["action_type"]
        if act_type in {"click", "double_click", "right_click"}:
            observation_learner.record_click(
                x=observed["x"],
                y=observed["y"],
                button=observed["button"],
                window_title=observed["window_title"],
                visual_cue=observed["visual_cue"],
            )
        elif act_type == "type":
            observation_learner.record_typing(
                text="{{typed_value}}",
                window_title=observed["window_title"],
            )
        elif act_type in {"key_press", "hotkey"}:
            observation_learner.record_key(
                key=observed["key"],
                window_title=observed["window_title"],
            )
        self._json_response({"success": True})

    def _stop_observation_session(self) -> None:
        global last_recorded_demo
        native_observation_recorder.stop()
        demo = observation_learner.stop_observation()
        last_recorded_demo = demo
        self._json_response({
            "success": True,
            "demonstration": demo.to_dict() if demo else None
        })

    def _synthesize_skill_from_observation(self, payload: dict[str, Any]) -> None:
        global last_recorded_demo
        demo = last_recorded_demo
        if not demo:
            self._error(400, "No observation demonstration available to synthesize. Record a demonstration first.")
            return
        skill_name = payload.get("name")
        if skill_name is not None:
            skill_name = validate_skill_name(skill_name)
        if not planner_lock.acquire(blocking=False):
            self._error(409, "Finish the current planning request before building a skill.")
            return
        from cogniagent.gui.server_manager import start_planner_server, stop_planner_server
        try:
            planner_ready = start_planner_server(use_gpu=False)
            if not planner_ready:
                logger.warning("Studio planner was unavailable; using the bounded offline compiler.")
                skill_synthesizer.enhance_with_models = False
            skill = skill_synthesizer.synthesize_skill(demo, skill_name=skill_name)
        finally:
            skill_synthesizer.enhance_with_models = True
            stop_planner_server()
            planner_lock.release()
        skills_registry.save_skill(skill)
        self._json_response({"success": True, "skill": skill.to_dict()}, 201)

    def do_GET(self) -> None:
        path = self._path
        try:
            if path == "/":
                self._asset_response("index.html")
                return
            if path == "/manifest.webmanifest":
                self._asset_response("manifest.webmanifest")
                return
            if path == "/sw.js":
                self._asset_response("sw.js")
                return
            if path.startswith("/assets/"):
                self._asset_response(path.removeprefix("/assets/"))
                return
            if path == "/api/status":
                if self._authorize():
                    self._json_response(self._status_payload())
                return
            if path == "/api/screen":
                if self._authorize():
                    self._json_response(self._screen_payload())
                return
            if path == "/api/skills":
                if self._authorize():
                    self._list_skills()
                return
            if path.startswith("/api/skills/"):
                if self._authorize():
                    skill_name = path.removeprefix("/api/skills/")
                    self._get_skill_detail(skill_name)
                return
            if path == "/api/pairing":
                if self._authorize(local_only=True):
                    self._json_response(pairing_session.local_payload())
                return
            self._error(404, "Route not found.")
        except Exception as error:
            logger.exception("Unhandled GET error: %s", error)
            self._error(500, "The command center could not complete that request.")

    def do_POST(self) -> None:
        path = self._path
        local_only_routes = {
            "/api/settings", "/api/safety", "/api/pairing/rotate", "/api/clear_vram", "/api/memory/clear",
            "/api/skills", "/api/skills/delete", "/api/skills/synthesize",
            "/api/observe/start", "/api/observe/action", "/api/observe/stop",
            "/api/shutdown", "/shutdown",
        }
        try:
            if path not in {
                "/api/chat",
                "/api/chats/new",
                "/api/chats/switch",
                "/api/chats/delete",
                "/api/chats/retry",
                "/api/plans/select",
                "/api/confirm",
                "/api/settings",
                "/api/safety",
                "/api/pairing/rotate",
                "/api/stop",
                "/api/pause",
                "/api/resume",
                "/api/hitl_submit",
                "/api/clear_vram",
                "/api/memory/clear",
                "/api/skills",
                "/api/skills/delete",
                "/api/skills/synthesize",
                "/api/observe/start",
                "/api/observe/action",
                "/api/observe/stop",
                "/api/reexecute",
                "/api/shutdown",
                "/shutdown",
            }:
                self._error(404, "Route not found.")
                return
            if not self._authorize(mutating=True, local_only=path in local_only_routes):
                return

            payload = self._read_json()
            if path in ("/api/shutdown", "/shutdown"):
                self._json_response({"success": True, "message": "OmniVLA shutting down cleanly."})

                def shutdown() -> None:
                    time.sleep(0.35)
                    try:
                        gui_app.shutdown_runtime()
                        from gui_telemetry import kill_port_owner
                        kill_port_owner(8089)
                        kill_port_owner(8090)
                        kill_port_owner(8082)
                    except Exception:
                        pass
                    os._exit(0)

                threading.Thread(target=shutdown, name="omnivla-shutdown", daemon=True).start()
            elif path == "/api/chat":

                self._create_plan(payload)
            elif path == "/api/chats/new":
                self._new_chat()
            elif path == "/api/chats/switch":
                self._switch_chat(payload)
            elif path == "/api/chats/delete":
                self._delete_chat(payload)
            elif path == "/api/chats/retry":
                self._retry_run()
            elif path == "/api/plans/select":
                self._select_plan(payload)
            elif path == "/api/confirm":

                self._confirm_run(payload)




            elif path == "/api/settings":
                self._save_settings(payload)
            elif path == "/api/safety":
                self._save_safety(payload)
            elif path == "/api/pairing/rotate":
                self._json_response(pairing_session.rotate())
            elif path == "/api/stop":
                self._stop_run()
            elif path == "/api/pause":
                self._pause_run(True)
            elif path == "/api/resume":
                self._pause_run(False)
            elif path == "/api/hitl_submit":
                self._submit_hitl(payload)
            elif path == "/api/clear_vram":
                self._clear_vram()
            elif path == "/api/memory/clear":
                self._clear_memory()
            elif path == "/api/skills":
                self._save_skill_definition(payload)
            elif path == "/api/skills/delete":
                self._delete_skill_definition(payload)
            elif path == "/api/skills/synthesize":
                self._synthesize_skill_from_observation(payload)
            elif path == "/api/observe/start":
                self._start_observation_session(payload)
            elif path == "/api/observe/action":
                self._record_observed_action(payload)
            elif path == "/api/observe/stop":
                self._stop_observation_session()
            else:
                self._error(410, "Create and approve a plan before starting a task.")
        except RequestValidationError as error:
            self._error(400, str(error))
        except Exception as error:
            logger.exception("Unhandled POST error for %s: %s", path, error)
            self._error(500, "The command center could not complete that request.")
