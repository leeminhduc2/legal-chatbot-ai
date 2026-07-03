from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


SCHEMA_PATH = Path(__file__).with_name("sqlite_schema.sql")


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        result = super().__exit__(exc_type, exc_value, traceback)
        self.close()
        return result


def get_connection(db_path: str) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path, factory=ClosingConnection)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db(db_path: str) -> None:
    if db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    with get_connection(db_path) as connection:
        _ensure_import_batch_id(connection)
        connection.executescript(schema)
        apply_migrations(connection)
        connection.commit()


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


def apply_migrations(connection: sqlite3.Connection) -> None:
    """Keep existing local SQLite files compatible with the current schema."""
    _ensure_import_batch_id(connection)
    _ensure_document_relations(connection)


def _ensure_import_batch_id(connection: sqlite3.Connection) -> None:
    columns = _get_columns(connection, "document_versions")
    if not columns:
        return

    has_import_batch_id = "import_batch_id" in columns
    has_crawl_batch_id = "crawl_batch_id" in columns

    if not has_import_batch_id:
        connection.execute("ALTER TABLE document_versions ADD COLUMN import_batch_id TEXT")

    if has_crawl_batch_id:
        connection.execute(
            """
            UPDATE document_versions
            SET import_batch_id = COALESCE(import_batch_id, crawl_batch_id)
            WHERE crawl_batch_id IS NOT NULL
            """
        )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_document_versions_import_batch_id
        ON document_versions(import_batch_id)
        """
    )


def _ensure_document_relations(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS document_relations (
            id TEXT PRIMARY KEY,
            source_document_id TEXT NOT NULL,
            target_document_id TEXT,
            target_document_number TEXT,
            relation_type TEXT NOT NULL,
            source_text TEXT,
            import_batch_id TEXT,
            is_published INTEGER NOT NULL DEFAULT 0 CHECK (is_published IN (0, 1)),
            created_at TEXT NOT NULL,
            FOREIGN KEY (source_document_id) REFERENCES document_registry(document_id)
        );

        CREATE INDEX IF NOT EXISTS idx_document_relations_source_document_id
        ON document_relations(source_document_id);

        CREATE INDEX IF NOT EXISTS idx_document_relations_import_batch_id
        ON document_relations(import_batch_id);
        """
    )


def _get_columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row["name"] for row in rows}
