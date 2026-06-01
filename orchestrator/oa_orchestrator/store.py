"""Dedicated SQLite store for structured business inputs.

Separate from the LangGraph checkpointer DB on purpose: the checkpointer owns
graph state, this table owns reusable/auditable parsed Excel content keyed by
thread_id.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .schemas import BusinessInput, Profile


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(path: Path) -> None:
    with _connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS business_inputs (
                thread_id   TEXT PRIMARY KEY,
                created_at  TEXT NOT NULL,
                source_file TEXT,
                payload     TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS profiles (
                user_id    TEXT PRIMARY KEY,
                updated_at TEXT NOT NULL,
                payload    TEXT NOT NULL
            )
            """
        )
        conn.commit()


def save_business_input(path: Path, thread_id: str, business: BusinessInput,
                        source_file: Optional[str]) -> None:
    init_db(path)
    with _connect(path) as conn:
        conn.execute(
            """
            INSERT INTO business_inputs (thread_id, created_at, source_file, payload)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(thread_id) DO UPDATE SET
                created_at=excluded.created_at,
                source_file=excluded.source_file,
                payload=excluded.payload
            """,
            (
                thread_id,
                datetime.now(timezone.utc).isoformat(),
                source_file,
                business.model_dump_json(),
            ),
        )
        conn.commit()


def get_business_input(path: Path, thread_id: str) -> Optional[BusinessInput]:
    if not path.exists():
        return None
    with _connect(path) as conn:
        row = conn.execute(
            "SELECT payload FROM business_inputs WHERE thread_id = ?",
            (thread_id,),
        ).fetchone()
    if not row:
        return None
    return BusinessInput.model_validate(json.loads(row["payload"]))


def save_profile(path: Path, profile: Profile) -> None:
    init_db(path)
    with _connect(path) as conn:
        conn.execute(
            """
            INSERT INTO profiles (user_id, updated_at, payload) VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                updated_at=excluded.updated_at, payload=excluded.payload
            """,
            (profile.user_id, datetime.now(timezone.utc).isoformat(), profile.model_dump_json()),
        )
        conn.commit()


def get_profile(path: Path, user_id: str) -> Optional[Profile]:
    if not path.exists():
        return None
    with _connect(path) as conn:
        row = conn.execute(
            "SELECT payload FROM profiles WHERE user_id = ?", (user_id,)
        ).fetchone()
    if not row:
        return None
    return Profile.model_validate(json.loads(row["payload"]))
