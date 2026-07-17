"""HTTP control plane for the OmniVLA command center.

The web application intentionally talks only to this local control plane.  The
handler validates every mutation, keeps provider secrets out of persisted state,
and requires a short-lived pairing token for optional LAN companion sessions.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler
from typing import Any
from urllib.parse import urlsplit

import cogniagent.gui.app as gui_app

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
    validate_settings,
    validate_task,
)
from cogniagent.gui.web_assets import get_asset


logger = logging.getLogger(__name__)

MAX_REQUEST_BYTES = 64 * 1024
CHATS_DB_PATH = "chats_db.json"

DEFAULT_SETTINGS = {
    "model_path": "models/Holo-3.1-4B-abliterated-rdo.Q4_K_M.gguf",
    "temperature": 0.2,
    "max_steps": 15,
    "enable_recording": False,
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
_db_cache: dict[str, Any] | None = None
telemetry_thread: threading.Thread | None = None
pairing_session = PairingSession()


def _new_chat() -> dict[str, Any]:
    return {
        "id": secrets.token_hex(10),
        "title": "New run",
        "status": "draft",
        "intent": "",
        "chat_history": [
            {
                "role": "assistant",
                "content": "Hello — I am OmniVLA. Describe a desktop task and I will prepare a reviewed runbook.",
            }
        ],
        "current_task": "",
    }


def _default_database() -> dict[str, Any]:
    chat = _new_chat()
    return {
        "active_chat_id": chat["id"],
        "chats": [chat],
        "settings": dict(DEFAULT_SETTINGS),
        "safety": default_safety_policy(),
        "audit_events": [],
    }


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
        normalized_chats.append(
            {
                "id": chat_id,
                "title": str(chat.get("title") or "Untitled run")[:120],
                "status": str(chat.get("status") or "draft")[:32],
                "intent": str(chat.get("intent") or "")[:12_000],
                "chat_history": history,
                "current_task": str(chat.get("current_task") or "")[:12_000],
                "reviewed_plan": str(chat.get("reviewed_plan") or "")[:12_000],
            }
        )

    if not normalized_chats:
        return _default_database()

    settings = database.get("settings")
    if not isinstance(settings, dict):
        settings = {}
    # Legacy files may contain an API key. It is intentionally discarded during
    # normalization; provider credentials belong only to the running process.
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
            _db_cache = _normalize_database(raw_database)
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
            "current_task": chat.get("current_task", ""),
        }
        for chat in database["chats"]
    ]


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

            vla_active = server_manager.active_vla_max_gpu
            if vla_active is None:
                try:
                    vla_active = requests.get("http://127.0.0.1:8089/health", timeout=0.5).status_code == 200
                except requests.RequestException:
                    vla_active = False
            telemetry_data["vla_gpu"] = vla_active

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


def _start_agent_task(task: str) -> bool:
    starter = getattr(gui_app, "start_agent_task", None)
    if callable(starter):
        return bool(starter(task))

    if gui_app.running_thread and gui_app.running_thread.is_alive():
        return False
    worker = threading.Thread(target=gui_app.execute_agent_task, args=(task,), daemon=True)
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
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
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
        # Browser-originated requests must be same-origin. Command-line and
        # native-desktop callers do not send Origin and remain supported.
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
        with gui_app.status_lock:
            agent_state = gui_app.get_safe_status()
        agent_state["settings"] = _public_settings()
        agent_state["chats"] = _chat_summaries(database)
        agent_state["active_chat_id"] = database["active_chat_id"]
        agent_state["active_plan"] = _active_plan(database)
        agent_state["safety"] = database["safety"]
        agent_state["audit_events"] = list(database["audit_events"])
        agent_state["logs"] = list(gui_app.web_log_handler.logs[-200:])
        agent_state["telemetry"] = dict(telemetry_data)
        agent_state["mobile"] = _mobile_status(self.server.server_address)
        agent_state["access"] = {
            "is_local": self._is_local,
            "remote_control_enabled": database["safety"].get("remote_control_enabled", False),
        }
        return agent_state

    def _sync_active_chat(self, chat: dict[str, Any]) -> None:
        with gui_app.status_lock:
            gui_app.agent_status["chat_history"] = list(chat.get("chat_history", []))
            gui_app.agent_status["current_task"] = chat.get("current_task", "")

    def _plan_in_background(self, chat_id: str, message: str) -> None:
        try:
            from cogniagent.memory.chats_rag import ChatsRAG

            chats_rag = ChatsRAG()
            chats_rag.index_message(chat_id, "user", message)
            rag_context = chats_rag.search_context(message, chat_id)
            response = gui_app.run_planner_chat(message, rag_context=rag_context)
            chats_rag.index_message(chat_id, "assistant", response)

            with db_lock:
                database = load_chats_db()
                chat = _find_chat(database, chat_id)
                if chat:
                    chat["chat_history"].append({"role": "assistant", "content": response})
                    chat["reviewed_plan"] = response
                    chat["status"] = "plan_created"
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
                    _record_audit(database, "plan.failed", "Planner could not prepare a runbook.")
                    save_chats_db(database)
        finally:
            with gui_app.status_lock:
                if gui_app.agent_status.get("status") == "thinking":
                    gui_app.agent_status["status"] = "idle"
                    gui_app.agent_status["phase"] = "idle"
                    gui_app.agent_status["phase_started_at"] = time.time()
                    gui_app.agent_status["current_action"] = "Ready for a reviewed task."
            planner_lock.release()

    def _create_plan(self, payload: dict[str, Any]) -> None:
        message = validate_chat_message(payload.get("message"))
        if not planner_lock.acquire(blocking=False):
            self._error(409, "The planner is already preparing a runbook.")
            return

        try:
            with db_lock:
                database = load_chats_db()
                chat = _active_chat(database)
                if chat["title"] in {"New run", "New Chat"}:
                    chat["title"] = message[:48] + ("…" if len(message) > 48 else "")
                chat["intent"] = message
                chat["status"] = "planning"
                chat["current_task"] = ""
                chat["chat_history"].append({"role": "user", "content": message})
                _record_audit(database, "plan.requested", "New runbook requested.")
                save_chats_db(database)
                self._sync_active_chat(chat)

            with gui_app.status_lock:
                gui_app.agent_status["status"] = "thinking"
                gui_app.agent_status["phase"] = "thinking"
                gui_app.agent_status["phase_started_at"] = time.time()
                gui_app.agent_status["current_action"] = "Planner is shaping a reviewed runbook."

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

        # A client cannot turn the approval endpoint into a second, unreviewed
        # execution channel. The accepted task must be the exact runbook that
        # is currently stored for the active chat.
        with db_lock:
            database = load_chats_db()
            stored_plan = _active_plan(database)
            if not stored_plan:
                self._error(409, "Draft a runbook before approving execution.")
                return
            if (
                submitted_task != stored_plan["execution_task"]
                or submitted_source_task != stored_plan["source_task"]
            ):
                self._error(409, "The reviewed runbook changed. Refresh it before approval.")
                return
            task = stored_plan["execution_task"]
            source_task = stored_plan["source_task"]
            policy = dict(database["safety"])

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

        if not _start_agent_task(task):
            self._error(409, "An agent run is already active. Stop or finish it before starting another.")
            return

        with db_lock:
            database = load_chats_db()
            chat = _active_chat(database)
            chat["current_task"] = task
            chat["status"] = "running"
            _record_audit(database, "run.approved", "Reviewed run approved and started.")
            save_chats_db(database)
            self._sync_active_chat(chat)

        with gui_app.status_lock:
            gui_app.agent_status["ui_mode"] = "executor"
            gui_app.agent_status["planner_synthesis"] = ""

        self._json_response({"success": True, "risk": risk}, 202)

    def _new_chat(self) -> None:
        with db_lock:
            database = load_chats_db()
            empty = next(
                (
                    chat
                    for chat in database["chats"]
                    if not any(message.get("role") == "user" for message in chat.get("chat_history", []))
                ),
                None,
            )
            chat = empty or _new_chat()
            if not empty:
                database["chats"].append(chat)
            database["active_chat_id"] = chat["id"]
            _record_audit(database, "run.created", "Created a new draft run.")
            save_chats_db(database)
            self._sync_active_chat(chat)

        with gui_app.status_lock:
            gui_app.agent_status["steps"] = []
            gui_app.agent_status["status"] = "idle"
            gui_app.agent_status["phase"] = "idle"
            gui_app.agent_status["phase_started_at"] = time.time()
            gui_app.agent_status["current_action"] = "Ready for a reviewed task."
        self._json_response({"success": True})

    def _retry_run(self) -> None:
        """Clone a completed run into a fresh, reviewable runbook.

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
        gui_app.stop_requested = True
        with gui_app.status_lock:
            gui_app.hitl_response.append("stop")
            gui_app.hitl_event.set()
            gui_app.agent_status["current_action"] = "Stop requested. Waiting for the next safe boundary."
            gui_app.agent_status["phase"] = "stopping"
            gui_app.agent_status["phase_started_at"] = time.time()
            gui_app.agent_status["ui_mode"] = "chat"
        with db_lock:
            database = load_chats_db()
            _record_audit(database, "run.stop_requested", "Operator requested the active run to stop.")
            save_chats_db(database)
        self._json_response({"success": True})

    def _pause_run(self, paused: bool) -> None:
        with gui_app.status_lock:
            gui_app.agent_status["paused"] = paused
            gui_app.agent_status["current_action"] = "Run paused by operator." if paused else "Run resumed by operator."
            gui_app.agent_status["phase"] = "paused" if paused else "thinking"
            gui_app.agent_status["phase_started_at"] = time.time()
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
            if path == "/api/pairing":
                if self._authorize(local_only=True):
                    self._json_response(pairing_session.local_payload())
                return
            if path == "/shutdown":
                if not self._authorize(local_only=True):
                    return
                self._json_response({"success": True})

                def shutdown() -> None:
                    time.sleep(0.35)
                    os._exit(0)

                threading.Thread(target=shutdown, name="omnivla-shutdown", daemon=True).start()
                return
            self._error(404, "Route not found.")
        except Exception as error:
            logger.exception("Unhandled GET error: %s", error)
            self._error(500, "The command center could not complete that request.")

    def do_POST(self) -> None:
        path = self._path
        local_only_routes = {"/api/settings", "/api/safety", "/api/pairing/rotate", "/api/clear_vram"}
        try:
            if path not in {
                "/api/chat",
                "/api/chats/new",
                "/api/chats/switch",
                "/api/chats/delete",
                "/api/chats/retry",
                "/api/confirm",
                "/api/settings",
                "/api/safety",
                "/api/pairing/rotate",
                "/api/stop",
                "/api/pause",
                "/api/resume",
                "/api/hitl_submit",
                "/api/clear_vram",
                "/api/run",
                "/api/reexecute",
            }:
                self._error(404, "Route not found.")
                return
            if not self._authorize(mutating=True, local_only=path in local_only_routes):
                return

            payload = self._read_json()
            if path == "/api/chat":
                self._create_plan(payload)
            elif path == "/api/chats/new":
                self._new_chat()
            elif path == "/api/chats/switch":
                self._switch_chat(payload)
            elif path == "/api/chats/delete":
                self._delete_chat(payload)
            elif path == "/api/chats/retry":
                self._retry_run()
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
            else:
                self._error(410, "Direct execution was retired. Draft and approve a runbook instead.")
        except RequestValidationError as error:
            self._error(400, str(error))
        except Exception as error:
            logger.exception("Unhandled POST error for %s: %s", path, error)
            self._error(500, "The command center could not complete that request.")
