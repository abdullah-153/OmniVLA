import sys
import logging
import json
from io import BytesIO
import mss
import mss.tools
from PIL import Image
import base64
import copy
import requests
from openai import OpenAI
from openai import APIConnectionError, APITimeoutError
from typing import Literal
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

class ClickArgs(BaseModel):
    """Click at (x, y) coordinates"""
    tool_name: Literal["click"]
    element: str = Field(min_length=1, max_length=300, description="Detailed description of the target UI element to click on")
    x: int = Field(ge=0, le=1000, description="X coordinate as integer in [0, 1000]")
    y: int = Field(ge=0, le=1000, description="Y coordinate as integer in [0, 1000]")

class DoubleClickArgs(BaseModel):
    """Open or activate a visible item with a double click."""
    tool_name: Literal["double_click"]
    element: str = Field(min_length=1, max_length=300)
    x: int = Field(ge=0, le=1000)
    y: int = Field(ge=0, le=1000)

class RightClickArgs(BaseModel):
    """Open the context menu for a visible item."""
    tool_name: Literal["right_click"]
    element: str = Field(min_length=1, max_length=300)
    x: int = Field(ge=0, le=1000)
    y: int = Field(ge=0, le=1000)

class MoveArgs(BaseModel):
    """Move the pointer to reveal hover-only UI without clicking."""
    tool_name: Literal["move"]
    element: str = Field(min_length=1, max_length=300)
    x: int = Field(ge=0, le=1000)
    y: int = Field(ge=0, le=1000)

class DragArgs(BaseModel):
    """Drag a visible source to a visible destination."""
    tool_name: Literal["drag"]
    source_element: str = Field(min_length=1, max_length=300)
    target_element: str = Field(min_length=1, max_length=300)
    from_x: int = Field(ge=0, le=1000)
    from_y: int = Field(ge=0, le=1000)
    to_x: int = Field(ge=0, le=1000)
    to_y: int = Field(ge=0, le=1000)
    duration: float = Field(default=0.6, ge=0.2, le=2.0)

class TypeArgs(BaseModel):
    """Type text"""
    tool_name: Literal["type"]
    text: str = Field(max_length=5_000, description="Content to type")
    submit: bool = Field(default=False, description="Whether to press Enter after typing")

class KeyPressArgs(BaseModel):
    """Press a specific system key"""
    tool_name: Literal["key_press"]
    key: str = Field(min_length=1, max_length=64, description="The key to press, e.g., 'tab', 'enter', 'esc', 'win'")

class ScrollArgs(BaseModel):
    """Scroll the screen or a specific window element"""
    tool_name: Literal["scroll"]
    direction: Literal["up", "down"] = Field(description="Direction to scroll")
    x: int | None = Field(default=None, ge=0, le=1000, description="Optional X coordinate to hover over before scrolling")
    y: int | None = Field(default=None, ge=0, le=1000, description="Optional Y coordinate to hover over before scrolling")

class TerminateArgs(BaseModel):
    """Terminate the task"""
    tool_name: Literal["terminate"]
    status: Literal["success", "failure"] = Field(description="Status of the task")
    reason: str = Field(min_length=1, max_length=1_000, description="Screen evidence supporting the termination status")

class HITLInterventionArgs(BaseModel):
    """Ask the human user for intervention, clarification, or input when absolutely necessary."""
    tool_name: Literal["hitl_intervention"]
    question: str = Field(min_length=1, max_length=2_000, description="The specific question, clarification, or instruction for the human to address.")

class WaitArgs(BaseModel):
    """Wait for a certain duration (in seconds) for applications to load, operations to complete, or screens to update."""
    tool_name: Literal["wait"]
    duration: int = Field(default=3, ge=1, le=10, description="Duration to wait in seconds (between 1 and 10).")

class GetOpenAppsArgs(BaseModel):
    """List all open application window titles currently active/running."""
    tool_name: Literal["get_open_apps"]

