"""Gmail labels are the source of truth for category and AI eligibility."""
from sqlalchemy import and_, select

from app.features.mailbox.models import EmailLabel, EmailMessage, MessageLabel

PRIMARY = "CATEGORY_PERSONAL"
CATEGORIES = (PRIMARY, "CATEGORY_PROMOTIONS", "CATEGORY_SOCIAL", "CATEGORY_UPDATES", "CATEGORY_FORUMS")
EXCLUDED_AI_LABELS = {"SPAM", "TRASH", "SENT", "DRAFT"}


def has_label(label):
    return EmailMessage.id.in_(select(MessageLabel.message_id).join(
        EmailLabel, and_(EmailLabel.id == MessageLabel.label_id, EmailLabel.account_id == MessageLabel.account_id)
    ).where(MessageLabel.account_id == EmailMessage.account_id, EmailLabel.gmail_label_id == label))


def primary_message():
    other_category = EmailMessage.id.in_(select(MessageLabel.message_id).join(
        EmailLabel, and_(EmailLabel.id == MessageLabel.label_id, EmailLabel.account_id == MessageLabel.account_id)
    ).where(MessageLabel.account_id == EmailMessage.account_id,
            EmailLabel.gmail_label_id.startswith("CATEGORY_", autoescape=True), EmailLabel.gmail_label_id != PRIMARY))
    return and_(has_label(PRIMARY), ~other_category, *(~has_label(label) for label in EXCLUDED_AI_LABELS))
