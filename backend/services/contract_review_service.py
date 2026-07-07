from __future__ import annotations

import json
import logging
import re
import time
import unicodedata
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from backend.config import Config
from backend.models.database import get_connection
from backend.services.auth_service import AuthService, ROLE_ADMIN
from backend.services.chat_agent_service import (
    AccessScope,
    ChromaVectorRetriever,
    DocumentStatusRepository,
    ElasticsearchBM25Retriever,
    FixedNeo4jContextRetriever,
    INACTIVE_STATUSES,
    RetrieverUnavailable,
    access_scope_for_user,
    append_warning,
    citation_from_status_record,
    filter_hits_for_access,
    fuse_hits,
    graph_enrich_with_scope,
    is_active_status,
    is_unknown_status,
    normalize_validity_status,
    unique_citations,
)
from backend.services.document_import_service import VALIDITY_UNKNOWN, extract_docx


logger = logging.getLogger(__name__)

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

DOCUMENT_KIND_CONTRACT = "contract"
DOCUMENT_KIND_LEGAL_DOCUMENT = "legal_document"
DOCUMENT_KIND_UNKNOWN = "unknown"

MODULE_AUTHORITY = "authority"
MODULE_EFFECTIVITY = "effectivity"
DEFAULT_ENABLED_MODULES = [MODULE_AUTHORITY, MODULE_EFFECTIVITY]

SEVERITY_HIGH = "high"
SEVERITY_MEDIUM = "medium"
SEVERITY_LOW = "low"
SEVERITY_INFO = "info"

RESULT_VALID = "valid"
RESULT_INVALID = "invalid"
RESULT_INSUFFICIENT = "insufficient_data"
RESULT_NOT_APPLICABLE = "not_applicable"

_REVIEW_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="contract-review")


class ContractReviewError(Exception):
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