class SwitchToAppArgs(BaseModel):
    """Switch focus to an open application window by its title."""
    tool_name: Literal["switch_to_app"]
    app_title: str = Field(min_length=1, max_length=160, description="Sub-string of the window/app title to focus (case-insensitive)")

class OpenAppArgs(BaseModel):
    """Open a named application through Windows search without screen coordinates."""
    tool_name: Literal["open_app"]
    app_name: str = Field(min_length=1, max_length=80, description="Visible application name, such as Notepad")

class MinimizeAllAppsArgs(BaseModel):
    """Minimize all open windows on the screen (show desktop)."""
    tool_name: Literal["minimize_all_apps"]

class Step(BaseModel):
    tool_call: ClickArgs | DoubleClickArgs | RightClickArgs | MoveArgs | DragArgs | TypeArgs | KeyPressArgs | ScrollArgs | TerminateArgs | HITLInterventionArgs | WaitArgs | GetOpenAppsArgs | SwitchToAppArgs | OpenAppArgs | MinimizeAllAppsArgs
    note: str | None = Field(
        default=None,
        max_length=4000,
        description="Task-relevant information extracted from the previous observation. Keep empty if no new info.",
    )
    thought: str = Field(default="", max_length=4000, description="Legacy compatibility field; omit from new responses.")

TOOL_MODELS = (
    ClickArgs, DoubleClickArgs, RightClickArgs, MoveArgs, DragArgs, TypeArgs,
    KeyPressArgs, ScrollArgs, TerminateArgs, HITLInterventionArgs, WaitArgs,
    GetOpenAppsArgs, SwitchToAppArgs, OpenAppArgs, MinimizeAllAppsArgs,
)


def native_tool_definitions() -> list[dict]:
    """Expose the validated action boundary through the model's native tools."""
    tools = []
    for model in TOOL_MODELS:
        schema = copy.deepcopy(model.model_json_schema())
        properties = schema.get("properties", {})
        tool_name_schema = properties.pop("tool_name", {})
        required = [field for field in schema.get("required", []) if field != "tool_name"]
        schema["required"] = required
        schema["additionalProperties"] = False
        # Pydantic's titles and duplicated class descriptions add hundreds of
        # tokens without improving tool choice. Keep constraints and the few
        # field descriptions that disambiguate coordinate semantics.
        schema.pop("title", None)
        schema.pop("description", None)
        for field_name, field_schema in properties.items():
            if not isinstance(field_schema, dict):
                continue
            field_schema.pop("title", None)
            if field_name not in {
                "element", "source_element", "target_element", "x", "y",
                "from_x", "from_y", "to_x", "to_y",
            }:
                field_schema.pop("description", None)
        name = str(tool_name_schema.get("const") or model.model_fields["tool_name"].default)
        description = (model.__doc__ or f"Run the {name} desktop action.").strip()
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": schema,
                },
            }
        )
    return tools


NATIVE_TOOLS = native_tool_definitions()


def native_tools_for_task(task: str) -> list[dict]:
    """Expose the complete native tool belt and let the model choose intelligently.

    Hiding tools with task-keyword heuristics turned tool selection into a macro
    router and removed valid recovery paths. The catalog is compact enough for
    the local context, so capability discovery remains model-owned.
    """
    return NATIVE_TOOLS


SYSTEM_PROMPT = """You are an expert Windows computer-use agent. Inspect the newest screenshot and tool results, reason privately about the current state, and call exactly one native tool.

Core Rules:
1. Visual Grounding: The screenshot is ground truth. Click coordinates (x, y) must be integers in [0, 1000] targeting the center of the visible element.
2. Window State: Do not confuse pinned taskbar icons with open windows; switch to or launch apps directly.
3. No Repetition: Never repeat ineffective actions. If an action fails or leaves state unchanged, adapt immediately.
4. Working Memory: Record extracted information (senders, subjects, rows, data) into "note" to retain findings across steps.
5. Verification: Call terminate(status="success", reason="...") only when the newest screen visually verifies completion.
6. Safety: Use hitl_intervention for credentials, MFA, payments, destructive file changes, or sending external data.
7. Execution: Reason privately without narrating to the user; finish with exactly one tool call.
"""


