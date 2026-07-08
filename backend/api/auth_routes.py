from __future__ import annotations

from flask import Blueprint, current_app, g, jsonify, request

from backend.api.decorators import error_response, extract_bearer_token, require_auth
from backend.services.auth_service import AuthError, AuthService


auth_bp = Blueprint("auth", __name__, url_prefix="/api/v1/auth")


@auth_bp.post("/login")
def login():
    payload = request.get_json(silent=True) or {}
    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", ""))

    if not username or not password:
        return error_response(
            "INVALID_CREDENTIALS",
            "Username and password are required.",
            401,
        )

    auth_service = _get_auth_service()
    try:
        result = auth_service.login(username=username, password=password)
    except AuthError as exc:
        return error_response(exc.code, exc.message, exc.status_code)

    return jsonify(result)


@auth_bp.post("/logout")
@require_auth
def logout():
    token = extract_bearer_token()
    if token is not None:
        _get_auth_service().logout(token)
    return jsonify({"status": "ok"})


@auth_bp.get("/me")
@require_auth
def me():
    return jsonify({"user": g.current_user})


def _get_auth_service() -> AuthService:
    app_config = current_app.config["APP_CONFIG"]
    return AuthService(
        db_path=app_config.sqlite_db_path,
        token_ttl_hours=app_config.token_ttl_hours,
    )
