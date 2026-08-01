"""
SQLite connection handling and schema bootstrap for the Personal AI Agent.

Design notes:
- Single connection helper (get_connection) — no pooling yet. We're
  single-threaded until the Job Queue (M10) introduces concurrency, at
  which point this will be revisited (likely thread-local connections).
- init_db() is idempotent: safe to call on every app startup.
- execution_history is the audit table required by Section 2 ("full audit
  trail: every tool call, success or failure, logged automatically inside
  call_tool"). It's created here, in M1, so it exists before the tool
  registry (M1-S4) and call_tool pipeline (M2) need to write to it.
- run_id is nullable and unused until M10 (Job Queue) / M13 (Workflow
  Templates), which will group multiple execution_history rows under one
  logical run — included now to avoid a schema migration later.
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from loguru import logger

from app.core.config import settings
from app.core.exceptions import DatabaseError


def get_connection() -> sqlite3.Connection:
    """
    Open a new SQLite connection to the configured db_path.

    Caller is responsible for closing it (prefer the connection()
    context manager below for automatic cleanup + commit/rollback).
    """
    try:
        db_path: Path = settings.db_path_resolved
        db_path.parent.mkdir(parents=True, exist_ok=True)  # safety net; data/ should already exist
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row  # access columns by name, e.g. row["tool_name"]
        conn.execute("PRAGMA foreign_keys = ON")
        return conn
    except sqlite3.Error as e:
        logger.error(f"Failed to open SQLite connection at {settings.db_path_resolved}: {e}")
        raise DatabaseError(f"Could not open database connection: {e}") from e


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    """
    Context-managed connection: commits on success, rolls back and
    re-raises (wrapped) on failure, always closes the connection.

    Usage:
        with connection() as conn:
            conn.execute("INSERT INTO ...", (...))
    """
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except sqlite3.Error as e:
        conn.rollback()
        logger.error(f"Database operation failed, rolled back: {e}")
        raise DatabaseError(f"Database operation failed: {e}") from e
    finally:
        conn.close()


def init_db() -> None:
    """
    Create all foundational tables if they don't already exist.
    Safe to call on every startup (idempotent).

    Tables created here:
      - execution_history: audit log for every tool call (Section 2 requirement)

    Later milestones add their own tables via their own init functions
    (e.g. init_knowledge_base() in M4), each following this same
    CREATE TABLE IF NOT EXISTS pattern, all called together from a single
    startup routine once more than one exists.
    """
    with connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS execution_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT,                       -- nullable; groups steps under one logical run (M10/M13)
                tool_name TEXT NOT NULL,
                input_json TEXT,                   -- tool input args, serialized as JSON
                output_json TEXT,                  -- tool result, serialized as JSON
                success INTEGER NOT NULL,          -- 0 or 1
                error_message TEXT,                -- populated only on failure
                duration_ms INTEGER,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_execution_history_tool_name ON execution_history(tool_name)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_execution_history_run_id ON execution_history(run_id)"
        )

    logger.info("Database initialized - execution_history table ready")