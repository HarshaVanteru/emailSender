import importlib.util
import io
import unittest
from pathlib import Path
from unittest.mock import patch

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.token_crypto import decrypt
from app.models.connection import ConnectedAccount
from app.models.mailbox import (
    AuditLog, EmailAttachment, EmailLabel, EmailMessage, EmailThread, MessageLabel, SyncJob,
)
from app.models.user import User
from app.repositories.mailbox_repository import mailbox_repository

BACKEND = Path(__file__).resolve().parents[1]
MAILBOX_TABLES = {"email_threads", "email_messages", "email_labels", "message_labels",
                  "email_attachments", "sync_jobs", "audit_logs"}


class MailboxSchemaTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        @event.listens_for(self.engine, "connect")
        def enable_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
        self.connection = self.engine.connect()
        self.config = Config(str(BACKEND / "alembic.ini"))
        self.config.attributes["connection"] = self.connection
        command.upgrade(self.config, "head")
        self.db = Session(self.connection)
        self.owner = User(email="owner@example.com", signature="Keep my signature")
        self.other = User(email="other@example.com")
        self.db.add_all([self.owner, self.other])
        self.db.flush()
        self.account = ConnectedAccount(user_id=self.owner.id, gmail_email=self.owner.email,
                                        encrypted_credentials="opaque-existing-ciphertext", profile_history_id="999")
        self.other_account = ConnectedAccount(user_id=self.other.id, gmail_email=self.other.email)
        self.db.add_all([self.account, self.other_account])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.connection.close()
        self.engine.dispose()

    def thread(self, account=None, gmail_id="same-provider-thread"):
        row = EmailThread(account_id=(account or self.account).id, gmail_thread_id=gmail_id,
                          last_message_at=1770000000123)
        self.db.add(row)
        self.db.flush()
        return row

    def message(self, thread, account=None, gmail_id="same-provider-message"):
        row = EmailMessage(account_id=(account or self.account).id, thread_id=thread.id,
                           gmail_message_id=gmail_id, internal_date=1770000000123)
        self.db.add(row)
        self.db.flush()
        return row

    def label(self, account=None, gmail_id="INBOX"):
        row = EmailLabel(account_id=(account or self.account).id, gmail_label_id=gmail_id,
                         name="Inbox", type="system")
        self.db.add(row)
        self.db.flush()
        return row

    def assert_rejected(self, row):
        # Savepoints leave the valid fixture data intact after each rejected write.
        with self.assertRaises(IntegrityError), self.db.begin_nested():
            self.db.add(row)
            self.db.flush()

    def test_migrated_schema_matches_orm_and_has_required_indexes(self):
        self.assertEqual(compare_metadata(MigrationContext.configure(self.connection), Base.metadata), [])
        inspector = inspect(self.connection)
        self.assertTrue(MAILBOX_TABLES.issubset(inspector.get_table_names()))
        self.assertEqual({tuple(index["column_names"]) for index in inspector.get_indexes("email_messages")},
                         {("account_id", "internal_date"), ("account_id", "thread_id", "internal_date")})
        self.assertIsNone(self.account.history_id)  # Profile is not a committed sync cursor.
        self.assertEqual(self.account.profile_history_id, "999")

    def test_provider_ids_are_unique_per_account_and_can_repeat_between_accounts(self):
        thread = self.thread()
        self.thread(self.other_account)
        message = self.message(thread)
        other_thread = self.db.query(EmailThread).filter_by(account_id=self.other_account.id).one()
        self.message(other_thread, self.other_account)
        self.label()
        self.label(self.other_account)
        self.assert_rejected(EmailThread(account_id=self.account.id, gmail_thread_id=thread.gmail_thread_id))
        self.assert_rejected(EmailMessage(account_id=self.account.id, thread_id=thread.id,
                                          gmail_message_id=message.gmail_message_id, internal_date=0))
        self.assert_rejected(EmailLabel(account_id=self.account.id, gmail_label_id="INBOX", name="Duplicate", type="system"))

    def test_database_allows_only_one_active_job_and_valid_account_key(self):
        self.db.add(SyncJob(account_id=self.account.id, active_account_id=self.account.id,
                            kind="initial", status="queued"))
        self.db.flush()
        self.assert_rejected(SyncJob(account_id=self.account.id, active_account_id=self.account.id,
                                     kind="incremental", status="queued"))
        self.assert_rejected(SyncJob(account_id=self.account.id, active_account_id=self.other_account.id,
                                     kind="initial", status="queued"))
        self.db.add_all([SyncJob(account_id=self.account.id, kind="initial", status="succeeded"),
                         SyncJob(account_id=self.account.id, kind="initial", status="failed")])
        self.db.flush()
        self.assertEqual(self.db.query(SyncJob).count(), 3)

    def test_worker_migration_preserves_cache_and_marks_legacy_jobs_interrupted(self):
        account_id = self.account.id
        cached_id = self.message(self.thread()).id
        self.db.add(SyncJob(account_id=account_id, active_account_id=account_id,
                            kind="initial", status="running"))
        self.db.commit()
        self.db.close()
        command.downgrade(self.config, "0004")
        self.assertEqual(self.connection.execute(text("SELECT status FROM sync_jobs")).scalar(), "failed")
        self.connection.execute(text("UPDATE sync_jobs SET status='running', error_code=NULL"))
        self.connection.commit()
        command.upgrade(self.config, "head")
        self.db = Session(self.connection)
        job = self.db.query(SyncJob).one()
        self.assertEqual((job.status, job.error_code, job.active_account_id), ("failed", "migration_interrupted", None))
        self.assertIsNotNone(job.finished_at)
        self.assertEqual(self.db.get(EmailMessage, cached_id).account_id, account_id)
        self.assertEqual(self.db.get(ConnectedAccount, account_id).encrypted_credentials, "opaque-existing-ciphertext")

    def test_database_rejects_cross_account_message_thread_links(self):
        foreign_thread = self.thread(self.other_account)
        self.assert_rejected(EmailMessage(account_id=self.account.id, thread_id=foreign_thread.id,
                                          gmail_message_id="forged", internal_date=0))

    def test_database_rejects_cross_account_labels_and_attachments(self):
        own_message = self.message(self.thread())
        own_label = self.label()
        foreign_message = self.message(self.thread(self.other_account), self.other_account)
        foreign_label = self.label(self.other_account)
        self.assert_rejected(MessageLabel(account_id=self.account.id, message_id=own_message.id, label_id=foreign_label.id))
        self.assert_rejected(MessageLabel(account_id=self.account.id, message_id=foreign_message.id, label_id=own_label.id))
        self.assert_rejected(EmailAttachment(account_id=self.account.id, message_id=foreign_message.id,
            mime_part_id="1", filename="forged.pdf", mime_type="application/pdf", size_bytes=1))

    def test_label_links_and_attachment_parts_are_deduplicated(self):
        message = self.message(self.thread())
        label = self.label()
        self.db.add(MessageLabel(account_id=self.account.id, message_id=message.id, label_id=label.id))
        self.db.add(EmailAttachment(account_id=self.account.id, message_id=message.id, mime_part_id="1",
                                   filename="resume.pdf", mime_type="application/pdf", size_bytes=1024))
        self.db.flush()
        self.assert_rejected(MessageLabel(account_id=self.account.id, message_id=message.id, label_id=label.id))
        self.assert_rejected(EmailAttachment(account_id=self.account.id, message_id=message.id, mime_part_id="1",
                                            filename="duplicate.pdf", mime_type="application/pdf", size_bytes=1024))

    def test_cache_deletion_cascades_only_to_local_message_children(self):
        message = self.message(self.thread())
        label = self.label()
        self.db.add(MessageLabel(account_id=self.account.id, message_id=message.id, label_id=label.id))
        self.db.add(EmailAttachment(account_id=self.account.id, message_id=message.id, mime_part_id="1",
                                   filename="resume.pdf", mime_type="application/pdf", size_bytes=1024))
        self.db.flush()
        self.db.delete(message)
        self.db.flush()
        self.assertEqual(self.db.query(MessageLabel).count(), 0)
        self.assertEqual(self.db.query(EmailAttachment).count(), 0)
        self.assertEqual(self.db.query(EmailLabel).count(), 1)
        self.assertEqual(self.db.query(ConnectedAccount).count(), 2)

    def test_owned_lookups_reject_guessed_internal_ids(self):
        thread = self.thread()
        message = self.message(thread)
        attachment = EmailAttachment(account_id=self.account.id, message_id=message.id, mime_part_id="1",
                                     filename="private.pdf", mime_type="application/pdf", size_bytes=100)
        self.db.add(attachment)
        self.db.flush()
        for lookup, row in ((mailbox_repository.get_message, message), (mailbox_repository.get_thread, thread),
                            (mailbox_repository.get_attachment, attachment)):
            self.assertEqual(lookup(self.db, self.owner.id, self.account.id, row.id).id, row.id)
            self.assertIsNone(lookup(self.db, self.other.id, self.account.id, row.id))
            self.assertIsNone(lookup(self.db, self.owner.id, self.other_account.id, row.id))

    def test_job_validation_and_audit_account_ownership(self):
        self.db.add(SyncJob(account_id=self.account.id, kind="initial"))
        self.db.add(AuditLog(user_id=self.owner.id, account_id=self.account.id, action="sync.requested", outcome="success"))
        self.db.flush()
        job = self.db.query(SyncJob).one()
        self.assertEqual((job.status, job.attempts), ("queued", 0))
        self.assert_rejected(SyncJob(account_id=self.account.id, kind="send", status="queued"))
        self.assert_rejected(SyncJob(account_id=self.account.id, kind="initial", status="unrecognized"))
        self.assert_rejected(SyncJob(account_id=self.account.id, kind="initial", attempts=-1))
        self.assert_rejected(AuditLog(user_id=self.other.id, account_id=self.account.id, action="forged", outcome="success"))

    def test_body_headers_and_recipient_roundtrip_preserves_large_unicode_content(self):
        row = self.message(self.thread())
        row.body_text = "Résumé — नमस्ते\n" * 10000
        row.body_html = "<p>Untrusted HTML</p>" * 10000
        row.to_addresses = [{"name": "Receiver", "email": "receiver@example.com"}]
        row.headers = [{"name": "References", "value": "<one@example.com>"},
                       {"name": "References", "value": "<two@example.com>"}]
        self.db.commit()
        self.db.expire_all()
        loaded = mailbox_repository.get_message(self.db, self.owner.id, self.account.id, row.id)
        self.assertEqual(len(loaded.headers), 2)
        self.assertEqual(loaded.to_addresses[0]["name"], "Receiver")
        self.assertGreater(len(loaded.body_text.encode()), 65535)

    def test_downgrade_to_security_revision_preserves_credentials_and_user_settings(self):
        self.message(self.thread())
        self.db.commit()
        self.db.close()
        command.downgrade(self.config, "0002")
        self.assertFalse(MAILBOX_TABLES & set(inspect(self.connection).get_table_names()))
        self.assertEqual(self.connection.execute(text("SELECT encrypted_credentials FROM connected_accounts WHERE id=1")).scalar_one(),
                         "opaque-existing-ciphertext")
        self.assertEqual(self.connection.execute(text("SELECT signature FROM users WHERE id=1")).scalar_one(), "Keep my signature")
        command.upgrade(self.config, "head")
        self.assertEqual(compare_metadata(MigrationContext.configure(self.connection), Base.metadata), [])


