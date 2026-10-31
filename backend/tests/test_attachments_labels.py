import base64
import unittest
import test_mailbox_actions as fixtures
from app.features.mailbox.models import EmailAttachment, EmailLabel
from app.features.mailbox.attachments import download
from app.features.mailbox.label_service import mutate
from fastapi import HTTPException


class AttachmentLabelTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.MailboxActionTests.setUpClass.__func__)
    setUp = fixtures.MailboxActionTests.setUp
    tearDown = fixtures.MailboxActionTests.tearDown

    def test_download_is_owned_on_demand_and_always_an_attachment(self):
        part = self.db.query(EmailAttachment).filter_by(account_id=self.account.id).first()
        part.filename = '../../unsafe\r\n.html'
        part.gmail_attachment_id = 'provider-attachment'
        self.db.commit()
        self.service.users.return_value.messages.return_value.attachments.return_value.get.return_value.execute.return_value = {'data': base64.urlsafe_b64encode(b'<script>untrusted</script>').decode()}
        with self.assertRaises(HTTPException):
            download(self.db, self.owner.id, self.foreign.id, part.id, self.service, self.gate)
        response = download(self.db, self.owner.id, self.account.id, part.id, self.service, self.gate)
        self.assertEqual(response.media_type, 'application/octet-stream')
        self.assertEqual(response.headers['x-content-type-options'], 'nosniff')
        self.assertNotIn('\r', response.headers['content-disposition'])
        self.assertNotIn('../', response.headers['content-disposition'])
        self.assertEqual(response.body, b'<script>untrusted</script>')

    def test_label_assignment_rejects_foreign_ids_and_reconciles_provider_state(self):
        own = EmailLabel(account_id=self.account.id, gmail_label_id='Label_own', name='Own', type='user')
        other = EmailLabel(account_id=self.foreign.id, gmail_label_id='Label_secret', name='Secret', type='user')
        self.db.add_all([own, other]); self.db.commit()
        with self.assertRaises(HTTPException):
            mutate(self.db, self.owner.id, self.account.id, 'assign', message_id=self.rows[0].id,
                   add=['Label_secret'], service=self.service, limiter=self.gate)
        self.service.users.return_value.messages.return_value.modify.assert_not_called()
        self.service.users.return_value.messages.return_value.modify.return_value.execute.return_value = {'id': 'm0', 'labelIds': ['Label_own'], 'historyId': '200'}
        result = mutate(self.db, self.owner.id, self.account.id, 'assign', message_id=self.rows[0].id,
                        add=['Label_own'], service=self.service, limiter=self.gate)
        self.assertEqual(result['labels'], ['Label_own'])
