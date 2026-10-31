"""Worker/outbox recovery with isolated SQL and fake Gmail/Redis; no mail is sent."""
import json
import unittest
from datetime import timedelta
from unittest.mock import MagicMock, patch

import fakeredis
from fastapi import HTTPException
from googleapiclient.errors import HttpError
from httplib2 import Response
from redis.exceptions import ConnectionError
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.features.google_login.models import ConnectedAccount
from app.features.mailbox.models import EmailMessage, SyncJob
from app.features.google_login.user import User
from app.features.mail_sync import jobs as jobs
from app.features.mail_sync.service import utcnow
from app.workers.rate_limit import GmailRateLimiter
from test_gmail_sync import FakeGmail, READ_SCOPE, error, message


class WorkerTests(unittest.TestCase):
    def setUp(self):
        notifications = patch.object(jobs, "publish_update")
        self.notifications = notifications.start()
        self.addCleanup(notifications.stop)
        self.engine = create_engine("sqlite://", poolclass=StaticPool)
        @event.listens_for(self.engine, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(self.engine, autoflush=False)
        self.db = self.sessions()
        user = User(email="owner@example.com")
        self.db.add(user)
        self.db.flush()
        self.uid = user.id
        account = ConnectedAccount(user_id=self.uid, gmail_email=user.email,
                                   encrypted_credentials="opaque", scopes=json.dumps([READ_SCOPE]))
        self.db.add(account)
        self.db.commit()
        self.aid = account.id
        self.service = FakeGmail()
        self.limiter = MagicMock()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def enqueue(self, **kwargs):
        return jobs.enqueue_sync(self.db, self.uid, self.aid, **kwargs).id

    def run_job(self, jid):
        self.db.rollback()
        jobs.process_job(jid, self.sessions, lambda: self.service, self.limiter)
        self.db.expire_all()
        return self.db.get(SyncJob, jid)

    def make_due(self, jid):
        job = self.db.get(SyncJob, jid)
        job.available_at = job.dispatch_after = utcnow() - timedelta(seconds=1)
        self.db.commit()

    def test_duplicate_submission_promotes_queued_job_without_resetting_backoff(self):
        jid = self.enqueue()
        job = self.db.get(SyncJob, jid)
        job.available_at = utcnow() + timedelta(minutes=1)
        job.attempts = 1
        self.db.commit()
        due = job.available_at
        self.assertEqual(self.enqueue(reconcile=True), jid)
        self.assertEqual((job.kind, job.attempts, job.available_at), ("reconcile", 1, due))
        self.assertEqual(self.db.query(SyncJob).count(), 1)

    def test_running_reconciliation_request_is_explicit_conflict(self):
        jid = self.enqueue()
        jobs.claim_job(self.db, jid)
        with self.assertRaises(HTTPException) as caught:
            self.enqueue(reconcile=True)
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(self.db.get(SyncJob, jid).kind, "initial")

    def test_broker_outage_persists_job_then_maintenance_redelivers(self):
        with patch("app.workers.celery_app.celery_app.send_task", side_effect=ConnectionError("offline")):
            with self.assertRaises(HTTPException) as caught:
                jobs.submit_sync(self.db, self.uid, self.aid)
        self.assertEqual(caught.exception.status_code, 503)
        self.assertTrue(caught.exception.detail["accepted"])
        jid = caught.exception.detail["job_id"]
        self.assertEqual(self.db.get(SyncJob, jid).error_code, "queue_unavailable")
        self.make_due(jid)
        publisher = MagicMock()
        jobs.maintenance(self.sessions, publisher)
        publisher.assert_called_once_with(jid)
        self.db.expire_all()
        self.assertIsNone(self.db.get(SyncJob, jid).error_code)
        self.assertEqual(self.db.query(SyncJob).count(), 1)
        self.assertEqual(self.service.calls, [])

    def test_success_and_duplicate_delivery_commit_once(self):
        jid = self.enqueue()
        job = self.run_job(jid)
        self.assertEqual((job.status, job.attempts, job.active_account_id), ("succeeded", 1, None))
        account = self.db.get(ConnectedAccount, self.aid)
        self.assertEqual(account.history_id, "100")
        self.assertGreater(account.next_reconcile_at, utcnow())
        self.assertEqual(self.db.query(EmailMessage).count(), 1)
        self.notifications.assert_called_once_with(self.aid)
        count = len(self.service.calls)
        self.assertEqual(self.limiter.wait.call_count, count)
        self.run_job(jid)
        self.assertEqual(len(self.service.calls), count)

    def test_transient_mid_import_failure_rolls_back_then_retries_same_job(self):
        self.service.message_pages = {None: {"messages": [{"id": "m1"}, {"id": "m2"}]}}
        self.service.messages_by_id["m2"] = error(503)
        jid = self.enqueue()
        before = utcnow()
        job = self.run_job(jid)
        self.assertEqual((job.status, job.attempts, job.error_code), ("queued", 1, "gmail_http_503"))
        self.assertGreaterEqual(job.available_at, before + timedelta(seconds=7.5))
        self.assertLessEqual(job.available_at, utcnow() + timedelta(seconds=15))
        self.assertEqual(self.db.query(EmailMessage).count(), 0)
        self.assertIsNone(self.db.get(ConnectedAccount, self.aid).history_id)
        # An early delivery does not bypass retry backoff.
        self.run_job(jid)
        self.assertEqual(self.db.get(SyncJob, jid).attempts, 1)
        self.service.messages_by_id["m2"] = message("m2")
        self.make_due(jid)
        job = self.run_job(jid)
        self.assertEqual((job.status, job.attempts), ("succeeded", 2))
        self.assertEqual(self.db.query(EmailMessage).count(), 2)

    def test_recent_window_continues_after_page_commit(self):
        self.service.message_pages = {None: {"messages": [{"id": "m1"}], "nextPageToken": "older"},
                                      "older": {"messages": [{"id": "m2"}]}}
        self.service.messages_by_id["m2"] = message("m2", thread="t2", date="946684800000")
        with patch("app.workers.celery_app.celery_app.send_task") as publish:
            self.assertEqual(self.run_job(self.enqueue()).status, "succeeded")
        account = self.db.get(ConnectedAccount, self.aid)
        self.assertEqual(account.history_id, "100")
        self.assertEqual(account.mail_import_page_token, "older")
        followup = self.db.query(SyncJob).filter_by(active_account_id=self.aid).one()
        publish.assert_called_once()
        self.assertEqual(publish.call_args.kwargs["args"], [followup.id])
        self.assertEqual(self.run_job(followup.id).status, "succeeded")
        self.assertEqual(account.history_id, "100")
        self.assertTrue(account.mail_import_complete)
        self.assertEqual(self.db.query(EmailMessage).count(), 2)

    def test_exhausted_temporary_failure_recovers_without_manual_sync(self):
        self.service.messages_by_id["m1"] = error(503)
        jid = self.enqueue()
        with patch.object(jobs.config, "SYNC_MAX_ATTEMPTS", 2):
            self.run_job(jid)
            self.make_due(jid)
            job = self.run_job(jid)
        self.assertEqual((job.status, job.attempts, job.active_account_id), ("failed", 2, None))
        account = self.db.get(ConnectedAccount, self.aid)
        self.assertFalse(account.sync_paused)
        self.assertGreater(account.next_sync_at, utcnow())
        publisher = MagicMock()
        jobs.maintenance(self.sessions, publisher)
        publisher.assert_not_called()
        self.service.messages_by_id["m1"] = message("m1")
        account.next_sync_at = utcnow() - timedelta(seconds=1)
        self.db.commit()
        jobs.maintenance(self.sessions, publisher)
        new_id = publisher.call_args.args[0]
        self.assertNotEqual(jid, new_id)
        self.assertEqual(self.run_job(new_id).status, "succeeded")
        self.assertFalse(self.db.get(ConnectedAccount, self.aid).sync_paused)

    def test_permanent_provider_failure_does_not_retry(self):
        self.service.messages_by_id["m1"] = error(403)
        job = self.run_job(self.enqueue())
        self.assertEqual((job.status, job.error_code, job.attempts), ("failed", "gmail_http_403", 1))
        self.assertTrue(self.db.get(ConnectedAccount, self.aid).sync_paused)
        self.assertFalse(self.db.get(ConnectedAccount, self.aid).requires_reauth)  # Not every 403 means a revoked grant.

    def test_rate_limit_403_retries_but_permissions_403_does_not(self):
        exc = HttpError(Response({"status": "403"}),
                        b'{"error":{"errors":[{"reason":"userRateLimitExceeded"}]}}')
        self.assertEqual(jobs.classify_failure(exc), ("gmail_rate_limited", True))
        self.assertEqual(jobs.classify_failure(error(403)), ("gmail_http_403", False))

    def test_server_failures_retry_while_client_failures_remain_permanent(self):
        for status in (400, 401, 403, 404, 500, 502, 503, 504):
            with self.subTest(status=status):
                retryable = status >= 500
                self.assertEqual(jobs.classify_failure(error(status)), (f"gmail_http_{status}", retryable))
                self.assertEqual(jobs.classify_failure(HTTPException(status)), ("connection_unavailable", retryable))

    def test_temporary_connection_failure_requeues_job_then_recovers(self):
        jid = self.enqueue()
        with patch.object(jobs, "check_read_access", side_effect=HTTPException(503)):
            job = self.run_job(jid)
        self.assertEqual((job.status, job.attempts, job.error_code), ("queued", 1, "connection_unavailable"))
        self.assertFalse(self.db.get(ConnectedAccount, self.aid).sync_paused)
        self.make_due(jid)
        job = self.run_job(jid)
        self.assertEqual((job.status, job.attempts, job.error_code), ("succeeded", 2, None))

    def test_worker_loss_recovers_and_old_token_cannot_overwrite_new_attempt(self):
        jid = self.enqueue()
        old_token = jobs.claim_job(self.db, jid)[2]
        self.db.get(SyncJob, jid).lease_expires_at = utcnow() - timedelta(seconds=1)
        self.db.commit()
        jobs.recover_expired(self.db)
        job = self.db.get(SyncJob, jid)
        self.assertEqual((job.status, job.error_code), ("queued", "worker_lost"))
        self.make_due(jid)
        new_token = jobs.claim_job(self.db, jid)[2]
        self.assertNotEqual(old_token, new_token)
        jobs.record_failure(self.db, jid, old_token, "stale_failure", False)
        self.db.refresh(job)
        self.assertEqual((job.status, job.lease_token, job.attempts), ("running", new_token, 2))

    def test_worker_rechecks_lease_after_service_creation(self):
        jid = self.enqueue()
        def changed_lease():
            with self.sessions() as db:
                db.get(SyncJob, jid).lease_token = "new-owner"
                db.commit()
            return self.service
        self.db.rollback()
        jobs.process_job(jid, self.sessions, changed_lease, self.limiter)
        self.assertEqual(self.service.calls, [])

    def test_disconnect_after_submission_prevents_provider_requests(self):
        jid = self.enqueue()
        self.db.get(ConnectedAccount, self.aid).encrypted_credentials = None
        self.db.commit()
        job = self.run_job(jid)
        self.assertEqual((job.status, job.error_code), ("failed", "connection_unavailable"))
        self.assertEqual(self.service.calls, [])

    def test_redis_failure_aborts_before_gmail_and_retries(self):
        self.limiter.wait.side_effect = ConnectionError("offline")
        job = self.run_job(self.enqueue())
        self.assertEqual((job.status, job.error_code), ("queued", "queue_unavailable"))
        self.assertEqual(self.service.calls, [])
        self.assertIsNone(self.db.get(ConnectedAccount, self.aid).history_id)

    def test_schedule_creates_initial_then_incremental_then_reconciliation(self):
        publisher = MagicMock()
        jobs.maintenance(self.sessions, publisher)
        jid = publisher.call_args.args[0]
        self.assertEqual(self.db.get(SyncJob, jid).kind, "initial")
        jobs.maintenance(self.sessions, publisher)
        publisher.assert_called_once()
        self.run_job(jid)
        account = self.db.get(ConnectedAccount, self.aid)
        account.next_sync_at = utcnow() - timedelta(seconds=1)
        self.db.commit()
        jobs.maintenance(self.sessions, publisher)
        jid = publisher.call_args.args[0]
        self.assertEqual(self.db.get(SyncJob, jid).kind, "incremental")
        self.run_job(jid)
        account = self.db.get(ConnectedAccount, self.aid)
        account.next_sync_at = account.next_reconcile_at = utcnow() - timedelta(seconds=1)
        self.db.commit()
        jobs.maintenance(self.sessions, publisher)
        self.assertEqual(self.db.get(SyncJob, publisher.call_args.args[0]).kind, "reconcile")

    def test_scheduler_rechecks_paused_future_and_send_only_accounts(self):
        account = self.db.get(ConnectedAccount, self.aid)
        for changes in ({"sync_paused": True}, {"sync_paused": False, "next_sync_at": utcnow() + timedelta(hours=1)},
                        {"next_sync_at": None, "scopes": "[]"}):
            for key, value in changes.items():
                setattr(account, key, value)
            self.db.commit()
            self.assertIsNone(jobs.enqueue_sync(self.db, self.uid, self.aid, scheduled=True))
        self.assertEqual(self.db.query(SyncJob).count(), 0)
        self.assertGreater(account.next_sync_at, utcnow())


class RateLimiterTests(unittest.TestCase):
    def test_budget_is_shared_across_workers_and_separate_per_account(self):
        server = fakeredis.FakeServer()
        first = fakeredis.FakeRedis(server=server)
        second = fakeredis.FakeRedis(server=server)
        sleeps = []
        def expire_window(delay):
            sleeps.append(delay)
            first.delete("email-studio:gmail-rate:1")
        one = GmailRateLimiter(first, sleep=expire_window)
        two = GmailRateLimiter(second, sleep=expire_window)
        with patch.object(jobs.config, "SYNC_REQUESTS_PER_SECOND", 2):
            one.wait(1)
            two.wait(1)
            two.wait(2)
            self.assertEqual(sleeps, [])
            two.wait(1)
        self.assertEqual(len(sleeps), 1)
        self.assertGreater(sleeps[0], 0)
        self.assertLessEqual(sleeps[0], 1)
        self.assertEqual(first.get("email-studio:gmail-rate:1"), b"1")
        self.assertGreater(first.pttl("email-studio:gmail-rate:1"), 0)
