from __future__ import annotations

from flask import Blueprint, current_app, g, jsonify, request, send_file

from backend.api.decorators import error_response, require_role
from backend.services.document_import_service import (
    DocumentImportError,
    DocumentImportService,
)
from backend.services.indexing_service import DocumentIndexingService, IndexingError


admin_bp = Blueprint("admin", __name__, url_prefix="/api/v1/admin")


@admin_bp.post("/documents/import")
@require_role("admin")
def import_document():
    service = _get_import_service()
    try:
        result = service.import_document(
            file_storage=request.files.get("file"),
            form_data=request.form.to_dict(),
            requested_by_user_id=g.current_user["id"],
        )
    except DocumentImportError as exc:
        return error_response(exc.code, exc.message, exc.status_code)

    return jsonify(result), 201


@admin_bp.get("/documents")
@require_role("admin")
def list_documents():
    return jsonify({"documents": _get_import_service().list_documents()})


@admin_bp.get("/documents/<document_id>")
@require_role("admin")
def get_document(document_id: str):
    detail = _get_import_service().get_document_detail(document_id)
    if detail is None:
        return error_response("DOCUMENT_NOT_FOUND", "Document not found.", 404)
    return jsonify(detail)


@admin_bp.get("/documents/<document_id>/download")
@require_role("admin")
def download_document(document_id: str):
    path = _get_import_service().get_raw_docx_path(document_id)
    if path is None:
        return error_response("DOCUMENT_NOT_FOUND", "Document not found.", 404)
    return send_file(path, as_attachment=True, download_name=path.name)


@admin_bp.patch("/documents/<document_id>/metadata")
@require_role("admin")
def update_document_metadata(document_id: str):
    try:
        detail = _get_import_service().update_document_metadata(
            document_id,
            request.get_json(silent=True) or {},
        )
    except DocumentImportError as exc:
        return error_response(exc.code, exc.message, exc.status_code)
    return jsonify(detail)


@admin_bp.patch("/documents/<document_id>/chunks")
@require_role("admin")
def update_document_chunks(document_id: str):
    payload = request.get_json(silent=True) or {}
    chunks = payload.get("chunks", payload if isinstance(payload, list) else None)
    if not isinstance(chunks, list):
        return error_response(
            "CHUNK_VALIDATION_FAILED",
            "Request body must include a chunks array.",
            400,
        )
    try:
        detail = _get_import_service().update_document_chunks(document_id, chunks)
    except DocumentImportError as exc:
        return error_response(exc.code, exc.message, exc.status_code)
    return jsonify(detail)


@admin_bp.put("/documents/<document_id>/relationships")
@require_role("admin")
def replace_document_relationships(document_id: str):
    payload = request.get_json(silent=True) or {}
    relations = payload.get("relations", payload if isinstance(payload, list) else None)
    if not isinstance(relations, list):
        return error_response(
            "METADATA_INCOMPLETE",
            "Request body must include a relations array.",
            400,
        )
    try:
        detail = _get_import_service().replace_document_relations(document_id, relations)
    except DocumentImportError as exc:
        return error_response(exc.code, exc.message, exc.status_code)
    return jsonify(detail)


@admin_bp.delete("/documents/<document_id>")
@require_role("admin")
def delete_document(document_id: str):
    try:
        result = _get_indexing_service().delete_document(
            document_id=document_id,
            requested_by_user_id=g.current_user["id"],
        )
    except IndexingError as exc:
        return error_response(exc.code, exc.message, exc.status_code)
    return jsonify(result)


@admin_bp.post("/documents/<document_id>/publish")
@require_role("admin")
def publish_document(document_id: str):
    try:
        result = _get_indexing_service().publish_document(
            document_id=document_id,
            requested_by_user_id=g.current_user["id"],
        )
    except IndexingError as exc:
        return error_response(exc.code, exc.message, exc.status_code)
    return jsonify(result)


@admin_bp.get("/pipeline")
@require_role("admin")
def list_pipeline_runs():
    return jsonify({"pipeline_runs": _get_import_service().list_pipeline_runs()})


@admin_bp.get("/pipeline/<run_id>")
@require_role("admin")
def get_pipeline_run(run_id: str):
    detail = _get_import_service().get_pipeline_detail(run_id)
    if detail is None:
        return error_response("DOCUMENT_NOT_FOUND", "Pipeline run not found.", 404)
    return jsonify(detail)


@admin_bp.post("/pipeline/<run_id>/rollback")
@require_role("admin")
def rollback_pipeline_run(run_id: str):
    try:
        result = _get_indexing_service().rollback_pipeline(
            run_id=run_id,
            requested_by_user_id=g.current_user["id"],
        )
    except IndexingError as exc:
        return error_response(exc.code, exc.message, exc.status_code)
    return jsonify(result)


def _get_import_service() -> DocumentImportService:
    return DocumentImportService(current_app.config["APP_CONFIG"])


def _get_indexing_service() -> DocumentIndexingService:
    return DocumentIndexingService(current_app.config["APP_CONFIG"])
