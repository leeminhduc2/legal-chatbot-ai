from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from backend.config import Config
from backend.services.auth_service import ROLE_BUSINESS_USER, ROLE_FREE_USER


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

    def test_register_creates_active_free_user_and_token(self) -> None:
        response = self.client.post(
            "/api/v1/auth/register",
            json={"username": "free-user", "password": "secret1"},
        )

        self.assertEqual(response.status_code, 201, response.get_data(as_text=True))
        payload = response.get_json()
        self.assertEqual(payload["user"]["role"], ROLE_FREE_USER)
        self.assertTrue(payload["user"]["is_active"])
        self.assertIn("created_at", payload["user"])

        me = self.client.get(
            "/api/v1/auth/me",
            headers=self._auth_headers(payload["access_token"]),
        )
        self.assertEqual(me.status_code, 200, me.get_data(as_text=True))
        self.assertEqual(me.get_json()["user"]["username"], "free-user")

    def test_register_rejects_duplicate_and_short_password(self) -> None:
        created = self.client.post(
            "/api/v1/auth/register",
            json={"username": "free-user", "password": "secret1"},
        )
        self.assertEqual(created.status_code, 201, created.get_data(as_text=True))

        duplicate = self.client.post(
            "/api/v1/auth/register",
            json={"username": "free-user", "password": "secret1"},
        )
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(duplicate.get_json()["error"]["code"], "USERNAME_EXISTS")

        short_password = self.client.post(
            "/api/v1/auth/register",
            json={"username": "another-user", "password": "123"},
        )
        self.assertEqual(short_password.status_code, 400)
        self.assertEqual(short_password.get_json()["error"]["code"], "INVALID_PASSWORD")

    def test_free_user_chat_persists_conversation_history(self) -> None:
        token = self._register("free-user", "secret1")

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

    def test_guest_chat_does_not_persist_history(self) -> None:
        chat = self.client.post("/api/v1/chat", json={"message": "Xin chao"})
        self.assertEqual(chat.status_code, 200, chat.get_data(as_text=True))
        self.assertNotIn("conversation_id", chat.get_json())

        conversations = self.client.get("/api/v1/chat/conversations")
        self.assertEqual(conversations.status_code, 401)

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

        update = self.client.patch(
            f"/api/v1/admin/users/{user['id']}",
            headers=self._auth_headers(admin_token),
            json={"role": ROLE_FREE_USER, "is_active": False},
        )
        self.assertEqual(update.status_code, 200, update.get_data(as_text=True))
        self.assertEqual(update.get_json()["user"]["role"], ROLE_FREE_USER)
        self.assertFalse(update.get_json()["user"]["is_active"])

        login = self.client.post(
            "/api/v1/auth/login",
            json={"username": "business-user", "password": "secret1"},
        )
        self.assertEqual(login.status_code, 403)

    def test_non_admin_cannot_manage_users_and_admin_cannot_self_demote(self) -> None:
        user_token = self._register("free-user", "secret1")
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
            json={"role": ROLE_FREE_USER},
        )
        self.assertEqual(demote.status_code, 400)
        self.assertEqual(demote.get_json()["error"]["code"], "CANNOT_CHANGE_OWN_ADMIN")

    def _register(self, username: str, password: str) -> str:
        response = self.client.post(
            "/api/v1/auth/register",
            json={"username": username, "password": password},
        )
        self.assertEqual(response.status_code, 201, response.get_data(as_text=True))
        return response.get_json()["access_token"]

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


if __name__ == "__main__":
    unittest.main()
