from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from flask import Blueprint, current_app, g, jsonify, request

from backend.api.decorators import error_response, extract_bearer_token, require_auth
from backend.models.database import get_connection, row_to_dict
from backend.services.auth_service import AuthService
from backend.services.chat_agent_service import ChatAgentService


chat_bp = Blueprint("chat", __name__, url_prefix="/api/v1/chat")


@chat_bp.post("")
def chat():
    payload = request.get_json(silent=True) or {}
    message = str(payload.get("message", "")).strip()
    if not message:
        return error_response("MESSAGE_REQUIRED", "Message is required.", 400)

    user = _get_optional_user()
    conversation_id = payload.get("conversation_id")
    app_config = current_app.config["APP_CONFIG"]
    history_service = _get_chat_history_service()
    conversation: dict[str, Any] | None = None
    conversation_context: dict[str, Any] = {}

    if user is not None:
        try:
            conversation = history_service.ensure_conversation(
                user_id=user["id"],
                conversation_id=str(conversation_id).strip() if conversation_id else "",
                first_message=message,
            )
        except ValueError:
            return error_response("CONVERSATION_NOT_FOUND", "Conversation not found.", 404)
        conversation_context = history_service.get_conversation_context(
            user_id=user["id"],
            conversation_id=conversation["id"],
            recent_limit=app_config.chat_memory_recent_messages,
            summary_enabled=app_config.chat_memory_summary_enabled,
        )

    answer_payload = _get_chat_agent_service().answer(
        message,
        user=user,
        requested_top_k=payload.get("top_k"),
        conversation_context=conversation_context,
    )

    if user is None:
        return jsonify(answer_payload)

    assert conversation is not None
    history_service.add_message(
        conversation_id=conversation["id"],
        role="user",
        content=message,
    )
    history_service.add_message(
        conversation_id=conversation["id"],
        role="assistant",
        content=answer_payload["answer"],
        citations=answer_payload["citations"],
        confidence=answer_payload["confidence"],
        metadata={
            "warnings": answer_payload.get("warnings", []),
            "retrieval_mode": answer_payload.get("retrieval_mode"),
            "trace_id": answer_payload.get("trace_id"),
            "agent_steps": answer_payload.get("agent_steps", []),
            "tool_trace": answer_payload.get("tool_trace", []),
            "memory_used": answer_payload.get("memory_used", {}),
            "agent_timeline": answer_payload.get("agent_timeline", []),
        },
    )
    history_service.refresh_summary(
        conversation_id=conversation["id"],
        recent_limit=app_config.chat_memory_recent_messages,
        summary_enabled=app_config.chat_memory_summary_enabled,
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
            "summary": "",
            "summary_updated_at": None,
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
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = utc_now_iso()
        message = {
            "id": str(uuid.uuid4()),
            "conversation_id": conversation_id,
            "role": role,
            "content": content,
            "citations": citations or [],
            "confidence": confidence,
            "metadata": metadata or {},
            "created_at": now,
        }
        with get_connection(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO chat_messages (
                    id, conversation_id, role, content, citations_json, confidence,
                    metadata_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message["id"],
                    conversation_id,
                    role,
                    content,
                    json.dumps(message["citations"], ensure_ascii=False),
                    confidence,
                    json.dumps(message["metadata"], ensure_ascii=False),
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
                SELECT id, user_id, title, summary, summary_updated_at,
                       created_at, updated_at
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
                SELECT id, user_id, title, summary, summary_updated_at,
                       created_at, updated_at
                FROM chat_conversations
                WHERE id = ? AND user_id = ?
                """,
                (conversation_id, user_id),
            ).fetchone()
            if conversation_row is None:
                return None

            message_rows = connection.execute(
                """
                SELECT id, conversation_id, role, content, citations_json, confidence,
                       metadata_json, created_at
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

    def get_conversation_context(
        self,
        user_id: str,
        conversation_id: str,
        recent_limit: int,
        summary_enabled: bool,
    ) -> dict[str, Any]:
        conversation = self.get_conversation(user_id, conversation_id)
        if conversation is None:
            return {"summary": "", "recent_messages": [], "older_message_count": 0}
        messages = conversation.get("messages", [])
        limit = max(1, int(recent_limit or 5))
        recent_messages = messages[-limit:]
        older_messages = messages[:-limit]
        summary = ""
        if summary_enabled:
            summary = conversation["conversation"].get("summary") or ""
            if older_messages and not summary:
                summary = build_conversation_summary(older_messages)
        return {
            "summary": summary,
            "recent_messages": [compact_history_message(item) for item in recent_messages],
            "older_message_count": len(older_messages),
        }

    def refresh_summary(
        self,
        conversation_id: str,
        recent_limit: int,
        summary_enabled: bool,
    ) -> None:
        if not summary_enabled:
            return
        limit = max(1, int(recent_limit or 5))
        with get_connection(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT id, conversation_id, role, content, citations_json, confidence,
                       metadata_json, created_at
                FROM chat_messages
                WHERE conversation_id = ?
                ORDER BY created_at ASC
                """,
                (conversation_id,),
            ).fetchall()
            messages = [format_message(row_to_dict(row)) for row in rows]
            summary = build_conversation_summary(messages[:-limit])
            now = utc_now_iso()
            connection.execute(
                """
                UPDATE chat_conversations
                SET summary = ?, summary_updated_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (summary, now if summary else None, now, conversation_id),
            )
            connection.commit()


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


def _get_chat_agent_service() -> ChatAgentService:
    service = current_app.extensions.get("chat_agent_service")
    if service is None:
        service = ChatAgentService(current_app.config["APP_CONFIG"])
        current_app.extensions["chat_agent_service"] = service
    return service


def format_message(message: dict[str, Any] | None) -> dict[str, Any]:
    if message is None:
        return {}
    try:
        citations = json.loads(message.get("citations_json") or "[]")
    except json.JSONDecodeError:
        citations = []
    try:
        metadata = json.loads(message.get("metadata_json") or "{}")
    except json.JSONDecodeError:
        metadata = {}
    return {
        "id": message["id"],
        "conversation_id": message["conversation_id"],
        "role": message["role"],
        "content": message["content"],
        "citations": citations,
        "confidence": message["confidence"],
        "warnings": metadata.get("warnings", []),
        "retrieval_mode": metadata.get("retrieval_mode"),
        "trace_id": metadata.get("trace_id"),
        "agent_steps": metadata.get("agent_steps", []),
        "tool_trace": metadata.get("tool_trace", []),
        "memory_used": metadata.get("memory_used", {}),
        "agent_timeline": metadata.get("agent_timeline", []),
        "metadata": metadata,
        "created_at": message["created_at"],
    }


def make_title(message: str) -> str:
    title = " ".join(message.split())
    if len(title) > 60:
        return f"{title[:57]}..."
    return title or "Conversation"


def compact_history_message(message: dict[str, Any]) -> dict[str, str]:
    return {
        "role": str(message.get("role") or ""),
        "content": trim_words(str(message.get("content") or ""), 120),
    }


def build_conversation_summary(messages: list[dict[str, Any]]) -> str:
    if not messages:
        return ""
    lines = []
    for item in messages[-12:]:
        role = str(item.get("role") or "message")
        content = trim_words(str(item.get("content") or ""), 60)
        if content:
            lines.append(f"{role}: {content}")
    return trim_words(" | ".join(lines), 240)


def trim_words(text: str, max_words: int) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + "..."


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
