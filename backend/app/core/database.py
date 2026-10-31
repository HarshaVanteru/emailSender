from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import DATABASE_URL

engine = create_engine(DATABASE_URL, pool_pre_ping=True,
                       **({"pool_recycle": 1800, "pool_timeout": 15,
                           "connect_args": {"connect_timeout": 10, "read_timeout": 30, "write_timeout": 30}}
                          if DATABASE_URL.startswith('mysql') else {}))
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
