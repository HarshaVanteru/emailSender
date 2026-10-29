"""Account-scoped invalidation hints; committed database state is authoritative."""
import logging

from redis import Redis
from redis.exceptions import RedisError

from app.core import config


def channel(account_id):
    return f"email-studio:mailbox-events:{account_id}"


def publish_update(account_id):
    # Called only after commit. Publication failure must never undo successful work.
    try:
        with Redis.from_url(config.REDIS_URL, socket_connect_timeout=1, socket_timeout=1) as client:
            client.publish(channel(account_id), "updated")
    except RedisError:
        logging.getLogger(__name__).warning("Mailbox notification deferred for account %s", account_id)
