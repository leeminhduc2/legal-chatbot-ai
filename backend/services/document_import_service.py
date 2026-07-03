from __future__ import annotations

import json
import re
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from docx import Document
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from backend.config import Config
from backend.models.database import get_connection, row_to_dict


PIPELINE_IMPORT_DOCUMENT = "import_document"
STATUS_PENDING = "pending"
STATUS_UPLOADED = "uploaded"
STATUS_PARSED = "parsed"
STATUS_CHUNKED = "chunked"
STATUS_READY_FOR_REVIEW = "ready_for_review"
STATUS_FAILED = "failed"
VALIDITY_UNKNOWN = "unknown"


class DocumentImportError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


@dataclass(frozen=True)
class ImportMetadata:
    document_number: str
    title: str
    source_url: str | None
    issued_date: str | None
    effective_date: str | None
    expiry_date: str | None
    validity_status: str
    relations: list[dict[str, Any]]
    relations_unavailable: bool


class DocumentImportService:
    def __init__(self, config: Config):
        self.config = config
        self.db_path = config.sqlite_db_path

    def import_document(
        self,
        file_storage: FileStorage | None,
        form_data: dict[str, Any],
        requested_by_user_id: str,
    ) -> dict[str, Any]:
        pipeline_run_id = str(uuid.uuid4())
        import_batch_id = str(uuid.uuid4())
        now = utc_now_iso()

        self._create_pipeline_run(
            pipeline_run_id=pipeline_run_id,
            requested_by_user_id=requested_by_user_id,
            status=STATUS_PENDING,
            input_json={
                "document_number": optional_str(form_data.get("document_number")),
                "title": optional_str(form_data.get("title")),
                "source_url": optional_str(form_data.get("source_url")),
                "issued_date": optional_str(form_data.get("issued_date")),
                "effective_date": optional_str(form_data.get("effective_date")),
                "expiry_date": optional_str(form_data.get("expiry_date")),
                "validity_status": optional_str(form_data.get("validity_status"))
                or VALIDITY_UNKNOWN,
                "import_batch_id": import_batch_id,
                "relations_json_provided": bool(
                    optional_str(form_data.get("relations_json"))
                ),
            },
            now=now,
        )

        try:
            self._validate_docx(file_storage)
            assert file_storage is not None

            raw_docx_path = self._save_raw_docx(
                file_storage=file_storage,
                import_batch_id=import_batch_id,
            )
            self._mark_pipeline(
                pipeline_run_id,
                STATUS_UPLOADED,
                "Raw DOCX uploaded.",
                {"raw_docx_path": str(raw_docx_path)},
            )

            try:
                extracted = extract_docx(raw_docx_path)
            except Exception as exc:  # pragma: no cover - exact parser errors vary.
                raise DocumentImportError(
                    "DOCX_PARSE_FAILED",
                    "Cannot parse uploaded DOCX.",
                    details={"reason": str(exc)},
                ) from exc

            text = "\n".join(extracted["paragraphs"])
            if not text.strip():
                raise DocumentImportError(
                    "DOCX_PARSE_FAILED",
                    "Uploaded DOCX does not contain extractable paragraph text.",
                )

            metadata_hints = extract_metadata_hints(
                text=text,
                tables=extracted["tables"],
                paragraphs=extracted["paragraphs"],
            )
            metadata = self._parse_metadata(
                form_data=form_data,
                metadata_hints=metadata_hints,
            )
            document_id, version = self._upsert_document_registry(metadata, now)
            preprocessed_text_path = self._write_preprocessed_text(
                document_id=document_id,
                import_batch_id=import_batch_id,
                text=text,
            )
            merged_metadata = build_normalized_metadata(
                document_id=document_id,
                version=version,
                import_batch_id=import_batch_id,
                metadata=metadata,
                metadata_hints=metadata_hints,
            )
            self._mark_pipeline(
                pipeline_run_id,
                STATUS_PARSED,
                "DOCX parsed and metadata hints extracted.",
                {
                    "preprocessed_text_path": str(preprocessed_text_path),
                    "tables_count": len(extracted["tables"]),
                    "metadata_hints": metadata_hints,
                    "resolved_document_number": metadata.document_number,
                    "resolved_title": metadata.title,
                },
            )

            warnings: list[str] = []
            chunks = self._chunk_text(
                text=text,
                document_id=document_id,
                import_batch_id=import_batch_id,
                metadata=merged_metadata,
                warnings=warnings,
            )
            validate_chunks(chunks)
            chunk_json_path = self._write_chunks(
                document_id=document_id,
                import_batch_id=import_batch_id,
                chunks=chunks,
            )

            if metadata.relations_unavailable:
                warnings.append("Document-level relations were not provided by admin.")

            self._store_version_and_relations(
                document_id=document_id,
                version=version,
                import_batch_id=import_batch_id,
                raw_docx_path=raw_docx_path,
                preprocessed_text_path=preprocessed_text_path,
                chunk_json_path=chunk_json_path,
                metadata_json={
                    **merged_metadata,
                    "metadata_hints": metadata_hints,
                    "warnings": warnings,
                    "relations_unavailable": metadata.relations_unavailable,
                },
                relations=metadata.relations,
                now=utc_now_iso(),
            )
            self._mark_pipeline(
                pipeline_run_id,
                STATUS_CHUNKED,
                "DOCX chunked into article/clause records.",
                {
                    "chunk_json_path": str(chunk_json_path),
                    "chunks_count": len(chunks),
                    "warnings": warnings,
                },
            )
            self._mark_pipeline(
                pipeline_run_id,
                STATUS_READY_FOR_REVIEW,
                "Import is ready for admin review.",
                {
                    "document_id": document_id,
                    "version": version,
                    "import_batch_id": import_batch_id,
                },
            )

            return {
                "document_id": document_id,
                "version": version,
                "import_batch_id": import_batch_id,
                "pipeline_run_id": pipeline_run_id,
                "status": STATUS_READY_FOR_REVIEW,
                "document_number": metadata.document_number,
                "title": metadata.title,
                "raw_docx_path": str(raw_docx_path),
                "preprocessed_text_path": str(preprocessed_text_path),
                "chunk_json_path": str(chunk_json_path),
                "warnings": warnings,
                "relations_unavailable": metadata.relations_unavailable,
            }
        except DocumentImportError as exc:
            self._fail_pipeline(
                pipeline_run_id,
                exc.message,
                {"code": exc.code, **exc.details},
            )
            raise
        except Exception as exc:
            self._fail_pipeline(
                pipeline_run_id,
                "Unexpected import failure.",
                {"code": "IMPORT_FAILED", "reason": str(exc)},
            )
            raise

    def list_documents(self) -> list[dict[str, Any]]:
        with get_connection(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT
                    dr.*,
                    dv.version AS latest_version,
                    dv.status AS latest_status,
                    dv.import_batch_id AS latest_import_batch_id,
                    dv.chunk_json_path AS latest_chunk_json_path
                FROM document_registry dr
                LEFT JOIN document_versions dv
                    ON dv.document_id = dr.document_id
                   AND dv.version = (
                       SELECT MAX(version)
                       FROM document_versions
                       WHERE document_id = dr.document_id
                   )
                WHERE dr.is_deleted = 0
                ORDER BY dr.updated_at DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def get_document_detail(
        self,
        document_id: str,
        chunk_preview_limit: int = 5,
    ) -> dict[str, Any] | None:
        with get_connection(self.db_path) as connection:
            registry = row_to_dict(
                connection.execute(
                    "SELECT * FROM document_registry WHERE document_id = ?",
                    (document_id,),
                ).fetchone()
            )
            if registry is None:
                return None

            version = row_to_dict(
                connection.execute(
                    """
                    SELECT *
                    FROM document_versions
                    WHERE document_id = ?
                    ORDER BY version DESC
                    LIMIT 1
                    """,
                    (document_id,),
                ).fetchone()
            )
            relations = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT *
                    FROM document_relations
                    WHERE source_document_id = ?
                    ORDER BY created_at DESC
                    """,
                    (document_id,),
                ).fetchall()
            ]
            events = []
            if version is not None:
                events = [
                    dict(row)
                    for row in connection.execute(
                        """
                        SELECT pe.*
                        FROM pipeline_events pe
                        JOIN pipeline_runs pr ON pr.id = pe.pipeline_run_id
                        WHERE json_extract(pr.input_json, '$.import_batch_id') = ?
                        ORDER BY pe.created_at ASC
                        """,
                        (version["import_batch_id"],),
                    ).fetchall()
                ]

        chunks_preview = []
        if version and version.get("chunk_json_path"):
            chunks_preview = load_chunk_preview(
                Path(version["chunk_json_path"]),
                limit=chunk_preview_limit,
            )

        return {
            "document": registry,
            "version": version,
            "relations": relations,
            "pipeline_events": events,
            "chunks_preview": chunks_preview,
        }

    def list_pipeline_runs(self) -> list[dict[str, Any]]:
        with get_connection(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM pipeline_runs
                ORDER BY created_at DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def get_pipeline_detail(self, run_id: str) -> dict[str, Any] | None:
        with get_connection(self.db_path) as connection:
            run = row_to_dict(
                connection.execute(
                    "SELECT * FROM pipeline_runs WHERE id = ?",
                    (run_id,),
                ).fetchone()
            )
            if run is None:
                return None
            events = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT *
                    FROM pipeline_events
                    WHERE pipeline_run_id = ?
                    ORDER BY created_at ASC
                    """,
                    (run_id,),
                ).fetchall()
            ]
        return {"pipeline_run": run, "events": events}

    def _parse_metadata(
        self,
        form_data: dict[str, Any],
        metadata_hints: dict[str, Any],
    ) -> ImportMetadata:
        document_number = (
            optional_str(form_data.get("document_number"))
            or optional_str(metadata_hints.get("document_number"))
            or ""
        )
        title = (
            optional_str(form_data.get("title"))
            or optional_str(metadata_hints.get("title"))
            or ""
        )
        if not document_number or not title:
            raise DocumentImportError(
                "METADATA_INCOMPLETE",
                "document_number and title are required when they cannot be extracted from DOCX.",
            )

        relations_raw = str(form_data.get("relations_json", "") or "").strip()
        relations = parse_relations_json(relations_raw)
        return ImportMetadata(
            document_number=document_number,
            title=title,
            source_url=optional_str(form_data.get("source_url")),
            issued_date=optional_str(form_data.get("issued_date")),
            effective_date=optional_str(form_data.get("effective_date")),
            expiry_date=optional_str(form_data.get("expiry_date")),
            validity_status=optional_str(form_data.get("validity_status"))
            or VALIDITY_UNKNOWN,
            relations=relations,
            relations_unavailable=not bool(relations),
        )

    def _validate_docx(self, file_storage: FileStorage | None) -> None:
        if file_storage is None or not file_storage.filename:
            raise DocumentImportError("DOCX_REQUIRED", "Uploaded .docx file is required.")

        filename = file_storage.filename.lower()
        if not filename.endswith(".docx"):
            raise DocumentImportError(
                "DOCX_REQUIRED",
                "Uploaded file must have a .docx extension.",
            )

        stream = file_storage.stream
        original_position = stream.tell()
        try:
            with zipfile.ZipFile(stream) as archive:
                names = set(archive.namelist())
                if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                    raise DocumentImportError(
                        "DOCX_REQUIRED",
                        "Uploaded file is not a valid DOCX archive.",
                    )
        except zipfile.BadZipFile as exc:
            raise DocumentImportError(
                "DOCX_REQUIRED",
                "Uploaded file is not a valid DOCX archive.",
            ) from exc
        finally:
            stream.seek(original_position)

    def _save_raw_docx(
        self,
        file_storage: FileStorage,
        import_batch_id: str,
    ) -> Path:
        raw_dir = Path("data/raw") / import_batch_id
        raw_dir.mkdir(parents=True, exist_ok=True)
        safe_filename = secure_filename(file_storage.filename or "document.docx")
        raw_docx_path = raw_dir / safe_filename
        file_storage.save(raw_docx_path)
        return raw_docx_path

    def _write_preprocessed_text(
        self,
        document_id: str,
        import_batch_id: str,
        text: str,
    ) -> Path:
        output_dir = Path("data/preprocessed") / import_batch_id
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{document_id}.txt"
        output_path.write_text(text, encoding="utf-8")
        return output_path

    def _write_chunks(
        self,
        document_id: str,
        import_batch_id: str,
        chunks: list[dict[str, Any]],
    ) -> Path:
        output_dir = Path("data/chunked") / import_batch_id
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{document_id}.json"
        output_path.write_text(
            json.dumps(chunks, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return output_path

    def _chunk_text(
        self,
        text: str,
        document_id: str,
        import_batch_id: str,
        metadata: dict[str, Any],
        warnings: list[str],
    ) -> list[dict[str, Any]]:
        if self.config.llm_chunking_enabled:
            try:
                from src.ingestion.llm_splitter import LLMVietnameseLegalSplitter

                splitter = LLMVietnameseLegalSplitter(doc_name=document_id)
                llm_chunks = splitter.split_text(text)
                chunks = normalize_llm_chunks(
                    llm_chunks=llm_chunks,
                    document_id=document_id,
                    import_batch_id=import_batch_id,
                    metadata=metadata,
                )
                if chunks:
                    return chunks
                warnings.append("LLM chunking returned no chunks; used regex fallback.")
            except Exception as exc:
                warnings.append(f"LLM chunking failed; used regex fallback: {exc}")

        warnings.append("Used deterministic regex chunking fallback.")
        return regex_chunk_text(
            text=text,
            document_id=document_id,
            import_batch_id=import_batch_id,
            metadata=metadata,
        )

    def _upsert_document_registry(
        self,
        metadata: ImportMetadata,
        now: str,
    ) -> tuple[str, int]:
        with get_connection(self.db_path) as connection:
            row = connection.execute(
                """
                SELECT document_id
                FROM document_registry
                WHERE document_number = ? AND is_deleted = 0
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (metadata.document_number,),
            ).fetchone()

            if row is None:
                document_id = str(uuid.uuid4())
                version = 1
                connection.execute(
                    """
                    INSERT INTO document_registry (
                        document_id, document_number, title, source_system,
                        source_url, issued_date, effective_date, expiry_date,
                        validity_status, raw_metadata_json, active_version,
                        is_published, is_deleted, created_at, updated_at
                    )
                    VALUES (?, ?, ?, 'admin_upload', ?, ?, ?, ?, ?, ?, NULL, 0, 0, ?, ?)
                    """,
                    (
                        document_id,
                        metadata.document_number,
                        metadata.title,
                        metadata.source_url,
                        metadata.issued_date,
                        metadata.effective_date,
                        metadata.expiry_date,
                        metadata.validity_status,
                        json.dumps(metadata.__dict__, ensure_ascii=False),
                        now,
                        now,
                    ),
                )
            else:
                document_id = row["document_id"]
                version_row = connection.execute(
                    """
                    SELECT COALESCE(MAX(version), 0) + 1 AS next_version
                    FROM document_versions
                    WHERE document_id = ?
                    """,
                    (document_id,),
                ).fetchone()
                version = int(version_row["next_version"])
                connection.execute(
                    """
                    UPDATE document_registry
                    SET title = ?,
                        source_url = ?,
                        issued_date = ?,
                        effective_date = ?,
                        expiry_date = ?,
                        validity_status = ?,
                        raw_metadata_json = ?,
                        updated_at = ?
                    WHERE document_id = ?
                    """,
                    (
                        metadata.title,
                        metadata.source_url,
                        metadata.issued_date,
                        metadata.effective_date,
                        metadata.expiry_date,
                        metadata.validity_status,
                        json.dumps(metadata.__dict__, ensure_ascii=False),
                        now,
                        document_id,
                    ),
                )
            connection.commit()

        return document_id, version

    def _store_version_and_relations(
        self,
        document_id: str,
        version: int,
        import_batch_id: str,
        raw_docx_path: Path,
        preprocessed_text_path: Path,
        chunk_json_path: Path,
        metadata_json: dict[str, Any],
        relations: list[dict[str, Any]],
        now: str,
    ) -> None:
        version_id = str(uuid.uuid4())
        with get_connection(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO document_versions (
                    id, document_id, version, import_batch_id, raw_docx_path,
                    preprocessed_text_path, chunk_json_path, metadata_json,
                    status, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    version_id,
                    document_id,
                    version,
                    import_batch_id,
                    str(raw_docx_path),
                    str(preprocessed_text_path),
                    str(chunk_json_path),
                    json.dumps(metadata_json, ensure_ascii=False),
                    STATUS_READY_FOR_REVIEW,
                    now,
                ),
            )
            for relation in relations:
                connection.execute(
                    """
                    INSERT INTO document_relations (
                        id, source_document_id, target_document_id,
                        target_document_number, relation_type, source_text,
                        import_batch_id, is_published, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        document_id,
                        optional_str(relation.get("target_document_id")),
                        optional_str(relation.get("target_document_number")),
                        str(relation.get("relation_type", "")).strip(),
                        optional_str(relation.get("source_text")),
                        import_batch_id,
                        now,
                    ),
                )
            connection.commit()

    def _create_pipeline_run(
        self,
        pipeline_run_id: str,
        requested_by_user_id: str,
        status: str,
        input_json: dict[str, Any],
        now: str,
    ) -> None:
        with get_connection(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO pipeline_runs (
                    id, pipeline_type, requested_by_user_id, input_json,
                    status, error_message, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, NULL, ?, ?)
                """,
                (
                    pipeline_run_id,
                    PIPELINE_IMPORT_DOCUMENT,
                    requested_by_user_id,
                    json.dumps(input_json, ensure_ascii=False),
                    status,
                    now,
                    now,
                ),
            )
            connection.execute(
                """
                INSERT INTO pipeline_events (
                    id, pipeline_run_id, state, message, payload_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    pipeline_run_id,
                    status,
                    "Import pipeline created.",
                    json.dumps(input_json, ensure_ascii=False),
                    now,
                ),
            )
            connection.commit()

    def _mark_pipeline(
        self,
        pipeline_run_id: str,
        status: str,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        now = utc_now_iso()
        with get_connection(self.db_path) as connection:
            connection.execute(
                """
                UPDATE pipeline_runs
                SET status = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, now, pipeline_run_id),
            )
            connection.execute(
                """
                INSERT INTO pipeline_events (
                    id, pipeline_run_id, state, message, payload_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    pipeline_run_id,
                    status,
                    message,
                    json.dumps(payload or {}, ensure_ascii=False),
                    now,
                ),
            )
            connection.commit()

    def _fail_pipeline(
        self,
        pipeline_run_id: str,
        message: str,
        payload: dict[str, Any],
    ) -> None:
        now = utc_now_iso()
        with get_connection(self.db_path) as connection:
            connection.execute(
                """
                UPDATE pipeline_runs
                SET status = ?, error_message = ?, updated_at = ?
                WHERE id = ?
                """,
                (STATUS_FAILED, message, now, pipeline_run_id),
            )
            connection.execute(
                """
                INSERT INTO pipeline_events (
                    id, pipeline_run_id, state, message, payload_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    pipeline_run_id,
                    STATUS_FAILED,
                    message,
                    json.dumps(payload, ensure_ascii=False),
                    now,
                ),
            )
            connection.commit()


def optional_str(value: Any) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def parse_relations_json(raw_value: str) -> list[dict[str, Any]]:
    if not raw_value:
        return []
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise DocumentImportError(
            "METADATA_INCOMPLETE",
            "relations_json must be valid JSON when provided.",
            details={"relations_json_error": str(exc)},
        ) from exc

    if isinstance(parsed, dict):
        parsed = parsed.get("relations", [])
    if not isinstance(parsed, list):
        raise DocumentImportError(
            "METADATA_INCOMPLETE",
            "relations_json must be a list or an object with a relations list.",
        )

    relations = []
    for item in parsed:
        if not isinstance(item, dict):
            raise DocumentImportError(
                "METADATA_INCOMPLETE",
                "Each relation must be an object.",
            )
        relation_type = str(item.get("relation_type", "")).strip()
        target_document_number = optional_str(item.get("target_document_number"))
        target_document_id = optional_str(item.get("target_document_id"))
        if not relation_type or not (target_document_number or target_document_id):
            raise DocumentImportError(
                "METADATA_INCOMPLETE",
                "Each relation needs relation_type and a target document.",
            )
        relations.append(item)
    return relations


def extract_docx(docx_path: Path) -> dict[str, Any]:
    document = Document(docx_path)
    paragraphs = [paragraph.text.strip() for paragraph in document.paragraphs]
    paragraphs = [text for text in paragraphs if text]
    tables = []
    for table_index, table in enumerate(document.tables, start=1):
        rows = []
        for row in table.rows:
            cells = []
            seen = set()
            for cell in row.cells:
                text = cell.text.strip()
                if text and text not in seen:
                    cells.append(text)
                    seen.add(text)
            if cells:
                rows.append(cells)
        tables.append({"table_index": table_index, "rows": rows})
    return {"paragraphs": paragraphs, "tables": tables}


def extract_metadata_hints(
    text: str,
    tables: list[dict[str, Any]],
    paragraphs: list[str],
) -> dict[str, Any]:
    head = "\n".join(text.splitlines()[:80])
    hints: dict[str, Any] = {}

    document_number = extract_document_number_from_first_table(tables)
    if document_number:
        hints["document_number"] = document_number
    else:
        document_number_match = re.search(
            r"(?:Số|So)\s*:\s*([^\n\r]+)",
            head,
            flags=re.IGNORECASE,
        )
        if document_number_match:
            hints["document_number"] = cleanup_document_number(
                document_number_match.group(1)
            )

    date_match = re.search(
        r"ngày\s+(\d{1,2})\s+tháng\s+(\d{1,2})\s+năm\s+(\d{4})",
        head,
        flags=re.IGNORECASE,
    )
    if date_match:
        day, month, year = date_match.groups()
        hints["issued_date"] = f"{int(year):04d}-{int(month):02d}-{int(day):02d}"

    title = extract_title_from_paragraphs(paragraphs)
    if title:
        hints["title"] = title
    else:
        for line in text.splitlines()[:30]:
            normalized = line.strip()
            if re.match(r"^(LUẬT|NGHỊ ĐỊNH|THÔNG TƯ|QUYẾT ĐỊNH)\b", normalized, re.I):
                hints["title"] = normalized
                break

    return hints


def extract_document_number_from_first_table(
    tables: list[dict[str, Any]],
) -> str | None:
    if not tables:
        return None

    first_table = tables[0]
    for row in first_table.get("rows", []):
        for cell in row:
            document_number = extract_document_number_from_text(str(cell))
            if document_number:
                return document_number

    table_text = "\n".join(
        str(cell)
        for row in first_table.get("rows", [])
        for cell in row
    )
    return extract_document_number_from_text(table_text)


def extract_document_number_from_text(value: str) -> str | None:
    patterns = [
        r"(?:Số|So)\s*[:：]\s*([^\n\r]+)",
        r"(?:Số|So)\s+([0-9][^\n\r]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if match:
            return cleanup_document_number(match.group(1))
    return None


def cleanup_document_number(value: str) -> str:
    cleaned = re.split(r"\s{2,}|\t|\|", value.strip())[0].strip()
    return cleaned.strip(" .;,")


def extract_title_from_paragraphs(paragraphs: list[str]) -> str | None:
    non_empty = [paragraph.strip() for paragraph in paragraphs if paragraph.strip()]
    if not non_empty:
        return None

    first = non_empty[0]
    if not is_standalone_document_type(first):
        return first

    title_parts = [first]
    for paragraph in non_empty[1:5]:
        if is_title_boundary(paragraph):
            break
        title_parts.append(paragraph)
        if len(title_parts) >= 3:
            break

    return " ".join(title_parts)


def is_standalone_document_type(value: str) -> bool:
    normalized = value.strip(" .:;").upper()
    return normalized in {
        "LUẬT",
        "BỘ LUẬT",
        "NGHỊ ĐỊNH",
        "THÔNG TƯ",
        "QUYẾT ĐỊNH",
        "NGHỊ QUYẾT",
    }


def is_title_boundary(value: str) -> bool:
    return bool(
        re.match(
            r"^(Căn cứ|Can cu|Điều\s+\d+|Dieu\s+\d+|Chương\b|Chuong\b)",
            value.strip(),
            flags=re.IGNORECASE,
        )
    )


def build_normalized_metadata(
    document_id: str,
    version: int,
    import_batch_id: str,
    metadata: ImportMetadata,
    metadata_hints: dict[str, Any],
) -> dict[str, Any]:
    return {
        "document_id": document_id,
        "document_number": metadata.document_number,
        "document_title": metadata.title,
        "title": metadata.title,
        "source_system": "admin_upload",
        "source_url": metadata.source_url,
        "issued_date": metadata.issued_date or metadata_hints.get("issued_date"),
        "effective_date": metadata.effective_date,
        "expiry_date": metadata.expiry_date,
        "validity_status": metadata.validity_status,
        "version": version,
        "published_version": version,
        "import_batch_id": import_batch_id,
        "is_published": False,
    }


def normalize_llm_chunks(
    llm_chunks: list[dict[str, Any]],
    document_id: str,
    import_batch_id: str,
    metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    normalized = []
    for index, chunk in enumerate(llm_chunks, start=1):
        content = str(chunk.get("content", "")).strip()
        if not content:
            continue
        raw_meta = chunk.get("metadata") or {}
        article_number = (
            optional_str(raw_meta.get("article_number"))
            or optional_str(raw_meta.get("article"))
            or str(index)
        )
        clause_number = optional_str(raw_meta.get("clause_number")) or optional_str(
            raw_meta.get("clause")
        )
        chunk_level = "clause" if clause_number else "article"
        normalized.append(
            build_chunk_record(
                content=content,
                document_id=document_id,
                import_batch_id=import_batch_id,
                metadata=metadata,
                article_number=article_number,
                clause_number=clause_number,
                chunk_level=chunk_level,
                ordinal=index,
            )
        )
    return normalized


def regex_chunk_text(
    text: str,
    document_id: str,
    import_batch_id: str,
    metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    article_matches = list(
        re.finditer(r"(?m)^\s*Điều\s+([0-9]+[a-zA-Z]?)\.?\s*(.*)$", text)
    )
    if not article_matches:
        return [
            build_chunk_record(
                content=text.strip(),
                document_id=document_id,
                import_batch_id=import_batch_id,
                metadata=metadata,
                article_number="1",
                clause_number=None,
                chunk_level="article",
                ordinal=1,
            )
        ]

    chunks: list[dict[str, Any]] = []
    for article_index, match in enumerate(article_matches, start=1):
        start = match.start()
        end = (
            article_matches[article_index].start()
            if article_index < len(article_matches)
            else len(text)
        )
        article_text = text[start:end].strip()
        article_number = match.group(1)
        clause_chunks = split_article_clauses(article_text)
        if not clause_chunks:
            chunks.append(
                build_chunk_record(
                    content=article_text,
                    document_id=document_id,
                    import_batch_id=import_batch_id,
                    metadata=metadata,
                    article_number=article_number,
                    clause_number=None,
                    chunk_level="article",
                    ordinal=len(chunks) + 1,
                )
            )
            continue
        for clause_number, clause_text in clause_chunks:
            chunks.append(
                build_chunk_record(
                    content=clause_text,
                    document_id=document_id,
                    import_batch_id=import_batch_id,
                    metadata=metadata,
                    article_number=article_number,
                    clause_number=clause_number,
                    chunk_level="clause",
                    ordinal=len(chunks) + 1,
                )
            )
    return chunks


def split_article_clauses(article_text: str) -> list[tuple[str, str]]:
    matches = list(re.finditer(r"(?m)^\s*(\d+)\.\s+", article_text))
    if len(matches) < 2:
        return []
    clauses = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(article_text)
        clauses.append((match.group(1), article_text[start:end].strip()))
    return clauses


def build_chunk_record(
    content: str,
    document_id: str,
    import_batch_id: str,
    metadata: dict[str, Any],
    article_number: str,
    clause_number: str | None,
    chunk_level: str,
    ordinal: int,
) -> dict[str, Any]:
    chunk_id = make_chunk_id(document_id, article_number, clause_number, ordinal)
    citation_label = make_citation_label(
        metadata.get("document_number"),
        article_number,
        clause_number,
    )
    hierarchy_path = (
        f"Document/{metadata.get('document_number')}/Article/{article_number}"
        + (f"/Clause/{clause_number}" if clause_number else "")
    )
    return {
        "chunk_id": chunk_id,
        "document_id": document_id,
        "import_batch_id": import_batch_id,
        "document_number": metadata.get("document_number"),
        "document_title": metadata.get("document_title"),
        "document_type": metadata.get("document_type"),
        "source_system": "admin_upload",
        "source_url": metadata.get("source_url"),
        "content": content,
        "article_number": article_number,
        "article_title": None,
        "clause_number": clause_number,
        "citation_label": citation_label,
        "hierarchy_path": hierarchy_path,
        "chunk_level": chunk_level,
        "validity_status": metadata.get("validity_status", VALIDITY_UNKNOWN),
        "effective_date": metadata.get("effective_date"),
        "expiry_date": metadata.get("expiry_date"),
        "is_published": False,
        "published_version": metadata.get("published_version"),
        "ordinal": ordinal,
    }


def make_chunk_id(
    document_id: str,
    article_number: str,
    clause_number: str | None,
    ordinal: int,
) -> str:
    raw = f"{document_id}:{article_number}:{clause_number or ''}:{ordinal}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, raw))


def make_citation_label(
    document_number: str | None,
    article_number: str,
    clause_number: str | None,
) -> str:
    label = f"{document_number or 'unknown'}, Điều {article_number}"
    if clause_number:
        label += f", khoản {clause_number}"
    return label


def validate_chunks(chunks: list[dict[str, Any]]) -> None:
    if not chunks:
        raise DocumentImportError(
            "CHUNK_VALIDATION_FAILED",
            "No valid chunks were produced from DOCX text.",
        )
    for index, chunk in enumerate(chunks, start=1):
        if not str(chunk.get("content", "")).strip():
            raise DocumentImportError(
                "CHUNK_VALIDATION_FAILED",
                f"Chunk #{index} has empty content.",
            )
        if not chunk.get("article_number"):
            raise DocumentImportError(
                "CHUNK_VALIDATION_FAILED",
                f"Chunk #{index} is missing article_number.",
            )
        if not chunk.get("hierarchy_path"):
            raise DocumentImportError(
                "CHUNK_VALIDATION_FAILED",
                f"Chunk #{index} is missing hierarchy_path.",
            )
        if chunk.get("chunk_level") == "clause" and not chunk.get("clause_number"):
            raise DocumentImportError(
                "CHUNK_VALIDATION_FAILED",
                f"Clause chunk #{index} is missing clause_number.",
            )


def load_chunk_preview(path: Path, limit: int) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        chunks = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    preview = []
    for chunk in chunks[:limit]:
        preview.append(
            {
                "chunk_id": chunk.get("chunk_id"),
                "citation_label": chunk.get("citation_label"),
                "chunk_level": chunk.get("chunk_level"),
                "content": str(chunk.get("content", ""))[:1000],
            }
        )
    return preview


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
