"""Fast, private full-text retrieval for opt-in conversation memory."""

from __future__ import annotations

import json
import logging
from pathlib import Path
import re
import sqlite3
import threading
import time

logger = logging.getLogger(__name__)


def redact_memory_text(text: str) -> str:
    """Remove common secret shapes before opt-in recall is persisted."""
    redacted = str(text)
    patterns = (
        r"\b(?:sk|rk|pk)-[A-Za-z0-9_-]{12,}\b",
        r"\bBearer\s+[A-Za-z0-9._~+/-]{12,}\b",
        r"(?i)\b(password|passcode|api[_ -]?key|secret|token)\s*[:=]\s*\S+",
        r"\b(?:\d[ -]*?){13,19}\b",
    )
    for pattern in patterns:
        redacted = re.sub(pattern, "[redacted secret]", redacted)
    return redacted


class ChatsRAG:
    """SQLite FTS5 retrieval with BM25 ranking and no model/download latency."""

    def __init__(self, storage_dir: str = "./omnivla_memory_v2"):
        self.storage_dir = Path(storage_dir).resolve()
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.storage_dir / "chat_recall.sqlite3"
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(self.db_path, timeout=2.0, check_same_thread=False)
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=NORMAL")
        self._connection.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS messages USING fts5("
            "chat_id UNINDEXED, role UNINDEXED, content, created_at UNINDEXED, tokenize='unicode61')"
        )
        self._connection.commit()
        self._migrate_legacy_json()

    @staticmethod
    def _eligible(content: str) -> bool:
        lowered = content.casefold()
        rejected = ("cannot complete", "limitations:", "connection error", "connection aborted")
        return bool(content.strip()) and not any(marker in lowered for marker in rejected)

    def _migrate_legacy_json(self) -> None:
        legacy = self.storage_dir / "chat_rag_store.json"
        if not legacy.is_file():
            return
        try:
            entries = json.loads(legacy.read_text(encoding="utf-8"))
            with self._lock, self._connection:
                for entry in entries[-2000:]:
                    content = redact_memory_text(str(entry.get("content") or ""))[:1000]
                    if self._eligible(content):
                        self._connection.execute(
                            "INSERT INTO messages(chat_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                            (str(entry.get("chat_id") or ""), str(entry.get("role") or "user"), content, float(entry.get("timestamp") or time.time())),
                        )
            legacy.rename(legacy.with_suffix(".json.migrated"))
        except Exception as error:
            logger.warning("Could not migrate the legacy recall index: %s", error)

    def index_message(self, chat_id: str, role: str, content: str) -> None:
        """Atomically add one redacted message, deduplicating rapid retries."""
        clean = redact_memory_text(content).strip()[:1000]
        if not chat_id or role == "system" or not self._eligible(clean):
            return
        with self._lock, self._connection:
            duplicate = self._connection.execute(
                "SELECT 1 FROM messages WHERE chat_id = ? AND role = ? AND content = ? LIMIT 1",
                (chat_id, role, clean),
            ).fetchone()
            if duplicate:
                return
            self._connection.execute(
                "INSERT INTO messages(chat_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                (chat_id, role, clean, time.time()),
            )

    @staticmethod
    def _fts_query(query: str) -> str:
        tokens = list(dict.fromkeys(re.findall(r"[\w-]{2,}", query.casefold())))[:24]
        return " OR ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens)

    def search_context(self, query: str, current_chat_id: str, n_results: int = 3) -> str:
        """Retrieve diverse, recent, relevant messages under a strict text budget."""
        match = self._fts_query(query)
        if not match:
            return ""
        limit = max(1, min(int(n_results), 6))
        try:
            with self._lock:
                rows = self._connection.execute(
                    "SELECT chat_id, role, content, bm25(messages) AS score, created_at "
                    "FROM messages WHERE messages MATCH ? AND chat_id != ? "
                    "ORDER BY score ASC, created_at DESC LIMIT ?",
                    (match, current_chat_id, limit * 4),
                ).fetchall()
        except sqlite3.Error as error:
            logger.warning("Conversation recall query failed: %s", error)
            return ""
        selected: list[str] = []
        seen_chats: set[str] = set()
        used = 0
        for chat_id, role, content, _score, _created_at in rows:
            if chat_id in seen_chats and len(seen_chats) < limit:
                continue
            item = f"[{role}]: {content}"
            if selected and used + len(item) > 1200:
                break
            selected.append(item)
            seen_chats.add(chat_id)
            used += len(item)
            if len(selected) >= limit:
                break
        return "\n".join(selected)

    def close(self) -> None:
        with self._lock:
            self._connection.close()
