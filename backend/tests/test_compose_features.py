"""Expanded compose validation, rich MIME, and safe draft round trips."""
import base64
import unittest
from email import message_from_bytes, policy
from unittest.mock import patch

from pydantic import ValidationError

from app.features.compose_email.schemas import SendEmailRequest
from app.features.drafts.schemas import DraftInput
from app.features.drafts.service import draft_details, discard_draft, save_draft
from app.features.compose_email.rich_text import clean_html
from app.integrations.gmail.client import gmail_service
import test_gmail_drafts


class ComposeFeatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        test_gmail_drafts.GmailDraftTests.setUpClass.__func__(cls)

    setUp = test_gmail_drafts.GmailDraftTests.setUp
    tearDown = test_gmail_drafts.GmailDraftTests.tearDown

    def test_multiple_recipients_cc_bcc_and_attachments_survive_mime_roundtrip(self):
        file = {"filename": "one.txt", "content_type": "text/plain", "data": base64.b64encode(b"first").decode()}
        content = DraftInput(to="a@example.com, b@example.com", cc="c@example.com", bcc="hidden@example.com",
                             subject="Rich draft", body="Hello", body_html='<p><b>Hello</b> <a href="https://example.com">link</a></p>',
                             attachments=[file, {**file, "filename": "two.txt"}])
        raw = gmail_service.build_raw(content.to, content.subject, content.body, draft=True, cc=content.cc,
                                     bcc=content.bcc, body_html=content.body_html,
                                     attachments=[item.model_dump() for item in content.attachments])
        result = draft_details({"id": "draft1", "message": {"raw": raw}})
        self.assertTrue(result["can_edit"])
        self.assertEqual(result["cc"], "c@example.com")
        self.assertEqual(result["bcc"], "hidden@example.com")
        self.assertIn("b@example.com", result["to"])
        self.assertIn("<b>Hello</b>", result["body_html"])
        self.assertEqual([item["filename"] for item in result["attachments"]], ["one.txt", "two.txt"])

    def test_inline_images_are_related_mime_and_restore_to_editable_html(self):
        png = base64.b64encode(b"image-bytes").decode()
        raw = gmail_service.build_raw("a@example.com", "Inline", "See image", draft=True,
                                     body_html=f'<p>See image<img src="data:image/png;base64,{png}"></p>')
        mime = message_from_bytes(base64.urlsafe_b64decode(raw), policy=policy.default)
        image = next(part for part in mime.walk() if part.get_content_type() == "image/png")
        self.assertTrue(image["Content-ID"])
        self.assertEqual(image.get_payload(decode=True), b"image-bytes")
        result = draft_details({"id": "draft1", "message": {"raw": raw}})
        self.assertTrue(result["can_edit"])
        self.assertIn(f"data:image/png;base64,{png}", result["body_html"])
        self.assertEqual(result["attachments"], [])

    def test_html_allowlist_rejects_active_content_tracking_and_layout_overrides(self):
        html, _ = clean_html('<script>alert(1)</script><svg onload="bad()"></svg><img src="https://tracker.example/a"><p onclick="bad()" style="position:fixed;color:red;background-color:expression(alert(1))">Safe</p><a href="javascript:alert(1)">link</a>')
        self.assertNotIn("script", html)
        self.assertNotIn("tracker", html)
        self.assertNotIn("onclick", html)
        self.assertNotIn("position", html)
        self.assertNotIn("expression", html)
        self.assertNotIn("javascript", html)
        self.assertIn("color:red", html)
        self.assertIn("Safe", html)

    def test_invalid_recipients_headers_and_files_rejected_before_sending(self):
        for extra in ({"to": "bad"}, {"bcc": "bad"}, {"cc": "a@example.com\r\nBcc: bad@example.com"},
                      {"subject": "unsafe\nHeader"}, {"attachments": [{"filename": "x", "content_type": "text/plain", "data": "!!!"}]}):
            with self.assertRaises(ValidationError):
                SendEmailRequest(**{"to": "a@example.com", "subject": "Hi", "body": "Hello", **extra})
        self.assertEqual(SendEmailRequest(bcc="a@example.com", subject="Hi", body="Hello").bcc, "a@example.com")
        self.assertIsNone(DraftInput().to)

    def test_save_passes_all_reviewed_fields_to_gmail(self):
        content = DraftInput(to="a@example.com, b@example.com", cc="c@example.com", bcc="d@example.com", body="Hello",
                             body_html="<b>Hello</b>", subject="Hi")
        save_draft(self.db, self.owner.id, self.account.id, content, service=self.provider, limiter=self.gate)
        raw = self.resource.create.call_args.kwargs["body"]["message"]["raw"]
        result = draft_details({"id": "draft1", "message": {"raw": raw}})
        self.assertEqual(result["bcc"], "d@example.com")
        self.assertEqual(result["body_html"].strip(), "<b>Hello</b>")

    def test_discard_checks_latest_hash_and_does_not_send(self):
        current = draft_details({"id": "draft1", "message": {"raw": self.raw}})
        with self.assertRaises(Exception) as caught:
            discard_draft(self.db, self.owner.id, self.account.id, "draft1", "0" * 64, self.provider, self.gate)
        self.assertEqual(caught.exception.status_code, 409)
        self.resource.delete.assert_not_called()
        discard_draft(self.db, self.owner.id, self.account.id, "draft1", current["content_hash"], self.provider, self.gate)
        self.resource.delete.assert_called_once_with(userId="me", id="draft1")
        self.resource.delete.return_value.execute.assert_called_once_with(num_retries=0)
        self.resource.send.assert_not_called()

    def test_send_uses_selected_owned_account(self):
        with patch("app.features.compose_email.routes.account_service.credentials_for_account") as credentials, patch.object(gmail_service, "send_email", return_value={"id": "sent-rich"}) as send:
            response = self.client.post("/api/v1/gmail/send", json={"account_id": self.account.id,
                "to": "a@example.com, b@example.com", "cc": "c@example.com", "bcc": "d@example.com", "subject": "Hi",
                "body": "Hello", "body_html": "<b>Hello</b>"})
        self.assertEqual(response.status_code, 200)
        credentials.assert_called_once_with(self.db, self.owner.id, self.account.id)
        self.assertEqual(send.call_args.kwargs["bcc"], "d@example.com")
        self.assertEqual(send.call_args.kwargs["body_html"], "<b>Hello</b>")

    def test_foreign_selected_account_never_reaches_gmail_send(self):
        with patch.object(gmail_service, "send_email") as send:
            response = self.client.post("/api/v1/gmail/send", json={"account_id": self.foreign.id,
                "to": "a@example.com", "subject": "Private", "body": "Hello"})
        self.assertEqual(response.status_code, 409)
        send.assert_not_called()

    def test_provider_send_is_called_once_with_retries_disabled(self):
        with patch.object(gmail_service, "get_gmail_service", return_value=self.provider):
            gmail_service.send_email("a@example.com", "Hello", "Body", google_token="mock", cc="c@example.com", bcc="b@example.com")
        resource = self.provider.users.return_value.messages.return_value
        resource.send.assert_called_once()
        resource.send.return_value.execute.assert_called_once_with(num_retries=0)
