from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import Config


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="Inspect document registry, versions, and pipeline status by document number.",
    )
    parser.add_argument(
        "--document-number",
        required=True,
        help="Exact document number to inspect, for example 32/2004/QH11.",
    )
    parser.add_argument(
        "--like",
        action="store_true",
        help="Use a contains match instead of exact document_number match.",
    )
    parser.add_argument(
        "--db-path",
        default=None,
        help="Override SQLite DB path. Defaults to SQLITE_DB_PATH from .env/config.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON instead of a human summary.",
    )
    args = parser.parse_args()

    config = Config.from_env()
    db_path = Path(args.db_path or config.sqlite_db_path)
    if not db_path.exists():
        print(f"SQLite database not found: {db_path}", file=sys.stderr)
        return 1

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        result = inspect_document(
            connection,
            document_number=args.document_number,
            use_like=args.like,
        )
    finally:
        connection.close()

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print_human_summary(result)
    return 0 if result["documents"] else 2


def inspect_document(
    connection: sqlite3.Connection,
    *,
    document_number: str,
    use_like: bool,
) -> dict[str, Any]:
    if use_like:
        rows = connection.execute(
            """
            SELECT *
            FROM document_registry
            WHERE document_number LIKE ?
            ORDER BY updated_at DESC
            """,
            (f"%{document_number}%",),
        ).fetchall()
    else:
        rows = connection.execute(
            """
            SELECT *
            FROM document_registry
            WHERE document_number = ?
            ORDER BY updated_at DESC
            """,
            (document_number,),
        ).fetchall()

    documents = []
    for row in rows:
        document = dict(row)
        versions = fetch_versions(connection, document["document_id"])
        batch_ids = sorted(
            {
                version["import_batch_id"]
                for version in versions
                if version.get("import_batch_id")
            }
        )
        document["versions"] = versions
        document["pipeline_runs"] = fetch_pipeline_runs(connection, document["document_id"], batch_ids)
        document["pipeline_events"] = fetch_pipeline_events(connection, batch_ids)
        documents.append(document)

    return {
        "query": {
            "document_number": document_number,
            "match": "like" if use_like else "exact",
        },
        "documents": documents,
    }


def fetch_versions(connection: sqlite3.Connection, document_id: str) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT *
        FROM document_versions
        WHERE document_id = ?
        ORDER BY version DESC, created_at DESC
        """,
        (document_id,),
    ).fetchall()
    versions = []
    for row in rows:
        version = dict(row)
        version["metadata_json"] = parse_json(version.get("metadata_json"))
        version["chunk_count"] = count_chunks(version.get("chunk_json_path"))
        version["artifact_exists"] = {
            "raw_docx_path": path_exists(version.get("raw_docx_path")),
            "preprocessed_text_path": path_exists(version.get("preprocessed_text_path")),
            "chunk_json_path": path_exists(version.get("chunk_json_path")),
        }
        versions.append(version)
    return versions


def fetch_pipeline_runs(
    connection: sqlite3.Connection,
    document_id: str,
    batch_ids: list[str],
) -> list[dict[str, Any]]:
    filters = ["json_extract(input_json, '$.document_id') = ?"]
    params: list[Any] = [document_id]
    if batch_ids:
        filters.append(
            "json_extract(input_json, '$.import_batch_id') IN ({})".format(
                ",".join("?" for _ in batch_ids)
            )
        )
        params.extend(batch_ids)
    rows = connection.execute(
        f"""
        SELECT *
        FROM pipeline_runs
        WHERE {" OR ".join(filters)}
        ORDER BY created_at ASC
        """,
        params,
    ).fetchall()
    runs = []
    for row in rows:
        run = dict(row)
        run["input_json"] = parse_json(run.get("input_json"))
        runs.append(run)
    return runs


def fetch_pipeline_events(
    connection: sqlite3.Connection,
    batch_ids: list[str],
) -> list[dict[str, Any]]:
    if not batch_ids:
        return []
    rows = connection.execute(
        """
        SELECT
            pr.pipeline_type,
            pr.status AS run_status,
            pe.pipeline_run_id,
            pe.state,
            pe.message,
            pe.payload_json,
            pe.created_at
        FROM pipeline_runs pr
        JOIN pipeline_events pe ON pe.pipeline_run_id = pr.id
        WHERE json_extract(pr.input_json, '$.import_batch_id') IN ({})
        ORDER BY pe.created_at ASC
        """.format(",".join("?" for _ in batch_ids)),
        batch_ids,
    ).fetchall()
    events = []
    for row in rows:
        event = dict(row)
        event["payload_json"] = parse_json(event.get("payload_json"))
        events.append(event)
    return events


def print_human_summary(result: dict[str, Any]) -> None:
    query = result["query"]
    documents = result["documents"]
    print(f"Query: document_number {query['match']} {query['document_number']}")
    print(f"Matches: {len(documents)}")
    if not documents:
        return

    for document in documents:
        print("")
        print(f"Document: {document.get('title') or '-'}")
        print(f"  document_id: {document.get('document_id')}")
        print(f"  document_number: {document.get('document_number') or '-'}")
        print(f"  registry_status: is_published={document.get('is_published')} active_version={document.get('active_version')}")
        print(f"  validity_status: {document.get('validity_status') or '-'}")
        print("")
        print("Versions:")
        for version in document["versions"]:
            print(
                "  "
                f"v{version.get('version')} status={version.get('status')} "
                f"batch={version.get('import_batch_id')} chunks={version.get('chunk_count')}"
            )
            print(f"    raw: {version.get('raw_docx_path')} exists={version['artifact_exists']['raw_docx_path']}")
            print(f"    chunks: {version.get('chunk_json_path')} exists={version['artifact_exists']['chunk_json_path']}")
            blockers = version["metadata_json"].get("needs_review_fields") or []
            last_error = version["metadata_json"].get("last_publish_error")
            if blockers:
                print(f"    needs_review_fields: {', '.join(str(item) for item in blockers)}")
            if last_error:
                print(f"    last_publish_error: {json.dumps(last_error, ensure_ascii=False)}")

        print("")
        print("Pipeline runs:")
        for run in document["pipeline_runs"]:
            print(
                "  "
                f"{run.get('pipeline_type')} status={run.get('status')} "
                f"run_id={run.get('id')} updated={run.get('updated_at')}"
            )
            if run.get("error_message"):
                print(f"    error: {run.get('error_message')}")

        print("")
        print("Pipeline events:")
        if not document["pipeline_events"]:
            print("  -")
        for event in document["pipeline_events"]:
            payload = event.get("payload_json") or {}
            extra = ""
            if payload.get("chunks_count") is not None:
                extra = f" chunks={payload['chunks_count']}"
            if payload.get("provider"):
                extra += f" provider={payload['provider']}"
            print(
                "  "
                f"{event.get('created_at')} "
                f"{event.get('pipeline_type')}:{event.get('state')} "
                f"{event.get('message') or ''}{extra}"
            )


def parse_json(raw_value: Any) -> dict[str, Any]:
    if not raw_value:
        return {}
    if isinstance(raw_value, dict):
        return raw_value
    try:
        parsed = json.loads(str(raw_value))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def count_chunks(path_value: str | None) -> int:
    if not path_value:
        return 0
    path = Path(path_value)
    if not path.exists():
        return 0
    try:
        chunks = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    return len(chunks) if isinstance(chunks, list) else 0


def path_exists(path_value: str | None) -> bool:
    return bool(path_value) and Path(path_value).exists()


if __name__ == "__main__":
    raise SystemExit(main())