LEGACY_JSON_CONTRACT = """
Return JSON only with "tool_call" first and an optional short "note". Do not expose private chain-of-thought.
JSON contract:
{"tool_call": object, "note": string|null}
tool_call variants:
- click: {"tool_name":"click","element":string,"x":0..1000,"y":0..1000}
- double_click or right_click: {"tool_name":...,"element":string,"x":0..1000,"y":0..1000}
- move: {"tool_name":"move","element":string,"x":0..1000,"y":0..1000}
- drag: {"tool_name":"drag","source_element":string,"target_element":string,"from_x":0..1000,"from_y":0..1000,"to_x":0..1000,"to_y":0..1000,"duration":0.2..2.0}
- type: {"tool_name":"type","text":string,"submit":boolean}
- key_press: {"tool_name":"key_press","key":string}; scroll: {"tool_name":"scroll","direction":"up"|"down"}
- switch_to_app: {"tool_name":"switch_to_app","app_title":string}; get_open_apps or minimize_all_apps: {"tool_name":...}
- open_app: {"tool_name":"open_app","app_name":string}
- wait: {"tool_name":"wait","duration":1..10}
- hitl_intervention: {"tool_name":"hitl_intervention","question":string}
- terminate: {"tool_name":"terminate","status":"success"|"failure","reason":string}
"""

def trim_to_last_n_images(messages, n=1):
    seen = 0
    for msg in reversed(messages):
        if msg["role"] != "user" or not isinstance(msg["content"], list):
            continue
        for chunk in msg["content"]:
            if chunk.get("type") != "image_url":
                continue
            seen += 1
            if seen > n:
                chunk["type"] = "text"
                chunk["text"] = "[screenshot evicted]"
                chunk.pop("image_url", None)


def extract_working_memory(messages: list[dict], limit: int = 8) -> list[str]:
    """Collect recent extracted notes and key actions so the model retains situational memory across screen evictions."""
    memory_items: list[str] = []
    for message in reversed(messages):
        if message.get("role") == "assistant":
            note = str(message.get("content") or "").strip()
            if note and not note.startswith("[") and not note.startswith("<"):
                memory_items.append(f"- Observation note: {note[:250]}")
            # Also extract tool calls
            for tool_call in message.get("tool_calls", []):
                fn = tool_call.get("function", {})
                name = fn.get("name", "")
                try:
                    args = json.loads(fn.get("arguments", "{}"))
                except Exception:
                    args = {}
                if name in {"click", "double_click", "right_click"}:
                    target = args.get("element", "element")
                    memory_items.append(f"- Action: {name} on '{target}'")
                elif name == "open_app":
                    memory_items.append(f"- Action: open app '{args.get('app_name', '')}'")
                elif name == "type":
                    memory_items.append(f"- Action: entered text ({len(args.get('text', ''))} chars)")
        if len(memory_items) >= limit:
            break
    return list(reversed(memory_items))


def compact_execution_history(messages, max_non_system_messages=8):
    """Bound prompt growth while retaining working memory from evicted turns."""

    system_messages = [message for message in messages if message.get("role") == "system"]
    non_system_messages = [
        message
        for message in messages
        if message.get("role") != "system"
        and not (
            message.get("role") == "user"
            and isinstance(message.get("content"), list)
            and any(
                isinstance(chunk, dict)
                and str(chunk.get("text", "")).startswith("<history_summary>")
                for chunk in message["content"]
            )
        )
    ]
    if len(non_system_messages) <= max_non_system_messages:
        return

    # Extract memorable notes/actions before evicting
    memory_notes = extract_working_memory(non_system_messages[:-max_non_system_messages], limit=6)
    memory_summary = "\n".join(memory_notes) if memory_notes else "Prior navigation accomplished."

    retained = non_system_messages[-max_non_system_messages:]
    summary = {
        "role": "user",
        "content": [
            {
                "type": "text",
                "text": (
                    f"<history_summary>\nPrior steps completed (screens evicted [screenshot evicted]):\n"
                    f"{memory_summary}\n"
                    f"Use the newest observation as source of truth. Do NOT repeat the above actions.\n"
                    f"</history_summary>"
                ),
            }
        ],
    }
    messages[:] = system_messages + [summary] + retained


