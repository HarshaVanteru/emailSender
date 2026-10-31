import unittest
from unittest.mock import patch
import test_gmail_push as fixtures
from app.features.mail_sync import push
from app.features.mail_sync.push_models import PushEvent


class PushInboxTests(unittest.TestCase):
    setUp = fixtures.PushTests.setUp
    tearDown = fixtures.PushTests.tearDown

    def test_duplicate_envelope_is_durable_and_dispatched_once(self):
        with patch.object(push, 'dispatch_job') as dispatch:
            push.accept_notification(self.db, self.account.gmail_email, '110', 'event-unique')
            push.accept_notification(self.db, self.account.gmail_email, '110', 'event-unique')
            self.assertEqual(self.db.query(PushEvent).count(), 1)
            self.assertEqual(dispatch.call_count, 1)
        self.assertEqual(self.db.query(PushEvent).one().status, 'pending')

    def test_unknown_mailbox_and_old_cursor_are_recorded_without_sync(self):
        push.accept_notification(self.db, 'unknown@example.com', '111', 'event-unknown')
        push.accept_notification(self.db, self.account.gmail_email, '99', 'event-old')
        states = {row.pubsub_message_id: row.status for row in self.db.query(PushEvent)}
        self.assertEqual(states, {'event-unknown': 'ignored', 'event-old': 'processed'})
