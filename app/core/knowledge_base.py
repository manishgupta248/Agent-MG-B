"""
Central Knowledge Base (Section 4, item 1): SQLite-backed store for
notes, contacts, preferences, and long-term memory.

Design notes:
- One flexible knowledge_items table, not one table per content type.
  content_type discriminates between note/contact/preference/memory;
  metadata_json carries type-specific structured extras (e.g. a
  contact's phone number) without needing a separate table per type.
- embedding + embedding_model columns are nullable and UNUSED for now -
  included from day one so a future semantic-search milestone can
  populate them without a schema migration. embedding is stored as
  JSON-serialized float array text since SQLite has no native vector
  type. embedding_model records which model produced a given embedding,
  since swapping embedding models later must not silently mix
  incompatible vectors in the same column without a way to tell them
  apart.
- created_at/updated_at let downstream consumers (e.g. a future
  "user no longer works at X"-style correction flow) reason about
  when something was learned or last confirmed true, not just what.
"""

import json
from typing import Optional

from loguru import logger

from app.core.database import connection
from app.core.exceptions import DatabaseError, ValidationError

VALID_CONTENT_TYPES = {"note", "contact", "preference", "memory"}


def init_knowledge_base() -> None:
    """
    Creates the knowledge_items table if it doesn't exist. Idempotent,
    same pattern as init_db() in app.core.database. Called alongside
    init_db() from the main boot sequence (main.py gets updated in
    M4-S2 to call this too).
    """
    with connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content_type TEXT NOT NULL,        -- note | contact | preference | memory
                content TEXT NOT NULL,             -- the actual text content
                metadata_json TEXT,                -- type-specific structured extras, nullable
                embedding TEXT,                    -- nullable; JSON float array, populated by a later milestone
                embedding_model TEXT,               -- nullable; which model produced `embedding`, if set
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_knowledge_items_content_type ON knowledge_items(content_type)"
        )

    logger.info("Knowledge base initialized - knowledge_items table ready")


def _validate_content_type(content_type: str) -> None:
    if content_type not in VALID_CONTENT_TYPES:
        raise ValidationError(
            f"Invalid content_type '{content_type}' - must be one of {VALID_CONTENT_TYPES}"
        )


def add_knowledge_item(
    content_type: str,
    content: str,
    metadata: Optional[dict] = None,
) -> int:
    """
    Insert a new knowledge item. Returns the new row's id.
    embedding/embedding_model are intentionally not parameters here -
    nothing populates them yet; that's a later milestone's job, and
    this function's signature shouldn't imply otherwise.
    """
    _validate_content_type(content_type)

    try:
        with connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO knowledge_items (content_type, content, metadata_json)
                VALUES (?, ?, ?)
                """,
                (content_type, content, json.dumps(metadata) if metadata else None),
            )
            return cursor.lastrowid
    except DatabaseError:
        logger.error(f"Failed to add knowledge item (content_type={content_type})")
        raise


def get_knowledge_item(item_id: int) -> Optional[dict]:
    """Fetch a single knowledge item by id. Returns None if not found."""
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM knowledge_items WHERE id = ?", (item_id,)
        ).fetchone()
        if row is None:
            return None
        return _row_to_dict(row)


def list_knowledge_items(content_type: Optional[str] = None) -> list[dict]:
    """
    List knowledge items, optionally filtered by content_type.
    No pagination yet - fine at current scale (single-user, local);
    revisit if this table grows large enough to matter.
    """
    if content_type is not None:
        _validate_content_type(content_type)

    with connection() as conn:
        if content_type:
            rows = conn.execute(
                "SELECT * FROM knowledge_items WHERE content_type = ? ORDER BY updated_at DESC",
                (content_type,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM knowledge_items ORDER BY updated_at DESC"
            ).fetchall()

    return [_row_to_dict(row) for row in rows]


def update_knowledge_item(
    item_id: int,
    content: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> bool:
    """
    Update content and/or metadata of an existing item; always bumps
    updated_at. Returns True if a row was actually updated, False if
    item_id didn't exist.
    """
    existing = get_knowledge_item(item_id)
    if existing is None:
        return False

    new_content = content if content is not None else existing["content"]
    new_metadata = metadata if metadata is not None else existing["metadata"]

    with connection() as conn:
        conn.execute(
            """
            UPDATE knowledge_items
            SET content = ?, metadata_json = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (new_content, json.dumps(new_metadata) if new_metadata else None, item_id),
        )
    return True


def delete_knowledge_item(item_id: int) -> bool:
    """Delete a knowledge item. Returns True if a row was deleted, False if item_id didn't exist."""
    with connection() as conn:
        cursor = conn.execute("DELETE FROM knowledge_items WHERE id = ?", (item_id,))
        return cursor.rowcount > 0


def _row_to_dict(row) -> dict:
    """Converts a sqlite3.Row into a plain dict, deserializing metadata_json back into a dict."""
    return {
        "id": row["id"],
        "content_type": row["content_type"],
        "content": row["content"],
        "metadata": json.loads(row["metadata_json"]) if row["metadata_json"] else None,
        "embedding": row["embedding"],  # left as raw text/None; no consumer deserializes this yet
        "embedding_model": row["embedding_model"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }