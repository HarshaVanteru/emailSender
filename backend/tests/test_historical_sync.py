import unittest
from datetime import timedelta
from unittest.mock import MagicMock, patch

from cryptography.fernet import Fernet
from fastapi import HTTPException
from sqlalchemy.orm import sessionmaker

import test_gmail_sync as fixtures
from app.core.token_crypto import decrypt
from app.features.mail_sync import historical
from app.features.mail_sync.history_models import HistorySession
from app.features.mailbox.models import EmailMessage
from app.features.mail_sync.service import utcnow


class HistoricalSyncTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.GmailSyncTests.setUpClass.__func__)
    setUp = fixtures.GmailSyncTests.setUp
    tearDown = fixtures.GmailSyncTests.tearDown

    def process(self, session_id):
        with patch('app.core.config.TOKEN_ENCRYPTION_KEY', Fernet.generate_key().decode()):
            historical.process_page(session_id, session_factory=sessionmaker(self.engine),
                                    service=self.service, limiter=MagicMock())
        self.db.expire_all()

    def test_explicit_page_encrypted_checkpoint_resume_and_account_isolation(self):
        self.account.history_id = '100'
        self.db.commit()
        result = historical.request_page(self.db, self.user.id, self.account.id)
        self.assertEqual(result['status'], 'pending')
        self.assertEqual(self.service.calls, [])  # HTTP only records work.
        self.service.message_pages = {None: {'messages': [{'id': 'm1'}], 'nextPageToken': 'provider-secret'},
                                      'provider-secret': {'messages': [{'id': 'm1'}]}}
        key = Fernet.generate_key().decode()
        with patch('app.core.config.TOKEN_ENCRYPTION_KEY', key):
            historical.process_page(result['session_id'], sessionmaker(self.engine), self.service, MagicMock())
            self.db.expire_all()
            row = self.db.query(HistorySession).filter_by(id=result['session_id']).first()
            self.assertEqual(row.status, 'ready')
            self.assertNotIn('provider-secret', row.page_token_ciphertext)
            self.assertEqual(decrypt(row.page_token_ciphertext), 'provider-secret')
            repeated = historical.request_page(self.db, self.user.id, self.account.id)
            self.assertEqual(repeated['status'], 'ready')  # Replaying start does not fetch another page.
            self.assertNotIn('page_token', historical.payload(row))
            self.assertEqual(self.db.get(type(self.account), self.account.id).history_id, '100')
            with self.assertRaises(HTTPException):
                historical.get_session(self.db, self.other.id, self.account.id, row.id)
            historical.request_page(self.db, self.user.id, self.account.id, session_id=row.id)
            historical.process_page(row.id, sessionmaker(self.engine), self.service, MagicMock())
            self.db.expire_all()
            self.assertEqual(self.db.query(HistorySession).filter_by(id=row.id).first().status, 'completed')
            self.assertEqual(self.db.query(EmailMessage).count(), 1)

    def test_failed_page_keeps_checkpoint_and_recovers(self):
        result = historical.request_page(self.db, self.user.id, self.account.id)
        self.service.message_pages[None] = fixtures.error(503)
        self.process(result['session_id'])
        row = self.db.query(HistorySession).filter_by(id=result['session_id']).first()
        self.assertEqual((row.status, row.attempts), ('pending', 1))
        self.assertIsNone(row.page_token_ciphertext)
        row.available_at = utcnow() - timedelta(seconds=1)
        self.db.commit()
        self.service.message_pages[None] = {'messages': [{'id': 'm1'}]}
        self.process(row.id)
        self.assertEqual(self.db.query(HistorySession).filter_by(id=row.id).first().status, 'completed')

    def test_initial_window_and_committed_progress_are_account_specific(self):
        from datetime import datetime, timezone
        from app.features.mail_sync import service
        self.account.initial_sync_days = 7
        self.db.commit()
        now = datetime(2026, 10, 31, 12)
        with patch.object(service, 'utcnow', return_value=now):
            result = service.synchronize(self.db, self.user.id, self.account.id, service=self.service)
        listing = next(options for operation, options in self.service.calls if operation == 'messages.list')
        cutoff = int((now - timedelta(days=7)).replace(tzinfo=timezone.utc).timestamp())
        self.assertEqual(listing['q'], f'after:{cutoff}')
        self.assertTrue(listing['includeSpamTrash'])
        self.assertEqual((result['messages_seen'], result['messages_inserted'], result['messages_updated']), (1, 1, 0))

    def test_stale_snapshot_cannot_create_a_thread_or_replace_labels(self):
        from app.features.mail_sync import service
        from app.features.mailbox.models import EmailThread, EmailLabel, MessageLabel
        service.synchronize(self.db, self.user.id, self.account.id, service=self.service)
        raw = fixtures.message(thread='stale-thread', labels=['SPAM'])
        raw['historyId'] = '99'
        data = service.normalize_message(raw)
        labels = {row.gmail_label_id: row for row in self.db.query(EmailLabel).filter_by(account_id=self.account.id)}
        affected = set()
        self.assertIsNone(service.upsert_message(self.db, self.account.id, data, labels, affected))
        self.assertEqual(self.db.query(EmailThread).count(), 1)
        self.assertEqual(self.db.query(MessageLabel).count(), 2)
        self.assertEqual(affected, set())
