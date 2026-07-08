from __future__ import annotations

from flask import Blueprint, current_app, g, jsonify, request

from backend.api.decorators import error_response, require_role
from backend.services.auth_service import ROLE_ADMIN, ROLE_BUSINESS_USER
from backend.services.contract_review_service import (
    ContractReviewAgentService,
    ContractReviewError,
)


contracts_bp = Blueprint("contracts", __name__, url_prefix="/api/v1/contracts")


@contracts_bp.post("/review")
@require_role(ROLE_BUSINESS_USER, ROLE_ADMIN)
def review_contract():
    try:
        job = _get_contract_review_service().enqueue_review(
            request.files.get("file"),
            user_id=g.current_user["id"],
        )
    except ContractReviewError as exc:
        return error_response(exc.code, exc.message, exc.status_code, exc.details)
    return jsonify(job), 202


@contracts_bp.get("/review/<job_id>")
@require_role(ROLE_BUSINESS_USER, ROLE_ADMIN)
def get_contract_review(job_id: str):
    try:
        job = _get_contract_review_service().get_job(
            job_id,
            requester_user_id=g.current_user["id"],
            requester_role=g.current_user["role"],
        )
    except ContractReviewError as exc:
        return error_response(exc.code, exc.message, exc.status_code, exc.details)
    if job is None:
        return error_response("CONTRACT_REVIEW_NOT_FOUND", "Review job not found.", 404)
    return jsonify(job)


def _get_contract_review_service() -> ContractReviewAgentService:
    service = current_app.extensions.get("contract_review_service")
    if service is None:
        service = ContractReviewAgentService(current_app.config["APP_CONFIG"])
        current_app.extensions["contract_review_service"] = service
    return service
