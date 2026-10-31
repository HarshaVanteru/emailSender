"""Jobs survive queue loss, duplicate delivery and ambiguous provider outcomes."""
import unittest
from datetime import timedelta
from unittest.mock import MagicMock, patch
from cryptography.fernet import Fernet
from fastapi import HTTPException
from sqlalchemy.orm import sessionmaker

import test_connection_security as fixtures
from app.core.time import utcnow
from app.features.google_login.accounts import save_connection
from app.features.compose_email import send_jobs
from app.workers import operations
from app.workers.operation_models import SendJob


class DurableOperationTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.ConnectionSecurityTests.setUpClass.__func__)
    setUp = fixtures.ConnectionSecurityTests.setUp
    tearDown = fixtures.ConnectionSecurityTests.tearDown

    def submit(self, key='client-idempotency-key'):
        account = save_connection(self.db, self.user, fixtures.credentials())
        return send_jobs.enqueue(self.db, self.user.id, account.id, 'compose',
            {'to': 'recipient@example.com', 'subject': 'Reviewed mail', 'body': 'Hello'}, key)

    def test_same_intent_is_stored_once_and_mismatched_content_is_rejected(self):
        first = self.submit()
        second = self.submit()
        self.assertEqual(first.id, second.id)
        self.assertEqual(self.db.query(SendJob).count(), 1)
        self.assertNotIn('Hello', first.payload_ciphertext)
        self.assertNotIn('payload_ciphertext', operations.payload(first))
        with self.assertRaises(HTTPException):
            send_jobs.enqueue(self.db, self.user.id, first.account_id, 'compose', {'body': 'Changed'}, first.idempotency_key)
        with self.assertRaises(HTTPException):
            operations.get_job(self.db, 'send', self.other.id, first.account_id, first.id)

    def test_accepted_timeout_becomes_unknown_and_duplicate_delivery_never_sends(self):
        job = self.submit()
        job_id, account_id = job.id, job.account_id
        executor = MagicMock(side_effect=TimeoutError('untrusted provider details'))
        factory = sessionmaker(self.engine)
        operations.process('send', job_id, factory, executor)
        operations.process('send', job_id, factory, executor)
        self.db.expire_all()
        row = self.db.query(SendJob).filter_by(id=job_id).first()
        self.assertEqual(row.status, 'unknown')
        executor.assert_called_once()
        self.assertNotIn('untrusted provider details', str(operations.payload(row)))
        service = MagicMock()
        service.users.return_value.messages.return_value.list.return_value.execute.return_value = {'messages': [{'id': 'sent-provider-id'}]}
        result = send_jobs.reconcile(self.db, self.user.id, account_id, job_id, service, MagicMock())
        self.assertEqual(result['status'], 'sent')
        service.users.return_value.messages.return_value.send.assert_not_called()

    def test_worker_loss_is_unknown_and_completed_send_releases_content(self):
        job_id = self.submit().id
        token = operations.claim(self.db, 'send', job_id)
        row = self.db.query(SendJob).filter_by(id=job_id).first()
        row.lease_expires_at = utcnow() - timedelta(seconds=1)
        self.db.commit()
        publisher = MagicMock()
        operations.dispatch(self.db, publisher)
        self.assertEqual(self.db.query(SendJob).filter_by(id=job_id).first().status, 'unknown')
        publisher.assert_not_called()
        next_id = self.submit('a-different-client-key').id
        executor = MagicMock(return_value={'message_id': 'sent-id'})
        operations.process('send', next_id, sessionmaker(self.engine), executor)
        operations.process('send', next_id, sessionmaker(self.engine), executor)
        self.db.expire_all()
        self.assertEqual(self.db.query(SendJob).filter_by(id=next_id).first().status, 'sent')
        self.assertIsNone(self.db.query(SendJob).filter_by(id=next_id).first().payload_ciphertext)
        executor.assert_called_once()

    def test_compose_worker_stamps_correlation_and_uses_provider_once(self):
        row = self.submit()
        service = MagicMock()
        service.users.return_value.messages.return_value.send.return_value.execute.return_value = {'id': 'sent'}
        result = send_jobs.execute_job(self.db, row, {'to': 'recipient@example.com', 'subject': 'Reviewed mail', 'body': 'Hello'},
                                       service, MagicMock())
        self.assertEqual(result['message_id'], 'sent')
        service.users.return_value.messages.return_value.send.return_value.execute.assert_called_once_with(num_retries=0)
