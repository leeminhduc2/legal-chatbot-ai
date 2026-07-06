from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.config import Config
from backend.models.database import get_connection, init_db
from backend.services.auth_service import ROLE_BUSINESS_USER


class AuthUsersChatTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_cwd = os.getcwd()
        os.chdir(self.temp_dir.name)
        self.db_path = str(Path(self.temp_dir.name) / "app.sqlite3")
        self.config = Config(
            app_env="test",
            sqlite_db_path=self.db_path,
            admin_username="admin",
            admin_password="password",
            flask_secret_key="test-secret",
            llm_chunking_enabled=False,
        )
        from backend.app import create_app

        self.app = create_app(self.config)
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        os.chdir(self.old_cwd)
        self.temp_dir.cleanup()

    def test_register_endpoint_is_removed(self) -> None:
        response = self.client.post(
            "/api/v1/auth/register",
            json={"username": "free-user", "password": "secret1"},
        )

        self.assertEqual(response.status_code, 404)

    def test_business_user_chat_persists_conversation_history(self) -> None:
        token = self._create_business_user_and_login("business-user", "secret1")

        with patch("backend.api.chat_routes._get_chat_agent_service") as agent:
            agent.return_value = FakeChatAgentService()
            chat = self.client.post(
                "/api/v1/chat",
                headers=self._auth_headers(token),
                json={"message": "Dieu kien kinh doanh bao hiem la gi?"},
            )
        self.assertEqual(chat.status_code, 200, chat.get_data(as_text=True))
        chat_payload = chat.get_json()
        self.assertIn("conversation_id", chat_payload)

        conversations = self.client.get(
            "/api/v1/chat/conversations",
            headers=self._auth_headers(token),
        )
        self.assertEqual(conversations.status_code, 200, conversations.get_data(as_text=True))
        self.assertEqual(len(conversations.get_json()["conversations"]), 1)

        detail = self.client.get(
            f"/api/v1/chat/conversations/{chat_payload['conversation_id']}",
            headers=self._auth_headers(token),
        )
        self.assertEqual(detail.status_code, 200, detail.get_data(as_text=True))
        messages = detail.get_json()["messages"]
        self.assertEqual([message["role"] for message in messages], ["user", "assistant"])
        self.assertEqual(messages[1]["retrieval_mode"], "legal_lookup")
        self.assertEqual(messages[1]["warnings"][0]["code"], "LOW_RELEVANCE")
        self.assertEqual(messages[1]["agent_steps"][0]["phase"], "retrieval")
        self.assertEqual(messages[1]["tool_trace"][0]["tool"], "vector_search")
        self.assertEqual(messages[1]["agent_timeline"][0]["title"], "Tim can cu")

    def test_guest_chat_does_not_persist_history(self) -> None:
        with patch("backend.api.chat_routes._get_chat_agent_service") as agent:
            agent.return_value = FakeChatAgentService()
            chat = self.client.post("/api/v1/chat", json={"message": "Xin chao"})
        self.assertEqual(chat.status_code, 200, chat.get_data(as_text=True))
        self.assertNotIn("conversation_id", chat.get_json())
        self.assertEqual(chat.get_json()["retrieval_mode"], "legal_lookup")

        conversations = self.client.get("/api/v1/chat/conversations")
        self.assertEqual(conversations.status_code, 401)

    def test_authenticated_chat_passes_recent_memory_and_summary(self) -> None:
        token = self._create_business_user_and_login("business-user", "secret1")
        fake_agent = FakeChatAgentService()

        with patch("backend.api.chat_routes._get_chat_agent_service") as agent:
            agent.return_value = fake_agent
            first = self.client.post(
                "/api/v1/chat",
                headers=self._auth_headers(token),
                json={"message": "Cau hoi 1"},
            )
            conversation_id = first.get_json()["conversation_id"]
            for index in range(2, 6):
                response = self.client.post(
                    "/api/v1/chat",
                    headers=self._auth_headers(token),
                    json={
                        "message": f"Cau hoi {index}",
                        "conversation_id": conversation_id,
                    },
                )
                self.assertEqual(response.status_code, 200, response.get_data(as_text=True))

        last_context = fake_agent.contexts[-1]
        self.assertEqual(len(last_context["recent_messages"]), 5)
        self.assertTrue(last_context["summary"])
        self.assertGreater(last_context["older_message_count"], 0)

    def test_admin_can_manage_users_and_locked_user_cannot_login(self) -> None:
        admin_token = self._login("admin", "password")

        create = self.client.post(
            "/api/v1/admin/users",
            headers=self._auth_headers(admin_token),
            json={
                "username": "business-user",
                "password": "secret1",
                "role": ROLE_BUSINESS_USER,
            },
        )
        self.assertEqual(create.status_code, 201, create.get_data(as_text=True))
        user = create.get_json()["user"]
        self.assertEqual(user["role"], ROLE_BUSINESS_USER)

        invalid_role = self.client.patch(
            f"/api/v1/admin/users/{user['id']}",
            headers=self._auth_headers(admin_token),
            json={"role": "free_user"},
        )
        self.assertEqual(invalid_role.status_code, 400)
        self.assertEqual(invalid_role.get_json()["error"]["code"], "INVALID_ROLE")

        update = self.client.patch(
            f"/api/v1/admin/users/{user['id']}",
            headers=self._auth_headers(admin_token),
            json={"is_active": False},
        )
        self.assertEqual(update.status_code, 200, update.get_data(as_text=True))
        self.assertEqual(update.get_json()["user"]["role"], ROLE_BUSINESS_USER)
        self.assertFalse(update.get_json()["user"]["is_active"])

        login = self.client.post(
            "/api/v1/auth/login",
            json={"username": "business-user", "password": "secret1"},
        )
        self.assertEqual(login.status_code, 403)

    def test_non_admin_cannot_manage_users_and_admin_cannot_self_demote(self) -> None:
        user_token = self._create_business_user_and_login("business-user", "secret1")
        forbidden = self.client.get(
            "/api/v1/admin/users",
            headers=self._auth_headers(user_token),
        )
        self.assertEqual(forbidden.status_code, 403)

        admin_token = self._login("admin", "password")
        me = self.client.get("/api/v1/auth/me", headers=self._auth_headers(admin_token))
        admin_id = me.get_json()["user"]["id"]

        demote = self.client.patch(
            f"/api/v1/admin/users/{admin_id}",
            headers=self._auth_headers(admin_token),
            json={"role": ROLE_BUSINESS_USER},
        )
        self.assertEqual(demote.status_code, 400)
        self.assertEqual(demote.get_json()["error"]["code"], "CANNOT_CHANGE_OWN_ADMIN")

    def test_init_db_deletes_legacy_free_users_and_dependents(self) -> None:
        legacy_db = str(Path(self.temp_dir.name) / "legacy.sqlite3")
        connection = sqlite3.connect(legacy_db)
        try:
            connection.executescript(
                """
                CREATE TABLE users (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('admin', 'business_user', 'free_user', 'guest')),
                    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE auth_sessions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    token_hash TEXT NOT NULL UNIQUE,
                    expires_at TEXT NOT NULL,
                    revoked_at TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE chat_conversations (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    title TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE chat_messages (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE contract_review_jobs (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                INSERT INTO users VALUES ('admin-id', 'admin', 'hash', 'admin', 1, 'now', 'now');
                INSERT INTO users VALUES ('free-id', 'free-user', 'hash', 'free_user', 1, 'now', 'now');
                INSERT INTO auth_sessions VALUES ('session-id', 'free-id', 'token', '2999', NULL, 'now');
                INSERT INTO chat_conversations VALUES ('conv-id', 'free-id', 'title', 'now', 'now');
                INSERT INTO chat_messages VALUES ('msg-id', 'conv-id', 'assistant', 'hello', 'now');
                INSERT INTO contract_review_jobs VALUES ('job-id', 'free-id', 'file.docx', 'file.docx', 'completed', 'now', 'now');
                """
            )
            connection.commit()
        finally:
            connection.close()

        init_db(legacy_db)

        with get_connection(legacy_db) as connection:
            roles = [
                row["role"]
                for row in connection.execute("SELECT role FROM users").fetchall()
            ]
            self.assertEqual(roles, ["admin"])
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM auth_sessions").fetchone()[0],
                0,
            )
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM chat_conversations").fetchone()[0],
                0,
            )
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0],
                0,
            )
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM contract_review_jobs").fetchone()[0],
                0,
            )
            table_sql = connection.execute(
                """
                SELECT sql
                FROM sqlite_master
                WHERE type = 'table' AND name = 'users'
                """
            ).fetchone()["sql"]
            self.assertNotIn("free_user", table_sql)

    def _create_business_user_and_login(self, username: str, password: str) -> str:
        admin_token = self._login("admin", "password")
        response = self.client.post(
            "/api/v1/admin/users",
            headers=self._auth_headers(admin_token),
            json={
                "username": username,
                "password": password,
                "role": ROLE_BUSINESS_USER,
            },
        )
        self.assertEqual(response.status_code, 201, response.get_data(as_text=True))
        return self._login(username, password)

    def _login(self, username: str, password: str) -> str:
        response = self.client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": password},
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.get_json()["access_token"]

    @staticmethod
    def _auth_headers(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}


