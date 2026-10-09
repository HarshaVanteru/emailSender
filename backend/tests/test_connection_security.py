import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit

import requests
from alembic import command
from alembic.config import Config
from cryptography.fernet import Fernet
from fastapi import HTTPException
from fastapi.testclient import TestClient
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.security import get_current_user
from app.core.token_crypto import decrypt, encrypt
from app.models.connection import ConnectedAccount, OAuthAttempt
from app.models.user import User
from app.services import account_service, oauth_state


def credentials(refresh="refresh-secret", expired=False, scopes=None):
    return Credentials(token="access-secret", refresh_token=refresh,
                       token_uri="https://oauth2.googleapis.com/token", client_id="client",
                       client_secret="client-secret", scopes=scopes or ["https://www.googleapis.com/auth/gmail.send"],
                       expiry=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=-1 if expired else 1))


class ConnectionSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch("app.core.config.GROQ_API_KEY", "test-not-real"):
            from app.main import app
        cls.app = app

    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.key_patch = patch("app.core.config.TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
        self.key_patch.start()
        self.secret_patch = patch("app.core.config.SECRET_KEY", "test-signing-key-with-at-least-32-characters")
        self.secret_patch.start()
        self.user = User(email="owner@example.com")
        self.other = User(email="other@example.com")
        self.db.add_all([self.user, self.other])
        self.db.commit()
        self.app.dependency_overrides[get_db] = lambda: self.db
        self.app.dependency_overrides[get_current_user] = lambda: self.user
        self.client = TestClient(self.app)

    def tearDown(self):
        self.app.dependency_overrides.clear()
        self.key_patch.stop()
        self.secret_patch.stop()
        self.db.close()
        self.engine.dispose()

    def test_state_survives_session_restart_and_is_single_use_browser_bound(self):
        state, browser, verifier = oauth_state.create_attempt(self.db)
        stored = self.db.query(OAuthAttempt).one()
        self.assertNotIn(verifier, stored.encrypted_verifier)
        with Session(self.engine) as fresh_session:
            with self.assertRaises(ValueError):
                oauth_state.consume_attempt(fresh_session, state, "wrong-browser")
            self.assertEqual(oauth_state.consume_attempt(fresh_session, state, browser).verifier, verifier)
            with self.assertRaises(ValueError):
                oauth_state.consume_attempt(fresh_session, state, browser)

    def test_pre_upgrade_pending_attempt_defaults_to_original_send_scopes(self):
        from app.core.config import GMAIL_SCOPES
        state, browser, _ = oauth_state.create_attempt(self.db)
        row = self.db.get(OAuthAttempt, oauth_state.digest(state))
        row.requested_scopes = None
        self.db.commit()
        self.assertEqual(oauth_state.consume_attempt(self.db, state, browser).scopes, GMAIL_SCOPES)

    def test_expired_state_is_rejected_without_token_exchange(self):
        state, browser, _ = oauth_state.create_attempt(self.db)
        self.db.query(OAuthAttempt).update({"expires_at": oauth_state.now() - timedelta(seconds=1)})
        self.db.commit()
        self.client.cookies.set(oauth_state.cookie_name(state), browser, path="/api")
        with patch("app.controllers.gmail_controller.gmail_service.create_google_flow") as create:
            response = self.client.get("/api/v1/auth/google/callback", params={"state": state, "code": "code"})
        self.assertEqual(response.status_code, 400)
        create.assert_not_called()

    def test_missing_encryption_key_fails_closed(self):
        with patch("app.core.config.TOKEN_ENCRYPTION_KEY", None):
            response = self.client.get("/api/v1/auth/google", follow_redirects=False)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.db.query(OAuthAttempt).count(), 0)

    def test_insecure_signing_key_is_rejected(self):
        from app.core.security import create_access_token
        with patch("app.core.config.SECRET_KEY", "your-super-secret-key-for-jwt"):
            with self.assertRaises(HTTPException) as result:
                create_access_token({"sub": self.user.email})
        self.assertEqual(result.exception.status_code, 503)

    def test_pkce_challenge_matches_persisted_verifier_and_consent_is_optional(self):
        import base64
        import hashlib
        flow = MagicMock()
        flow.authorization_url.return_value = ("https://accounts.google.com/test", "ignored")
        with patch("app.controllers.gmail_controller.gmail_service.create_google_flow", return_value=flow):
            for renew in (False, True):
                response = self.client.get("/api/v1/auth/google", params={"renew_consent": str(renew).lower()}, follow_redirects=False)
                args = flow.authorization_url.call_args.kwargs
                row = self.db.get(OAuthAttempt, oauth_state.digest(args["state"]))
                verifier = decrypt(row.encrypted_verifier)
                challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
                self.assertEqual(args["code_challenge"], challenge)
                self.assertEqual(args.get("prompt"), "consent" if renew else None)
                self.assertIn("SameSite=lax", response.headers["set-cookie"])

    def callback(self, creds, info=None, mailbox=None):
        state, browser, verifier = oauth_state.create_attempt(self.db, creds.scopes)
        self.client.cookies.set(oauth_state.cookie_name(state), browser, path="/api")
        flow = MagicMock(credentials=creds)
        userinfo = MagicMock()
        userinfo.json.return_value = info or {"email": self.user.email, "email_verified": True}
        service = MagicMock()
        service.users.return_value.getProfile.return_value.execute.return_value = mailbox
        with patch("app.controllers.gmail_controller.gmail_service.create_google_flow", return_value=flow) as create_flow, patch(
            "app.controllers.gmail_controller.requests.get", return_value=userinfo), patch(
            "app.controllers.gmail_controller.gmail_service.get_gmail_service", return_value=service):
            response = self.client.get("/api/v1/auth/google/callback", params={"state": state, "code": "code"}, follow_redirects=False)
        self.assertEqual(flow.code_verifier, verifier)
        create_flow.assert_called_once_with(scopes=creds.scopes)
        return response, service

    def test_mailbox_permission_is_opt_in_and_persisted_in_oauth_attempt(self):
        from app.core.config import GMAIL_READ_SCOPE
        flow = MagicMock()
        flow.authorization_url.return_value = ("https://accounts.google.com/test", "ignored")
        with patch("app.controllers.gmail_controller.gmail_service.create_google_flow", return_value=flow) as create:
            for enable in (False, True):
                response = self.client.get("/api/v1/auth/google", params={"mailbox_access": str(enable).lower()}, follow_redirects=False)
                self.assertEqual(response.status_code, 307)
                scopes = create.call_args.kwargs["scopes"]
                self.assertEqual(GMAIL_READ_SCOPE in scopes, enable)
                state = flow.authorization_url.call_args.kwargs["state"]
                row = self.db.get(OAuthAttempt, oauth_state.digest(state))
                self.assertEqual(json.loads(row.requested_scopes), scopes)

    def test_callback_encrypts_preserves_refresh_and_uses_fragment(self):
        account = account_service.save_connection(self.db, self.user, credentials())
        response, service = self.callback(credentials(refresh=None))
        self.assertEqual(response.status_code, 307)
        self.assertIn("token", parse_qs(urlsplit(response.headers["location"]).fragment))
        self.assertNotIn("token", urlsplit(response.headers["location"]).query)
        self.assertEqual(json.loads(decrypt(account.encrypted_credentials))["refresh_token"], "refresh-secret")
        self.assertNotIn("access-secret", account.encrypted_credentials)
        self.assertIsNone(self.user.google_token)
        service.users.assert_not_called()  # Send-only grants cannot call Gmail profile.

    def test_mailbox_profile_is_checked_when_scope_allows_it(self):
        creds = credentials(scopes=["https://www.googleapis.com/auth/gmail.readonly"])
        response, service = self.callback(creds, mailbox={"emailAddress": self.user.email, "historyId": "123"})
        self.assertEqual(response.status_code, 307)
        self.assertEqual(account_service.find_account(self.db, self.user).profile_history_id, "123")
        service.users.return_value.getProfile.assert_called_once_with(userId="me")

    def test_gmail_client_accepts_fresh_returning_grant_without_refresh_token(self):
        from app.services.gmail_service import gmail_service
        creds = credentials(refresh=None)
        with patch("app.services.gmail_service.build") as build:
            gmail_service.get_gmail_service(creds.to_json())
        restored = build.call_args.kwargs["http"].credentials
        self.assertEqual(restored.token, "access-secret")
        self.assertIsNone(restored.refresh_token)
        self.assertTrue(restored.valid)

    def test_token_exchange_tracks_actual_incremental_or_partial_granted_scopes(self):
        from google_auth_oauthlib.flow import Flow
        from app.services.gmail_service import gmail_service
        send = "https://www.googleapis.com/auth/gmail.send"
        read = "https://www.googleapis.com/auth/gmail.readonly"
        settings = {"web": {"client_id": "test-client", "client_secret": "test-secret",
                            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                            "token_uri": "https://oauth2.googleapis.com/token"}}
        for requested, granted in (([send], [send, read]), ([send, read], [send])):
            flow = Flow.from_client_config(settings, scopes=requested, redirect_uri="https://local.invalid/callback")
            response = requests.Response()
            response.status_code = 200
            response._content = json.dumps({"access_token": "test-access", "token_type": "Bearer", "expires_in": 3600,
                                            "refresh_token": "test-refresh", "scope": " ".join(granted)}).encode()
            response.request = requests.Request("POST", "https://oauth2.googleapis.com/token").prepare()
            with patch.object(flow.oauth2session, "request", return_value=response):
                loaded = gmail_service.exchange_google_code(flow, "test-code")
            self.assertEqual(set(loaded.granted_scopes), set(granted))
            self.assertEqual(set(loaded.scopes), set(granted))

    def test_callback_rejects_unverified_identity_and_mailbox_mismatch(self):
        response, _ = self.callback(credentials(), info={"email": self.user.email, "email_verified": False})
        self.assertEqual(response.status_code, 400)
        response, _ = self.callback(credentials(scopes=["https://www.googleapis.com/auth/gmail.readonly"]),
                                    mailbox={"emailAddress": self.other.email})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.db.query(ConnectedAccount).count(), 0)

    def test_cancelled_consent_consumes_state(self):
        state, browser, _ = oauth_state.create_attempt(self.db)
        self.client.cookies.set(oauth_state.cookie_name(state), browser, path="/api")
        response = self.client.get("/api/v1/auth/google/callback", params={"state": state, "error": "access_denied"}, follow_redirects=False)
        self.assertEqual(response.status_code, 307)
        self.assertIn("auth=cancelled", response.headers["location"])
        self.assertIsNone(self.db.get(OAuthAttempt, oauth_state.digest(state)))

    def test_refresh_is_saved_encrypted_before_send(self):
        account = account_service.save_connection(self.db, self.user, credentials(expired=True))
        def refresh(creds, request):
            creds.token = "new-access-secret"
            creds.expiry = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1)
        with patch.object(Credentials, "refresh", autospec=True, side_effect=refresh) as refresh_mock:
            loaded = account_service.credentials_for_user(self.db, self.user)
        refresh_mock.assert_called_once()
        self.assertEqual(loaded.token, "new-access-secret")
        self.assertEqual(json.loads(decrypt(account.encrypted_credentials))["token"], "new-access-secret")

    def test_invalid_refresh_marks_reconnect_and_temporary_failure_does_not(self):
        account = account_service.save_connection(self.db, self.user, credentials(expired=True))
        for retryable in (True, False):
            with patch.object(Credentials, "refresh", side_effect=RefreshError("not exposed", retryable=retryable)):
                with self.assertRaises(HTTPException) as result:
                    account_service.credentials_for_user(self.db, self.user)
            self.assertEqual(result.exception.status_code, 503 if retryable else 409)
            self.assertEqual(account.requires_reauth, not retryable)

    def test_account_isolation_and_no_credential_disclosure(self):
        own = account_service.save_connection(self.db, self.user, credentials())
        other = account_service.save_connection(self.db, self.other, credentials())
        response = self.client.get("/api/v1/accounts")
        self.assertEqual([row["id"] for row in response.json()], [own.id])
        self.assertNotIn("secret", response.text)
        with patch("app.services.account_service.requests.post") as revoke:
            self.assertEqual(self.client.delete(f"/api/v1/accounts/{other.id}").status_code, 404)
        revoke.assert_not_called()
        self.app.dependency_overrides.pop(get_current_user)
        self.assertEqual(self.client.get("/api/v1/accounts").status_code, 401)

    def test_disconnect_revokes_and_disables_send_while_preserving_preferences(self):
        self.user.signature = "Keep this signature"
        account = account_service.save_connection(self.db, self.user, credentials())
        with patch("app.services.account_service.requests.post", return_value=MagicMock(status_code=200)) as revoke:
            response = self.client.delete(f"/api/v1/accounts/{account.id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(revoke.call_args.kwargs["data"]["token"], "refresh-secret")
        self.assertIsNone(account.encrypted_credentials)
        self.assertEqual(self.user.signature, "Keep this signature")
        self.assertFalse(self.client.get("/api/v1/gmail/profile").json()["is_connected"])
        with patch("app.controllers.gmail_controller.gmail_service.send_email") as send:
            response = self.client.post("/api/v1/gmail/send", json={"to": "test@example.com", "subject": "Test", "body": "Hello"})
        self.assertEqual(response.status_code, 409)
        send.assert_not_called()

    def test_revocation_failure_retains_connection_for_retry(self):
        account = account_service.save_connection(self.db, self.user, credentials())
        with patch("app.services.account_service.requests.post", side_effect=requests.Timeout()):
            response = self.client.delete(f"/api/v1/accounts/{account.id}")
        self.assertEqual(response.status_code, 502)
        self.assertTrue(account.encrypted_credentials)


class ConnectionMigrationTests(unittest.TestCase):
    def test_fresh_upgrade_and_legacy_credential_roundtrip(self):
        engine = create_engine("sqlite://")
        config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        with engine.begin() as connection, patch("app.core.config.TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode()):
            config.attributes["connection"] = connection
            command.upgrade(config, "0001")
            token = credentials().to_json()
            connection.execute(text("INSERT INTO users (id,email,google_token) VALUES (1,'owner@example.com',:token)"), {"token": token})
            command.upgrade(config, "head")
            encrypted = connection.execute(text("SELECT encrypted_credentials FROM connected_accounts")).scalar_one()
            self.assertEqual(decrypt(encrypted), token)
            self.assertIsNone(connection.execute(text("SELECT google_token FROM users")).scalar_one())
            command.downgrade(config, "0001")
            self.assertEqual(connection.execute(text("SELECT google_token FROM users")).scalar_one(), token)
            command.upgrade(config, "head")
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
