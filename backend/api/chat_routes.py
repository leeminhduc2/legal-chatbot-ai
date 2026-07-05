from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from flask import Blueprint, current_app, g, jsonify, request

from backend.api.decorators import error_response, extract_bearer_token, require_auth
from backend.models.database import get_connection, row_to_dict
from backend.services.auth_service import AuthService


chat_bp = Blueprint("chat", __name__, url_prefix="/api/v1/chat")


@chat_bp.post("")
def chat():
    payload = request.get_json(silent=True) or {}
    message = str(payload.get("message", "")).strip()
    if not message:
        return error_response("MESSAGE_REQUIRED", "Message is required.", 400)

    user = _get_optional_user()
    conversation_id = payload.get("conversation_id")
    answer_payload = _build_fallback_answer(message)

    if user is None:
        return jsonify(answer_payload)

    service = _get_chat_history_service()
    try:
        conversation = service.ensure_conversation(
            user_id=user["id"],
            conversation_id=str(conversation_id).strip() if conversation_id else "",
            first_message=message,
        )
    except ValueError:
        return error_response("CONVERSATION_NOT_FOUND", "Conversation not found.", 404)
    service.add_message(
        conversation_id=conversation["id"],
        role="user",
        content=message,
    )
    service.add_message(
        conversation_id=conversation["id"],
        role="assistant",
        content=answer_payload["answer"],
        citations=answer_payload["citations"],
        confidence=answer_payload["confidence"],
    )

    return jsonify(
        {
            **answer_payload,
            "conversation_id": conversation["id"],
            "conversation": conversation,
        }
    )


@chat_bp.get("/conversations")
@require_auth
def list_conversations():
    return jsonify(
        {
            "conversations": _get_chat_history_service().list_conversations(
                user_id=g.current_user["id"],
            )
        }
    )


@chat_bp.get("/conversations/<conversation_id>")
@require_auth
def get_conversation(conversation_id: str):
    conversation = _get_chat_history_service().get_conversation(
        user_id=g.current_user["id"],
        conversation_id=conversation_id,
    )
    if conversation is None:
        return error_response("CONVERSATION_NOT_FOUND", "Conversation not found.", 404)
    return jsonify(conversation)


class ChatHistoryService:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def ensure_conversation(
        self,
        user_id: str,
        conversation_id: str,
        first_message: str,
    ) -> dict[str, Any]:
        if conversation_id:
            conversation = self.get_conversation(user_id, conversation_id)
            if conversation is None:
                raise ValueError("Conversation not found.")
            return conversation["conversation"]

        now = utc_now_iso()
        new_conversation = {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "title": make_title(first_message),
            "created_at": now,
            "updated_at": now,
        }
        with get_connection(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO chat_conversations (id, user_id, title, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    new_conversation["id"],
                    user_id,
                    new_conversation["title"],
                    now,
                    now,
                ),
            )
            connection.commit()
        return new_conversation

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        citations: list[dict[str, Any]] | None = None,
        confidence: float | None = None,
    ) -> dict[str, Any]:
        now = utc_now_iso()
        message = {
            "id": str(uuid.uuid4()),
            "conversation_id": conversation_id,
            "role": role,
            "content": content,
            "citations": citations or [],
            "confidence": confidence,
            "created_at": now,
        }
        with get_connection(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO chat_messages (
                    id, conversation_id, role, content, citations_json, confidence, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message["id"],
                    conversation_id,
                    role,
                    content,
                    json.dumps(message["citations"], ensure_ascii=False),
                    confidence,
                    now,
                ),
            )
            connection.execute(
                """
                UPDATE chat_conversations
                SET updated_at = ?
                WHERE id = ?
                """,
                (now, conversation_id),
            )
            connection.commit()
        return message

    def list_conversations(self, user_id: str) -> list[dict[str, Any]]:
        with get_connection(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT id, user_id, title, created_at, updated_at
                FROM chat_conversations
                WHERE user_id = ?
                ORDER BY updated_at DESC
                """,
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_conversation(
        self,
        user_id: str,
        conversation_id: str,
    ) -> dict[str, Any] | None:
        with get_connection(self.db_path) as connection:
            conversation_row = connection.execute(
                """
                SELECT id, user_id, title, created_at, updated_at
                FROM chat_conversations
                WHERE id = ? AND user_id = ?
                """,
                (conversation_id, user_id),
            ).fetchone()
            if conversation_row is None:
                return None

            message_rows = connection.execute(
                """
                SELECT id, conversation_id, role, content, citations_json, confidence, created_at
                FROM chat_messages
                WHERE conversation_id = ?
                ORDER BY created_at ASC
                """,
                (conversation_id,),
            ).fetchall()

        return {
            "conversation": dict(conversation_row),
            "messages": [format_message(row_to_dict(row)) for row in message_rows],
        }


def _build_fallback_answer(message: str) -> dict[str, Any]:
    return {
        "answer": (
            "Tôi đã ghi nhận câu hỏi của bạn. Chức năng truy xuất pháp lý đang "
            "được kết nối với kho dữ liệu đã xuất bản; vui lòng kiểm tra trích dẫn "
            "trước khi sử dụng nội dung này cho quyết định pháp lý."
        ),
        "response": (
            "Tôi đã ghi nhận câu hỏi của bạn. Chức năng truy xuất pháp lý đang "
            "được kết nối với kho dữ liệu đã xuất bản; vui lòng kiểm tra trích dẫn "
            "trước khi sử dụng nội dung này cho quyết định pháp lý."
        ),
        "citations": [],
        "confidence": None,
        "query": message,
    }


def _get_optional_user() -> dict[str, Any] | None:
    token = extract_bearer_token()
    if not token:
        return None
    return _get_auth_service().get_user_for_token(token)


def _get_auth_service() -> AuthService:
    app_config = current_app.config["APP_CONFIG"]
    return AuthService(
        db_path=app_config.sqlite_db_path,
        token_ttl_hours=app_config.token_ttl_hours,
    )


def _get_chat_history_service() -> ChatHistoryService:
    return ChatHistoryService(current_app.config["APP_CONFIG"].sqlite_db_path)


def format_message(message: dict[str, Any] | None) -> dict[str, Any]:
    if message is None:
        return {}
    try:
        citations = json.loads(message.get("citations_json") or "[]")
    except json.JSONDecodeError:
        citations = []
    return {
        "id": message["id"],
        "conversation_id": message["conversation_id"],
        "role": message["role"],
        "content": message["content"],
        "citations": citations,
        "confidence": message["confidence"],
        "created_at": message["created_at"],
    }


def make_title(message: str) -> str:
    title = " ".join(message.split())
    if len(title) > 60:
        return f"{title[:57]}..."
    return title or "Conversation"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