class MailboxMigrationTests(unittest.TestCase):
    def test_missing_key_stops_legacy_import_before_schema_or_credentials_change(self):
        engine = create_engine("sqlite://")
        with engine.begin() as connection, patch("app.core.config.TOKEN_ENCRYPTION_KEY", None):
            User.__table__.create(connection)
            token = '{"token":"existing-access","refresh_token":"existing-refresh"}'
            connection.execute(text("INSERT INTO users (id,email,google_token) VALUES (1,'legacy@example.com',:token)"), {"token": token})
            config = Config(str(BACKEND / "alembic.ini"))
            config.attributes["connection"] = connection
            command.stamp(config, "0001")
            with self.assertRaises(ValueError):
                command.upgrade(config, "head")
            self.assertNotIn("connected_accounts", inspect(connection).get_table_names())
            self.assertEqual(connection.execute(text("SELECT google_token FROM users")).scalar_one(), token)
            self.assertEqual(connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one(), "0001")
        engine.dispose()

    def test_existing_unversioned_users_can_be_stamped_and_upgraded_without_consent(self):
        engine = create_engine("sqlite://")
        with engine.begin() as connection, patch("app.core.config.TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode()):
            # Simulate the original app's create_all users table, not a versioned DB.
            User.__table__.create(connection)
            original = '{"token":"access","refresh_token":"refresh","scopes":["gmail.send"]}'
            connection.execute(text("INSERT INTO users (id,email,google_token,name,bio) VALUES (1,'legacy@example.com',:token,'Legacy','My bio')"),
                               {"token": original})
            config = Config(str(BACKEND / "alembic.ini"))
            config.attributes["connection"] = connection
            command.stamp(config, "0001")
            command.upgrade(config, "head")
            row = connection.execute(text("SELECT encrypted_credentials,history_id FROM connected_accounts")).one()
            self.assertEqual(decrypt(row.encrypted_credentials), original)
            self.assertIsNone(row.history_id)
            self.assertIsNone(connection.execute(text("SELECT google_token FROM users")).scalar_one())
            self.assertEqual(connection.execute(text("SELECT bio FROM users")).scalar_one(), "My bio")
            self.assertEqual(connection.execute(text("SELECT count(*) FROM email_messages")).scalar_one(), 0)
        engine.dispose()

    def test_mysql_migration_generates_composite_foreign_keys_and_large_body_columns(self):
        spec = importlib.util.spec_from_file_location("mailbox_migration", BACKEND / "migrations/versions/0003_mailbox_cache.py")
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        output = io.StringIO()
        context = MigrationContext.configure(dialect_name="mysql", opts={"as_sql": True, "output_buffer": output})
        with Operations.context(context):
            migration.upgrade()
            migration.downgrade()
        sql = output.getvalue()
        self.assertIn("body_html LONGTEXT", sql)
        self.assertIn("COLLATE utf8mb4_bin", sql)
        self.assertIn("FOREIGN KEY(account_id, thread_id) REFERENCES email_threads (account_id, id)", sql)
        self.assertIn("DROP TABLE email_messages", sql)


if __name__ == "__main__":
    unittest.main()
