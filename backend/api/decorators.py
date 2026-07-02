from __future__ import annotations

from functools import wraps
from typing import Callable, TypeVar

from flask import current_app, g, request

from backend.services.auth_service import AuthService


F = TypeVar("F", bound=Callable)


def require_auth(route: F) -> F:
    @wraps(route)
    def wrapper(*args, **kwargs):
        token = extract_bearer_token()
        if not token:
            return error_response("AUTH_REQUIRED", "Authentication is required.", 401)

        auth_service = _get_auth_service()
        user = auth_service.get_user_for_token(token)
        if user is None:
            return error_response("AUTH_REQUIRED", "Invalid or expired token.", 401)

        g.current_user = user
        g.current_token = token
        return route(*args, **kwargs)

    return wrapper  # type: ignore[return-value]


def require_role(*roles: str):
    def decorator(route: F) -> F:
        @wraps(route)
        @require_auth
        def wrapper(*args, **kwargs):
            current_user = g.current_user
            if current_user["role"] not in roles:
                return error_response("FORBIDDEN", "Insufficient permissions.", 403)
            return route(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator


def extract_bearer_token() -> str | None:
    auth_header = request.headers.get("Authorization", "")
    scheme, _, token = auth_header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token.strip()


def error_response(code: str, message: str, status_code: int):
    return {"error": {"code": code, "message": message}}, status_code


def _get_auth_service() -> AuthService:
    app_config = current_app.config["APP_CONFIG"]
    return AuthService(
        db_path=app_config.sqlite_db_path,
        token_ttl_hours=app_config.token_ttl_hours,
    )
