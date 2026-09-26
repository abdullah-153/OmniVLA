"""Transactional application snapshots with bounded history and legacy import."""
from __future__ import annotations

import json
from contextlib import closing
import os
from pathlib import Path
import shutil
import sqlite3
import time


class StateStore:
    def __init__(self, legacy_path: str):
        self.legacy = Path(legacy_path)
        self.path = self.legacy.with_suffix(".sqlite3")
        self.backup = self.path.with_suffix(".sqlite3.bak")

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=5)
        try:
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("CREATE TABLE IF NOT EXISTS snapshots (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)")
            return connection
        except Exception:
            connection.close()
            raise

    def load(self):
        if self.path.exists():
            try:
                with closing(self._connect()) as connection:
                    if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                        raise sqlite3.DatabaseError("Application database integrity check failed")
                    row = connection.execute("SELECT payload FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
                    return json.loads(row[0]) if row else None
            except (sqlite3.DatabaseError, ValueError):
                damaged = self.path.with_name(self.path.name + f".corrupt-{time.time_ns()}")
                # Preserve evidence even if the backup itself is unusable.
                shutil.copy2(self.path, damaged)
                if not self.backup.exists():
                    raise
                with closing(sqlite3.connect(self.backup)) as backup:
                    if backup.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                        raise sqlite3.DatabaseError("Application database backup is damaged")
                    row = backup.execute("SELECT payload FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
                    recovered = json.loads(row[0]) if row else None
                shutil.copy2(self.backup, self.path)
                return recovered
        if self.legacy.exists() and self.legacy.stat().st_size:
            try:
                return json.loads(self.legacy.read_text(encoding="utf-8"))
            except ValueError:
                shutil.copy2(self.legacy, self.legacy.with_name(self.legacy.name + f".corrupt-{time.time_ns()}"))
                raise ValueError("Chat history is damaged. The original was preserved; restore a valid backup before continuing.")
        return None

    def save(self, value):
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            # Keep an independent last-known-good database before the next commit.
            if connection.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]:
                pending = self.backup.with_suffix(".bak.tmp")
                with closing(sqlite3.connect(pending)) as backup:
                    connection.backup(backup)
                os.replace(pending, self.backup)
            with connection:
                connection.execute("INSERT INTO snapshots(payload) VALUES (?)", (encoded,))
                connection.execute("DELETE FROM snapshots WHERE id NOT IN (SELECT id FROM snapshots ORDER BY id DESC LIMIT 5)")
            if not self.backup.exists():
                pending = self.backup.with_suffix(".bak.tmp")
                with closing(sqlite3.connect(pending)) as backup:
                    connection.backup(backup)
                os.replace(pending, self.backup)
