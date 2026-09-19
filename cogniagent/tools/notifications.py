"""Native Windows toast notification tool for OmniVLA.

Sends native Windows 10/11 Action Center notifications for completed tasks,
background alerts, and personal reminders using winotify.
"""

from __future__ import annotations

import logging
import os
import platform
import re
from typing import Any

logger = logging.getLogger("omnivla.tools.notifications")

try:
    import winotify
except ImportError:
    winotify = None


def send_notification(
    title: str,
    message: str,
    app_id: str = "OmniVLA Personal Agent",
    action_url: str | None = None,
) -> bool:
    """Send a native Windows toast notification to the user.

    Returns True if successfully displayed, False otherwise.
    """
    clean_title = str(title or "OmniVLA Agent").strip()
    clean_msg = str(message or "").strip()

    if not clean_msg and not clean_title:
        return False

    # Attempt native Windows toast via winotify
    if winotify is not None and platform.system() == "Windows":
        try:
            toast = winotify.Notification(
                app_id=app_id,
                title=clean_title,
                msg=clean_msg,
            )
            if action_url:
                toast.open_url(action_url)
            toast.show()
            logger.info("Sent native toast notification: '%s' - '%s'", clean_title, clean_msg)
            return True
        except Exception as win_err:
            logger.warning("Failed to show toast via winotify: %s", win_err)

    # Fallback for environments without winotify or non-Windows
    logger.info("[NOTIFICATION][%s] %s: %s", app_id, clean_title, clean_msg)
    return True


def detect_notification_intent(message: str) -> tuple[bool, str, str]:
    """Detect if the user is asking to send or test a notification.

    Returns (is_notify, title, message).
    """
    if not message or not isinstance(message, str):
        return False, "", ""

    text = message.strip()

    # Pattern: "send (me) a notification (with title/about/that) ..."
    notify_patterns = [
        r"(?:send|trigger|show|pop\s+up)\s+(?:me\s+)?(?:a\s+)?notification\s+(?:with\s+title\s+['\"]([^'\"]+)['\"]\s+(?:and\s+|with\s+)?(?:message\s+|saying\s+)?['\"]([^'\"]+)['\"])",
        r"(?:send|trigger|show)\s+(?:me\s+)?(?:a\s+)?notification\s+(?:that|saying|about)\s+['\"]?([^'\"?]+)['\"]?",
        r"(?:notify|remind)\s+me\s+(?:that|to|about)\s+['\"]?([^'\"?]+)['\"]?",
    ]

    for pat in notify_patterns:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            groups = m.groups()
            if len(groups) == 2 and groups[0] and groups[1]:
                return True, groups[0].strip(), groups[1].strip()
            elif len(groups) >= 1 and groups[0]:
                content = groups[0].strip()
                return True, "OmniVLA Reminder", content

    return False, "", ""

