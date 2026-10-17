import base64
import copy
import json
import unittest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from googleapiclient.errors import HttpError
from httplib2 import Response
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.security import get_current_user
from app.features.google_login.models import ConnectedAccount
from app.features.mailbox.models import AuditLog, EmailAttachment, EmailLabel, EmailMessage, EmailThread, MessageLabel, SyncJob
from app.features.google_login.user import User
from app.features.mail_sync import service as gmail_sync
from app.integrations.gmail.mime import InvalidMessage, normalize_message

READ_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"


def encoded(text, charset="utf-8"):
    return base64.urlsafe_b64encode(text.encode(charset)).decode().rstrip("=")


def message(gmail_id="m1", labels=None, thread="t1", date="1770000000000"):
    return {"id": gmail_id, "threadId": thread, "historyId": "100", "internalDate": date,
            "sizeEstimate": 600, "labelIds": labels if labels is not None else ["INBOX", "UNREAD"],
            "snippet": "Hello", "payload": {"mimeType": "multipart/mixed", "headers": [
                {"name": "From", "value": '"Sender" <sender@example.com>'},
                {"name": "To", "value": '"Owner" <owner@example.com>'},
                {"name": "Subject", "value": "=?utf-8?b?UsOpc3Vtw6k=?="},
                {"name": "Message-ID", "value": f"<{gmail_id}@example.com>"},
                {"name": "References", "value": "<first@example.com>"}], "parts": [
                {"partId": "0", "mimeType": "multipart/alternative", "parts": [
                    {"partId": "0.0", "mimeType": "text/plain", "body": {"data": encoded("Hello नमस्ते")}},
                    {"partId": "0.1", "mimeType": "text/html", "body": {"data": encoded('<p>Hello</p><img src="https://tracker.invalid/pixel">')}}]},
                {"partId": "1", "mimeType": "application/pdf", "filename": "resume.pdf",
                 "body": {"attachmentId": "binary-file", "size": 1000}}]}}


def error(status):
    return HttpError(Response({"status": str(status)}), b'{"error":"provider-secret-must-not-leak"}')


class FakeRequest:
    def __init__(self, call):
        self.call = call

    def execute(self, num_retries=0):
        assert num_retries == 0
        return self.call()


class FakeResource:
    def __init__(self, service, resource):
        self.service, self.resource = service, resource

    def list(self, **kwargs):
        return FakeRequest(lambda: self.service.call(self.resource + ".list", kwargs))

    def get(self, **kwargs):
        return FakeRequest(lambda: self.service.call(self.resource + ".get", kwargs))

    def attachments(self):
        return FakeResource(self.service, "attachments")


class FakeGmail:
    def __init__(self):
        self.calls = []
        self.profile = {"emailAddress": "owner@example.com", "historyId": "100"}
        self.message_pages = {None: {"messages": [{"id": "m1"}]}}
        self.history_pages = {None: {"historyId": "110", "history": []}}
        self.messages_by_id = {"m1": message()}
        self.catalog = [{"id": "INBOX", "name": "Inbox", "type": "system"},
                        {"id": "UNREAD", "name": "Unread", "type": "system"}]
        self.body_data = {}

    def users(self): return self
    def messages(self): return FakeResource(self, "messages")
    def labels(self): return FakeResource(self, "labels")
    def history(self): return FakeResource(self, "history")
    def getProfile(self, **kwargs): return FakeRequest(lambda: self.call("profile", kwargs))

    def call(self, operation, kwargs):
        self.calls.append((operation, kwargs))
        if operation == "profile": result = self.profile
        elif operation == "messages.list": result = self.message_pages[kwargs.get("pageToken")]
        elif operation == "history.list": result = self.history_pages[kwargs.get("pageToken")]
        elif operation == "labels.list": result = {"labels": self.catalog}
        elif operation == "messages.get": result = self.messages_by_id.get(kwargs["id"], error(404))
        elif operation == "attachments.get": result = {"data": self.body_data[kwargs["id"]]}
        else: raise AssertionError(operation)
        if isinstance(result, Exception): raise result
        return copy.deepcopy(result)


class GmailSyncTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch("app.core.config.GROQ_API_KEY", "test-not-real"):
            from app.main import app
        cls.app = app

    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        @event.listens_for(self.engine, "connect")
        def foreign_keys(connection, _): connection.execute("PRAGMA foreign_keys=ON")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine, autoflush=False)
        self.user, self.other = User(email="owner@example.com"), User(email="other@example.com")
        self.db.add_all([self.user, self.other])
        self.db.flush()
        self.account = ConnectedAccount(user_id=self.user.id, gmail_email=self.user.email, encrypted_credentials="test-opaque", scopes=json.dumps([READ_SCOPE]))
        self.other_account = ConnectedAccount(user_id=self.other.id, gmail_email=self.other.email, encrypted_credentials="other-opaque", scopes=json.dumps([READ_SCOPE]))
        self.db.add_all([self.account, self.other_account])
        self.db.commit()
        self.service = FakeGmail()
        self.app.dependency_overrides[get_db] = lambda: self.db
        self.app.dependency_overrides[get_current_user] = lambda: self.user
        self.client = TestClient(self.app)

    def tearDown(self):
        self.app.dependency_overrides.clear()
        self.db.close()
        self.engine.dispose()

    def sync(self, **kwargs):
        return gmail_sync.synchronize(self.db, self.user.id, self.account.id, service=self.service, **kwargs)

    def test_initial_import_paginates_and_keeps_pre_scan_cursor(self):
        self.service.message_pages = {None: {"messages": [{"id": "m1"}], "nextPageToken": "next"},
                                      "next": {"messages": [{"id": "m2"}]}}
        self.service.messages_by_id["m2"] = message("m2", thread="t2")
        self.service.messages_by_id["m2"]["historyId"] = "120"
        result = self.sync()
        self.assertEqual((result["status"], result["kind"]), ("succeeded", "initial"))
        self.assertEqual(self.account.history_id, "100")
        self.assertEqual(self.db.query(EmailMessage).count(), 2)
        self.assertEqual(self.db.query(EmailAttachment).count(), 2)
        self.assertEqual(self.db.query(MessageLabel).count(), 4)
        self.assertIsNotNone(self.account.last_synced_at)
        self.assertFalse(any(call[0] == "attachments.get" for call in self.service.calls))
        listing = [kwargs for operation, kwargs in self.service.calls if operation == "messages.list"]
        self.assertEqual(listing[1]["pageToken"], "next")
        self.assertEqual(listing[0]["q"], "newer_than:30d")

    def test_initial_sync_replay_preserves_message_and_attachment_ids(self):
        self.sync()
        message_id, attachment_id = self.db.query(EmailMessage).one().id, self.db.query(EmailAttachment).one().id
        self.sync(reconcile=True)
        self.assertEqual(self.db.query(EmailMessage).one().id, message_id)
        self.assertEqual(self.db.query(EmailAttachment).one().id, attachment_id)
        self.assertEqual(self.db.query(MessageLabel).count(), 2)

    def test_history_pagination_reconciles_additions_labels_and_deletions(self):
        self.sync()
        self.service.history_pages = {
            None: {"historyId": "110", "history": [{"messagesAdded": [{"message": {"id": "m2"}}],
                                                    "labelsRemoved": [{"message": {"id": "m1"}, "labelIds": ["UNREAD"]}]}], "nextPageToken": "next"},
            "next": {"historyId": "120", "history": [{"messagesDeleted": [{"message": {"id": "gone"}}]}]}}
        self.service.messages_by_id["m1"] = message(labels=["INBOX"])
        self.service.messages_by_id["m2"] = message("m2", labels=["INBOX"], date="1770000001000")
        self.sync()
        self.assertEqual(self.account.history_id, "120")
        self.assertEqual(self.db.query(EmailMessage).count(), 2)
        self.assertEqual(self.db.query(MessageLabel).count(), 2)
        self.assertEqual(self.db.query(EmailThread).one().last_message_at, 1770000001000)
        histories = [kwargs for operation, kwargs in self.service.calls if operation == "history.list"]
        self.assertTrue(all(kwargs["startHistoryId"] == "100" for kwargs in histories))

    def test_history_delete_removes_message_children_and_empty_thread(self):
        self.sync()
        self.service.history_pages[None] = {"historyId": "110", "history": [{"messagesDeleted": [{"message": {"id": "m1"}}]}]}
        self.service.messages_by_id.clear()
        self.sync()
        for model in (EmailMessage, EmailAttachment, MessageLabel, EmailThread):
            self.assertEqual(self.db.query(model).count(), 0)
        self.assertEqual(self.account.history_id, "110")

    def test_mid_import_failure_rolls_back_cache_and_cursor_and_records_safe_error(self):
        self.sync()
        previous_time = self.account.last_synced_at
        self.service.history_pages[None] = {"historyId": "120", "history": [{"messages": [{"id": "m1"}, {"id": "m2"}]}]}
        self.service.messages_by_id["m1"] = message(labels=[])
        self.service.messages_by_id["m2"] = error(503)
        with self.assertRaises(HTTPException) as result: self.sync()
        self.assertEqual(self.account.history_id, "100")
        self.assertEqual(self.account.last_synced_at, previous_time)
        self.assertEqual(self.db.query(EmailMessage).count(), 1)
        self.assertEqual(self.db.query(MessageLabel).count(), 2)
        failed = self.db.query(SyncJob).order_by(SyncJob.id.desc()).first()
        self.assertEqual((failed.status, failed.error_code), ("failed", "gmail_http_503"))
        self.assertNotIn("provider-secret", str(result.exception.detail))
        self.assertEqual(self.db.query(AuditLog).filter_by(outcome="failure").count(), 1)

    def test_later_history_page_failure_cannot_advance_cursor(self):
        self.sync()
        self.service.history_pages = {None: {"historyId": "110", "history": [], "nextPageToken": "next"}, "next": error(600)}
        with self.assertRaises(HTTPException): self.sync()
        self.assertEqual(self.account.history_id, "100")

    def test_expired_cursor_reconciles_cached_ids_outside_recent_listing(self):
        self.sync()
        self.service.history_pages[None] = error(404)
        self.service.profile["historyId"] = "200"
        self.service.message_pages[None] = {"messages": [{"id": "m2"}]}
        self.service.messages_by_id["m2"] = message("m2", thread="t2")
        self.service.messages_by_id["m1"] = message(labels=["SENT"])  # Archived/outside recent listing.
        result = self.sync()
        self.assertEqual(result["kind"], "reconcile")
        self.assertEqual(self.account.history_id, "200")
        self.assertEqual(self.db.query(EmailMessage).count(), 2)
        labels = self.db.query(EmailLabel.gmail_label_id).join(MessageLabel, MessageLabel.label_id == EmailLabel.id).join(
            EmailMessage, EmailMessage.id == MessageLabel.message_id).filter(EmailMessage.gmail_message_id == "m1").all()
        self.assertEqual(labels, [("SENT",)])

    def test_expired_cursor_removes_cached_permanent_deletions(self):
        self.sync()
        self.service.history_pages[None] = error(404)
        self.service.profile["historyId"] = "200"
        self.service.message_pages[None] = {}
        self.service.messages_by_id.clear()
        self.sync()
        self.assertEqual(self.db.query(EmailMessage).count(), 0)
        self.assertEqual(self.account.history_id, "200")

    def test_reconciliation_failure_retains_old_cursor_and_cache(self):
        self.sync()
        self.service.history_pages[None] = error(404)
        self.service.message_pages[None] = error(503)
        with self.assertRaises(HTTPException): self.sync()
        self.assertEqual(self.account.history_id, "100")
        self.assertEqual(self.db.query(EmailMessage).count(), 1)

    def test_no_history_still_advances_to_terminal_cursor(self):
        self.sync()
        self.sync()
        self.assertEqual(self.account.history_id, "110")
        self.assertEqual(self.db.query(EmailMessage).count(), 1)

    def test_regressing_provider_cursor_is_rejected(self):
        self.sync()
        self.service.history_pages[None] = {"historyId": "99", "history": []}
        with self.assertRaises(HTTPException): self.sync()
        self.assertEqual(self.account.history_id, "100")

    def test_busy_account_returns_retryable_conflict_without_provider_calls(self):
        original = gmail_sync.owned_account
        def locked(db, user_id, account_id, lock=False):
            if lock:
                raise OperationalError("SELECT FOR UPDATE NOWAIT", {}, Exception(3572, "busy"))
            return original(db, user_id, account_id)
        with patch.object(gmail_sync, "owned_account", side_effect=locked):
            with self.assertRaises(HTTPException) as result: self.sync()
        self.assertEqual(result.exception.status_code, 409)
        self.assertEqual(self.service.calls, [])
        self.assertIsNone(self.account.history_id)
        self.assertEqual(self.db.query(SyncJob).one().error_code, "sync_busy")

    def test_budget_or_repeated_page_failure_retains_cursor(self):
        self.sync()
        self.service.history_pages[None] = {"historyId": "120", "history": [{"messages": [{"id": "m1"}]}]}
        with patch.object(gmail_sync, "MAX_CHANGED_MESSAGES", 0):
            with self.assertRaises(HTTPException): self.sync()
        self.assertEqual(self.account.history_id, "100")
        self.service.history_pages = {None: {"historyId": "120", "nextPageToken": "again"},
                                      "again": {"historyId": "120", "nextPageToken": "again"}}
        with self.assertRaises(HTTPException): self.sync()
        self.assertEqual(self.account.history_id, "100")

    def test_invalid_mime_and_wrong_mailbox_are_not_committed(self):
        self.service.messages_by_id["m1"]["payload"]["parts"][0]["parts"][0]["body"]["data"] = "%%%"
        with self.assertRaises(HTTPException): self.sync()
        self.assertIsNone(self.account.history_id)
        self.assertEqual(self.db.query(EmailMessage).count(), 0)
        self.service.profile["emailAddress"] = "wrong@example.com"
        with self.assertRaises(HTTPException): self.sync()
        self.assertIsNone(self.account.history_id)

    def test_scope_and_owner_checks_prevent_provider_calls(self):
        with self.assertRaises(HTTPException) as result:
            gmail_sync.synchronize(self.db, self.user.id, self.other_account.id, service=self.service)
        self.assertEqual(result.exception.status_code, 404)
        self.account.scopes = json.dumps(["https://www.googleapis.com/auth/gmail.send"])
        self.db.commit()
        with self.assertRaises(HTTPException) as result: self.sync()
        self.assertEqual(result.exception.status_code, 409)
        self.assertEqual(self.service.calls, [])

    def test_api_enqueues_sync_and_status_routes_are_owner_scoped(self):
        with patch("app.workers.celery_app.celery_app.send_task") as publish, patch.object(
            gmail_sync.gmail_service, "get_gmail_service") as gmail:
            response = self.client.post(f"/api/v1/accounts/{self.account.id}/sync")
        publish.assert_called_once()
        gmail.assert_not_called()
        self.assertEqual(response.status_code, 202)
        job_id = response.json()["id"]
        self.assertEqual(response.json()["status"], "queued")
        self.assertEqual(self.client.get(f"/api/v1/accounts/{self.account.id}/sync-jobs/{job_id}").status_code, 200)
        self.assertEqual(len(self.client.get(f"/api/v1/accounts/{self.account.id}/sync-jobs").json()), 1)
        self.assertEqual(self.client.get(f"/api/v1/accounts/{self.other_account.id}/sync-jobs/{job_id}").status_code, 404)
        self.assertEqual(self.client.post(f"/api/v1/accounts/{self.other_account.id}/sync").status_code, 404)
        self.app.dependency_overrides.pop(get_current_user)
        self.assertEqual(self.client.post(f"/api/v1/accounts/{self.account.id}/sync").status_code, 401)


