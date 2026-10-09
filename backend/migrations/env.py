from alembic import context
from sqlalchemy import create_engine, pool

from app.core.config import DATABASE_URL
from app.core.database import Base
import app.models.user
import app.models.connection
import app.models.mailbox

config = context.config


def run_migrations(connection):
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    raise RuntimeError("Credential migrations require an online connection; SQL export is not supported.")
elif config.attributes.get("connection") is not None:
    run_migrations(config.attributes["connection"])
else:
    engine = create_engine(DATABASE_URL, poolclass=pool.NullPool)
    with engine.connect() as connection:
        run_migrations(connection)
