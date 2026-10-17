"""Gmail push stays a hint; no live Google, Redis, or mail delivery."""
import base64
import importlib.util
import json
import unittest
from datetime import timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.core.database import Base
from app.core.database import get_db
from app.main import app
from app.features.google_login.models import ConnectedAccount
from app.features.mailbox.models import SyncJob
from app.features.google_login.user import User
from app.features.mail_sync import push as push
from app.features.mail_sync.service import utcnow
from test_gmail_sync import READ_SCOPE


class PushTests(unittest.TestCase):
    def setUp(self):
        self.config = patch.multiple(push.config,
            GMAIL_PUSH_TOPIC="projects/demo/topics/gmail",
            PUBSUB_PUSH_AUDIENCE="https://example.com/api/v1/webhooks/gmail/pubsub",
            PUBSUB_PUSH_SERVICE_ACCOUNT="push@example.iam.gserviceaccount.com",
            PUBSUB_SUBSCRIPTION="projects/demo/subscriptions/gmail-push")
        self.config.start()
        self.engine = create_engine("sqlite://", poolclass=StaticPool,
                                    connect_args={"check_same_thread": False})
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(self.engine, autoflush=False)
        self.db = self.sessions()
        user = User(email="owner@example.com")
        self.db.add(user)
        self.db.flush()
        self.account = ConnectedAccount(user_id=user.id, gmail_email=user.email,
            encrypted_credentials="opaque", scopes=json.dumps([READ_SCOPE]), history_id="100")
        self.db.add(self.account)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        self.config.stop()

    def envelope(self, *, email="owner@example.com", cursor="101", subscription=None):
        data = base64.b64encode(json.dumps({"emailAddress": email, "historyId": cursor}).encode()).decode()
        return json.dumps({"subscription": subscription or push.config.PUBSUB_SUBSCRIPTION,
                           "message": {"messageId": "m1", "data": data}}).encode()

    def test_push_token_rejects_wrong_claims_and_missing_configuration(self):
        claims = {"iss": "https://accounts.google.com", "email": push.config.PUBSUB_PUSH_SERVICE_ACCOUNT,
                  "email_verified": True}
        with patch.object(push.id_token, "verify_oauth2_token", return_value=claims) as verify:
            push.verify_push_token("Bearer token")
            self.assertEqual(verify.call_args.kwargs["audience"], push.config.PUBSUB_PUSH_AUDIENCE)
            for altered in ({**claims, "email": "other@example.com"},
                            {**claims, "email_verified": False}, {**claims, "iss": "evil.example"}):
                verify.return_value = altered
                with self.assertRaises(HTTPException) as caught:
                    push.verify_push_token("Bearer token")
                self.assertEqual(caught.exception.status_code, 401)
        with patch.object(push.config, "GMAIL_PUSH_TOPIC", ""):
            with self.assertRaises(HTTPException) as caught:
                push.verify_push_token("Bearer token")
            self.assertEqual(caught.exception.status_code, 503)

    def test_envelope_validation_and_notifications_do_not_advance_cursor(self):
        for body in (self.envelope(subscription="projects/demo/subscriptions/other"),
                     b'{"message":{"data":"!!!","messageId":"m1"}}',
                     self.envelope(cursor="bad")):
            with self.assertRaises(HTTPException) as caught:
                push.parse_push(body)
            self.assertEqual(caught.exception.status_code, 400)
        email, cursor = push.parse_push(self.envelope())
        with patch.object(push, "dispatch_job") as dispatch:
            push.accept_notification(self.db, email, cursor)
            push.accept_notification(self.db, email, cursor)
            self.assertEqual(self.db.query(SyncJob).count(), 1)
            self.assertEqual(self.account.history_id, "100")
            self.assertEqual(dispatch.call_count, 2)
            push.accept_notification(self.db, email, "100")
            push.accept_notification(self.db, "unknown@example.com", "102")
            self.assertEqual(self.db.query(SyncJob).count(), 1)

    def test_failed_publish_keeps_durable_job(self):
        email, cursor = push.parse_push(self.envelope())
        from app.features.mail_sync.jobs import dispatch_job
        with patch.object(push, "dispatch_job", side_effect=lambda db, jid: dispatch_job(
                db, jid, publisher=lambda _jid: (_ for _ in ()).throw(RuntimeError("offline")))):
            push.accept_notification(self.db, email, cursor)
        job = self.db.query(SyncJob).one()
        self.assertEqual((job.status, job.error_code), ("queued", "queue_unavailable"))
        self.assertEqual(self.account.history_id, "100")

    def test_http_push_accepts_durable_job_and_rejects_invalid_token(self):
        app.dependency_overrides[get_db] = lambda: self.db
        try:
            client = TestClient(app)
            with patch("app.features.mail_sync.push_routes.verify_push_token", side_effect=HTTPException(401, "invalid")):
                response = client.post("/api/v1/webhooks/gmail/pubsub", content=self.envelope(),
                                       headers={"Authorization": "Bearer invalid"})
                self.assertEqual(response.status_code, 401)
                self.assertEqual(self.db.query(SyncJob).count(), 0)
            with patch("app.features.mail_sync.push_routes.verify_push_token"), \
                 patch.object(push, "dispatch_job"):
                response = client.post("/api/v1/webhooks/gmail/pubsub", content=self.envelope(),
                                       headers={"Authorization": "Bearer valid"})
                self.assertEqual(response.status_code, 204)
                self.assertEqual(self.db.query(SyncJob).count(), 1)
        finally:
            app.dependency_overrides.clear()

    def test_watch_renewal_preserves_sync_cursor_and_backs_off_failures(self):
        service = MagicMock()
        service.users.return_value.watch.return_value.execute.return_value = {
            "historyId": "150", "expiration": str(int((utcnow().replace(tzinfo=timezone.utc) + timedelta(days=7)).timestamp() * 1000))}
        limiter = MagicMock()
        self.assertTrue(push.renew_watch(self.db, self.account.user_id, self.account.id,
                                         service=service, limiter=limiter))
        self.db.refresh(self.account)
        self.assertEqual(self.account.history_id, "100")
        self.assertGreater(self.account.watch_expiration, utcnow() + timedelta(days=6))
        self.assertGreater(self.account.next_watch_attempt_at, utcnow() + timedelta(hours=23))
        limiter.wait.assert_called_once_with(self.account.id)
        service.users.return_value.watch.return_value.execute.side_effect = RuntimeError("offline")
        self.assertFalse(push.renew_watch(self.db, self.account.user_id, self.account.id,
                                          service=service, limiter=limiter))
        self.db.refresh(self.account)
        self.assertGreater(self.account.next_watch_attempt_at, utcnow() + timedelta(minutes=59))
        self.assertGreater(self.account.watch_expiration, utcnow() + timedelta(days=6))

    def test_watch_migration_is_reversible(self):
        path = Path(__file__).resolve().parents[1] / "migrations/versions/0007_gmail_push_watch.py"
        spec = importlib.util.spec_from_file_location("watch_migration", path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        # Use a separate pre-upgrade table in a disposable database.
        old = create_engine("sqlite://")
        try:
            with old.begin() as connection:
                connection.execute(text("CREATE TABLE connected_accounts (id INTEGER PRIMARY KEY, watch_expiration DATETIME)"))
                operations = Operations(MigrationContext.configure(connection))
                with patch.object(migration, "op", operations):
                    migration.upgrade()
                    self.assertIn("next_watch_attempt_at", {c["name"] for c in inspect(connection).get_columns("connected_accounts")})
                    migration.downgrade()
                    self.assertNotIn("next_watch_attempt_at", {c["name"] for c in inspect(connection).get_columns("connected_accounts")})
        finally:
            old.dispose()


if __name__ == "__main__":
    unittest.main()