def checkpoint_execution_context(messages):
    """Create a lightweight replan checkpoint without copying JPEG payloads."""
    checkpoint = copy.deepcopy(messages)
    trim_to_last_n_images(checkpoint, n=0)
    compact_execution_history(checkpoint)
    return checkpoint


def recent_execution_feedback(messages: list[dict], limit: int = 4) -> str:
    """Surface recent outcomes beside the newest image so small local models cannot miss them."""
    feedback: list[str] = []
    for message in reversed(messages):
        if message.get("role") != "tool":
            continue
        content = message.get("content", "")
        try:
            payload = json.loads(content) if isinstance(content, str) else {}
        except json.JSONDecodeError:
            payload = {}
        detail = str(payload.get("detail") or "").strip()
        if detail:
            feedback.append(f"- {'Succeeded' if payload.get('success') else 'Failed'}: {detail[:300]}")
        if len(feedback) >= limit:
            break
    return "\n".join(reversed(feedback))


import re

def configured_output_tokens(value) -> int:
    """Reserve enough room for private reasoning and one complete tool call."""
    try:
        tokens = int(value)
    except (TypeError, ValueError):
        tokens = 256
    return max(256, min(tokens, 512))


def parse_native_tool_call(message) -> dict | None:
    """Normalize one provider-native function call through the same schema."""
    tool_calls = getattr(message, "tool_calls", None)
    if not tool_calls:
        return None
    function = getattr(tool_calls[0], "function", None)
    name = getattr(function, "name", None)
    arguments = getattr(function, "arguments", "{}")
    if not isinstance(name, str) or not name.strip():
        return None
    try:
        parsed_arguments = json.loads(arguments) if isinstance(arguments, str) else arguments
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(parsed_arguments, dict):
        return None

    reasoning = getattr(message, "reasoning_content", None)
    if reasoning is None and hasattr(message, "model_extra") and isinstance(message.model_extra, dict):
        reasoning = message.model_extra.get("reasoning_content")
    payload = {
        "tool_call": {"tool_name": name.strip(), **parsed_arguments},
        "note": None,
        # Retain internal rationale without mid-word character chopping.
        "thought": str(reasoning or "").strip()[:4000],
    }
    try:
        step = Step.model_validate(payload)
    except Exception as exc:
        logger.warning("Rejected invalid native tool call: %s", exc)
        return None
    return {
        "note": step.note,
        "thought": step.thought,
        "tool_call": step.tool_call.model_dump(),
        "tool_call_id": str(getattr(tool_calls[0], "id", "") or ""),
    }

def clean_json_response(text: str) -> str:
    """Robustly extract and clean JSON payload from VLM model outputs."""
    if not text:
        return ""
    text = text.strip()
    # 1. Match code blocks ```json ... ``` or ``` ... ```
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if match:
        return match.group(1).strip()
    # 2. Match outer braces { ... }
    match_braces = re.search(r"(\{[\s\S]*\})", text)
    if match_braces:
        return match_braces.group(1).strip()
    return text

