"""Lifetime user preferences and personal memory for OmniVLA.

Provides persistent, privacy-first storage for user facts, application preferences,
default accounts (e.g. Gmail vs. Outlook), and workflow habits. Automatically
injected into planner and visual executor prompts to ensure personal agent continuity.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import re
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_PROFILE = {
    "version": 1,
    "user_name": "User",
    "preferences": {
        "email": {
            "service": "Gmail",
            "account": "ak1399er@gmail.com",
            "client": "Microsoft Edge (mail.google.com)",
            "read_only_default": True,
        },
        "browser": {
            "default": "Microsoft Edge",
        },
        "general": {
            "concise_summaries": True,
            "confirm_destructive": True,
        },
    },
    "facts": [
        "Primary email address is ak1399er@gmail.com, accessed via Gmail in Microsoft Edge.",
        "When the user asks to check email without naming a client, always use Gmail (ak1399er@gmail.com), not desktop Outlook.",
        "Prefers Microsoft Edge as the default web browser.",
        "Prefers concise, structured bullet summaries of unread emails and documents.",
    ],
    "workflow_anchors": {
        "email": {
            "app": "Microsoft Edge",
            "url": "https://mail.google.com",
            "preferred_service": "Gmail",
            "account": "ak1399er@gmail.com",
        }
    },
    "last_updated": 0,
}


class UserProfileMemory:
    """Thread-safe persistent storage and learning engine for user lifetime memory."""

    def __init__(self, storage_dir: str = "./omnivla_memory_v2"):
        self.storage_dir = Path(storage_dir).resolve()
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.file_path = self.storage_dir / "user_profile.json"
        self._lock = threading.RLock()
        self._data: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        with self._lock:
            if self.file_path.is_file():
                try:
                    loaded = json.loads(self.file_path.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict) and "preferences" in loaded:
                        self._data = loaded
                        if not self._data.get("preferences", {}).get("email", {}).get("account"):
                            self._data.setdefault("preferences", {})["email"] = dict(DEFAULT_PROFILE["preferences"]["email"])
                        return
                except Exception as error:
                    logger.warning("Failed to load user profile JSON, resetting to defaults: %s", error)
            self._data = dict(DEFAULT_PROFILE)
            self._data["last_updated"] = int(time.time())
            self._save_unlocked()

    def _save_unlocked(self) -> None:
        try:
            self._data["last_updated"] = int(time.time())
            tmp_file = self.file_path.with_suffix(".tmp")
            tmp_file.write_text(json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp_file.replace(self.file_path)
        except Exception as error:
            logger.error("Failed to save user profile: %s", error)

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._data))

    def update_preference(self, category: str, key: str, value: Any) -> None:
        with self._lock:
            prefs = self._data.setdefault("preferences", {})
            cat = prefs.setdefault(category, {})
            cat[key] = value
            self._save_unlocked()

    def add_fact(self, fact: str) -> bool:
        clean = str(fact or "").strip()
        if not clean:
            return False
        with self._lock:
            facts = self._data.setdefault("facts", [])
            if clean not in facts:
                facts.append(clean)
                self._save_unlocked()
                return True
        return False

    def remove_fact(self, index: int) -> bool:
        with self._lock:
            facts = self._data.get("facts", [])
            if 0 <= index < len(facts):
                facts.pop(index)
                self._save_unlocked()
                return True
        return False

    def get_planner_context(self) -> str:
        """Return a formatted prompt segment with lifetime preferences for the planner."""
        with self._lock:
            prefs = self._data.get("preferences", {})
            facts = self._data.get("facts", [])
            email_info = prefs.get("email", {})
            browser_info = prefs.get("browser", {})

            lines = [
                "<user_profile_and_lifetime_memory>",
                "USER PREFERENCES & HABITS:",
                f"- Primary Email: {email_info.get('service', 'Gmail')} (Account: {email_info.get('account', 'ak1399er@gmail.com')}) via {email_info.get('client', 'Microsoft Edge')}.",
                f"- Default Browser: {browser_info.get('default', 'Microsoft Edge')}.",
            ]
            if facts:
                lines.append("PERSONAL HABITS & KNOWLEDGE:")
                for fact in facts[:6]:
                    lines.append(f"- {fact}")
            lines.append(
                "IMPORTANT INSTRUCTIONS:\n"
                "- When the user asks to check, read, or summarize email without specifying an account or client, ALWAYS plan for their preferred service: Gmail (ak1399er@gmail.com) via Microsoft Edge. Do NOT open desktop Outlook unless explicitly asked.\n"
                "- State your assumption clearly in the plan preface: e.g. 'Using your preferred Gmail (ak1399er@gmail.com).'"
            )
            lines.append("</user_profile_and_lifetime_memory>")
            return "\n".join(lines)

    def get_vla_context(self) -> str:
        """Return concise execution guidance for Holo VLA."""
        with self._lock:
            email_info = self._data.get("preferences", {}).get("email", {})
            account = email_info.get("account", "ak1399er@gmail.com")
            service = email_info.get("service", "Gmail")
            return (
                f"<user_memory>\n"
                f"Preferred email: {service} ({account}) via Microsoft Edge. "
                f"Do not switch to desktop Outlook unless user specifically commands it. "
                f"For logins/account choosers, select {account} if present, or use saved passwords. "
                f"If account is ambiguous or for OTP/verification, request help via hitl_intervention.\n"
                f"</user_memory>"
            )

    def learn_from_task(self, intent: str, steps: list, status: str, summary: str = "") -> None:
        """Inspect successful task executions to extract and reinforce habits."""
        if status != "success" or not intent:
            return
        intent_lower = intent.lower()
        with self._lock:
            if "gmail" in intent_lower:
                self.update_preference("email", "service", "Gmail")
            elif "outlook" in intent_lower and ("use outlook" in intent_lower or "check outlook" in intent_lower):
                self.update_preference("email", "service", "Outlook")

            for step in steps:
                action_text = str(step.get("action_text", "")).lower()
                note = str(step.get("note", "")).lower()
                combined = f"{action_text} {note}"
                if "gmail" in combined and "ak1399er@gmail.com" in combined:
                    self.update_preference("email", "account", "ak1399er@gmail.com")
                    self.update_preference("email", "service", "Gmail")
                    break

    def learn_from_message(self, message: str) -> list[str]:
        """Extract user preferences, identity, and persistent facts from natural language messages."""
        text = str(message or "").strip()
        if not text or len(text) < 3:
            return []
        learned = []
        text_lower = text.lower()

        # 1. User Name
        name_match = re.search(r"\b(?:my name is|i am|call me)\s+([A-Z][a-zA-Z0-9_-]+)\b", text)
        if name_match:
            name = name_match.group(1).strip()
            if name.lower() not in {"here", "ready", "trying", "going", "asking", "doing", "looking"}:
                with self._lock:
                    self._data["user_name"] = name
                    self._save_unlocked()
                fact = f"User's name is {name}."
                self.add_fact(fact)
                learned.append(fact)

        # 2. Email Address
        email_match = re.search(r"\b([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)\b", text)
        if email_match:
            email_addr = email_match.group(1).lower()
            service = "Gmail" if "gmail.com" in email_addr else ("Outlook" if ("outlook.com" in email_addr or "hotmail.com" in email_addr) else "Email")
            self.update_preference("email", "account", email_addr)
            if service != "Email":
                self.update_preference("email", "service", service)
            learned.append(f"Email account set to {email_addr} ({service}).")

        # 3. Browser Preference
        browser_match = re.search(r"\b(?:prefer|use|default to)\s+(google chrome|chrome|microsoft edge|edge|firefox|brave)\s*(?:as\s+(?:my\s+)?browser|for browsing)?\b", text_lower)
        if browser_match:
            raw_b = browser_match.group(1)
            b_name = "Microsoft Edge" if "edge" in raw_b else ("Google Chrome" if "chrome" in raw_b else raw_b.title())
            self.update_preference("browser", "default", b_name)
            learned.append(f"Default browser set to {b_name}.")

        # 4. Explicit Memory / Habit / Constraint Cues
        remember_match = re.search(
            r"\b(?:remember\s+that|keep\s+in\s+mind\s+that|note\s+that|please\s+remember|never\s+forget\s+that)\s+(.+?)(?:[.!?]|$)",
            text,
            re.IGNORECASE,
        )
        if remember_match:
            fact_candidate = remember_match.group(1).strip()
            if len(fact_candidate) > 5 and len(fact_candidate) < 200:
                clean_fact = fact_candidate[0].upper() + fact_candidate[1:]
                if not clean_fact.endswith("."):
                    clean_fact += "."
                if self.add_fact(clean_fact):
                    learned.append(clean_fact)

        # 5. Negative constraints ("never use outlook", "don't ever delete files without asking")
        negative_match = re.search(
            r"\b(?:never|don't\s+ever|do\s+not\s+ever)\s+(?:use|open|delete|remove)\s+(.+?)(?:[.!?]|$)",
            text,
            re.IGNORECASE,
        )
        if negative_match and not remember_match:
            neg_candidate = negative_match.group(0).strip()
            clean_fact = neg_candidate[0].upper() + neg_candidate[1:]
            if not clean_fact.endswith("."):
                clean_fact += "."
            if self.add_fact(clean_fact):
                learned.append(clean_fact)

        if learned:
            logger.info("Automatically learned from user message: %s", learned)
        return learned


_profile_memory_instance: UserProfileMemory | None = None


def get_user_profile(storage_dir: str = "./omnivla_memory_v2") -> UserProfileMemory:
    global _profile_memory_instance
    if _profile_memory_instance is None:
        _profile_memory_instance = UserProfileMemory(storage_dir)
    return _profile_memory_instance
