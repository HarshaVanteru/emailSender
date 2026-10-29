"""Resolve legacy host-gateway database URLs without rewriting credentials."""
from sqlalchemy.engine import make_url


def resolve_database_url(value, host_override=None):
    if not host_override:
        return value
    url = make_url(value)
    # A cloud database or already explicit container address must remain intact.
    if url.get_backend_name() != "mysql" or url.host not in {"host.docker.internal", "localhost", "127.0.0.1", "::1", "mysql"}:
        return value
    return url.set(host=host_override).render_as_string(hide_password=False)
