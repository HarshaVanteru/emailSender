"""All Gmail categories remain readable; only explicit Primary reaches AI."""
import json
import unittest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from sqlalchemy.orm import sessionmaker

import test_mailbox_reader
from app.features.ai_assistant.context_schemas import ContextAiRequest
from app.features.ai_assistant.context_service import generate
from app.features.ai_assistant.mybox import classify_pending
from app.features.mailbox.models import EmailLabel, EmailMessage, MessageLabel, MessageTriage


class CategoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        test_mailbox_reader.MailboxReaderTests.setUpClass.__func__(cls)

    tearDown = test_mailbox_reader.MailboxReaderTests.tearDown
    get = test_mailbox_reader.MailboxReaderTests.get

    def setUp(self):
        test_mailbox_reader.MailboxReaderTests.setUp(self)
        self.db.query(MessageLabel).filter_by(account_id=self.account.id).delete(synchronize_session=False)
        self.categories = ['CATEGORY_PERSONAL', 'CATEGORY_PROMOTIONS', 'CATEGORY_SOCIAL', 'CATEGORY_UPDATES', 'CATEGORY_FORUMS']
        self.labels = {}
        for name in [*self.categories, 'SPAM', 'TRASH']:
            label = EmailLabel(account_id=self.account.id, gmail_label_id=name, name=name, type='system')
            self.db.add(label); self.db.flush()
            self.labels[name] = label.id
        for row, category in zip(self.rows, self.categories):
            self.add_labels(row, category)
        self.blocked = []
        for index, names in enumerate([['CATEGORY_PERSONAL', 'SPAM'], ['CATEGORY_PERSONAL', 'TRASH'],
                                       ['CATEGORY_PERSONAL', 'CATEGORY_PROMOTIONS'], []]):
            row = EmailMessage(account_id=self.account.id, thread_id=self.thread.id, gmail_message_id=f'blocked{index}',
                subject=f'blocked{index}', body_text=f'NEVER SEND blocked{index}', internal_date=9000 + index)
            self.db.add(row); self.db.flush()
            self.add_labels(row, *names)
            self.blocked.append(row)
        self.account.encrypted_credentials = 'opaque'
        self.db.commit()
        self.sessions = sessionmaker(bind=self.engine)

    def add_labels(self, row, *names):
        for name in names:
            self.db.add(MessageLabel(account_id=self.account.id, message_id=row.id, label_id=self.labels[name]))

    def test_only_primary_reaches_ai_while_every_category_stays_in_its_section(self):
        model = MagicMock()
        model.invoke.return_value = {'is_spam': False, 'importance': 'normal', 'category': 'other', 'reason': 'Ordinary mail'}
        with patch('app.core.config.MYBOX_ENABLED', True), patch('app.features.ai_assistant.mybox.publish_update'):
            self.assertEqual(classify_pending(self.sessions, model=model), 1)
        model.invoke.assert_called_once()
        self.assertEqual(json.loads(model.invoke.call_args.args[0][1].content)['subject'], self.rows[0].subject)
        self.assertEqual(self.db.query(MessageTriage).count(), 1)
        self.assertEqual([item['id'] for item in self.get(label='MYBOX').json()['items']], [self.rows[0].id])
        for category, row in zip(self.categories, self.rows):
            visible = {item['id'] for item in self.get(label=category).json()['items']}
            self.assertIn(row.id, visible)
            self.assertFalse(visible & {self.blocked[0].id, self.blocked[1].id})
            if category == 'CATEGORY_PERSONAL':
                self.assertEqual(visible, {self.rows[0].id})
        self.assertEqual([item['id'] for item in self.get(label='SPAM').json()['items']], [self.blocked[0].id])
        self.assertEqual([item['id'] for item in self.get(label='TRASH').json()['items']], [self.blocked[1].id])

    def test_nonprimary_manual_ai_is_blocked_and_mixed_threads_are_filtered(self):
        model = MagicMock()
        for row in [*self.rows[1:], *self.blocked]:
            with self.assertRaises(HTTPException) as caught:
                generate(self.db, self.owner.id, self.account.id, self.thread.id, 'summarize',
                    ContextAiRequest(message_id=row.id), model=model)
            self.assertEqual(caught.exception.status_code, 409)
        model.invoke.assert_not_called()
        model.invoke.return_value = {'summary': 'Primary only.', 'key_points': []}
        generate(self.db, self.owner.id, self.account.id, self.thread.id, 'summarize', ContextAiRequest(), model=model)
        source = json.loads(model.invoke.call_args.args[0][1].content)
        self.assertEqual([item['id'] for item in source['conversation']], [self.rows[0].id])

    def test_category_pagination_is_scoped_and_never_includes_spam_or_trash(self):
        ids, token = [], None
        while True:
            page = self.get(page_size=2, **({'page_token': token} if token else {})).json()
            ids.extend(item['id'] for item in page['items'])
            token = page['next_page_token']
            if not token: break
        self.assertEqual(len(ids), len(set(ids)))
        self.assertNotIn(self.blocked[0].id, ids)
        self.assertNotIn(self.blocked[1].id, ids)
        first = self.get(label='CATEGORY_PROMOTIONS', page_size=1).json()
        self.assertIsNotNone(first['next_page_token'])
        self.assertEqual(self.get(label='CATEGORY_PERSONAL', page_token=first['next_page_token']).status_code, 400)