class GmailMimeTests(unittest.TestCase):
    def test_nested_mime_unicode_headers_body_and_attachment_metadata(self):
        normalized = normalize_message(message())
        self.assertEqual(normalized["body_text"], "Hello नमस्ते")
        self.assertEqual(normalized["subject"], "Résumé")
        self.assertEqual(normalized["to_addresses"], [{"name": "Owner", "email": "owner@example.com"}])
        self.assertIn("tracker.invalid", normalized["body_html"])  # Source cached, never rendered/fetched here.
        self.assertEqual(normalized["attachments"][0]["mime_part_id"], "1")

    def test_external_text_body_is_loaded_but_file_is_metadata_only(self):
        raw = message()
        raw["payload"]["parts"][0]["parts"][0]["body"] = {"attachmentId": "large-text"}
        loader = MagicMock(return_value=encoded("External body"))
        self.assertEqual(normalize_message(raw, loader)["body_text"], "External body")
        loader.assert_called_once_with("large-text")

    def test_text_attachments_do_not_become_message_body(self):
        raw = message()
        raw["payload"]["parts"].append({"partId": "2", "mimeType": "text/plain", "filename": "secret.txt",
                                           "body": {"data": encoded("Attachment contents"), "size": 100}})
        normalized = normalize_message(raw)
        self.assertNotIn("Attachment contents", normalized["body_text"])
        self.assertEqual(len(normalized["attachments"]), 2)

    def test_size_and_depth_limits_fail_without_truncation(self):
        with patch("app.integrations.gmail.mime.MAX_BODY_BYTES", 1):
            with self.assertRaises(InvalidMessage): normalize_message(message())
        with patch("app.integrations.gmail.mime.MAX_DEPTH", 0):
            with self.assertRaises(InvalidMessage): normalize_message(message())


if __name__ == "__main__": unittest.main()