class ContractReviewAgentService:
    def __init__(
        self,
        config: Config,
        *,
        status_repository: DocumentStatusRepository | None = None,
        vector_retriever: Any | None = None,
        bm25_retriever: Any | None = None,
        graph_retriever: Any | None = None,
        run_synchronously: bool = False,
    ):
        self.config = config
        self.status_repository = status_repository or DocumentStatusRepository(
            config.sqlite_db_path
        )
        self.vector_retriever = vector_retriever or ChromaVectorRetriever(config)
        self.bm25_retriever = bm25_retriever or ElasticsearchBM25Retriever(config)
        self.graph_retriever = graph_retriever or FixedNeo4jContextRetriever(config)
        self.run_synchronously = run_synchronously

    def enqueue_review(
        self,
        file_storage: FileStorage | None,
        *,
        user_id: str,
    ) -> dict[str, Any]:
        filename = self._validate_file_name(file_storage)
        job_id = str(uuid.uuid4())
        file_path = self._save_upload(file_storage, filename, job_id)
        try:
            validate_docx_signature(file_path)
        except ContractReviewError:
            try:
                file_path.unlink(missing_ok=True)
            except OSError:
                logger.warning("Could not remove invalid contract upload: %s", file_path)
            raise

        now = utc_now_iso()
        with get_connection(self.config.sqlite_db_path) as connection:
            connection.execute(
                """
                INSERT INTO contract_review_jobs (
                    id, user_id, file_name, file_path, status,
                    document_kind, result_json, error_message,
                    created_at, updated_at, completed_at
                )
                VALUES (?, ?, ?, ?, ?, NULL, NULL, NULL, ?, ?, NULL)
                """,
                (
                    job_id,
                    user_id,
                    filename,
                    str(file_path),
                    STATUS_QUEUED,
                    now,
                    now,
                ),
            )
            connection.commit()

        if self.run_synchronously:
            self.run_review_job(job_id)
        else:
            _REVIEW_EXECUTOR.submit(self.run_review_job, job_id)
        return self.get_job(job_id, requester_user_id=user_id, requester_role=ROLE_ADMIN) or {}

    def get_job(
        self,
        job_id: str,
        *,
        requester_user_id: str,
        requester_role: str,
    ) -> dict[str, Any] | None:
        with get_connection(self.config.sqlite_db_path) as connection:
            row = connection.execute(
                """
                SELECT *
                FROM contract_review_jobs
                WHERE id = ?
                """,
                (job_id,),
            ).fetchone()
        if row is None:
            return None
        job = dict(row)
        if requester_role != ROLE_ADMIN and job["user_id"] != requester_user_id:
            raise ContractReviewError("FORBIDDEN", "Cannot access this review job.", 403)
        return format_job(job)

    def run_review_job(self, job_id: str) -> None:
        job = self._get_raw_job(job_id)
        if job is None:
            logger.warning("Contract review job not found: %s", job_id)
            return

        self._mark_job(job_id, STATUS_RUNNING)
        try:
            report = self._build_report(job)
            self._complete_job(
                job_id=job_id,
                document_kind=report["document"]["kind"],
                result=report,
            )
        except Exception as exc:
            logger.exception("Contract review failed job_id=%s", job_id)
            message = exc.message if isinstance(exc, ContractReviewError) else str(exc)
            self._fail_job(job_id, message or type(exc).__name__)

    def _build_report(self, job: dict[str, Any]) -> dict[str, Any]:
        state: dict[str, Any] = {
            "job": job,
            "access_scope": self._access_scope_for_job(job),
            "tool_trace": [],
            "warnings": [],
            "citations": [],
            "modules": [],
            "section_reviews": [],
        }
        for node in (
            self._parse_docx,
            self._classify_document,
            self._extract_fields,
            self._run_enabled_modules,
            self._synthesize_report,
        ):
            state.update(node(state))
        return state["report"]

    def _parse_docx(self, state: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        path = Path(state["job"]["file_path"])
        extracted = extract_docx(path)
        paragraphs = [str(item).strip() for item in extracted.get("paragraphs", []) if str(item).strip()]
        tables = extracted.get("tables", [])
        table_lines = table_rows_to_lines(tables)
        text = "\n".join([*paragraphs, *table_lines]).strip()
        sections = build_review_sections(paragraphs, table_lines)
        record_tool_trace(
            state,
            "docx_parse",
            "parse",
            path.name,
            len(sections),
            started,
            "ok",
            [],
        )
        warnings = state.get("warnings", [])
        if not text:
            warnings = append_warning(
                warnings,
                "EMPTY_DOCX",
                "The uploaded DOCX did not contain extractable text.",
            )
        return {
            "paragraphs": paragraphs,
            "tables": tables,
            "table_lines": table_lines,
            "text": text,
            "sections": sections,
            "warnings": warnings,
        }

    def _classify_document(self, state: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        kind = detect_document_kind(state.get("text", ""))
        record_tool_trace(
            state,
            "document_classifier",
            "classification",
            kind,
            1,
            started,
            "ok",
            [],
        )
        return {"document_kind": kind}

    def _extract_fields(self, state: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        text = state.get("text", "")
        sections = state.get("sections", [])
        fields = {
            "parties": extract_parties(text),
            "signature_blocks": extract_signature_blocks(text),
            "authorization_mentions": extract_matching_lines(
                text,
                ("uy quyen", "dai dien", "nguoi dai dien", "chuc vu", "signer", "representative"),
            ),
            "issuing_body": extract_issuing_body(text, state.get("tables", [])),
            "signer_title": extract_signer_title(text, state.get("tables", [])),
            "referenced_documents": extract_referenced_documents(text, sections),
            "legal_citations": extract_legal_citations(text, sections),
            "effectivity_mentions": extract_matching_lines(
                text,
                ("hieu luc", "het hieu luc", "thay the", "bai bo", "sua doi", "bo sung", "expiry"),
            ),
        }
        record_tool_trace(
            state,
            "field_extractor",
            "extraction",
            state.get("document_kind", DOCUMENT_KIND_UNKNOWN),
            sum(len(value) if isinstance(value, list) else int(bool(value)) for value in fields.values()),
            started,
            "ok",
            [],
        )
        return {"fields": fields}

    def _run_enabled_modules(self, state: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        enabled_modules, module_warnings = load_enabled_modules(
            Path(self.config.contract_review_modules_path)
        )
        warnings = state.get("warnings", [])
        for item in module_warnings:
            warnings = append_warning(warnings, item["code"], item["message"])

        modules = []
        if MODULE_AUTHORITY in enabled_modules:
            modules.append(self._run_authority_module(state))
        if MODULE_EFFECTIVITY in enabled_modules:
            modules.append(self._run_effectivity_module(state))

        record_tool_trace(
            state,
            "module_registry",
            "modules",
            ",".join(enabled_modules),
            len(modules),
            started,
            "ok",
            [item["code"] for item in module_warnings],
        )
        return {"modules": modules, "warnings": warnings}

    def _run_authority_module(self, state: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        kind = state.get("document_kind", DOCUMENT_KIND_UNKNOWN)
        fields = state.get("fields", {})
        rules, rules_warning = load_json_rules("authority_rules.json", self.config)
        findings = []
        citations: list[dict[str, Any]] = []

        if kind == DOCUMENT_KIND_CONTRACT:
            parties = fields.get("parties", [])
            signatures = fields.get("signature_blocks", [])
            auth_mentions = fields.get("authorization_mentions", [])
            section_id = section_for_first_evidence(parties, signatures, auth_mentions)

            if not parties:
                findings.append(
                    make_finding(
                        MODULE_AUTHORITY,
                        "contract_parties",
                        section_id,
                        RESULT_INSUFFICIENT,
                        SEVERITY_MEDIUM,
                        "Could not identify contract parties from the uploaded file.",
                        "Add clearly labelled Party A/Party B or contracting party information.",
                    )
                )
            elif rules_warning:
                findings.append(
                    make_finding(
                        MODULE_AUTHORITY,
                        "contract_parties",
                        section_id,
                        RESULT_INSUFFICIENT,
                        SEVERITY_LOW,
                        "Parties were detected, but authority rules are not configured.",
                        "Provide authority_rules.json before making a legal authority conclusion.",
                        evidence=[item.get("text", "") for item in parties[:4]],
                    )
                )
            else:
                findings.append(
                    make_finding(
                        MODULE_AUTHORITY,
                        "contract_parties",
                        section_id,
                        RESULT_VALID,
                        SEVERITY_INFO,
                        "Contract parties were detected and authority rules are available.",
                        "Review the extracted party names against internal authority records.",
                        evidence=[item.get("text", "") for item in parties[:4]],
                    )
                )

            signer_title = extract_best_signer_title(signatures, auth_mentions)
            signer_result = evaluate_signer_title(signer_title, rules)
            if signer_result == RESULT_NOT_APPLICABLE:
                result = RESULT_INSUFFICIENT
                severity = SEVERITY_MEDIUM
                reason = "Could not identify signer title or representative authority language."
            elif signer_result == RESULT_INSUFFICIENT:
                result = RESULT_INSUFFICIENT
                severity = SEVERITY_LOW
                reason = "Signer information was detected, but authority rules are missing or incomplete."
            elif signer_result == RESULT_VALID:
                result = RESULT_VALID
                severity = SEVERITY_INFO
                reason = "Signer title matches configured authority rules."
            else:
                result = RESULT_INVALID
                severity = SEVERITY_HIGH
                reason = "Signer title does not match configured authority rules."
            findings.append(
                make_finding(
                    MODULE_AUTHORITY,
                    "contract_signer_authority",
                    section_id,
                    result,
                    severity,
                    reason,
                    "Verify signing authority documents or update the contract signer block.",
                    evidence=[item.get("text", "") for item in [*signatures, *auth_mentions][:5]],
                )
            )
        elif kind == DOCUMENT_KIND_LEGAL_DOCUMENT:
            issuing_body = fields.get("issuing_body")
            signer_title = fields.get("signer_title")
            findings.append(
                self._legal_document_authority_finding(
                    "issuing_body_authority",
                    "issuing_bodies",
                    issuing_body,
                    rules,
                    rules_warning,
                )
            )
            findings.append(
                self._legal_document_authority_finding(
                    "signer_title_authority",
                    "signer_titles",
                    signer_title,
                    rules,
                    rules_warning,
                )
            )
        else:
            findings.append(
                make_finding(
                    MODULE_AUTHORITY,
                    "authority_scope",
                    "whole_document",
                    RESULT_INSUFFICIENT,
                    SEVERITY_MEDIUM,
                    "Could not classify the uploaded file as a contract or legal document.",
                    "Use a clearer DOCX structure or review the file manually.",
                )
            )

        warnings = [rules_warning] if rules_warning else []
        record_tool_trace(
            state,
            "authority_module",
            "review",
            kind,
            len(findings),
            started,
            "warning" if warnings else "ok",
            [item["code"] for item in warnings],
        )
        return make_module_result(
            MODULE_AUTHORITY,
            "Authority Review",
            findings,
            citations,
            warnings,
        )

    def _legal_document_authority_finding(
        self,
        question_id: str,
        rule_key: str,
        value: str | None,
        rules: dict[str, Any],
        rules_warning: dict[str, str] | None,
    ) -> dict[str, Any]:
        if not value:
            return make_finding(
                MODULE_AUTHORITY,
                question_id,
                "whole_document",
                RESULT_INSUFFICIENT,
                SEVERITY_MEDIUM,
                "Required authority field was not detected.",
                "Check the heading/signature block or enter metadata manually.",
            )
        if rules_warning:
            return make_finding(
                MODULE_AUTHORITY,
                question_id,
                "whole_document",
                RESULT_INSUFFICIENT,
                SEVERITY_LOW,
                "Authority value was detected, but authority rules are not configured.",
                "Provide authority_rules.json before making a legal authority conclusion.",
                evidence=[value],
            )
        allowed = [fold_text(item) for item in rules.get(rule_key, []) if str(item).strip()]
        if not allowed:
            return make_finding(
                MODULE_AUTHORITY,
                question_id,
                "whole_document",
                RESULT_INSUFFICIENT,
                SEVERITY_LOW,
                f"No configured rule list for {rule_key}.",
                "Complete authority_rules.json.",
                evidence=[value],
            )
        result = RESULT_VALID if any(item in fold_text(value) for item in allowed) else RESULT_INVALID
        return make_finding(
            MODULE_AUTHORITY,
            question_id,
            "whole_document",
            result,
            SEVERITY_INFO if result == RESULT_VALID else SEVERITY_HIGH,
            "Authority field was compared with configured rules.",
            "Review rule coverage if this conclusion looks wrong.",
            evidence=[value],
        )

    def _run_effectivity_module(self, state: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        fields = state.get("fields", {})
        references = fields.get("referenced_documents", [])
        findings: list[dict[str, Any]] = []
        module_citations: list[dict[str, Any]] = []
        warnings: list[dict[str, str]] = []

        if not references:
            findings.append(
                make_finding(
                    MODULE_EFFECTIVITY,
                    "referenced_legal_basis",
                    "whole_document",
                    RESULT_INSUFFICIENT,
                    SEVERITY_MEDIUM,
                    "No referenced legal document number was detected.",
                    "Add explicit legal basis numbers or review legal basis manually.",
                )
            )
        else:
            context = self._retrieve_effectivity_context(state, references)
            module_citations = context["citations"]
            warnings.extend(context["warnings"])
            records_by_number = group_status_records(context["status_records"])
            for reference in references:
                doc_number = reference["document_number"]
                records = records_by_number.get(doc_number, [])
                if not records:
                    findings.append(
                        make_finding(
                            MODULE_EFFECTIVITY,
                            "document_status",
                            reference["section_id"],
                            RESULT_INSUFFICIENT,
                            SEVERITY_MEDIUM,
                            f"{doc_number} was cited but not found in accessible published metadata.",
                            "Publish or correct the referenced legal document metadata.",
                            evidence=[reference["text"]],
                        )
                    )
                    continue
                for record in records[:2]:
                    status = normalize_validity_status(record.get("validity_status"))
                    relations = record.get("relations") or []
                    relation_warning = not relations
                    result, severity, reason = effectivity_result_from_status(status, relations)
                    if relation_warning:
                        warnings.append(
                            {
                                "code": "RELATION_DATA_INCOMPLETE",
                                "message": f"{doc_number} has no published relation data.",
                            }
                        )
                    evidence = [
                        f"validity_status={status or VALIDITY_UNKNOWN}",
                        *[
                            f"{item.get('relation_type')} -> {item.get('target_document_number') or item.get('target_document_id')}"
                            for item in relations[:3]
                        ],
                    ]
                    finding = make_finding(
                        MODULE_EFFECTIVITY,
                        "document_status",
                        reference["section_id"],
                        result,
                        severity,
                        reason,
                        "Verify effectivity metadata and relation data before relying on this clause.",
                        citations=[citation_from_status_record(record)],
                        evidence=evidence,
                    )
                    finding["document_number"] = doc_number
                    finding["document_status"] = status or VALIDITY_UNKNOWN
                    finding["article_status"] = RESULT_INSUFFICIENT
                    finding["article_reason"] = (
                        "Article-level effectivity is not available unless article-specific "
                        "amendment/replacement evidence exists."
                    )
                    findings.append(finding)
                    module_citations.append(citation_from_status_record(record))

        module_citations = unique_citations(module_citations)
        warnings = dedupe_warnings(warnings)
        record_tool_trace(
            state,
            "effectivity_module",
            "review",
            f"references={len(references)}",
            len(findings),
            started,
            "warning" if warnings else "ok",
            [item["code"] for item in warnings],
        )
        return make_module_result(
            MODULE_EFFECTIVITY,
            "Effectivity Review",
            findings,
            module_citations,
            warnings,
        )

    def _retrieve_effectivity_context(
        self,
        state: dict[str, Any],
        references: list[dict[str, Any]],
    ) -> dict[str, Any]:
        status_records: list[dict[str, Any]] = []
        citations: list[dict[str, Any]] = []
        warnings: list[dict[str, str]] = []
        query = " ".join(item["document_number"] for item in references[:8])
        access_scope = state.get("access_scope")
        if not isinstance(access_scope, AccessScope):
            access_scope = AccessScope()
        access_filter = {"_access_scope": access_scope}

        started = time.perf_counter()
        for reference in references[:12]:
            records = self.status_repository.find_status_records(
                reference["document_number"],
                {"document_number": reference["document_number"], **access_filter},
                5,
            )
            status_records.extend(records)
            citations.extend(citation_from_status_record(record) for record in records)
        record_tool_trace(
            state,
            "status_lookup",
            "retrieval",
            query,
            len(status_records),
            started,
            "ok",
            [],
        )

        hits = []
        for tool_name, retriever in (
            ("vector_search", self.vector_retriever),
            ("bm25_search", self.bm25_retriever),
        ):
            started = time.perf_counter()
            try:
                tool_hits = retriever.search(query, 8, access_filter, True)
                tool_hits = filter_hits_for_access(tool_hits, access_scope)
                hits.extend(tool_hits)
                record_tool_trace(
                    state,
                    tool_name,
                    "retrieval",
                    query,
                    len(tool_hits),
                    started,
                    "ok",
                    [],
                )
            except (RetrieverUnavailable, Exception) as exc:
                code = "RETRIEVER_UNAVAILABLE"
                warnings.append(
                    {
                        "code": code,
                        "message": f"{tool_name} unavailable: {type(exc).__name__}.",
                    }
                )
                record_tool_trace(
                    state,
                    tool_name,
                    "retrieval",
                    query,
                    0,
                    started,
                    "error",
                    [type(exc).__name__],
                )

        fused = fuse_hits([hits], 8)
        citations.extend(hit.citation() for hit in fused)

        started = time.perf_counter()
        try:
            graph_context = graph_enrich_with_scope(
                self.graph_retriever,
                fused,
                8,
                access_scope,
            )
            record_tool_trace(
                state,
                "graph_context",
                "expansion",
                f"hits={len(fused)}",
                len(graph_context.get("effectivity_relations") or []),
                started,
                "ok",
                [],
            )
        except Exception as exc:
            warnings.append(
                {
                    "code": "GRAPH_CONTEXT_UNAVAILABLE",
                    "message": f"graph_context unavailable: {type(exc).__name__}.",
                }
            )
            record_tool_trace(
                state,
                "graph_context",
                "expansion",
                f"hits={len(fused)}",
                0,
                started,
                "error",
                [type(exc).__name__],
            )

        return {
            "status_records": status_records,
            "citations": unique_citations(citations),
            "warnings": dedupe_warnings(warnings),
        }

    def _access_scope_for_job(self, job: dict[str, Any]) -> AccessScope:
        user_id = str(job.get("user_id") or "").strip()
        if not user_id:
            return AccessScope()
        user = AuthService(self.config.sqlite_db_path).get_user_by_id(user_id)
        return access_scope_for_user(user)

    def _synthesize_report(self, state: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        modules = state.get("modules", [])
        all_findings = [
            finding
            for module in modules
            for finding in module.get("findings", [])
        ]
        citations = unique_citations(
            [
                *state.get("citations", []),
                *[
                    citation
                    for module in modules
                    for citation in module.get("citations", [])
                ],
            ]
        )
        warnings = dedupe_warnings(
            [
                *state.get("warnings", []),
                *[
                    warning_item
                    for module in modules
                    for warning_item in module.get("warnings", [])
                ],
            ]
        )
        report = {
            "job": {
                "id": state["job"]["id"],
                "status": STATUS_COMPLETED,
                "file_name": state["job"]["file_name"],
                "created_at": state["job"]["created_at"],
            },
            "document": {
                "kind": state.get("document_kind", DOCUMENT_KIND_UNKNOWN),
                "fields": state.get("fields", {}),
                "sections": compact_sections(state.get("sections", [])),
                "warnings": warnings,
            },
            "modules": modules,
            "section_reviews": build_section_reviews(state.get("sections", []), all_findings),
            "risk_summary": build_risk_summary(all_findings),
            "tool_trace": state.get("tool_trace", []),
            "citations": citations,
            "warnings": warnings,
        }
        record_tool_trace(
            state,
            "report_synthesizer",
            "synthesis",
            state.get("document_kind", DOCUMENT_KIND_UNKNOWN),
            len(all_findings),
            started,
            "ok",
            [],
        )
        report["tool_trace"] = state.get("tool_trace", [])
        return {"report": report}

    def _get_raw_job(self, job_id: str) -> dict[str, Any] | None:
        with get_connection(self.config.sqlite_db_path) as connection:
            row = connection.execute(
                "SELECT * FROM contract_review_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
        return dict(row) if row else None

    def _mark_job(self, job_id: str, status: str) -> None:
        now = utc_now_iso()
        with get_connection(self.config.sqlite_db_path) as connection:
            connection.execute(
                """
                UPDATE contract_review_jobs
                SET status = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, now, job_id),
            )
            connection.commit()

    def _complete_job(
        self,
        *,
        job_id: str,
        document_kind: str,
        result: dict[str, Any],
    ) -> None:
        now = utc_now_iso()
        with get_connection(self.config.sqlite_db_path) as connection:
            connection.execute(
                """
                UPDATE contract_review_jobs
                SET status = ?, document_kind = ?, result_json = ?,
                    error_message = NULL, updated_at = ?, completed_at = ?
                WHERE id = ?
                """,
                (
                    STATUS_COMPLETED,
                    document_kind,
                    json.dumps(json_safe(result), ensure_ascii=False),
                    now,
                    now,
                    job_id,
                ),
            )
            connection.commit()

    def _fail_job(self, job_id: str, message: str) -> None:
        now = utc_now_iso()
        with get_connection(self.config.sqlite_db_path) as connection:
            connection.execute(
                """
                UPDATE contract_review_jobs
                SET status = ?, error_message = ?, updated_at = ?, completed_at = ?
                WHERE id = ?
                """,
                (STATUS_FAILED, message, now, now, job_id),
            )
            connection.commit()

    def _validate_file_name(self, file_storage: FileStorage | None) -> str:
        if file_storage is None or not file_storage.filename:
            raise ContractReviewError(
                "DOCX_REQUIRED",
                "Uploaded .docx file is required.",
                400,
            )
        filename = secure_filename(file_storage.filename or "contract.docx")
        if not filename.lower().endswith(".docx"):
            raise ContractReviewError(
                "DOCX_REQUIRED",
                "Uploaded file must have a .docx extension.",
                400,
            )
        return filename or "contract.docx"

    def _save_upload(
        self,
        file_storage: FileStorage,
        filename: str,
        job_id: str,
    ) -> Path:
        upload_dir = Path("data/uploads/contracts") / job_id
        upload_dir.mkdir(parents=True, exist_ok=True)
        file_path = upload_dir / filename
        file_storage.save(file_path)
        return file_path


def validate_docx_signature(path: Path) -> None:
    if not zipfile.is_zipfile(path):
        raise ContractReviewError(
            "DOCX_REQUIRED",
            "Uploaded file is not a valid .docx archive.",
            400,
        )
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
    except zipfile.BadZipFile as exc:
        raise ContractReviewError(
            "DOCX_REQUIRED",
            "Uploaded file is not a valid .docx archive.",
            400,
        ) from exc
    required = {"[Content_Types].xml", "word/document.xml"}
    if not required.issubset(names):
        raise ContractReviewError(
            "DOCX_REQUIRED",
            "Uploaded file is missing required DOCX parts.",
            400,
        )


def format_job(job: dict[str, Any]) -> dict[str, Any]:
    result = None
    if job.get("result_json"):
        try:
            result = json.loads(job["result_json"])
        except json.JSONDecodeError:
            result = None
    return {
        "job_id": job["id"],
        "id": job["id"],
        "user_id": job["user_id"],
        "file_name": job["file_name"],
        "status": job["status"],
        "document_kind": job.get("document_kind"),
        "result": result,
        "error_message": job.get("error_message"),
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
        "completed_at": job.get("completed_at"),
    }


def table_rows_to_lines(tables: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for table in tables:
        for row in table.get("rows") or []:
            text = " | ".join(str(cell).strip() for cell in row if str(cell).strip())
            if text:
                lines.append(text)
    return lines


def build_review_sections(paragraphs: list[str], table_lines: list[str] | None = None) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    lines = [*paragraphs, *(table_lines or [])]
    for line in lines:
        text = str(line).strip()
        if not text:
            continue
        if is_section_heading(text) or current is None:
            if current is not None:
                sections.append(current)
            current = {
                "id": f"section_{len(sections) + 1}",
                "title": text[:120],
                "content": text,
            }
        else:
            current["content"] = f"{current['content']}\n{text}".strip()
    if current is not None:
        sections.append(current)
    if not sections:
        sections.append({"id": "whole_document", "title": "Toan van", "content": ""})
    return sections


def is_section_heading(text: str) -> bool:
    folded = fold_text(text)
    if re.match(r"^(dieu|article)\s+[0-9]+[a-z]?\b", folded):
        return True
    if re.match(r"^(chuong|chapter|muc|section)\s+[ivxlcdm0-9]+", folded):
        return True
    if re.match(r"^[0-9]{1,2}[.)]\s+\S+", folded):
        return True
    letters = [char for char in text if char.isalpha()]
    if 5 <= len(text) <= 100 and letters:
        upper_count = sum(1 for char in letters if char.upper() == char)
        return upper_count / len(letters) > 0.75
    return False


def detect_document_kind(text: str) -> str:
    folded = fold_text(text)
    contract_terms = (
        "hop dong",
        "contract",
        "ben a",
        "ben b",
        "dai dien ben",
        "party a",
        "party b",
    )
    legal_terms = (
        "cong hoa xa hoi chu nghia viet nam",
        "quoc hoi",
        "chinh phu",
        "bo truong",
        "nghi dinh",
        "thong tu",
        "quyet dinh",
        "luat",
    )
    if any(term in folded for term in contract_terms):
        return DOCUMENT_KIND_CONTRACT
    head = "\n".join(folded.splitlines()[:40])
    if any(term in head for term in legal_terms) and (" so:" in head or " so " in head):
        return DOCUMENT_KIND_LEGAL_DOCUMENT
    if re.search(r"\b[0-9]{1,4}/[0-9]{4}/[a-z0-9.-]+\b", folded) and any(
        term in head for term in legal_terms
    ):
        return DOCUMENT_KIND_LEGAL_DOCUMENT
    return DOCUMENT_KIND_UNKNOWN


def extract_parties(text: str) -> list[dict[str, Any]]:
    matches = []
    for line in text.splitlines():
        folded = fold_text(line)
        if any(term in folded for term in ("ben a", "ben b", "party a", "party b", "cong ty", "doanh nghiep")):
            matches.append({"text": line.strip(), "section_id": "whole_document"})
    return matches[:12]


def extract_signature_blocks(text: str) -> list[dict[str, Any]]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    tail = lines[-80:]
    blocks = []
    for line in tail:
        folded = fold_text(line)
        if any(
            term in folded
            for term in (
                "dai dien",
                "nguoi dai dien",
                "giam doc",
                "tong giam doc",
                "chu tich",
                "ky ten",
                "signer",
                "representative",
            )
        ):
            blocks.append({"text": line, "section_id": "whole_document"})
    return blocks[:12]


def extract_matching_lines(text: str, terms: tuple[str, ...]) -> list[dict[str, Any]]:
    matches = []
    for line in text.splitlines():
        folded = fold_text(line)
        if any(term in folded for term in terms):
            matches.append({"text": line.strip(), "section_id": "whole_document"})
    return matches[:20]


def extract_issuing_body(text: str, tables: list[dict[str, Any]]) -> str | None:
    for table in tables[:2]:
        for row in table.get("rows") or []:
            if row:
                candidate = str(row[0]).strip()
                if candidate and len(candidate) <= 160:
                    return candidate
    for line in text.splitlines()[:30]:
        folded = fold_text(line)
        if any(term in folded for term in ("quoc hoi", "chinh phu", "bo ", "uy ban", "toa an")):
            return line.strip()
    return None


def extract_signer_title(text: str, tables: list[dict[str, Any]]) -> str | None:
    for table in reversed(tables[-3:]):
        for row in table.get("rows") or []:
            joined = " | ".join(str(cell).strip() for cell in row if str(cell).strip())
            folded = fold_text(joined)
            if any(term in folded for term in ("chu tich", "bo truong", "giam doc", "tong giam doc", "pho")):
                return joined[:160]
    signatures = extract_signature_blocks(text)
    best = extract_best_signer_title(signatures, [])
    return best


def extract_referenced_documents(text: str, sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pattern = re.compile(r"\b([0-9]{1,4}/[0-9]{4}/[A-Z0-9.-]+)\b", flags=re.IGNORECASE)
    seen: set[str] = set()
    references: list[dict[str, Any]] = []
    for section in sections:
        for match in pattern.finditer(section.get("content", "")):
            doc_number = match.group(1).upper()
            if doc_number in seen:
                continue
            seen.add(doc_number)
            references.append(
                {
                    "document_number": doc_number,
                    "section_id": section["id"],
                    "text": surrounding_text(section.get("content", ""), match.start(), match.end()),
                }
            )
    return references


def extract_legal_citations(text: str, sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    del text
    pattern = re.compile(r"\b(?:dieu|article)\s+([0-9]+[a-z]?)", flags=re.IGNORECASE)
    citations = []
    for section in sections:
        folded = fold_text(section.get("content", ""))
        for match in pattern.finditer(folded):
            citations.append(
                {
                    "article_number": match.group(1),
                    "section_id": section["id"],
                }
            )
    return citations[:40]


def extract_best_signer_title(
    signatures: list[dict[str, Any]],
    auth_mentions: list[dict[str, Any]],
) -> str | None:
    candidates = [item.get("text", "") for item in [*signatures, *auth_mentions]]
    for candidate in candidates:
        folded = fold_text(candidate)
        if any(term in folded for term in ("tong giam doc", "giam doc", "chu tich", "bo truong", "pho")):
            return candidate
    return candidates[0] if candidates else None


def evaluate_signer_title(signer_title: str | None, rules: dict[str, Any]) -> str:
    if not signer_title:
        return RESULT_NOT_APPLICABLE
    allowed_raw = (
        rules.get("contract_signer_titles")
        or rules.get("allowed_signer_titles")
        or rules.get("signer_titles")
        or []
    )
    allowed = [fold_text(item) for item in allowed_raw if str(item).strip()]
    if not allowed:
        return RESULT_INSUFFICIENT
    folded_title = fold_text(signer_title)
    return RESULT_VALID if any(item in folded_title for item in allowed) else RESULT_INVALID


def effectivity_result_from_status(
    status: str | None,
    relations: list[dict[str, Any]],
) -> tuple[str, str, str]:
    relation_types = {fold_text(item.get("relation_type", "")) for item in relations}
    if status in INACTIVE_STATUSES:
        return (
            "inactive",
            SEVERITY_HIGH,
            "Published metadata marks this document as inactive.",
        )
    if any(term in relation_types for term in ("replaced_by", "abolished_by", "revoked_by")):
        return (
            "inactive",
            SEVERITY_HIGH,
            "Published relation data indicates this document was replaced or abolished.",
        )
    if is_active_status(status):
        return (
            "active",
            SEVERITY_INFO,
            "Published metadata marks this document as active.",
        )
    if is_unknown_status(status):
        return (
            RESULT_INSUFFICIENT,
            SEVERITY_MEDIUM,
            "Published metadata does not confirm the document's effectivity status.",
        )
    return (
        RESULT_INSUFFICIENT,
        SEVERITY_MEDIUM,
        "Effectivity status is not recognized.",
    )


def load_enabled_modules(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.exists():
        return DEFAULT_ENABLED_MODULES[:], []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return DEFAULT_ENABLED_MODULES[:], [
            {
                "code": "MODULE_CONFIG_INVALID",
                "message": f"Could not read contract review module config: {type(exc).__name__}.",
            }
        ]
    raw_modules = payload.get("enabled_modules") if isinstance(payload, dict) else payload
    if not isinstance(raw_modules, list):
        return DEFAULT_ENABLED_MODULES[:], [
            {
                "code": "MODULE_CONFIG_INVALID",
                "message": "Contract review module config must contain enabled_modules list.",
            }
        ]
    enabled = [str(item).strip() for item in raw_modules if str(item).strip()]
    supported = [item for item in enabled if item in DEFAULT_ENABLED_MODULES]
    warnings = []
    if len(supported) != len(enabled):
        warnings.append(
            {
                "code": "UNSUPPORTED_REVIEW_MODULE",
                "message": "Unsupported contract review module names were ignored.",
            }
        )
    return supported or DEFAULT_ENABLED_MODULES[:], warnings


def load_json_rules(filename: str, config: Config) -> tuple[dict[str, Any], dict[str, str] | None]:
    module_path = Path(config.contract_review_modules_path)
    rules_path = module_path.with_name(filename)
    if not rules_path.exists():
        return {}, {
            "code": "RULES_MISSING",
            "message": f"{filename} is not configured; module conclusions are limited.",
        }
    try:
        payload = json.loads(rules_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {}, {
            "code": "RULES_INVALID",
            "message": f"{filename} could not be read: {type(exc).__name__}.",
        }
    if not isinstance(payload, dict):
        return {}, {
            "code": "RULES_INVALID",
            "message": f"{filename} must contain a JSON object.",
        }
    return payload, None


def make_module_result(
    module_id: str,
    title: str,
    findings: list[dict[str, Any]],
    citations: list[dict[str, Any]],
    warnings: list[dict[str, str]],
) -> dict[str, Any]:
    statuses = [finding.get("result") for finding in findings]
    if any(status in {RESULT_INVALID, "inactive", "conflict"} for status in statuses):
        status = "risk_found"
    elif any(status == RESULT_INSUFFICIENT for status in statuses):
        status = RESULT_INSUFFICIENT
    elif all(status in {RESULT_VALID, "active", RESULT_NOT_APPLICABLE} for status in statuses):
        status = "passed"
    else:
        status = "partial"
    confidence = 0.0
    if findings:
        confidence = sum(confidence_for_finding(finding) for finding in findings) / len(findings)
    return {
        "module_id": module_id,
        "title": title,
        "status": status,
        "confidence": round(confidence, 3),
        "findings": findings,
        "citations": unique_citations(citations),
        "warnings": dedupe_warnings(warnings),
    }


def make_finding(
    module_id: str,
    question_id: str,
    section_id: str | None,
    result: str,
    severity: str,
    reason: str,
    recommendation: str,
    *,
    citations: list[dict[str, Any]] | None = None,
    evidence: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "module_id": module_id,
        "question_id": question_id,
        "section_id": section_id or "whole_document",
        "result": result,
        "severity": severity,
        "reason": reason,
        "recommendation": recommendation,
        "citations": citations or [],
        "evidence": [item for item in (evidence or []) if item],
    }


def confidence_for_finding(finding: dict[str, Any]) -> float:
    result = finding.get("result")
    if result in {RESULT_VALID, RESULT_INVALID, "active", "inactive", "conflict"}:
        return 0.75 if finding.get("citations") or finding.get("evidence") else 0.55
    if result == RESULT_INSUFFICIENT:
        return 0.2
    return 0.35


def build_risk_summary(findings: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {SEVERITY_HIGH: 0, SEVERITY_MEDIUM: 0, SEVERITY_LOW: 0, SEVERITY_INFO: 0}
    for finding in findings:
        severity = finding.get("severity") or SEVERITY_INFO
        counts[severity] = counts.get(severity, 0) + 1
    if counts[SEVERITY_HIGH]:
        overall = SEVERITY_HIGH
    elif counts[SEVERITY_MEDIUM]:
        overall = SEVERITY_MEDIUM
    elif counts[SEVERITY_LOW]:
        overall = SEVERITY_LOW
    else:
        overall = "none"
    return {"overall": overall, "counts": counts, "total_findings": len(findings)}


def build_section_reviews(
    sections: list[dict[str, Any]],
    findings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_section = {section["id"]: [] for section in sections}
    by_section.setdefault("whole_document", [])
    for finding in findings:
        by_section.setdefault(finding.get("section_id") or "whole_document", []).append(finding)
    section_map = {section["id"]: section for section in sections}
    reviews = []
    for section_id, section_findings in by_section.items():
        if not section_findings:
            continue
        section = section_map.get(section_id, {"id": section_id, "title": "Whole document", "content": ""})
        reviews.append(
            {
                "section_id": section_id,
                "title": section.get("title") or section_id,
                "content_preview": trim_text(section.get("content", ""), 320),
                "findings": section_findings,
            }
        )
    return reviews


def compact_sections(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": section["id"],
            "title": section.get("title") or section["id"],
            "content_preview": trim_text(section.get("content", ""), 320),
        }
        for section in sections[:80]
    ]


def group_status_records(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        doc_number = str(record.get("document_number") or "").upper()
        if not doc_number:
            continue
        grouped.setdefault(doc_number, []).append(record)
    return grouped


def dedupe_warnings(warnings: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    deduped = []
    for item in warnings:
        key = (item.get("code", ""), item.get("message", ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append({"code": key[0], "message": key[1]})
    return deduped


def record_tool_trace(
    state: dict[str, Any],
    tool_name: str,
    phase: str,
    input_summary: str,
    result_count: int,
    started: float,
    status: str,
    warnings: list[str],
) -> None:
    trace = {
        "tool": tool_name,
        "phase": phase,
        "input_summary": trim_text(str(input_summary or ""), 180),
        "result_count": int(result_count),
        "duration_ms": int((time.perf_counter() - started) * 1000),
        "status": status,
        "warnings": warnings,
    }
    state["tool_trace"] = [*state.get("tool_trace", []), trace]


def section_for_first_evidence(*groups: list[dict[str, Any]]) -> str:
    for group in groups:
        for item in group:
            if item.get("section_id"):
                return item["section_id"]
    return "whole_document"


def surrounding_text(text: str, start: int, end: int, radius: int = 120) -> str:
    return trim_text(text[max(0, start - radius) : min(len(text), end + radius)], 260)


def trim_text(text: str, limit: int) -> str:
    normalized = " ".join(str(text or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 3)].rstrip() + "..."


def fold_text(value: Any) -> str:
    text = str(value or "").lower()
    text = text.replace("đ", "d").replace("Đ", "d")
    normalized = unicodedata.normalize("NFD", text)
    return "".join(char for char in normalized if unicodedata.category(char) != "Mn")


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, set):
        return sorted(json_safe(item) for item in value)
    return value


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
