"""SQLite persistence with versioned migrations and small typed helpers."""

from __future__ import annotations

import contextlib
import json
import sqlite3
import threading
import uuid
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import NotFoundError

MIGRATIONS: list[str] = [
    # 1 — initial schema
    """
    CREATE TABLE campaigns (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        slug TEXT NOT NULL,
        platforms TEXT NOT NULL DEFAULT '[]',
        game TEXT NOT NULL DEFAULT '',
        url TEXT NOT NULL DEFAULT '',
        payout_cpm REAL,
        payout_notes TEXT NOT NULL DEFAULT '',
        objective TEXT NOT NULL DEFAULT '',
        requirements TEXT NOT NULL DEFAULT '[]',
        restrictions TEXT NOT NULL DEFAULT '[]',
        content_goals TEXT NOT NULL DEFAULT '[]',
        hook_examples TEXT NOT NULL DEFAULT '[]',
        reference_links TEXT NOT NULL DEFAULT '[]',
        codes TEXT NOT NULL DEFAULT '[]',
        notes TEXT NOT NULL DEFAULT '',
        analysis TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE campaign_documents (
        id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
        kind TEXT NOT NULL,
        name TEXT NOT NULL,
        source TEXT NOT NULL DEFAULT '',
        text TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE media (
        id TEXT PRIMARY KEY,
        kind TEXT NOT NULL,
        path TEXT NOT NULL,
        filename TEXT NOT NULL,
        sha256 TEXT NOT NULL,
        size INTEGER NOT NULL,
        duration REAL,
        width INTEGER,
        height INTEGER,
        fps REAL,
        has_audio INTEGER NOT NULL DEFAULT 0,
        codec TEXT,
        audio_codec TEXT,
        orientation TEXT,
        thumbnail TEXT,
        category TEXT,
        tags TEXT NOT NULL DEFAULT '[]',
        license_note TEXT NOT NULL DEFAULT '',
        campaign_id TEXT REFERENCES campaigns(id) ON DELETE SET NULL,
        analysis TEXT,
        created_at TEXT NOT NULL
    );
    CREATE UNIQUE INDEX media_sha_kind ON media(sha256, kind);
    CREATE TABLE segments (
        id TEXT PRIMARY KEY,
        media_id TEXT NOT NULL REFERENCES media(id) ON DELETE CASCADE,
        start REAL NOT NULL,
        end REAL NOT NULL,
        label TEXT NOT NULL,
        kind TEXT NOT NULL,
        score REAL NOT NULL DEFAULT 0,
        confidence REAL NOT NULL DEFAULT 0,
        tags TEXT NOT NULL DEFAULT '[]',
        source TEXT NOT NULL DEFAULT 'auto',
        enabled INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL
    );
    CREATE TABLE ideas (
        id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
        position INTEGER NOT NULL DEFAULT 0,
        category TEXT NOT NULL,
        title TEXT NOT NULL,
        hook TEXT NOT NULL,
        concept TEXT NOT NULL,
        script_angle TEXT NOT NULL,
        est_duration INTEGER NOT NULL,
        required_gameplay TEXT NOT NULL DEFAULT '[]',
        cta TEXT NOT NULL DEFAULT '',
        novelty_score REAL NOT NULL DEFAULT 0,
        compliance_score REAL NOT NULL DEFAULT 0,
        compliance_notes TEXT NOT NULL DEFAULT '[]',
        generator TEXT NOT NULL,
        selected INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    );
    CREATE TABLE scripts (
        id TEXT PRIMARY KEY,
        idea_id TEXT REFERENCES ideas(id) ON DELETE SET NULL,
        campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
        target_seconds INTEGER NOT NULL,
        text TEXT NOT NULL,
        est_seconds REAL NOT NULL,
        warnings TEXT NOT NULL DEFAULT '[]',
        generator TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE voice_profiles (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        provider TEXT NOT NULL,
        voice_id TEXT NOT NULL DEFAULT '',
        settings TEXT NOT NULL DEFAULT '{}',
        authorized INTEGER NOT NULL DEFAULT 0,
        notes TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL
    );
    CREATE TABLE narrations (
        id TEXT PRIMARY KEY,
        script_id TEXT NOT NULL REFERENCES scripts(id) ON DELETE CASCADE,
        voice_profile_id TEXT REFERENCES voice_profiles(id) ON DELETE SET NULL,
        provider TEXT NOT NULL,
        cache_key TEXT NOT NULL,
        audio_path TEXT NOT NULL,
        duration REAL NOT NULL,
        words TEXT NOT NULL DEFAULT '[]',
        alignment_method TEXT NOT NULL DEFAULT 'none',
        created_at TEXT NOT NULL
    );
    CREATE TABLE projects (
        id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
        idea_id TEXT REFERENCES ideas(id) ON DELETE SET NULL,
        script_id TEXT REFERENCES scripts(id) ON DELETE SET NULL,
        narration_id TEXT REFERENCES narrations(id) ON DELETE SET NULL,
        template_id TEXT NOT NULL DEFAULT 'roblox_story',
        title TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'DRAFT',
        media_ids TEXT NOT NULL DEFAULT '[]',
        music_id TEXT,
        timeline TEXT,
        render_path TEXT,
        qa TEXT,
        export_path TEXT,
        caption_text TEXT NOT NULL DEFAULT '',
        hashtags TEXT NOT NULL DEFAULT '[]',
        seed INTEGER NOT NULL DEFAULT 0,
        notes TEXT NOT NULL DEFAULT '',
        history TEXT NOT NULL DEFAULT '[]',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE submissions (
        id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
        project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
        platform TEXT NOT NULL,
        post_url TEXT NOT NULL DEFAULT '',
        submitted_at TEXT,
        status TEXT NOT NULL DEFAULT 'PENDING',
        views INTEGER NOT NULL DEFAULT 0,
        likes INTEGER NOT NULL DEFAULT 0,
        comments INTEGER NOT NULL DEFAULT 0,
        shares INTEGER NOT NULL DEFAULT 0,
        saves INTEGER NOT NULL DEFAULT 0,
        earnings REAL,
        approved INTEGER,
        notes TEXT NOT NULL DEFAULT '',
        metrics_source TEXT NOT NULL DEFAULT 'manual',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    """,
]

