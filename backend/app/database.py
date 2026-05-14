from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


DEFAULT_DB_PATH = Path(__file__).resolve().parents[1] / "data" / "inventory_health.db"


def connect(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            data_quality TEXT,
            overview TEXT,
            details TEXT,
            error TEXT
        )
        """
    )
    conn.commit()


def save_job(
    conn: sqlite3.Connection,
    *,
    job_id: str,
    filename: str,
    status: str,
    created_at: str,
    data_quality: dict[str, Any] | None = None,
    overview: dict[str, Any] | None = None,
    details: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO jobs (id, filename, status, created_at, data_quality, overview, details, error)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job_id,
            filename,
            status,
            created_at,
            _dump(data_quality),
            _dump(overview),
            _dump(details),
            _dump(error),
        ),
    )
    conn.commit()


def get_job(conn: sqlite3.Connection, job_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "filename": row["filename"],
        "status": row["status"],
        "created_at": row["created_at"],
        "data_quality": _load(row["data_quality"]),
        "overview": _load(row["overview"]),
        "details": _load(row["details"]),
        "error": _load(row["error"]),
    }


def _dump(value: dict[str, Any] | None) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def _load(value: str | None) -> dict[str, Any] | None:
    if not value:
        return None
    return json.loads(value)
