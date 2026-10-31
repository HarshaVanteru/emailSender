from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from app.core.database import Base
from app.core.sql_types import ID_TYPE


class PushEvent(Base):
    __tablename__ = "gmail_push_events"
    id = Column(ID_TYPE, primary_key=True)
    account_id = Column(ID_TYPE, ForeignKey("connected_accounts.id"), nullable=True, index=True)
    pubsub_message_id = Column(String(255), nullable=False, unique=True)
    history_id = Column(String(255), nullable=False)
    received_at = Column(DateTime, nullable=False)
    processed_at = Column(DateTime)
    status = Column(String(24), nullable=False)
