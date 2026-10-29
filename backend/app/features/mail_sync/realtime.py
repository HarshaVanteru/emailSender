"""Account-scoped WebSocket notifications from committed sync state.

Workers publish after commit. Reconnect snapshots and a slow safety heartbeat
recover missed hints without holding a database session while waiting.
"""
import asyncio
import json

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from app.core import config
from app.core.database import SessionLocal
from app.core.security import get_current_user
from app.features.mail_sync.service import check_read_access, owned_account
from app.features.mailbox.models import SyncJob, MessageTriage

from app.features.mail_sync.events import channel

router = APIRouter(tags=["sync"])
HEARTBEAT_SECONDS = 60


def authorize_connection(token, account_id):
    with SessionLocal() as db:
        user = get_current_user(token=token, db=db)
        check_read_access(owned_account(db, user.id, account_id))


def sync_snapshot(token, account_id):
    with SessionLocal() as db:
        user = get_current_user(token=token, db=db)
        account = owned_account(db, user.id, account_id)
        check_read_access(account)
        job = db.query(SyncJob.id).filter_by(
            account_id=account_id, status="succeeded"
        ).order_by(SyncJob.id.desc()).first()
        revision = job[0] if job else None
        failed = db.query(SyncJob.id).filter_by(
            account_id=account_id, status="failed"
        ).order_by(SyncJob.id.desc()).first()
        if failed and (revision is None or failed[0] > revision):
            revision = f"{revision}:failed:{failed[0]}"
        states = dict(db.query(MessageTriage.state, func.count()).filter_by(account_id=account_id).group_by(MessageTriage.state).all())
        if states:
            return f"{revision}:{sum(states.values())}:{states.get('succeeded', 0)}:{states.get('failed', 0)}"
        return revision


@router.websocket("/accounts/{account_id}/events")
async def mailbox_events(websocket: WebSocket, account_id: int):
    # WebSocket CORS is independent of HTTP CORS. Bearer credentials are sent
    # in the first frame, never in a URL, browser history, or access logs.
    origin = websocket.headers.get("origin")
    if origin and origin.rstrip("/") != config.FRONTEND_URL.rstrip("/"):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=5)
        if len(raw) > 8192:
            await websocket.close(code=1008)
            return
        auth = json.loads(raw)
        token = auth.get("token") if isinstance(auth, dict) else None
        if not isinstance(token, str) or not token:
            await websocket.close(code=1008)
            return
        await run_in_threadpool(authorize_connection, token, account_id)
        # Subscribe before the snapshot so a concurrent worker commit cannot
        # fall between reading the database and registering for notifications.
        async with Redis.from_url(config.REDIS_URL, socket_connect_timeout=3) as client:
            async with client.pubsub() as subscription:
                await subscription.subscribe(channel(account_id))
                ack = await subscription.get_message(timeout=5)
                if not ack or ack["type"] != "subscribe":
                    raise RedisError("Subscription unavailable")
                revision = await run_in_threadpool(sync_snapshot, token, account_id)
                await websocket.send_json({"type": "ready", "account_id": account_id, "revision": revision})
                notifications = subscription.listen().__aiter__()
                incoming = asyncio.create_task(websocket.receive_text())
                event = asyncio.create_task(anext(notifications))
                try:
                    while True:
                        done, _ = await asyncio.wait(
                            {incoming, event}, timeout=HEARTBEAT_SECONDS,
                            return_when=asyncio.FIRST_COMPLETED)
                        if incoming in done:
                            incoming.result()  # Propagate disconnects immediately.
                            await websocket.close(code=1008)
                            return
                        notified = event in done
                        if notified:
                            event.result()
                            event = asyncio.create_task(anext(notifications))
                        # Revalidate access on events and the slow heartbeat.
                        # The heartbeat also repairs a rare failed publication.
                        current = await run_in_threadpool(sync_snapshot, token, account_id)
                        await websocket.send_json({
                            "type": "mailbox.updated" if notified or current != revision else "heartbeat",
                            "account_id": account_id, "revision": current,
                        })
                        revision = current
                finally:
                    incoming.cancel()
                    event.cancel()
                    await asyncio.gather(incoming, event, return_exceptions=True)
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    except (HTTPException, ValueError, asyncio.TimeoutError):
        await websocket.close(code=1008)
    except (SQLAlchemyError, RedisError):
        await websocket.close(code=1013)
