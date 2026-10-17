"""Thread recipients, RFC headers, and explicit send boundaries."""
import base64
import json
import unittest
from email import message_from_bytes, policy
from unittest.mock import MagicMock
from redis.exceptions import ConnectionError

from app.core.config import GMAIL_READ_SCOPE
from app.features.mailbox.models import AuditLog
from app.features.compose_email.thread_schemas import ThreadSend
from app.features.compose_email.thread_service import prepare, send
import test_mailbox_reader


class ThreadSendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        test_mailbox_reader.MailboxReaderTests.setUpClass()
        cls.app = test_mailbox_reader.MailboxReaderTests.app

    setUp = test_mailbox_reader.MailboxReaderTests.setUp
    tearDown = test_mailbox_reader.MailboxReaderTests.tearDown

    def setUp(self):
        test_mailbox_reader.MailboxReaderTests.setUp(self)
        self.account.encrypted_credentials = 'encrypted-test-only'
        self.account.scopes = json.dumps(['https://www.googleapis.com/auth/gmail.send'])
        self.row = self.rows[0]
        self.row.from_address = 'Alex <alex@example.com>'
        self.row.to_addresses = [{'name': 'Owner', 'email': 'owner@example.com'},
                                 {'name': 'Bob', 'email': 'bob@example.com'}]
        self.row.cc_addresses = [{'name': 'Bob', 'email': 'bob@example.com'},
                                 {'name': 'Casey', 'email': 'casey@example.com'}]
        self.row.headers = [{'name': 'Message-ID', 'value': '<old@example.com>'},
                            {'name': 'References', 'value': '<first@example.com>'},
                            {'name': 'Reply-To', 'value': 'Alex <reply@example.com>'}]
        self.db.commit()
        self.provider = MagicMock()
        self.gate = MagicMock()
        self.provider.users.return_value.messages.return_value.send.return_value.execute.return_value = {
            'id': 'sent1', 'threadId': 't1'}

    def input(self, mode='reply', **changes):
        context = prepare(self.db, self.owner.id, self.account.id, self.row.id, mode)
        return ThreadSend.model_validate({'mode': mode, 'context_hash': context['context_hash'],
                                          'to': context['to'] or ['new@example.com'], 'cc': context['cc'],
                                          'body': 'Reviewed response', **changes})

    def test_reply_and_reply_all_recipient_defaults(self):
        reply = prepare(self.db, self.owner.id, self.account.id, self.row.id, 'reply')
        self.assertEqual(reply['to'], ['reply@example.com'])
        self.assertEqual(reply['cc'], [])
        self.assertEqual(reply['subject'], 'Re: Project 0')
        self.assertEqual(reply['in_reply_to'], '<old@example.com>')
        self.assertEqual(reply['references'], '<first@example.com> <old@example.com>')
        all_recipients = prepare(self.db, self.owner.id, self.account.id, self.row.id, 'reply_all')
        self.assertEqual(all_recipients['to'], ['reply@example.com'])
        self.assertEqual(all_recipients['cc'], ['bob@example.com', 'casey@example.com'])

    def test_reply_sends_threaded_mime_with_reviewed_recipients(self):
        data = self.input('reply_all', attachment={'filename': 'note.txt', 'content_type': 'text/plain',
                                                   'data': base64.b64encode(b'hello').decode()})
        result = send(self.db, self.owner.id, self.account.id, self.row.id, data, self.provider, self.gate)
        self.assertEqual(result, {'message_id': 'sent1', 'threaded': True})
        request = self.provider.users.return_value.messages.return_value.send.call_args.kwargs['body']
        self.assertEqual(request['threadId'], 't1')
        mime = message_from_bytes(base64.urlsafe_b64decode(request['raw']), policy=policy.default)
        self.assertEqual(mime['To'], 'reply@example.com')
        self.assertEqual(mime['Cc'], 'bob@example.com, casey@example.com')
        self.assertEqual(mime['In-Reply-To'], '<old@example.com>')
        self.assertEqual(mime['References'], '<first@example.com> <old@example.com>')
        self.assertEqual(mime['Subject'], 'Re: Project 0')
        self.assertEqual(next(part.get_payload(decode=True) for part in mime.walk()
                              if part.get_filename() == 'note.txt'), b'hello')
        self.assertEqual(self.provider.users.return_value.messages.return_value.send.return_value.execute.call_args.kwargs['num_retries'], 0)
        self.assertEqual(self.db.query(AuditLog).filter_by(action='thread.reply_all').count(), 1)

    def test_forward_starts_new_conversation_and_does_not_copy_original_attachment(self):
        context = prepare(self.db, self.owner.id, self.account.id, self.row.id, 'forward')
        self.assertEqual(context['original_attachments'], 1)
        self.assertIn('Forwarded message', context['body'])
        self.assertEqual(context['to'], [])
        self.provider.users.return_value.messages.return_value.send.return_value.execute.return_value = {'id': 'sent2', 'threadId': 'new-thread'}
        send(self.db, self.owner.id, self.account.id, self.row.id, self.input('forward'), self.provider, self.gate)
        request = self.provider.users.return_value.messages.return_value.send.call_args.kwargs['body']
        self.assertNotIn('threadId', request)
        mime = message_from_bytes(base64.urlsafe_b64decode(request['raw']), policy=policy.default)
        self.assertEqual(mime['Subject'], 'Fwd: Project 0')
        self.assertIsNone(mime['In-Reply-To'])

    def test_stale_context_and_missing_message_id_never_send(self):
        data = self.input()
        self.row.subject = 'Changed elsewhere'; self.db.commit()
        with self.assertRaises(Exception) as caught:
            send(self.db, self.owner.id, self.account.id, self.row.id, data, self.provider, self.gate)
        self.assertEqual(caught.exception.status_code, 409)
        self.row.headers = []; self.db.commit()
        with self.assertRaises(Exception) as caught:
            prepare(self.db, self.owner.id, self.account.id, self.row.id, 'reply')
        self.assertEqual(caught.exception.status_code, 409)
        self.provider.users.assert_not_called()

    def test_provider_or_rate_limit_failure_never_retries_send(self):
        data = self.input()
        self.provider.users.return_value.messages.return_value.send.return_value.execute.side_effect = OSError('private timeout')
        with self.assertRaises(Exception) as caught:
            send(self.db, self.owner.id, self.account.id, self.row.id, data, self.provider, self.gate)
        self.assertEqual(caught.exception.status_code, 503)
        self.assertIn('Check Sent', caught.exception.detail)
        self.assertEqual(self.provider.users.return_value.messages.return_value.send.return_value.execute.call_count, 1)
        self.assertEqual(self.db.query(AuditLog).filter_by(action='thread.reply').count(), 0)
        self.gate.wait.side_effect = ConnectionError('private broker detail')
        with self.assertRaises(Exception) as caught:
            send(self.db, self.owner.id, self.account.id, self.row.id, data, self.provider, self.gate)
        self.assertEqual(caught.exception.status_code, 503)
        self.assertEqual(self.provider.users.return_value.messages.return_value.send.return_value.execute.call_count, 1)

    def test_reply_to_own_sent_message_uses_other_recipient(self):
        self.row.from_address = 'Owner <owner@example.com>'
        self.row.headers = [{'name': 'Message-ID', 'value': '<mine@example.com>'}]
        self.db.commit()
        context = prepare(self.db, self.owner.id, self.account.id, self.row.id, 'reply')
        self.assertEqual(context['to'], ['bob@example.com'])

    def test_cross_account_scope_and_bad_payload_rejected(self):
        with self.assertRaises(Exception) as caught:
            prepare(self.db, self.owner.id, self.foreign.id, self.secret.id, 'reply')
        self.assertEqual(caught.exception.status_code, 404)
        self.account.scopes = json.dumps([GMAIL_READ_SCOPE]); self.db.commit()
        with self.assertRaises(Exception) as caught:
            prepare(self.db, self.owner.id, self.account.id, self.row.id, 'reply')
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(self.client.post(f'/api/v1/accounts/{self.account.id}/messages/{self.row.id}/send', json={}).status_code, 422)
        self.provider.users.assert_not_called()

    def test_preview_route_private_and_no_provider_call(self):
        response = self.client.get(f'/api/v1/accounts/{self.account.id}/messages/{self.row.id}/compose',
                                   params={'mode': 'reply_all'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertEqual(response.json()['cc'], ['bob@example.com', 'casey@example.com'])
        self.provider.users.assert_not_called()


if __name__ == '__main__':
    unittest.main()
