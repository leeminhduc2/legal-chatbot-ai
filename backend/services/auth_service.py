from __future__ import annotations

import hashlib
import sqlite3
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from werkzeug.security import check_password_hash, generate_password_hash

from backend.models.database import get_connection, row_to_dict


ROLE_ADMIN = "admin"
ROLE_BUSINESS_USER = "business_user"
ROLE_GUEST = "guest"
VALID_ROLES = {ROLE_ADMIN, ROLE_BUSINESS_USER}


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

    def create_user(
        self,
        username: str,
        password: str,
        role: str,
        allowed_field_ids: Any | None = None,
    ) -> dict[str, Any]:
        username = normalize_username(username)
        validate_username(username)
        validate_password(password)

        if role not in VALID_ROLES:
            raise AuthError("INVALID_ROLE", f"Unsupported role: {role}", 400)
        field_ids = [] if role == ROLE_ADMIN else validate_allowed_field_ids(allowed_field_ids)

        now = utc_now_iso()
        user_id = str(uuid.uuid4())
        password_hash = generate_password_hash(password)

        with get_connection(self.db_path) as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO users (id, username, password_hash, role, is_active, created_at, updated_at)
                    VALUES (?, ?, ?, ?, 1, ?, ?)
                    """,
                    (user_id, username, password_hash, role, now, now),
                )
                self._replace_allowed_field_ids(connection, user_id, field_ids, now)
                connection.commit()
            except sqlite3.IntegrityError as exc:
                if "UNIQUE" in str(exc).upper():
                    raise AuthError(
                        "USERNAME_EXISTS",
                        "Username is already registered.",
                        409,
                    ) from exc
                raise

        user = self.get_user_by_id(user_id)
        if user is None:
            raise RuntimeError("Failed to load user after creation.")
        return sanitize_user(user)

    def list_users(self) -> list[dict[str, Any]]:
        with get_connection(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM users
                ORDER BY created_at DESC, username ASC
                """
            ).fetchall()
            users = []
            for row in rows:
                user = row_to_dict(row)
                if user is not None:
                    users.append(sanitize_user(self._attach_allowed_field_ids(connection, user)))
        return users

    def get_user_by_username(self, username: str) -> dict[str, Any] | None:
        username = normalize_username(username)
        with get_connection(self.db_path) as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE username = ?",
                (username,),
            ).fetchone()
            user = row_to_dict(row)
            return self._attach_allowed_field_ids(connection, user) if user else None

    def update_user(
        self,
        user_id: str,
        updates: dict[str, Any],
        current_user_id: str,
    ) -> dict[str, Any]:
        user = self.get_user_by_id(user_id)
        if user is None:
            raise AuthError("USER_NOT_FOUND", "User not found.", 404)

        next_role = updates.get("role", user["role"])
        if next_role not in VALID_ROLES:
            raise AuthError("INVALID_ROLE", f"Unsupported role: {next_role}", 400)
        field_ids_provided = "allowed_field_ids" in updates
        next_field_ids = (
            []
            if next_role == ROLE_ADMIN
            else validate_allowed_field_ids(
                updates.get("allowed_field_ids")
                if field_ids_provided
                else user.get("allowed_field_ids", [])
            )
        )

        if "is_active" in updates:
            next_is_active = bool(updates["is_active"])
        else:
            next_is_active = bool(user["is_active"])

        is_self = user_id == current_user_id
        if is_self and (next_role != ROLE_ADMIN or not next_is_active):
            raise AuthError(
                "CANNOT_CHANGE_OWN_ADMIN",
                "Administrators cannot lock or demote their own account.",
                400,
            )

        removes_active_admin = (
            user["role"] == ROLE_ADMIN
            and bool(user["is_active"])
            and (next_role != ROLE_ADMIN or not next_is_active)
        )
        if removes_active_admin and self._active_admin_count() <= 1:
            raise AuthError(
                "LAST_ADMIN_REQUIRED",
                "At least one active administrator is required.",
                400,
            )

        assignments = ["role = ?", "is_active = ?", "updated_at = ?"]
        params: list[Any] = [next_role, 1 if next_is_active else 0, utc_now_iso()]
        should_revoke_sessions = False

        new_password = str(updates.get("password", ""))
        if new_password:
            validate_password(new_password)
            assignments.append("password_hash = ?")
            params.append(generate_password_hash(new_password))
            should_revoke_sessions = True

        if not next_is_active:
            should_revoke_sessions = True

        params.append(user_id)

        with get_connection(self.db_path) as connection:
            connection.execute(
                f"""
                UPDATE users
                SET {", ".join(assignments)}
                WHERE id = ?
                """,
                params,
            )
            if should_revoke_sessions:
                connection.execute(
                    """
                    UPDATE auth_sessions
                    SET revoked_at = ?
                    WHERE user_id = ? AND revoked_at IS NULL
                    """,
                    (utc_now_iso(), user_id),
                )
            if field_ids_provided or next_role == ROLE_ADMIN:
                self._replace_allowed_field_ids(
                    connection,
                    user_id,
                    next_field_ids,
                    utc_now_iso(),
                )
            connection.commit()

        updated_user = self.get_user_by_id(user_id)
        if updated_user is None:
            raise RuntimeError("Failed to load user after update.")
        return sanitize_user(updated_user)

    def get_user_by_id(self, user_id: str) -> dict[str, Any] | None:
        with get_connection(self.db_path) as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
            user = row_to_dict(row)
            return self._attach_allowed_field_ids(connection, user) if user else None

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
            return sanitize_user(self._attach_allowed_field_ids(connection, user))

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

    def _active_admin_count(self) -> int:
        with get_connection(self.db_path) as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM users
                WHERE role = ? AND is_active = 1
                """,
                (ROLE_ADMIN,),
            ).fetchone()
        return int(row["count"] if row else 0)

    def _attach_allowed_field_ids(
        self,
        connection,
        user: dict[str, Any],
    ) -> dict[str, Any]:
        if user.get("role") == ROLE_ADMIN:
            return {**user, "allowed_field_ids": []}
        rows = connection.execute(
            """
            SELECT field_id
            FROM user_field_permissions
            WHERE user_id = ?
            ORDER BY field_id ASC
            """,
            (user["id"],),
        ).fetchall()
        return {**user, "allowed_field_ids": [int(row["field_id"]) for row in rows]}

    def _replace_allowed_field_ids(
        self,
        connection,
        user_id: str,
        field_ids: list[int],
        now: str,
    ) -> None:
        connection.execute(
            "DELETE FROM user_field_permissions WHERE user_id = ?",
            (user_id,),
        )
        for field_id in sorted(set(field_ids)):
            connection.execute(
                """
                INSERT INTO user_field_permissions (user_id, field_id, created_at)
                VALUES (?, ?, ?)
                """,
                (user_id, field_id, now),
            )


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def sanitize_user(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": user["id"],
        "username": user["username"],
        "role": user["role"],
        "is_active": bool(user["is_active"]),
        "allowed_field_ids": sorted(
            {
                int(field_id)
                for field_id in user.get("allowed_field_ids", [])
                if isinstance(field_id, int) and field_id >= 0
            }
        ),
        "field_access": "all" if user["role"] == ROLE_ADMIN else "restricted",
        "created_at": user.get("created_at"),
        "updated_at": user.get("updated_at"),
    }


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_username(username: str) -> str:
    return str(username or "").strip()


def validate_username(username: str) -> None:
    if not username:
        raise AuthError("INVALID_USERNAME", "Username is required.", 400)
    if len(username) < 3 or len(username) > 50:
        raise AuthError(
            "INVALID_USERNAME",
            "Username must be between 3 and 50 characters.",
            400,
        )


def validate_password(password: str) -> None:
    if not password:
        raise AuthError("INVALID_PASSWORD", "Password is required.", 400)
    if len(password) < 6:
        raise AuthError(
            "INVALID_PASSWORD",
            "Password must be at least 6 characters.",
            400,
        )


def validate_allowed_field_ids(value: Any) -> list[int]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        raw_items = [item.strip() for item in value.split(",") if item.strip()]
    elif isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    else:
        raise AuthError(
            "INVALID_FIELD_IDS",
            "allowed_field_ids must be a list of non-negative integers.",
            400,
        )

    field_ids: list[int] = []
    for item in raw_items:
        if isinstance(item, bool):
            raise AuthError("INVALID_FIELD_IDS", "field_id must be a non-negative integer.", 400)
        if isinstance(item, int):
            field_id = item
        elif isinstance(item, str) and item.isdigit():
            field_id = int(item)
        else:
            raise AuthError("INVALID_FIELD_IDS", "field_id must be a non-negative integer.", 400)
        if field_id < 0:
            raise AuthError("INVALID_FIELD_IDS", "field_id must be a non-negative integer.", 400)
        field_ids.append(field_id)
    return sorted(set(field_ids))
