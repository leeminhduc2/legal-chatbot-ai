from __future__ import annotations

from flask import Blueprint, current_app, g, jsonify, request

from backend.api.decorators import error_response, require_role
from backend.services.document_import_service import (
    DocumentImportError,
    DocumentImportService,
)


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


def _get_import_service() -> DocumentImportService:
    return DocumentImportService(current_app.config["APP_CONFIG"])
