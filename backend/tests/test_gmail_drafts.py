"""Draft MIME round-trips and explicit reviewed Gmail sends."""
import base64
import json
from email import message_from_bytes, policy
import unittest
from unittest.mock import MagicMock, patch

from app.core.config import GMAIL_COMPOSE_SCOPE, GMAIL_READ_SCOPE
from app.features.mailbox.models import AuditLog
from app.features.drafts.schemas import DraftInput
from app.features.drafts.service import draft_details, get_draft, list_drafts, save_draft, send_draft
from app.integrations.gmail.client import gmail_service
import test_mailbox_reader


class GmailDraftTests(unittest.TestCase):
    def test_provider_page_tokens_are_encrypted_and_bound_to_owner_and_mailbox(self):
        from cryptography.fernet import Fernet
        with patch('app.core.config.TOKEN_ENCRYPTION_KEY', Fernet.generate_key().decode()):
            self.resource.list.return_value.execute.return_value = {'drafts': [], 'nextPageToken': 'provider-private-page'}
            page = list_drafts(self.db, self.owner.id, self.account.id, service=self.provider, limiter=self.gate)
            cursor = page['next_page_token']
            self.assertNotIn('provider-private-page', cursor)
            self.resource.list.return_value.execute.return_value = {'drafts': []}
            list_drafts(self.db, self.owner.id, self.account.id, cursor, self.provider, self.gate)
            self.assertEqual(self.resource.list.call_args.kwargs['pageToken'], 'provider-private-page')
            with self.assertRaises(Exception) as caught:
                list_drafts(self.db, self.owner.id, self.foreign.id, cursor, self.provider, self.gate)
            self.assertEqual(caught.exception.status_code, 400)

    @classmethod
    def setUpClass(cls):
        test_mailbox_reader.MailboxReaderTests.setUpClass()
        cls.app = test_mailbox_reader.MailboxReaderTests.app

    setUp = test_mailbox_reader.MailboxReaderTests.setUp
    tearDown = test_mailbox_reader.MailboxReaderTests.tearDown

    def setUp(self):
        test_mailbox_reader.MailboxReaderTests.setUp(self)
        self.account.encrypted_credentials = 'encrypted-test-only'
        self.account.scopes = json.dumps([GMAIL_COMPOSE_SCOPE])
        self.db.commit()
        self.provider = MagicMock()
        self.gate = MagicMock()
        self.resource = self.provider.users.return_value.drafts.return_value
        self.input = DraftInput(to='receiver@example.com', subject='Hello', body='A short note.')
        self.raw = gmail_service.build_raw(self.input.to, self.input.subject, self.input.body, draft=True)
        self.resource.get.return_value.execute.return_value = {'id': 'draft1', 'message': {'raw': self.raw}}
        self.resource.create.return_value.execute.return_value = {'id': 'draft1'}
        self.resource.update.return_value.execute.return_value = {'id': 'draft1'}
        self.resource.send.return_value.execute.return_value = {'id': 'sent1'}

    def test_create_and_update_use_gmail_drafts_and_version_hash(self):
        created = save_draft(self.db, self.owner.id, self.account.id, self.input, service=self.provider, limiter=self.gate)
        self.assertEqual(created['to'], 'receiver@example.com')
        self.assertEqual(created['subject'], 'Hello')
        self.assertTrue(created['can_edit'])
        created_raw = self.resource.create.call_args.kwargs['body']['message']['raw']
        self.assertEqual(draft_details({'id': 'draft1', 'message': {'raw': created_raw}})['body'], created['body'])
        changed = self.input.model_copy(update={'content_hash': created['content_hash'], 'subject': 'Changed'})
        save_draft(self.db, self.owner.id, self.account.id, changed, 'draft1', self.provider, self.gate)
        self.assertEqual(self.resource.update.call_args.kwargs['id'], 'draft1')
        self.assertEqual(self.db.query(AuditLog).filter_by(resource_type='gmail_draft').count(), 2)
        stale = self.input.model_copy(update={'content_hash': '0' * 64})
        with self.assertRaises(Exception) as caught:
            save_draft(self.db, self.owner.id, self.account.id, stale, 'draft1', self.provider, self.gate)
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(self.resource.update.call_count, 1)

    def test_reviewed_send_uses_draft_id_once_and_rejects_stale_hash(self):
        current = get_draft(self.db, self.owner.id, self.account.id, 'draft1', self.provider, self.gate)
        with self.assertRaises(Exception) as caught:
            send_draft(self.db, self.owner.id, self.account.id, 'draft1', '0' * 64, self.provider, self.gate)
        self.assertEqual(caught.exception.status_code, 409)
        self.resource.send.assert_not_called()
        result = send_draft(self.db, self.owner.id, self.account.id, 'draft1', current['content_hash'], self.provider, self.gate)
        self.assertEqual(result, {'message_id': 'sent1'})
        self.resource.send.assert_called_once_with(userId='me', body={'id': 'draft1'})
        self.assertEqual(self.resource.send.return_value.execute.call_args.kwargs['num_retries'], 0)

    def test_external_recipients_or_html_only_cannot_be_rewritten_or_sent(self):
        raw = base64.urlsafe_b64encode(b'To: a@example.com, b@example.com\nCc: c@example.com\nSubject: Hi\nContent-Type: text/html\n\n<p>Hello</p>').decode()
        self.resource.get.return_value.execute.return_value = {'id': 'draft1', 'message': {'raw': raw}}
        item = get_draft(self.db, self.owner.id, self.account.id, 'draft1', self.provider, self.gate)
        self.assertIn('b@example.com', item['to'])
        self.assertEqual(item['cc'], 'c@example.com')
        self.assertFalse(item['can_edit'])
        with self.assertRaises(Exception) as caught:
            send_draft(self.db, self.owner.id, self.account.id, 'draft1', item['content_hash'], self.provider, self.gate)
        self.assertEqual(caught.exception.status_code, 409)
        self.resource.send.assert_not_called()

    def test_attachment_roundtrip_is_available_for_editor(self):
        raw = gmail_service.build_raw('receiver@example.com', 'File', 'See attached.',
                                      {'filename': 'notes.txt', 'content_type': 'text/plain', 'data': base64.b64encode(b'hello').decode()}, draft=True)
        item = draft_details({'id': 'draft1', 'message': {'raw': raw}})
        self.assertTrue(item['can_edit'])
        self.assertEqual(base64.b64decode(item['attachments'][0]['data']), b'hello')

    def test_app_draft_with_connected_sender_can_be_updated_and_sent(self):
        message = message_from_bytes(base64.urlsafe_b64decode(self.raw), policy=policy.default)
        message['From'] = 'Owner <owner@example.com>'
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        self.resource.get.return_value.execute.return_value = {'id': 'draft1', 'message': {'raw': raw}}
        current = get_draft(self.db, self.owner.id, self.account.id, 'draft1', self.provider, self.gate)
        self.assertTrue(current['can_edit'])
        changed = self.input.model_copy(update={'content_hash': current['content_hash']})
        save_draft(self.db, self.owner.id, self.account.id, changed, 'draft1', self.provider, self.gate)
        result = send_draft(self.db, self.owner.id, self.account.id, 'draft1', current['content_hash'], self.provider, self.gate)
        self.assertEqual(result['message_id'], 'sent1')

    def test_other_sender_reply_headers_and_duplicate_sender_remain_protected(self):
        for header, value in [('From', 'other@example.com'), ('Reply-To', 'other@example.com'),
                              ('In-Reply-To', '<original@example.com>'), ('References', '<original@example.com>'),
                              ('From', 'owner@example.com\nFrom: owner@example.com')]:
            with self.subTest(header=header, value=value):
                raw = base64.urlsafe_b64encode(
                    f'{header}: {value}\n'.encode() + base64.urlsafe_b64decode(self.raw)).decode()
                self.resource.get.return_value.execute.return_value = {'id': 'draft1', 'message': {'raw': raw}}
                current = get_draft(self.db, self.owner.id, self.account.id, 'draft1', self.provider, self.gate)
                self.assertFalse(current['can_edit'])
                with self.assertRaises(Exception) as caught:
                    send_draft(self.db, self.owner.id, self.account.id, 'draft1', current['content_hash'], self.provider, self.gate)
                self.assertEqual(caught.exception.status_code, 409)
        self.resource.send.assert_not_called()

    def test_scope_ownership_and_validation_fail_before_provider_call(self):
        self.account.scopes = json.dumps([GMAIL_READ_SCOPE]); self.db.commit()
        for account_id in (self.account.id, self.foreign.id):
            with self.assertRaises(Exception) as caught:
                list_drafts(self.db, self.owner.id, account_id, service=self.provider, limiter=self.gate)
            self.assertEqual(caught.exception.status_code, 409 if account_id == self.account.id else 404)
        self.provider.users.assert_not_called()
        self.assertEqual(self.client.post(f'/api/v1/accounts/{self.account.id}/drafts', json={'to': 'bad'}).status_code, 422)
        self.assertEqual(self.client.post(f'/api/v1/accounts/{self.account.id}/drafts', json={
            'subject': 'bad\nheader', 'attachment': {'filename': 'notes.txt', 'content_type': 'text/plain', 'data': '!!!'}
        }).status_code, 422)
        self.assertEqual(self.client.post(f'/api/v1/accounts/{self.account.id}/drafts', json={
            'attachment': {'filename': 'notes.txt', 'content_type': 'text/plain', 'data': '!!!'}
        }).status_code, 422)
        self.assertEqual(self.client.post(f'/api/v1/accounts/{self.account.id}/drafts/draft1/send', json={}).status_code, 422)

    def test_api_routes_have_private_headers_and_use_owned_account(self):
        with patch('app.features.drafts.service.credentials_for_account', return_value=MagicMock()) as credentials, patch(
             'app.features.drafts.service.gmail_service.get_gmail_service', return_value=self.provider), patch(
             'app.features.drafts.service.GmailRateLimiter', return_value=self.gate):
            response = self.client.get(f'/api/v1/accounts/{self.account.id}/drafts/draft1')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertEqual(response.json()['subject'], 'Hello')
        credentials.assert_called_once_with(self.db, self.owner.id, self.account.id)


if __name__ == '__main__':
    unittest.main()
