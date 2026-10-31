from sqlalchemy import Column, Integer, String, Text

from app.core.database import Base
from app.core.sql_types import ID_TYPE


class User(Base):
    __tablename__ = "users"
    id = Column(ID_TYPE, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=True)
    google_token = Column(String(2048), nullable=True)
    signature = Column(String(1024), nullable=True)
    preferences = Column(String(2048), nullable=True)
    bio = Column(Text, nullable=True)
