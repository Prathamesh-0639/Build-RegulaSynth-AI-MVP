import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


DATABASE_PATH = Path(
    os.getenv("REGULASYNTH_DB", Path(__file__).resolve().parents[1] / "data" / "regulasynth.db")
)


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def initialize_database() -> None:
    with _connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS cases (
                case_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                status TEXT NOT NULL,
                analysis_mode TEXT,
                created_at TEXT NOT NULL,
                error TEXT
            );
            CREATE TABLE IF NOT EXISTS documents (
                doc_id TEXT PRIMARY KEY,
                case_id TEXT NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
                kind TEXT NOT NULL CHECK(kind IN ('regulation', 'policy')),
                name TEXT NOT NULL,
                page_count INTEGER NOT NULL,
                text TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS findings (
                finding_id TEXT PRIMARY KEY,
                case_id TEXT NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
                requirement TEXT NOT NULL,
                regulation_page INTEGER NOT NULL,
                status TEXT NOT NULL,
                similarity REAL NOT NULL,
                regulation_evidence TEXT NOT NULL,
                policy_evidence TEXT NOT NULL,
                action TEXT NOT NULL,
                rationale TEXT NOT NULL,
                decision TEXT NOT NULL DEFAULT 'pending',
                review_note TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS audits (
                audit_id TEXT PRIMARY KEY,
                case_id TEXT NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
                finding_id TEXT NOT NULL REFERENCES findings(finding_id) ON DELETE CASCADE,
                decision TEXT NOT NULL,
                note TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )


def execute(sql: str, values: tuple[Any, ...] = ()) -> None:
    with _connect() as connection:
        connection.execute(sql, values)


def execute_many(sql: str, rows: list[tuple[Any, ...]]) -> None:
    with _connect() as connection:
        connection.executemany(sql, rows)


def fetch_one(sql: str, values: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute(sql, values).fetchone()
    return dict(row) if row else None


def fetch_all(sql: str, values: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(sql, values).fetchall()
    return [dict(row) for row in rows]
