"""Provider request construction, separate from domain transactions and retries.

The adapter accepts Google's resource client or the deterministic resource fake.
Requests are returned unexecuted so workers own throttling and transaction policy.
"""
from typing import Any, Protocol


class ProviderRequest(Protocol):
    def execute(self, num_retries: int = 0) -> dict[str, Any]: ...


class MailProvider(Protocol):
    def profile(self) -> ProviderRequest: ...
    def list_messages(self, **options: Any) -> ProviderRequest: ...
    def message(self, message_id: str) -> ProviderRequest: ...
    def labels(self) -> ProviderRequest: ...
    def history(self, **options: Any) -> ProviderRequest: ...
    def attachment(self, message_id: str, attachment_id: str) -> ProviderRequest: ...


class GmailAdapter:
    def __init__(self, resource):
        self.resource = resource

    def profile(self):
        return self.resource.users().getProfile(userId="me")

    def list_messages(self, **options):
        return self.resource.users().messages().list(userId="me", **options)

    def message(self, message_id):
        return self.resource.users().messages().get(userId="me", id=message_id, format="full")

    def labels(self):
        return self.resource.users().labels().list(userId="me")

    def history(self, **options):
        return self.resource.users().history().list(userId="me", **options)

    def attachment(self, message_id, attachment_id):
        return self.resource.users().messages().attachments().get(userId="me", messageId=message_id, id=attachment_id)

    def send(self, payload):
        return self.resource.users().messages().send(userId="me", body=payload)

    def draft(self, draft_id):
        return self.resource.users().drafts().get(userId="me", id=draft_id, format="raw")

    def send_draft(self, draft_id):
        return self.resource.users().drafts().send(userId="me", body={"id": draft_id})

    def modify_message(self, message_id, add, remove):
        return self.resource.users().messages().modify(userId="me", id=message_id,
            body={"addLabelIds": add, "removeLabelIds": remove})

    def create_label(self, name):
        return self.resource.users().labels().create(userId="me", body={"name": name})

    def rename_label(self, label_id, name):
        return self.resource.users().labels().patch(userId="me", id=label_id, body={"name": name})

    def delete_label(self, label_id):
        return self.resource.users().labels().delete(userId="me", id=label_id)

    def trash_message(self, message_id):
        return self.resource.users().messages().trash(userId="me", id=message_id)

    def watch(self, topic):
        return self.resource.users().watch(userId="me", body={"topicName": topic})

    def list_drafts(self, page_token=None):
        options = {"userId": "me", "maxResults": 20}
        if page_token:
            options['pageToken'] = page_token
        return self.resource.users().drafts().list(**options)

    def draft_metadata(self, draft_id):
        return self.resource.users().drafts().get(userId="me", id=draft_id, format="metadata")

    def save_draft(self, raw, draft_id=None):
        if draft_id:
            return self.resource.users().drafts().update(userId="me", id=draft_id, body={"id": draft_id, "message": {"raw": raw}})
        return self.resource.users().drafts().create(userId="me", body={"message": {"raw": raw}})

    def delete_draft(self, draft_id):
        return self.resource.users().drafts().delete(userId="me", id=draft_id)
