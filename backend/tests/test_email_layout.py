import base64
import json
import unittest
from email import policy
from email.parser import BytesParser
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.features.compose_email.email_layout import reflow_email_body, render_email_html
from app.integrations.gmail.client import GmailService


class EmailLayoutTests(unittest.TestCase):
    def test_paragraphs_reflow_without_losing_structural_breaks(self):
        fixtures = json.loads(
            (Path(__file__).parent / "fixtures/email_layout.json").read_text(encoding="utf-8")
        )
        for fixture in fixtures:
            with self.subTest(name=fixture["name"]):
                result = reflow_email_body(fixture["input"])
                self.assertEqual(result, fixture["expected"])
                self.assertEqual(reflow_email_body(result), result)

    def test_html_is_escaped_and_has_no_fixed_width(self):
        html = render_email_html("Hello <img src=x onerror=alert(1)> & team\nwrapped prose.")
        self.assertNotIn("<img", html)
        self.assertIn("&lt;img", html)
        self.assertIn("&amp;", html)
        self.assertIn("team wrapped prose.", html)
        self.assertIn("width:100%", html)
        self.assertNotIn("max-width", html)
        self.assertNotIn("<pre", html)

    def test_gmail_mime_contains_fluid_html_plain_text_and_attachment(self):
        service = GmailService()
        gmail = MagicMock()
        gmail.users.return_value.messages.return_value.send.return_value.execute.return_value = {
            "id": "test-only"
        }
        body = "Dear Alex,\n\nThis paragraph was wrapped\nto a narrow column.\n\nBest,\nSam"
        for attachment in (None, {
            "filename": "resume.pdf",
            "content_type": "application/pdf",
            "data": base64.b64encode(b"test attachment").decode(),
        }):
            with self.subTest(attachment=bool(attachment)):
                with patch.object(service, "get_gmail_service", return_value=gmail):
                    service.send_email("alex@example.com", "Update", body, attachment, "mock")
                raw = gmail.users.return_value.messages.return_value.send.call_args.kwargs["body"]["raw"]
                message = BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(raw))
                self.assertEqual(message["To"], "alex@example.com")
                self.assertEqual(message.get_body(preferencelist=("plain",)).get_content().strip(), reflow_email_body(body))
                html = message.get_body(preferencelist=("html",)).get_content()
                self.assertIn("This paragraph was wrapped to a narrow column.", html)
                self.assertIn("Best,<br>Sam", html)
                attachments = list(message.iter_attachments())
                self.assertEqual(len(attachments), int(bool(attachment)))
                if attachment:
                    self.assertEqual(attachments[0].get_payload(decode=True), b"test attachment")


if __name__ == "__main__":
    unittest.main()
