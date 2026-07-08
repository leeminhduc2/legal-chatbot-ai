from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import Config


DOCUMENT_PIPELINES = {
    "import_document",
    "publish_document",
    "rollback_indexes",
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reset document corpus state and retrieval indexes while preserving users/auth/chat.",
    )
    parser.add_argument("--confirm-reset-documents", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.confirm_reset_documents and not args.dry_run:
        parser.error("Pass --confirm-reset-documents to delete data, or --dry-run to inspect.")

    config = Config.from_env()
    db_path = Path(config.sqlite_db_path)
    if not db_path.exists():
        print(f"SQLite database not found: {db_path}")
    else:
        reset_sqlite_documents(db_path, dry_run=args.dry_run)

    reset_chroma(config, dry_run=args.dry_run)
    reset_elasticsearch(config, dry_run=args.dry_run)
    reset_neo4j(config, dry_run=args.dry_run)
    return 0


def reset_sqlite_documents(db_path: Path, dry_run: bool) -> None:
    connection = sqlite3.connect(db_path)
    try:
        connection.row_factory = sqlite3.Row
        paths = [
            Path(value)
            for row in connection.execute(
                """
                SELECT raw_docx_path, preprocessed_text_path, chunk_json_path
                FROM document_versions
                """
            )
            for value in row
            if value
        ]
        pipeline_ids = [
            row["id"]
            for row in connection.execute(
                """
                SELECT id
                FROM pipeline_runs
                WHERE pipeline_type IN ({})
                """.format(",".join("?" for _ in DOCUMENT_PIPELINES)),
                tuple(DOCUMENT_PIPELINES),
            )
        ]
        counts = {
            "document_relations": count_rows(connection, "document_relations"),
            "document_versions": count_rows(connection, "document_versions"),
            "document_registry": count_rows(connection, "document_registry"),
            "document_pipeline_runs": len(pipeline_ids),
            "artifact_paths": len(paths),
        }
        print(f"SQLite reset target: {counts}")
        if dry_run:
            return

        if pipeline_ids:
            connection.execute(
                "DELETE FROM pipeline_events WHERE pipeline_run_id IN ({})".format(
                    ",".join("?" for _ in pipeline_ids)
                ),
                tuple(pipeline_ids),
            )
            connection.execute(
                "DELETE FROM pipeline_runs WHERE id IN ({})".format(
                    ",".join("?" for _ in pipeline_ids)
                ),
                tuple(pipeline_ids),
            )
        connection.execute("DELETE FROM document_relations")
        connection.execute("DELETE FROM document_versions")
        connection.execute("DELETE FROM document_registry")
        connection.commit()
    finally:
        connection.close()

    for path in paths:
        delete_managed_artifact(path)


def reset_chroma(config: Config, dry_run: bool) -> None:
    chroma_path = Path(config.chroma_path)
    print(f"Chroma reset target: {chroma_path}")
    if dry_run or not chroma_path.exists():
        return
    shutil.rmtree(chroma_path)


def reset_elasticsearch(config: Config, dry_run: bool) -> None:
    if not config.elasticsearch_url:
        return
    print(f"Elasticsearch reset target: {config.elasticsearch_index}")
    if dry_run:
        return
    try:
        from elasticsearch import Elasticsearch
    except ImportError:
        print("Skipping Elasticsearch reset: package is not installed.")
        return
    kwargs = {"hosts": [config.elasticsearch_url], "verify_certs": config.elasticsearch_verify_certs}
    if config.elasticsearch_api_key:
        kwargs["api_key"] = config.elasticsearch_api_key
    elif config.elasticsearch_username or config.elasticsearch_password:
        kwargs["basic_auth"] = (config.elasticsearch_username, config.elasticsearch_password)
    client = Elasticsearch(**kwargs)
    if client.indices.exists(index=config.elasticsearch_index):
        client.indices.delete(index=config.elasticsearch_index)


def reset_neo4j(config: Config, dry_run: bool) -> None:
    if not config.neo4j_password:
        print("Skipping Neo4j reset: NEO4J_PASSWORD is not configured.")
        return
    print("Neo4j reset target: Document/Article/Clause nodes and document relations")
    if dry_run:
        return
    try:
        from neo4j import GraphDatabase
    except ImportError:
        print("Skipping Neo4j reset: package is not installed.")
        return
    driver = GraphDatabase.driver(
        config.neo4j_uri,
        auth=(config.neo4j_user, config.neo4j_password),
    )
    session_kwargs = {"database": config.neo4j_database} if config.neo4j_database else {}
    with driver:
        with driver.session(**session_kwargs) as session:
            session.run(
                """
                MATCH (n)
                WHERE n:Document OR n:Article OR n:Clause
                DETACH DELETE n
                """
            )


def count_rows(connection: sqlite3.Connection, table: str) -> int:
    return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def delete_managed_artifact(path: Path) -> None:
    roots = [
        (Path.cwd() / "data" / "raw").resolve(),
        (Path.cwd() / "data" / "preprocessed").resolve(),
        (Path.cwd() / "data" / "chunked").resolve(),
    ]
    resolved = path.resolve()
    if not is_relative_to_any(resolved, roots):
        print(f"Skipping unmanaged artifact path: {path}")
        return
    if resolved.is_file():
        resolved.unlink()
    cleanup_empty_parents(resolved.parent, roots)


def cleanup_empty_parents(path: Path, roots: Iterable[Path]) -> None:
    root_list = list(roots)
    current = path.resolve()
    while is_relative_to_any(current, root_list) and current not in root_list:
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


def is_relative_to_any(path: Path, roots: Iterable[Path]) -> bool:
    return any(is_relative_to(path, root) for root in roots)


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


if __name__ == "__main__":
    raise SystemExit(main())
