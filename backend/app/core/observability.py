"""Sanitized request telemetry and optional distributed sensitive-route limits."""
import hashlib
import json
import logging
import secrets
import time
from redis import Redis
from redis.exceptions import RedisError
from starlette.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from app.core import config
from jose import jwt, JWTError

logger = logging.getLogger('email_sender.requests')
logger.setLevel(logging.INFO)
if not logger.handlers:
    logger.addHandler(logging.StreamHandler())
logger.propagate = False
RATE_SCRIPT = """
local used = redis.call('INCR', KEYS[1])
if used == 1 then redis.call('EXPIRE', KEYS[1], 60) end
return {used, redis.call('TTL', KEYS[1])}
"""


def check_limit(identity, client=None):
    client = client or Redis.from_url(config.REDIS_URL, socket_connect_timeout=2, socket_timeout=2)
    digest = hashlib.sha256(identity.encode()).hexdigest()
    used, ttl = client.eval(RATE_SCRIPT, 1, 'email-studio:api-rate:' + digest)
    return int(used) <= config.API_REQUESTS_PER_MINUTE, max(1, int(ttl))


def rate_identity(authorization, address):
    if authorization and authorization.startswith('Bearer ') and config.SECRET_KEY:
        try:
            claims = jwt.decode(authorization[7:], config.SECRET_KEY, algorithms=[config.ALGORITHM])
            if isinstance(claims.get('sub'), str):
                return 'user:' + claims['sub']
        except JWTError:
            pass
    return 'address:' + address


def log_operation(operation, user_id, account_id, job_id, outcome, started, error_code=None):
    from celery import current_task
    task_id = getattr(getattr(current_task, 'request', None), 'id', None)
    logger.info(json.dumps({'operation': operation, 'user_id': user_id, 'account_id': account_id,
        'job_id': job_id, 'task_id': task_id, 'outcome': outcome, 'error_code': error_code,
        'duration_ms': round((time.monotonic() - started) * 1000, 1)}))


async def request_telemetry(request, call_next):
    started = time.monotonic()
    request_id = secrets.token_hex(16)
    request.state.request_id = request_id
    sensitive = (request.method in ('POST', 'PUT', 'PATCH', 'DELETE')
                 or request.url.path.endswith(('/auth/google', '/gmail/auth'))) and not request.url.path.startswith('/api/v1/webhooks/')
    if config.RATE_LIMIT_ENABLED and sensitive:
        # No raw token, IP or email is retained in Redis keys or request logs.
        identity = rate_identity(request.headers.get('authorization'), request.client.host if request.client else 'unknown')
        try:
            allowed, ttl = await run_in_threadpool(check_limit, identity)
            if not allowed:
                return JSONResponse({'detail': 'Too many requests. Try again shortly.'}, 429, headers={'Retry-After': str(ttl), 'X-Request-ID': request_id})
        except RedisError:
            return JSONResponse({'detail': 'Request limiting is temporarily unavailable.'}, 503)
    response = await call_next(request)
    response.headers['X-Request-ID'] = request_id
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['Cache-Control'] = 'no-store' if request.url.path.startswith('/api/') else response.headers.get('Cache-Control', 'no-cache')
    route = request.scope.get('route')
    logger.info(json.dumps({'request_id': request_id, 'operation': getattr(route, 'path', 'unmatched'),
        'user_id': getattr(request.state, 'user_id', None), 'account_id': request.path_params.get('account_id'),
        'method': request.method, 'status': response.status_code,
        'duration_ms': round((time.monotonic() - started) * 1000, 1)}))
    return response
