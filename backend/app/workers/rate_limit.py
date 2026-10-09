import time

from redis import Redis

from app.core import config

# One atomic fixed-window counter per account, shared by all worker processes.
# TTL is relative to Redis, so worker wall-clock differences cannot evade it.
LIMIT_SCRIPT = """
local used = tonumber(redis.call('GET', KEYS[1]) or '0')
if used >= tonumber(ARGV[1]) then
    return math.max(redis.call('PTTL', KEYS[1]), 1)
end
local count = redis.call('INCR', KEYS[1])
if count == 1 then redis.call('PEXPIRE', KEYS[1], 1000) end
return 0
"""


class GmailRateLimiter:
    def __init__(self, client=None, sleep=time.sleep):
        self.client = client if client is not None else Redis.from_url(
            config.REDIS_URL, socket_connect_timeout=3, socket_timeout=3)
        self.script = self.client.register_script(LIMIT_SCRIPT)
        self.sleep = sleep

    def wait(self, account_id: int):
        while True:
            delay = int(self.script(keys=[f"email-studio:gmail-rate:{account_id}"],
                                    args=[config.SYNC_REQUESTS_PER_SECOND]))
            if delay <= 0:
                return
            self.sleep(min(delay / 1000, 1))