def parse_vlm_output(raw_output: str) -> dict | None:
    """Validate a model response without ever inventing an executable action.

    Computer-use output is a security boundary. A partial JSON object, prose,
    or provider error must cause the perception cycle to retry; it must never
    become a guessed click, key press, or successful termination.
    """
    if not isinstance(raw_output, str) or not raw_output.strip():
        return None

    cleaned = clean_json_response(raw_output)
    try:
        payload = json.loads(cleaned)
        if not isinstance(payload, dict):
            return None

        # Compact local checkpoints sometimes emit their explicit tool name at
        # `tool_call` and place arguments beside it (or under args). Normalize
        # that provider shape, then apply the same strict Pydantic boundary.
        raw_tool = payload.get("tool_call")
        if isinstance(raw_tool, str):
            tool_name = raw_tool.strip()
            allowed_fields = {
                "click": {"element", "x", "y"},
                "double_click": {"element", "x", "y"},
                "right_click": {"element", "x", "y"},
                "move": {"element", "x", "y"},
                "drag": {"source_element", "target_element", "from_x", "from_y", "to_x", "to_y", "duration"},
                "type": {"text", "submit"},
                "key_press": {"key"},
                "scroll": {"direction", "x", "y"},
                "terminate": {"status", "reason"},
                "hitl_intervention": {"question"},
                "wait": {"duration"},
                "get_open_apps": set(),
                "switch_to_app": {"app_title"},
                "open_app": {"app_name"},
                "minimize_all_apps": set(),
            }
            if tool_name not in allowed_fields:
                return None
            nested = next(
                (payload.get(key) for key in ("arguments", "args", "parameters") if isinstance(payload.get(key), dict)),
                {},
            )
            tool_payload = {"tool_name": tool_name}
            for key in allowed_fields[tool_name]:
                if key in nested:
                    tool_payload[key] = nested[key]
                elif key in payload:
                    tool_payload[key] = payload[key]
            payload = {
                "tool_call": tool_payload,
                "note": payload.get("note"),
                "thought": payload.get("thought", ""),
            }
        step = Step.model_validate(payload)
    except Exception as exc:
        logger.warning("Rejected invalid VLM action payload: %s", exc)
        return None

    return {
        "note": step.note,
        "thought": step.thought,
        "tool_call": step.tool_call.model_dump(),
    }


