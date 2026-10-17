"""Every cache lookup includes the authenticated owner, even with internal IDs."""
from sqlalchemy.orm import Session

from app.features.google_login.models import ConnectedAccount
from app.features.mailbox.models import EmailAttachment, EmailMessage, EmailThread


class MailboxRepository:
    def get_message(self, db: Session, user_id: int, account_id: int, message_id: int):
        return db.query(EmailMessage).join(
            ConnectedAccount, ConnectedAccount.id == EmailMessage.account_id,
        ).filter(ConnectedAccount.user_id == user_id, EmailMessage.account_id == account_id,
                 EmailMessage.id == message_id).first()

    def get_thread(self, db: Session, user_id: int, account_id: int, thread_id: int):
        return db.query(EmailThread).join(
            ConnectedAccount, ConnectedAccount.id == EmailThread.account_id,
        ).filter(ConnectedAccount.user_id == user_id, EmailThread.account_id == account_id,
                 EmailThread.id == thread_id).first()

    def get_attachment(self, db: Session, user_id: int, account_id: int, attachment_id: int):
        return db.query(EmailAttachment).join(
            ConnectedAccount, ConnectedAccount.id == EmailAttachment.account_id,
        ).filter(ConnectedAccount.user_id == user_id, EmailAttachment.account_id == account_id,
                 EmailAttachment.id == attachment_id).first()


mailbox_repository = MailboxRepository()
