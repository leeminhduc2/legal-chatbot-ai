from __future__ import annotations

from flask import Blueprint, current_app, g, jsonify, request, send_file

from backend.api.decorators import error_response, require_role
from backend.services.auth_service import AuthError, AuthService
from backend.services.document_import_service import (
    DocumentImportError,
    DocumentImportService,
)
from backend.services.indexing_service import DocumentIndexingService, IndexingError


admin_bp = Blueprint("admin", __name__, url_prefix="/api/v1/admin")


@admin_bp.get("/users")
@require_role("admin")
def list_users():
    return jsonify({"users": _get_auth_service().list_users()})


@admin_bp.post("/users")
@require_role("admin")
def create_user():
    payload = request.get_json(silent=True) or {}
    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", ""))
    role = str(payload.get("role", "business_user"))

    try:
        user = _get_auth_service().create_user(
            username=username,
            password=password,
            role=role,
        )
    except AuthError as exc:
        return error_response(exc.code, exc.message, exc.status_code)

    return jsonify({"user": user}), 201


@admin_bp.patch("/users/<user_id>")
@require_role("admin")
def update_user(user_id: str):
    payload = request.get_json(silent=True) or {}
    allowed_fields = {"role", "password", "is_active"}
    updates = {key: value for key, value in payload.items() if key in allowed_fields}

    try:
        user = _get_auth_service().update_user(
            user_id=user_id,
            updates=updates,
            current_user_id=g.current_user["id"],
        )
    except AuthError as exc:
        return error_response(exc.code, exc.message, exc.status_code)

    return jsonify({"user": user})


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
        if result.get("is_publishable"):
            try:
                publish_result = _get_indexing_service().enqueue_publish_document(
                    document_id=result["document_id"],
                    requested_by_user_id=g.current_user["id"],
                )
                result.update(
                    {
                        "status": publish_result["status"],
                        "publish_result": publish_result,
                    }
                )
            except IndexingError as exc:
                service.mark_latest_version_needs_republish(
                    result["document_id"],
                    exc.message,
                    {"code": exc.code, **exc.details},
                )
                result.update(
                    {
                        "status": "ready_for_review",
                        "needs_republish": True,
                        "auto_publish_error": {
                            "code": exc.code,
                            "message": exc.message,
                            "details": exc.details,
                        },
                    }
                )
    except DocumentImportError as exc:
        return error_response(exc.code, exc.message, exc.status_code)

    return jsonify(result), 201


@admin_bp.get("/documents")
@require_role("admin")
def list_documents():
    status_filter = request.args.get("status")
    return jsonify({"documents": _get_import_service().list_documents(status_filter)})


@admin_bp.get("/documents/<document_id>")
@require_role("admin")
def get_document(document_id: str):
    detail = _get_import_service().get_document_detail(
        document_id,
        scope=request.args.get("scope", "latest"),
    )
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
        detail = _auto_publish_after_save(document_id, detail)
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
        detail = _auto_publish_after_save(document_id, detail)
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
        detail = _auto_publish_after_save(document_id, detail)
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
        result = _get_indexing_service().enqueue_publish_document(
            document_id=document_id,
            requested_by_user_id=g.current_user["id"],
        )
    except IndexingError as exc:
        return error_response(exc.code, exc.message, exc.status_code, exc.details)
    return jsonify(result), 202


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


def _auto_publish_after_save(document_id: str, detail: dict):
    if request.args.get("auto_publish") != "1" or not detail.get("is_publishable"):
        return detail
    try:
        publish_result = _get_indexing_service().enqueue_publish_document(
            document_id=document_id,
            requested_by_user_id=g.current_user["id"],
        )
        fresh_detail = _get_import_service().get_document_detail(document_id, scope="latest")
        assert fresh_detail is not None
        fresh_detail["publish_result"] = publish_result
        return fresh_detail
    except IndexingError as exc:
        _get_import_service().mark_latest_version_needs_republish(
            document_id,
            exc.message,
            {"code": exc.code, **exc.details},
        )
        fresh_detail = _get_import_service().get_document_detail(document_id, scope="latest")
        assert fresh_detail is not None
        fresh_detail["publish_error"] = {
            "code": exc.code,
            "message": exc.message,
            "details": exc.details,
        }
        return fresh_detail


def _get_auth_service() -> AuthService:
    app_config = current_app.config["APP_CONFIG"]
    return AuthService(
        db_path=app_config.sqlite_db_path,
        token_ttl_hours=app_config.token_ttl_hours,
    )
