import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.security import get_current_user
from app.features.google_login.models import ConnectedAccount
from app.features.mailbox.models import EmailAttachment, EmailLabel, EmailMessage, EmailThread, MessageLabel
from app.features.google_login.user import User


class MailboxReaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch('app.core.config.GROQ_API_KEY', 'test-not-real'):
            from app.main import app
        cls.app = app

    def setUp(self):
        self.engine = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
        @event.listens_for(self.engine, 'connect')
        def enable_fk(connection, _): connection.execute('PRAGMA foreign_keys=ON')
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.owner = User(email='owner@example.com')
        self.stranger = User(email='stranger@example.com')
        self.db.add_all([self.owner, self.stranger]); self.db.flush()
        self.account = ConnectedAccount(user_id=self.owner.id, gmail_email=self.owner.email,
                                       scopes=json.dumps(['https://www.googleapis.com/auth/gmail.readonly']))
        self.foreign = ConnectedAccount(user_id=self.stranger.id, gmail_email=self.stranger.email)
        self.db.add_all([self.account, self.foreign]); self.db.flush()
        self.thread = EmailThread(account_id=self.account.id, gmail_thread_id='t1', subject='Project notes')
        foreign_thread = EmailThread(account_id=self.foreign.id, gmail_thread_id='t1', subject='Private')
        self.db.add_all([self.thread, foreign_thread]); self.db.flush()
        self.rows = []
        for index in range(5):
            row = EmailMessage(account_id=self.account.id, thread_id=self.thread.id, gmail_message_id=f'm{index}',
                               subject=f'Project {index}', from_address='Alex <alex@example.com>',
                               to_addresses=[{'name': 'Owner', 'email': self.owner.email}],
                               internal_date=1000 if index < 3 else 2000 + index,
                               body_text='Meeting notes 100%_done', body_html='<script>bad()</script><p>Hi</p>', snippet='Project update')
            self.db.add(row); self.rows.append(row)
        self.secret = EmailMessage(account_id=self.foreign.id, thread_id=foreign_thread.id, gmail_message_id='secret',
                                   internal_date=9999, subject='Secret from other account')
        self.db.add(self.secret); self.db.flush()
        inbox = EmailLabel(account_id=self.account.id, gmail_label_id='INBOX', name='Inbox', type='system')
        unread = EmailLabel(account_id=self.account.id, gmail_label_id='UNREAD', name='Unread', type='system')
        sent = EmailLabel(account_id=self.account.id, gmail_label_id='SENT', name='Sent', type='system')
        self.db.add_all([inbox, unread, sent]); self.db.flush()
        for row in self.rows[:4]:
            self.db.add(MessageLabel(account_id=self.account.id, message_id=row.id, label_id=inbox.id))
        self.db.add(MessageLabel(account_id=self.account.id, message_id=self.rows[0].id, label_id=unread.id))
        self.db.add(MessageLabel(account_id=self.account.id, message_id=self.rows[-1].id, label_id=sent.id))
        self.db.add(EmailAttachment(account_id=self.account.id, message_id=self.rows[0].id,
                                   mime_part_id='1', filename='notes.pdf', mime_type='application/pdf', size_bytes=600))
        self.db.commit()
        self.app.dependency_overrides[get_db] = lambda: self.db
        self.app.dependency_overrides[get_current_user] = lambda: self.owner
        self.client = TestClient(self.app)

    def tearDown(self):
        self.app.dependency_overrides.clear()
        self.db.close(); self.engine.dispose()

    def get(self, path='/emails', **params):
        return self.client.get('/api/v1' + path, params={'account_id': self.account.id, **params})

    def test_inbox_unread_and_sent_filters_are_intersected(self):
        result = self.get(label='INBOX', unread=True).json()['items']
        self.assertEqual([item['id'] for item in result], [self.rows[0].id])
        self.assertEqual(result[0]['labels'], ['INBOX', 'UNREAD'])
        self.assertTrue(result[0]['has_attachments'])
        self.assertEqual(len(self.get(label='INBOX', unread=False).json()['items']), 3)
        self.assertEqual([item['id'] for item in self.get(label='SENT').json()['items']], [self.rows[-1].id])
        self.assertEqual(self.get(label='DRAFT').json()['items'], [])

    def test_keyset_pagination_has_no_duplicates_when_dates_tie(self):
        ids, token = [], None
        while True:
            response = self.get(page_size=2, **({'page_token': token} if token else {}))
            self.assertEqual(response.status_code, 200)
            page = response.json()
            ids.extend(item['id'] for item in page['items'])
            token = page['next_page_token']
            if not token: break
        self.assertEqual(ids, [row.id for row in reversed(self.rows)])
        self.assertEqual(len(ids), len(set(ids)))

    def test_cursor_is_bound_to_account_filters_and_thread(self):
        token = self.get(page_size=1).json()['next_page_token']
        for params in ({'unread': True}, {'label': 'INBOX'}, {'q': 'Project'}):
            self.assertEqual(self.get(page_token=token, **params).status_code, 400)
        self.assertEqual(self.get(f'/threads/{self.thread.id}', page_token=token).status_code, 400)
        self.assertEqual(self.get(page_token='%%%').status_code, 400)
        self.assertEqual(self.get(page_token='x'*1025).status_code, 422)

    def test_search_is_literal_case_insensitive_and_scoped(self):
        for query in ('ALEX', 'meeting NOTES', '100%_done', 'owner@example.com'):
            self.assertEqual(len(self.get('/search', q=query).json()['items']), 5)
        self.assertEqual(self.get('/search', q='secret').json()['items'], [])
        self.assertEqual(self.get('/search', q='100%_missing').json()['items'], [])
        self.assertEqual(self.get('/search', q="' OR 1=1 --").json()['items'], [])

    def test_message_detail_returns_body_and_attachment_metadata_only(self):
        response = self.get(f'/emails/{self.rows[0].id}')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertEqual(response.headers['x-content-type-options'], 'nosniff')
        data = response.json()
        self.assertEqual(data['attachments'][0]['filename'], 'notes.pdf')
        self.assertIn('<script>', data['body_html'])  # API is JSON; rendering sanitizes at the client boundary.
        for field in ('headers', 'bcc_addresses', 'gmail_attachment_id', 'encrypted_credentials'):
            self.assertNotIn(field, data)
        self.assertNotIn('body_html', self.get().json()['items'][0])

    def test_thread_reads_all_cached_messages_chronologically_across_labels(self):
        first = self.get(f'/threads/{self.thread.id}', page_size=2).json()
        self.assertEqual([item['id'] for item in first['items']], [row.id for row in self.rows[:2]])
        second = self.get(f'/threads/{self.thread.id}', page_size=25, page_token=first['next_page_token']).json()
        self.assertEqual([item['id'] for item in second['items']], [row.id for row in self.rows[2:]])
        self.assertIsNone(second['next_page_token'])

    def test_other_users_accounts_messages_threads_and_labels_are_hidden(self):
        for path in ('/emails', '/search', f'/emails/{self.secret.id}', f'/threads/{self.secret.thread_id}', f'/accounts/{self.foreign.id}/labels'):
            self.assertEqual(self.get(path, account_id=self.foreign.id).status_code, 404, path)
        self.assertEqual(self.get(f'/emails/{self.secret.id}').status_code, 404)
        self.assertEqual(self.get(f'/threads/{self.secret.thread_id}').status_code, 404)

    def test_reading_cache_never_calls_google_or_changes_unread(self):
        with patch('app.integrations.gmail.client.gmail_service.get_gmail_service') as provider:
            self.get(f'/threads/{self.thread.id}')
            self.get(f'/emails/{self.rows[0].id}')
            provider.assert_not_called()
        self.assertIn('UNREAD', self.get(f'/emails/{self.rows[0].id}').json()['labels'])

    def test_labels_and_input_bounds(self):
        self.assertEqual({item['id'] for item in self.get(f'/accounts/{self.account.id}/labels').json()}, {'INBOX', 'SENT', 'UNREAD'})
        for params in ({'page_size': 0}, {'page_size': 101}, {'account_id': -1}, {'q': 'x'*201}):
            self.assertEqual(self.get(**params).status_code, 422)
        self.assertEqual(self.get(f'/threads/{self.thread.id}', page_size=26).status_code, 422)

    def test_mailbox_routes_require_authentication(self):
        self.app.dependency_overrides.pop(get_current_user)
        self.assertEqual(self.get().status_code, 401)