class VLMEngine:
    def __init__(self, endpoint=None, model_name=None):
        from cogniagent.config import config

        self.config = config
        m_type = getattr(config.llm, "model_type", "local")
        self.model_type = m_type
        api_key = getattr(config.llm, "api_key", "")
        if not api_key:
            api_key = "antigravity"
            
        if m_type == "openai":
            self.endpoint = "https://api.openai.com/v1"
            self.model_name = model_name or config.llm.model
            self.client = OpenAI(api_key=api_key)
        elif m_type == "anthropic":
            self.endpoint = "https://api.anthropic.com/v1/messages"
            self.model_name = model_name or config.llm.model
            self.client = None
            self._anthropic_api_key = api_key
        else:
            if endpoint is None:
                endpoint = "http://127.0.0.1:8089/v1"
            if endpoint == "http://127.0.0.1:8089/v1":
                base = config.llm.base_url.rstrip('/')
                if base.endswith('/v1'):
                    self.endpoint = base
                else:
                    self.endpoint = f"{base}/v1"
            else:
                self.endpoint = endpoint
            self.model_name = model_name or config.llm.model
            self.client = OpenAI(
                base_url=self.endpoint,
                api_key="antigravity",
                timeout=60.0,
                max_retries=0,
            )

        self.sct = mss.mss()
        monitors = self.sct.monitors
        requested_monitor = getattr(config.perception, "capture_monitor", 1)
        if isinstance(requested_monitor, int) and 1 <= requested_monitor < len(monitors):
            self.monitor = monitors[requested_monitor]
        elif len(monitors) > 1:
            logger.warning(
                "Configured capture monitor %r is unavailable; using monitor 1.",
                requested_monitor,
            )
            self.monitor = monitors[1]
        else:
            # mss index 0 represents the virtual desktop.  It is a safe
            # fallback for unusual single-monitor/remote-desktop setups.
            self.monitor = monitors[0]
        self.capture_origin = (
            int(self.monitor.get("left", 0)),
            int(self.monitor.get("top", 0)),
        )
        logger.info(f"VLM Engine initialized ({m_type}). Using API endpoint: {self.endpoint}, model: {self.model_name}")

    def capture_screen(self, for_vlm=True):
        from PIL import Image, ImageGrab

        if sys.platform == "win32":
            try:
                import ctypes
                user32 = ctypes.windll.user32
                hdesk = user32.OpenDesktopW("default", 0, False, 0x01FF)
                if hdesk:
                    user32.SetThreadDesktop(hdesk)
            except Exception:
                pass

        img = None
        # Attempt 1: Fast mss with fresh context
        try:
            with mss.mss() as sct:
                mon = self.monitor if isinstance(self.monitor, dict) else sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
                sct_img = sct.grab(mon)
                img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
        except Exception as me:
            logger.warning("mss grab failed (%s), attempting desktop refresh and ImageGrab", me)
            if sys.platform == "win32":
                try:
                    import ctypes
                    user32 = ctypes.windll.user32
                    hdesk = user32.OpenDesktopW("default", 0, False, 0x01FF)
                    if hdesk:
                        user32.SetThreadDesktop(hdesk)
                except Exception:
                    pass

        # Attempt 2: PIL.ImageGrab (handles Windows Desktop / multi-threading without BitBlt lock)
        if img is None:
            try:
                bbox = None
                if isinstance(self.monitor, dict):
                    left = int(self.monitor.get("left", 0))
                    top = int(self.monitor.get("top", 0))
                    bbox = (
                        left,
                        top,
                        left + int(self.monitor.get("width", 0)),
                        top + int(self.monitor.get("height", 0)),
                    )
                img = ImageGrab.grab(bbox=bbox, all_screens=True).convert("RGB")
            except Exception as ie:
                logger.warning("ImageGrab all_screens failed (%s), falling back to standard grab", ie)
                try:
                    img = ImageGrab.grab().convert("RGB")
                except Exception as ie2:
                    logger.warning("ImageGrab standard failed (%s), trying desktop re-attach", ie2)
                    if sys.platform == "win32":
                        try:
                            import ctypes
                            user32 = ctypes.windll.user32
                            hdesk = user32.OpenDesktopW("default", 0, False, 0x01FF)
                            if hdesk:
                                user32.SetThreadDesktop(hdesk)
                            img = ImageGrab.grab().convert("RGB")
                        except Exception as ie3:
                            logger.error("All screenshot captures failed after desktop re-attach: %s", ie3)
                            raise RuntimeError("Unable to capture the desktop safely. Ensure the interactive screen is unlocked.") from ie3
                    else:
                        logger.error("All screenshot captures failed: %s", ie2)
                        raise RuntimeError("Unable to capture the desktop safely") from ie2

        # Keep the monitor's virtual-desktop origin alongside dimensions.
        self.capture_origin = (
            int(self.monitor.get("left", 0)) if isinstance(self.monitor, dict) else 0,
            int(self.monitor.get("top", 0)) if isinstance(self.monitor, dict) else 0,
        )
        return img, (img.width, img.height)


    def encode_screenshot(self, pil_image):
        """Encode a bounded screenshot for the 6 GB local inference profile."""
        img_copy = pil_image.copy()
        max_width = max(1280, min(int(getattr(self.config.perception, "screenshot_max_width", 1920)), 2560))
        max_height = max(720, min(int(getattr(self.config.perception, "screenshot_max_height", 1080)), 1440))
        quality = max(65, min(int(getattr(self.config.perception, "screenshot_jpeg_quality", 80)), 90))
        if img_copy.width > max_width or img_copy.height > max_height:
            img_copy.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
        buffered = BytesIO()
        img_copy.save(buffered, format="JPEG", quality=quality, optimize=True)
        return base64.b64encode(buffered.getvalue()).decode("utf-8")




    def _anthropic_completion(self, messages: list[dict]) -> str:
        """Translate OpenAI-shaped visual context to Anthropic Messages API with strict alternating turns."""
        system_parts = []
        raw_translated = []
        for message in messages:
            role = message.get("role")
            content = message.get("content", "")
            if role == "system":
                if isinstance(content, str):
                    system_parts.append(content)
                continue
            if role not in {"user", "assistant"}:
                continue

            if isinstance(content, str):
                translated_content = [{"type": "text", "text": content}]
            elif isinstance(content, list):
                translated_content = []
                for chunk in content:
                    if not isinstance(chunk, dict):
                        continue
                    if chunk.get("type") == "text":
                        translated_content.append({"type": "text", "text": str(chunk.get("text", ""))})
                        continue
                    image_url = chunk.get("image_url", {}).get("url", "")
                    if chunk.get("type") == "image_url" and isinstance(image_url, str) and image_url.startswith("data:image/"):
                        try:
                            header, encoded_image = image_url.split(",", 1)
                            media_type = header.split(";", 1)[0].split(":", 1)[1]
                            translated_content.append(
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": media_type,
                                        "data": encoded_image,
                                    },
                                }
                            )
                        except (IndexError, ValueError):
                            translated_content.append({"type": "text", "text": "[unavailable screenshot]"})
                if not translated_content:
                    translated_content = [{"type": "text", "text": "[empty observation]"}]
            else:
                translated_content = [{"type": "text", "text": str(content)}]
            raw_translated.append({"role": role, "content": translated_content})

        # Merge adjacent turns of the same role to strictly obey Anthropic alternating-turn schema
        merged_messages = []
        for msg in raw_translated:
            if merged_messages and merged_messages[-1]["role"] == msg["role"]:
                merged_messages[-1]["content"].extend(msg["content"])
            else:
                merged_messages.append({"role": msg["role"], "content": list(msg["content"])})

        response = requests.post(
            self.endpoint,
            headers={
                "x-api-key": self._anthropic_api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": self.model_name,
                "max_tokens": configured_output_tokens(self.config.llm.max_tokens),
                "temperature": self.config.llm.temperature,
                "system": "\n\n".join(system_parts),
                "messages": merged_messages,
            },
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        text_parts = [
            block.get("text", "")
            for block in payload.get("content", [])
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        if not text_parts:
            raise ValueError("Anthropic returned no text content.")
        return "\n".join(text_parts)


    def reason(self, task: str, messages: list):
        if not messages:
            system = SYSTEM_PROMPT + f"\nCurrent goal: {task}"
            if self.model_type == "anthropic":
                system += LEGACY_JSON_CONTRACT
            messages.append({"role": "system", "content": system})
        img, orig_dims = self.capture_screen()
        b64_img = self.encode_screenshot(img)
        
        feedback = recent_execution_feedback(messages)
        working_memory = extract_working_memory(messages, limit=6)
        memory_str = "\n".join(working_memory) if working_memory else ""

        state_blocks = []
        if working_memory:
            state_blocks.append(f"<working_memory>\nKey items observed / actions taken so far:\n{memory_str}\nDo NOT re-open or repeat these items.\n</working_memory>")
        if feedback:
            state_blocks.append(f"<execution_state>\nRecent outcomes:\n{feedback}\nDo not redo an accomplished step. Continue from the visible state using a different action.\n</execution_state>")

        state_note = ("\n\n".join(state_blocks) + "\n\n") if state_blocks else ""
        messages.append({"role": "user", "content": [
            {"type": "text", "text": state_note + "<observation>\n"},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}},
            {"type": "text", "text": "\n</observation>"},
        ]})
        
        # Keep one image by default for the 6 GB local-GPU deployment. Older
        # screenshots are still represented by their text observations, while
        # retaining fewer image embeddings avoids unnecessary VRAM/context use.
        visual_context_images = getattr(self.config.perception, "visual_context_images", 1)
        if isinstance(visual_context_images, bool) or not isinstance(visual_context_images, int):
            visual_context_images = 1
        visual_context_images = max(1, min(visual_context_images, 3))
        trim_to_last_n_images(messages, n=visual_context_images)
        compact_execution_history(messages)
        
        logger.info("Sending screen to Holo3 API...")
        try:
            raw_output = ""
            finish_reason = None
            parsed_res = None
            for attempt in range(1, 3):
                try:
                    if self.model_type == "anthropic":
                        raw_output = self._anthropic_completion(messages)
                        parsed_res = parse_vlm_output(raw_output)
                    else:
                        resp = self.client.chat.completions.create(
                            model=self.model_name,
                            messages=messages,
                            temperature=self.config.llm.temperature,
                            max_tokens=configured_output_tokens(self.config.llm.max_tokens),
                            tools=native_tools_for_task(task),
                            tool_choice="required",
                        )
                        msg = resp.choices[0].message
                        finish_reason = getattr(resp.choices[0], "finish_reason", None)
                        raw_output = msg.content or ""
                        parsed_res = parse_native_tool_call(msg)
                        # API providers without native tool-call parsing can
                        # still return the validated legacy JSON envelope.
                        if parsed_res is None and raw_output.strip():
                            parsed_res = parse_vlm_output(raw_output)

                    if parsed_res is not None:
                        break
                    if raw_output.strip():
                        logger.warning("Invalid action schema on attempt %d/2", attempt)
                    if finish_reason == "length":
                        if attempt == 1:
                            logger.warning("VLM generation truncated by token limit on attempt 1. Retrying with concise instruction.")
                            messages.append({
                                "role": "user",
                                "content": "The previous generation was cut off by token limits. Be concise and call exactly one available tool immediately without extensive reasoning.",
                            })
                            continue
                        break
                    if attempt == 1:
                        messages.append({
                            "role": "user",
                            "content": "The previous response did not contain one valid tool call. Re-check the newest screenshot, then call exactly one available tool.",
                        })
                except (APITimeoutError, APIConnectionError) as err:
                    logger.warning("VLM request stopped after transport failure: %s", err)
                    return None
                except Exception as err:
                    logger.warning("VLM request failed on attempt %d/2: %s", attempt, err)
                    break
            
            if parsed_res is None:
                logger.error("VLM produced no valid action within the bounded request budget.")
                return None

            thought = parsed_res["thought"]
            tool_call = parsed_res["tool_call"]
            note = parsed_res.get("note")

            if note:
                logger.info("[OBSERVATION] %s", note)
            logger.info("[REASONING] Model evaluated the current screen before acting.")
            logger.info("[ACTION] %s", tool_call.get("tool_name"))

            # Preserve the native call shape and retain the observation note
            # in context so the model remembers what it read across turns.
            call_id = parsed_res.get("tool_call_id") or f"desktop-step-{len(messages)}"
            function_args = {key: value for key, value in tool_call.items() if key != "tool_name"}
            assistant_content = str(note).strip() if note else ""
            messages.append(
                {
                    "role": "assistant",
                    "content": assistant_content,
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": tool_call.get("tool_name", ""),
                                "arguments": json.dumps(function_args, ensure_ascii=False),
                            },
                        }
                    ],
                }
            )

            action_desp = tool_call.get("tool_name", "click")
            action_call = json.dumps(tool_call)

            return {
                "think": thought,
                "note": note,
                "action_desp": action_desp,
                "action_call": action_call,
                "parsed_action": tool_call,
                "target_pixel": None,
                "raw_output": raw_output,
                "screenshot": img,
                "orig_dims": orig_dims,
                "screen_origin": self.capture_origin,
                "tool_call_id": call_id,
            }

        except Exception as e:
            logger.error(f"VLM reasoning failed: {e}")
            return None