JSON_COLUMNS = {
    "platforms", "requirements", "restrictions", "content_goals", "hook_examples", "reference_links",
    "codes", "analysis", "tags", "required_gameplay", "compliance_notes", "warnings", "settings",
    "words", "media_ids", "timeline", "qa", "hashtags", "history",
}
BOOL_COLUMNS = {"has_audio", "enabled", "selected", "authorized"}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def new_id() -> str:
    return uuid.uuid4().hex[:16]


def _decode(row: sqlite3.Row) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in row.keys():  # noqa: SIM118 - iterating a sqlite3.Row yields values, not keys
        val = row[key]
        if key in JSON_COLUMNS and isinstance(val, str):
            with contextlib.suppress(json.JSONDecodeError):
                val = json.loads(val)
        elif key in BOOL_COLUMNS and val is not None:
            val = bool(val)
        out[key] = val
    return out


def _encode(key: str, val: Any) -> Any:
    if key in JSON_COLUMNS and val is not None and not isinstance(val, str):
        return json.dumps(val, ensure_ascii=False)
    if key in BOOL_COLUMNS and isinstance(val, bool):
        return int(val)
    return val


class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(str(path), check_same_thread=False, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.migrate()

    def migrate(self) -> None:
        with self._lock:
            version = self.conn.execute("PRAGMA user_version").fetchone()[0]
            for i, sql in enumerate(MIGRATIONS[version:], start=version + 1):
                self.conn.executescript(sql)
                self.conn.execute(f"PRAGMA user_version = {i}")
            self.conn.commit()

    @property
    def schema_version(self) -> int:
        return int(self.conn.execute("PRAGMA user_version").fetchone()[0])

    def close(self) -> None:
        self.conn.close()

    # ---- generic helpers -------------------------------------------------
    def insert(self, table: str, data: dict[str, Any]) -> dict[str, Any]:
        data = dict(data)
        data.setdefault("id", new_id())
        cols = self._columns(table)
        if "created_at" in cols:
            data.setdefault("created_at", now_iso())
        if "updated_at" in cols:
            data.setdefault("updated_at", data.get("created_at", now_iso()))
        data = {k: v for k, v in data.items() if k in cols}
        keys = list(data)
        with self._lock:
            self.conn.execute(
                f"INSERT INTO {table} ({', '.join(keys)}) VALUES ({', '.join('?' for _ in keys)})",
                [_encode(k, data[k]) for k in keys],
            )
            self.conn.commit()
        return self.get(table, data["id"])

    def update(self, table: str, id_: str, data: dict[str, Any]) -> dict[str, Any]:
        cols = self._columns(table)
        data = {k: v for k, v in data.items() if k in cols and k not in ("id", "created_at")}
        if "updated_at" in cols:
            data["updated_at"] = now_iso()
        if data:
            with self._lock:
                cur = self.conn.execute(
                    f"UPDATE {table} SET {', '.join(f'{k} = ?' for k in data)} WHERE id = ?",
                    [_encode(k, v) for k, v in data.items()] + [id_],
                )
                self.conn.commit()
                if cur.rowcount == 0:
                    raise NotFoundError(f"{table[:-1].capitalize()} not found.", detail=f"{table}/{id_}")
        return self.get(table, id_)

    def get(self, table: str, id_: str) -> dict[str, Any]:
        row = self.conn.execute(f"SELECT * FROM {table} WHERE id = ?", (id_,)).fetchone()
        if row is None:
            raise NotFoundError(f"{table[:-1].replace('_', ' ').capitalize()} not found.", detail=f"{table}/{id_}")
        return _decode(row)

    def find(self, table: str, id_: str) -> dict[str, Any] | None:
        row = self.conn.execute(f"SELECT * FROM {table} WHERE id = ?", (id_,)).fetchone()
        return _decode(row) if row else None

    def list(self, table: str, where: str = "", params: Iterable[Any] = (), order: str = "created_at DESC") -> list[dict[str, Any]]:
        sql = f"SELECT * FROM {table}"
        if where:
            sql += f" WHERE {where}"
        if order:
            sql += f" ORDER BY {order}"
        return [_decode(r) for r in self.conn.execute(sql, tuple(params)).fetchall()]

    def delete(self, table: str, id_: str) -> None:
        with self._lock:
            cur = self.conn.execute(f"DELETE FROM {table} WHERE id = ?", (id_,))
            self.conn.commit()
        if cur.rowcount == 0:
            raise NotFoundError(f"{table[:-1].capitalize()} not found.", detail=f"{table}/{id_}")

    def scalar(self, sql: str, params: Iterable[Any] = ()) -> Any:
        row = self.conn.execute(sql, tuple(params)).fetchone()
        return row[0] if row else None

    def get_setting(self, key: str, default: Any = None) -> Any:
        row = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_setting(self, key: str, value: Any) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, json.dumps(value)),
            )
            self.conn.commit()

    _col_cache: dict[str, set[str]] = {}

    def _columns(self, table: str) -> set[str]:
        if table not in self._col_cache:
            self._col_cache[table] = {r[1] for r in self.conn.execute(f"PRAGMA table_info({table})").fetchall()}
        return self._col_cache[table]
