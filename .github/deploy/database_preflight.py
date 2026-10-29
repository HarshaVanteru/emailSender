"""Read-only connectivity check before application writers are stopped."""
import time

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool


def main():
    try:
        from app.core.config import DATABASE_URL
        options = {"connect_timeout": 5} if make_url(DATABASE_URL).get_backend_name() == "mysql" else {}
        engine = create_engine(DATABASE_URL, poolclass=NullPool, connect_args=options)
        try:
            for attempt in range(3):
                try:
                    with engine.connect() as connection:
                        connection.execute(text("SELECT 1"))
                    print("Database connectivity verified before stopping application services.")
                    return
                except Exception:
                    if attempt == 2:
                        raise
                    time.sleep(1)
        finally:
            engine.dispose()
    except Exception:
        # Connection exceptions can include credentials. Never echo their text.
        raise SystemExit("Database connectivity check failed; no application services were stopped. Check the database host, port, network, and credentials.") from None


if __name__ == "__main__":
    main()