class FakeChatAgentService:
    def __init__(self):
        self.contexts = []

    def answer(
        self,
        message: str,
        *,
        user=None,
        requested_top_k=None,
        conversation_context=None,
    ) -> dict:
        self.contexts.append(conversation_context or {})
        return {
            "answer": "Mocked legal answer.",
            "response": "Mocked legal answer.",
            "query": message,
            "retrieval_mode": "legal_lookup",
            "confidence": 0.78,
            "warnings": [
                {"code": "LOW_RELEVANCE", "message": "Mocked warning."},
            ],
            "citations": [
                {
                    "citation_label": "01/2026/QH, Dieu 1",
                    "document_id": "doc-1",
                    "document_title": "Luat test",
                    "document_name": "Luat test",
                    "document_number": "01/2026/QH",
                    "article_number": "1",
                    "clause_number": None,
                    "article": "Dieu 1",
                    "validity_status": "active",
                    "is_active": True,
                    "chunk_id": "chunk-1",
                }
            ],
            "trace_id": "trace-test",
            "agent_steps": [
                {"phase": "retrieval", "message": "Mocked retrieval.", "status": "ok"}
            ],
            "tool_trace": [
                {
                    "tool": "vector_search",
                    "phase": "retrieval",
                    "input_summary": "mock query",
                    "result_count": 1,
                    "duration_ms": 3,
                    "status": "ok",
                    "warnings": [],
                }
            ],
            "memory_used": {
                "recent_message_count": len(
                    (conversation_context or {}).get("recent_messages", [])
                ),
                "summary_used": bool((conversation_context or {}).get("summary")),
            },
            "agent_timeline": [
                {
                    "title": "Tim can cu",
                    "description": "Da tim thay van ban lien quan.",
                    "status": "ok",
                }
            ],
        }


if __name__ == "__main__":
    unittest.main()
