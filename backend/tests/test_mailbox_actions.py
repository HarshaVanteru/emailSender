"""Account and provider boundaries for explicit Gmail mailbox mutations."""
import json
import unittest
from unittest.mock import MagicMock, patch

from googleapiclient.errors import HttpError
from httplib2 import Response
from redis.exceptions import ConnectionError

from app.core.config import GMAIL_MODIFY_SCOPE, GMAIL_READ_SCOPE
from app.features.mailbox.models import AuditLog, EmailMessage
from app.features.mailbox.actions import change_message
import test_mailbox_reader


class MailboxActionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        test_mailbox_reader.MailboxReaderTests.setUpClass()
        cls.app = test_mailbox_reader.MailboxReaderTests.app

    setUp = test_mailbox_reader.MailboxReaderTests.setUp
    tearDown = test_mailbox_reader.MailboxReaderTests.tearDown
    get = test_mailbox_reader.MailboxReaderTests.get

    def setUp(self):
        test_mailbox_reader.MailboxReaderTests.setUp(self)
        self.account.encrypted_credentials = 'encrypted-test-only'
        self.account.scopes = json.dumps([GMAIL_MODIFY_SCOPE])
        self.db.commit()
        self.service = MagicMock()
        self.gate = MagicMock()

    def labels(self, message_id=None):
        return self.get(f'/emails/{message_id or self.rows[0].id}').json()['labels']

    def mutate(self, response, **change):
        self.service.users.return_value.messages.return_value.modify.return_value.execute.return_value = response
        return change_message(self.db, self.owner.id, self.account.id, self.rows[0].id,
                              service=self.service, limiter=self.gate, **change)

    def test_read_unread_star_and_unstar_follow_gmail_response(self):
        for change, expected_body, labels in [
            ({'read': True}, {'addLabelIds': [], 'removeLabelIds': ['UNREAD']}, ['INBOX']),
            ({'read': False}, {'addLabelIds': ['UNREAD'], 'removeLabelIds': []}, ['INBOX', 'UNREAD']),
            ({'starred': True}, {'addLabelIds': ['STARRED'], 'removeLabelIds': []}, ['INBOX', 'UNREAD', 'STARRED']),
            ({'starred': False}, {'addLabelIds': [], 'removeLabelIds': ['STARRED']}, ['INBOX', 'UNREAD']),
        ]:
            result = self.mutate({'id': 'm0', 'labelIds': labels, 'historyId': '200'}, **change)
            self.assertEqual(set(result['labels']), set(labels))
            self.assertEqual(set(self.labels()), set(labels))
            self.assertEqual(self.rows[0].gmail_history_id, '200')
            self.assertEqual(self.service.users.return_value.messages.return_value.modify.call_args.kwargs['body'], expected_body)
        self.assertEqual(self.db.query(AuditLog).filter_by(action='mailbox.modify', outcome='success').count(), 4)
        self.assertEqual(self.gate.wait.call_count, 4)

    def test_archive_and_trash_are_distinct_and_cache_follows_provider(self):
        result = self.mutate({'id': 'm0', 'labelIds': ['UNREAD']}, action='archive')
        self.assertEqual(result['labels'], ['UNREAD'])
        self.assertNotIn(self.rows[0].id, [item['id'] for item in self.get(label='INBOX').json()['items']])
        self.service.users.return_value.messages.return_value.trash.return_value.execute.return_value = {
            'id': 'm0', 'labelIds': ['TRASH', 'UNREAD']}
        result = change_message(self.db, self.owner.id, self.account.id, self.rows[0].id,
                                action='trash', service=self.service, limiter=self.gate)
        self.assertEqual(set(result['labels']), {'TRASH', 'UNREAD'})
        self.assertEqual(self.db.query(EmailMessage).filter_by(account_id=self.account.id).count(), 5)
        self.service.users.return_value.messages.return_value.trash.assert_called_once_with(userId='me', id='m0')
        self.service.users.return_value.messages.return_value.delete.assert_not_called()
        self.assertEqual(self.db.query(AuditLog).filter_by(action='mailbox.trash', outcome='success').count(), 1)

    def test_readonly_and_disconnected_accounts_reject_before_gmail_call(self):
        for scopes, credentials, expected in [([GMAIL_READ_SCOPE], 'opaque', 409),
                                               ([GMAIL_MODIFY_SCOPE], None, 409)]:
            self.account.scopes = json.dumps(scopes)
            self.account.encrypted_credentials = credentials
            self.db.commit()
            response = self.client.patch(f'/api/v1/emails/{self.rows[0].id}', params={'account_id': self.account.id},
                                         json={'read': True})
            self.assertEqual(response.status_code, expected)
            self.assertIn('UNREAD', self.labels())
        self.service.users.assert_not_called()

    def test_guessed_message_or_account_ids_do_not_reach_gmail(self):
        for account_id, message_id in [(self.account.id, self.secret.id), (self.foreign.id, self.secret.id),
                                       (self.foreign.id, self.rows[0].id)]:
            with self.assertRaises(Exception) as caught:
                change_message(self.db, self.owner.id, account_id, message_id,
                               read=True, service=self.service, limiter=self.gate)
            self.assertEqual(caught.exception.status_code, 404)
        self.service.users.assert_not_called()

    def test_provider_rejection_retains_cache_and_reports_safe_error(self):
        self.service.users.return_value.messages.return_value.modify.return_value.execute.side_effect = HttpError(
            Response({'status': '403'}), b'{"error":"private-provider-detail"}')
        with self.assertRaises(Exception) as caught:
            change_message(self.db, self.owner.id, self.account.id, self.rows[0].id,
                           read=True, service=self.service, limiter=self.gate)
        self.assertEqual(caught.exception.status_code, 409)
        self.assertNotIn('private-provider-detail', str(caught.exception.detail))
        self.assertIn('UNREAD', self.labels())
        self.assertEqual(self.db.query(AuditLog).count(), 0)

    def test_bad_provider_response_and_rate_service_outage_leave_cache_unchanged(self):
        with self.assertRaises(Exception) as caught:
            self.mutate({'id': 'other-message', 'labelIds': []}, read=True)
        self.assertEqual(caught.exception.status_code, 502)
        self.assertIn('UNREAD', self.labels())
        self.gate.wait.side_effect = ConnectionError('private')
        with self.assertRaises(Exception) as caught:
            self.mutate({'id': 'm0', 'labelIds': []}, read=True)
        self.assertEqual(caught.exception.status_code, 503)
        self.assertIn('UNREAD', self.labels())

    def test_validation_rejects_missing_or_unrecognized_changes_without_calls(self):
        for body in ({}, {'read': None}, {'read': 'maybe'}, {'delete': True}):
            response = self.client.patch(f'/api/v1/emails/{self.rows[0].id}', params={'account_id': self.account.id}, json=body)
            self.assertEqual(response.status_code, 422)
        self.service.users.assert_not_called()

    def test_api_calls_authorized_service_and_never_permanent_delete(self):
        response = {'id': 'm0', 'labelIds': ['INBOX']}
        self.service.users.return_value.messages.return_value.modify.return_value.execute.return_value = response
        with patch('app.features.mailbox.actions.credentials_for_account', return_value=MagicMock()) as credentials, patch(
             'app.features.mailbox.actions.gmail_service.get_gmail_service', return_value=self.service), patch(
             'app.features.mailbox.actions.GmailRateLimiter', return_value=self.gate):
            result = self.client.patch(f'/api/v1/emails/{self.rows[0].id}', params={'account_id': self.account.id}, json={'read': True})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.headers['cache-control'], 'no-store')
        self.assertEqual(result.json()['labels'], ['INBOX'])
        credentials.assert_called_once_with(self.db, self.owner.id, self.account.id)
        self.service.users.return_value.messages.return_value.delete.assert_not_called()


if __name__ == '__main__':
    unittest.main()
