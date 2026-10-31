"""Real WebSocket handshake and account isolation; no live database or Gmail."""
import json
import time
import unittest
from datetime import timedelta
from unittest.mock import patch
import fakeredis
from fakeredis.aioredis import FakeRedis as AsyncFakeRedis

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.websockets import WebSocketDisconnect

from app.core.database import Base
from app.core.security import create_access_token
from app.features.google_login.user import User
from app.features.google_login.models import ConnectedAccount
from app.features.mailbox.models import SyncJob
from app.features.mail_sync import realtime
from app.main import app


class RealtimeTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        with self.sessions() as db:
            owner = User(email="owner@example.com")
            other = User(email="other@example.com")
            db.add_all([owner, other])
            db.flush()
            account = ConnectedAccount(user_id=owner.id, gmail_email=owner.email,
                encrypted_credentials="encrypted", scopes=json.dumps([
                    "https://www.googleapis.com/auth/gmail.modify"]))
            db.add(account)
            db.commit()
            self.account_id = account.id
        self.patches = [
            patch.object(realtime, "SessionLocal", self.sessions),
            patch("app.core.config.ALLOW_LEGACY_SESSIONS", True),
            patch("app.core.config.SECRET_KEY", "test-signing-key-with-at-least-32-characters"),
            patch("app.core.config.FRONTEND_URL", "http://localhost:5173"),
            patch.object(realtime, "HEARTBEAT_SECONDS", 0.01),
        ]
        self.redis_server = fakeredis.FakeServer()
        self.publisher = fakeredis.FakeRedis(server=self.redis_server)
        self.patches.append(patch.object(realtime.Redis, "from_url", side_effect=lambda *a, **k: AsyncFakeRedis(server=self.redis_server)))
        for item in self.patches:
            item.start()
        self.client = TestClient(app)
        self.token = create_access_token({"sub": "owner@example.com"})
        self.path = f"/api/v1/accounts/{self.account_id}/events"

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.engine.dispose()

    def assert_rejected(self, token):
        with self.client.websocket_connect(self.path) as ws:
            ws.send_json({"token": token})
            with self.assertRaises(WebSocketDisconnect) as caught:
                ws.receive_json()
            self.assertEqual(caught.exception.code, 1008)

    def test_authenticated_socket_ready_and_heartbeat(self):
        with self.client.websocket_connect(self.path, headers={"origin": "http://localhost:5173"}) as ws:
            ws.send_json({"token": self.token})
            self.assertEqual(ws.receive_json(), {"type": "ready", "account_id": self.account_id, "revision": None})
            self.assertEqual(ws.receive_json()["type"], "heartbeat")

    def test_worker_event_notifies_without_frequent_database_snapshots(self):
        with patch.object(realtime, "HEARTBEAT_SECONDS", 60), patch.object(
                realtime, "sync_snapshot", side_effect=[1, 2]) as snapshot:
            with self.client.websocket_connect(self.path) as ws:
                ws.send_json({"token": self.token})
                self.assertEqual(ws.receive_json()["revision"], 1)
                time.sleep(0.05)
                self.assertEqual(snapshot.call_count, 1)
                self.publisher.publish(realtime.channel(self.account_id), "updated")
                self.assertEqual(ws.receive_json(), {"type": "mailbox.updated", "account_id": self.account_id, "revision": 2})

    def test_redis_outage_closes_socket_for_http_fallback(self):
        with patch.object(realtime.Redis, "from_url", side_effect=realtime.RedisError("offline")):
            with self.client.websocket_connect(self.path) as ws:
                ws.send_json({"token": self.token})
                with self.assertRaises(WebSocketDisconnect) as caught:
                    ws.receive_json()
                self.assertEqual(caught.exception.code, 1013)

    def test_foreign_account_invalid_and_expired_tokens_rejected(self):
        self.assert_rejected(create_access_token({"sub": "other@example.com"}))
        self.assert_rejected("invalid")
        self.assert_rejected(create_access_token({"sub": "owner@example.com"}, timedelta(seconds=-1)))

    def test_wrong_origin_rejected(self):
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect(self.path, headers={"origin": "https://evil.example"}):
                pass

    def test_missing_credentials_rejected(self):
        with self.client.websocket_connect(self.path) as ws:
            ws.send_json({})
            with self.assertRaises(WebSocketDisconnect):
                ws.receive_json()

    def test_committed_sync_change_notifies_and_reconnect_has_current_revision(self):
        snapshots = iter([1, 2])
        with patch.object(realtime, "sync_snapshot", side_effect=lambda *_: next(snapshots, 2)):
            with self.client.websocket_connect(self.path) as ws:
                ws.send_json({"token": self.token})
                self.assertEqual(ws.receive_json()["revision"], 1)
                self.assertEqual(ws.receive_json(), {"type": "mailbox.updated", "account_id": self.account_id, "revision": 2})
            with self.client.websocket_connect(self.path) as ws:
                ws.send_json({"token": self.token})
                self.assertEqual(ws.receive_json()["revision"], 2)

    def test_access_rechecked_during_connection(self):
        with patch.object(realtime, "sync_snapshot", side_effect=[1, HTTPException(401)]):
            with self.client.websocket_connect(self.path) as ws:
                ws.send_json({"token": self.token})
                ws.receive_json()
                with self.assertRaises(WebSocketDisconnect) as caught:
                    ws.receive_json()
                self.assertEqual(caught.exception.code, 1008)

    def test_snapshot_only_observes_successful_account_jobs(self):
        with self.sessions() as db:
            job = SyncJob(account_id=self.account_id, kind="initial", status="running")
            db.add(job)
            db.commit()
            job_id = job.id
        self.assertIsNone(realtime.sync_snapshot(self.token, self.account_id))
        with self.sessions() as db:
            db.get(SyncJob, job_id).status = "succeeded"
            db.commit()
        self.assertEqual(realtime.sync_snapshot(self.token, self.account_id), job_id)

    def test_failed_job_changes_safety_snapshot_after_missed_publication(self):
        self.assertIsNone(realtime.sync_snapshot(self.token, self.account_id))
        with self.sessions() as db:
            job = SyncJob(account_id=self.account_id, kind="initial", status="failed")
            db.add(job)
            db.commit()
            job_id = job.id
        self.assertEqual(realtime.sync_snapshot(self.token, self.account_id), f"None:failed:{job_id}")
