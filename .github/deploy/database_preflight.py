"""Read-only connectivity check before application writers are stopped."""
import time

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool


def failure_reason(error):
    """Use only numeric driver codes; provider exception text can contain secrets."""
    original = getattr(error, "orig", error)
    args = getattr(original, "args", ())
    code = args[0] if args and type(args[0]) is int else None
    reasons = {
        1044: "Database permission denied: check this user's grants for the configured database.",
        1045: "Authentication denied: check the production username, password, and MySQL user host grants.",
        1049: "Unknown database: check the production database name and whether it exists.",
        2002: "MySQL connection unavailable: check the endpoint and server listener.",
        2003: "MySQL connection failed: check the Docker network, internal port, listener, and firewall.",
        2005: "Database hostname could not be resolved: check the hostname and shared Docker network.",
        2026: "TLS connection failed: check database TLS settings and certificates.",
    }
    return reasons.get(code, "Database configuration or driver failure; check URL encoding, installed driver, and server availability.") + (f" (MySQL code {code})" if code is not None else "")


def main():
    try:
        from app.core.config import DATABASE_URL
        url = make_url(DATABASE_URL)
        # Never print the URL, username, password, or query options.
        print("Database target: " + repr({"driver": url.drivername, "host": url.host,
              "port": url.port or (3306 if url.get_backend_name() == "mysql" else None),
              "database": url.database}), flush=True)
        options = {"connect_timeout": 5} if url.get_backend_name() == "mysql" else {}
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
    except Exception as error:
        # Connection exceptions can include credentials. Never echo their text.
        raise SystemExit("Database connectivity check failed; no application services were stopped. " + failure_reason(error)) from None


if __name__ == "__main__":
    main()
