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
        _ensure_user_roles(connection)
        _ensure_import_batch_id(connection)
        _ensure_document_field_id(connection)
        connection.executescript(schema)
        apply_migrations(connection)
        connection.commit()


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


def apply_migrations(connection: sqlite3.Connection) -> None:
    """Keep existing local SQLite files compatible with the current schema."""
    _ensure_user_roles(connection)
    _ensure_user_field_permissions(connection)
    _ensure_document_field_id(connection)
    _ensure_import_batch_id(connection)
    _ensure_document_relations(connection)
    _ensure_chat_history(connection)
    _ensure_contract_review_jobs(connection)


def _ensure_user_roles(connection: sqlite3.Connection) -> None:
    row = connection.execute(
        """
        SELECT sql
        FROM sqlite_master
        WHERE type = 'table' AND name = 'users'
        """
    ).fetchone()
    if row is None:
        return

    table_sql = row["sql"] or ""
    roles_to_remove = ("free_user", "guest")
    _delete_users_by_role(connection, roles_to_remove)

    if "free_user" not in table_sql and "guest" not in table_sql:
        return

    connection.commit()
    connection.execute("PRAGMA foreign_keys = OFF")
    connection.executescript(
        """
        CREATE TABLE users_new (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('admin', 'business_user')),
            is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        INSERT INTO users_new (
            id, username, password_hash, role, is_active, created_at, updated_at
        )
        SELECT id, username, password_hash, role, is_active, created_at, updated_at
        FROM users
        WHERE role IN ('admin', 'business_user');

        DROP TABLE users;
        ALTER TABLE users_new RENAME TO users;
        """
    )
    connection.execute("PRAGMA foreign_keys = ON")


def _delete_users_by_role(
    connection: sqlite3.Connection,
    roles: tuple[str, ...],
) -> None:
    placeholders = ", ".join("?" for _ in roles)
    rows = connection.execute(
        f"SELECT id FROM users WHERE role IN ({placeholders})",
        roles,
    ).fetchall()
    user_ids = [row["id"] for row in rows]
    if not user_ids:
        return

    id_placeholders = ", ".join("?" for _ in user_ids)
    if _table_exists(connection, "auth_sessions"):
        connection.execute(
            f"DELETE FROM auth_sessions WHERE user_id IN ({id_placeholders})",
            user_ids,
        )
    if _table_exists(connection, "chat_conversations"):
        if _table_exists(connection, "chat_messages"):
            conversation_rows = connection.execute(
                f"SELECT id FROM chat_conversations WHERE user_id IN ({id_placeholders})",
                user_ids,
            ).fetchall()
            conversation_ids = [row["id"] for row in conversation_rows]
            if conversation_ids:
                conversation_placeholders = ", ".join("?" for _ in conversation_ids)
                connection.execute(
                    f"DELETE FROM chat_messages WHERE conversation_id IN ({conversation_placeholders})",
                    conversation_ids,
                )
        connection.execute(
            f"DELETE FROM chat_conversations WHERE user_id IN ({id_placeholders})",
            user_ids,
        )
    if _table_exists(connection, "contract_review_jobs"):
        connection.execute(
            f"DELETE FROM contract_review_jobs WHERE user_id IN ({id_placeholders})",
            user_ids,
        )
    connection.execute(
        f"DELETE FROM users WHERE id IN ({id_placeholders})",
        user_ids,
    )


def _ensure_user_field_permissions(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS user_field_permissions (
            user_id TEXT NOT NULL,
            field_id INTEGER NOT NULL CHECK (field_id >= 0),
            created_at TEXT NOT NULL,
            PRIMARY KEY (user_id, field_id),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_user_field_permissions_user_id
        ON user_field_permissions(user_id);
        """
    )


def _ensure_document_field_id(connection: sqlite3.Connection) -> None:
    columns = _get_columns(connection, "document_registry")
    if not columns:
        return
    if "field_id" not in columns:
        connection.execute(
            "ALTER TABLE document_registry ADD COLUMN field_id INTEGER CHECK (field_id IS NULL OR field_id >= 0)"
        )
    connection.execute(
        """
        UPDATE document_registry
        SET field_id = 0
        WHERE field_id IS NULL
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_document_registry_field_id
        ON document_registry(field_id)
        """
    )


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


def _ensure_chat_history(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS chat_conversations (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            title TEXT,
            summary TEXT,
            summary_updated_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE INDEX IF NOT EXISTS idx_chat_conversations_user_id
        ON chat_conversations(user_id);

        CREATE TABLE IF NOT EXISTS chat_messages (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
            content TEXT NOT NULL,
            citations_json TEXT,
            confidence REAL,
            metadata_json TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (conversation_id) REFERENCES chat_conversations(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_chat_messages_conversation_id
        ON chat_messages(conversation_id);
        """
    )
    columns = _get_columns(connection, "chat_messages")
    if columns and "metadata_json" not in columns:
        connection.execute("ALTER TABLE chat_messages ADD COLUMN metadata_json TEXT")
    conversation_columns = _get_columns(connection, "chat_conversations")
    if conversation_columns and "summary" not in conversation_columns:
        connection.execute("ALTER TABLE chat_conversations ADD COLUMN summary TEXT")
    if conversation_columns and "summary_updated_at" not in conversation_columns:
        connection.execute(
            "ALTER TABLE chat_conversations ADD COLUMN summary_updated_at TEXT"
        )


def _ensure_contract_review_jobs(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS contract_review_jobs (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            file_name TEXT NOT NULL,
            file_path TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'completed', 'failed')),
            document_kind TEXT,
            result_json TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            completed_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE INDEX IF NOT EXISTS idx_contract_review_jobs_user_id
        ON contract_review_jobs(user_id);

        CREATE INDEX IF NOT EXISTS idx_contract_review_jobs_status
        ON contract_review_jobs(status);
        """
    )
    columns = _get_columns(connection, "contract_review_jobs")
    if columns and "document_kind" not in columns:
        connection.execute("ALTER TABLE contract_review_jobs ADD COLUMN document_kind TEXT")
    if columns and "result_json" not in columns:
        connection.execute("ALTER TABLE contract_review_jobs ADD COLUMN result_json TEXT")
    if columns and "error_message" not in columns:
        connection.execute("ALTER TABLE contract_review_jobs ADD COLUMN error_message TEXT")
    if columns and "completed_at" not in columns:
        connection.execute("ALTER TABLE contract_review_jobs ADD COLUMN completed_at TEXT")


def _get_columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row["name"] for row in rows}


def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    row = connection.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table' AND name = ?
        """,
        (table_name,),
    ).fetchone()
    return row is not None
