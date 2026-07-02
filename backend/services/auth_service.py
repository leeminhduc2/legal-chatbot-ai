from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from werkzeug.security import check_password_hash, generate_password_hash

from backend.models.database import get_connection, row_to_dict


ROLE_ADMIN = "admin"
ROLE_BUSINESS_USER = "business_user"
ROLE_GUEST = "guest"
VALID_ROLES = {ROLE_ADMIN, ROLE_BUSINESS_USER, ROLE_GUEST}


class AuthError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class AuthService:
    def __init__(self, db_path: str, token_ttl_hours: int = 24):
        self.db_path = db_path
        self.token_ttl = timedelta(hours=token_ttl_hours)

    def create_user(self, username: str, password: str, role: str) -> dict[str, Any]:
        if role not in VALID_ROLES:
            raise ValueError(f"Unsupported role: {role}")

        now = utc_now_iso()
        user_id = str(uuid.uuid4())
        password_hash = generate_password_hash(password)

        with get_connection(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO users (id, username, password_hash, role, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, 1, ?, ?)
                """,
                (user_id, username, password_hash, role, now, now),
            )
            connection.commit()

        user = self.get_user_by_id(user_id)
        if user is None:
            raise RuntimeError("Failed to load user after creation.")
        return sanitize_user(user)

    def get_user_by_username(self, username: str) -> dict[str, Any] | None:
        with get_connection(self.db_path) as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE username = ?",
                (username,),
            ).fetchone()
        return row_to_dict(row)

    def get_user_by_id(self, user_id: str) -> dict[str, Any] | None:
        with get_connection(self.db_path) as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        return row_to_dict(row)

    def login(self, username: str, password: str) -> dict[str, Any]:
        user = self.get_user_by_username(username)
        if user is None or not check_password_hash(user["password_hash"], password):
            raise AuthError("INVALID_CREDENTIALS", "Invalid username or password.", 401)

        if not bool(user["is_active"]):
            raise AuthError("INACTIVE_USER", "User account is inactive.", 403)

        token = secrets.token_urlsafe(48)
        token_hash = hash_token(token)
        session_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        expires_at = now + self.token_ttl

        with get_connection(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO auth_sessions (id, user_id, token_hash, expires_at, revoked_at, created_at)
                VALUES (?, ?, ?, ?, NULL, ?)
                """,
                (
                    session_id,
                    user["id"],
                    token_hash,
                    expires_at.isoformat(),
                    now.isoformat(),
                ),
            )
            connection.commit()

        return {
            "access_token": token,
            "token_type": "Bearer",
            "expires_at": expires_at.isoformat(),
            "user": sanitize_user(user),
        }

    def get_user_for_token(self, token: str) -> dict[str, Any] | None:
        token_hash = hash_token(token)
        now = datetime.now(timezone.utc)

        with get_connection(self.db_path) as connection:
            row = connection.execute(
                """
                SELECT users.*
                FROM auth_sessions
                JOIN users ON users.id = auth_sessions.user_id
                WHERE auth_sessions.token_hash = ?
                  AND auth_sessions.revoked_at IS NULL
                  AND auth_sessions.expires_at > ?
                  AND users.is_active = 1
                """,
                (token_hash, now.isoformat()),
            ).fetchone()

        user = row_to_dict(row)
        if user is None:
            return None
        return sanitize_user(user)

    def logout(self, token: str) -> None:
        token_hash = hash_token(token)
        now = utc_now_iso()

        with get_connection(self.db_path) as connection:
            connection.execute(
                """
                UPDATE auth_sessions
                SET revoked_at = ?
                WHERE token_hash = ? AND revoked_at IS NULL
                """,
                (now, token_hash),
            )
            connection.commit()


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def sanitize_user(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": user["id"],
        "username": user["username"],
        "role": user["role"],
        "is_active": bool(user["is_active"]),
    }


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
