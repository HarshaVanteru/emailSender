import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.security import get_current_user
from app.features.ai_assistant.schemas import CopilotResponse, GeneratedEmail


class ApiVersioningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Route tests must not touch a real DB or initialize a real AI client.
        with patch.object(Base.metadata, "create_all"), patch("app.core.config.GROQ_API_KEY", "test-not-real"):
            from app.main import app
        cls.app = app

    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.app.dependency_overrides[get_db] = lambda: self.db
        self.key_patch = patch("app.core.config.TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
        self.key_patch.start()
        self.client = TestClient(self.app)

    def tearDown(self):
        self.app.dependency_overrides.clear()
        self.key_patch.stop()
        self.db.close()
        self.engine.dispose()

    def authorize(self):
        from app.features.google_login.user import User
        from app.features.google_login.models import ConnectedAccount
        self.user = User(
            email="sender@example.com", name="Sender", bio=None,
            signature=None, preferences=None, google_token="test-only-token",
        )
        self.db.add(self.user)
        self.db.flush()
        self.db.add(ConnectedAccount(user_id=self.user.id, gmail_email=self.user.email,
                                    encrypted_credentials="test-only", scopes="[]", requires_reauth=False))
        self.db.commit()
        self.app.dependency_overrides[get_current_user] = lambda: self.user

    def test_health_and_schema_preserve_legacy_routes_without_duplicate_prefixes(self):
        for prefix in ("/api", "/api/v1"):
            self.assertEqual(self.client.get(prefix + "/health").json()["status"], "healthy")
        paths = self.client.get("/openapi.json").json()["paths"]
        for path in (
            "/api/v1/health", "/api/v1/auth/google", "/api/v1/auth/google/callback",
            "/api/v1/gmail/profile", "/api/v1/gmail/send", "/api/v1/ai/generate-email",
        ):
            self.assertIn(path, paths)
        self.assertNotIn("/api/gmail/profile", paths)
        self.assertFalse(any("/api/api/" in path for path in paths))

    def test_old_and_new_mailbox_operations_require_authentication(self):
        for prefix in ("/api", "/api/v1"):
            self.assertEqual(self.client.get(prefix + "/gmail/profile").status_code, 401)
            self.assertEqual(self.client.put(prefix + "/gmail/profile", json={"name": "Test"}).status_code, 401)
            self.assertEqual(self.client.post(prefix + "/gmail/send", json={
                "to": "recipient@example.com", "subject": "Test", "body": "Hello",
            }).status_code, 401)
            self.assertEqual(self.client.post(prefix + "/ai/generate-email", json={
                "instruction": "Draft a greeting",
            }).status_code, 401)

    def test_profile_and_reviewed_send_work_through_both_versions(self):
        self.authorize()
        from app.features.google_login.routes import gmail_service, user_repository
        for prefix in ("/api", "/api/v1"):
            self.assertEqual(self.client.get(prefix + "/gmail/profile").json()["email"], self.user.email)
            with patch.object(user_repository, "update") as update:
                response = self.client.put(prefix + "/gmail/profile", json={"name": "Updated"})
                self.assertEqual(response.status_code, 200)
                update.assert_called_once()
            with patch.object(gmail_service, "send_email", return_value={"id": "mock-message"}) as send, patch(
                "app.features.google_login.accounts.credentials_for_user", return_value=MagicMock()):
                response = self.client.post(prefix + "/gmail/send", json={
                    "to": "recipient@example.com", "subject": "Test", "body": "Hello",
                })
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["message_id"], "mock-message")
                send.assert_called_once()

    def test_ai_returns_drafts_without_sending(self):
        self.authorize()
        from app.features.ai_assistant.routes import ai_service
        from app.features.google_login.routes import gmail_service
        suggestion = CopilotResponse(draft=GeneratedEmail(
            to="recipient@example.com", subject="Test", body="Hello",
        ))
        with patch.object(ai_service, "generate_email", return_value=suggestion) as model:
            with patch.object(gmail_service, "send_email") as send:
                for prefix in ("/api", "/api/v1"):
                    response = self.client.post(prefix + "/ai/generate-email", json={"instruction": "Draft a greeting"})
                    self.assertEqual(response.status_code, 202)
                    job_id = response.json()['id']
                    self.assertEqual(response.json()['status'], 'pending')
                model.assert_not_called()
                from sqlalchemy.orm import sessionmaker
                from app.workers.operations import process
                process('ai', job_id, sessionmaker(self.engine))
                status = self.client.get('/api/v1/ai/jobs/' + job_id)
                self.assertEqual(status.json()['result']['draft']['body'], 'Hello')
                send.assert_not_called()

    def test_oauth_aliases_share_state_and_reject_invalid_callbacks(self):
        from app.features.google_login.routes import gmail_service
        from app.features.google_login.models import OAuthAttempt
        flow = MagicMock()
        flow.authorization_url.return_value = ("https://accounts.google.com/test-auth", "mock-state")
        flow.code_verifier = "mock-verifier"
        paths = ("/api/gmail/auth", "/api/v1/gmail/auth", "/api/v1/auth/google")
        with patch.object(gmail_service, "create_google_flow", return_value=flow):
            for path in paths:
                response = self.client.get(path, follow_redirects=False)
                self.assertEqual(response.status_code, 307)
                self.assertEqual(response.headers["location"], "https://accounts.google.com/test-auth")
                self.assertIn("HttpOnly", response.headers["set-cookie"])
                self.assertEqual(flow.authorization_url.call_args.kwargs["code_challenge_method"], "S256")
        self.assertEqual(self.db.query(OAuthAttempt).count(), 3)
        for path in (
                "/api/gmail/auth/google/callback",
                "/api/v1/gmail/auth/google/callback", "/api/v1/auth/google/callback",
        ):
            response = self.client.get(path, params={"code": "mock", "state": "unknown-test-state"})
            self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
