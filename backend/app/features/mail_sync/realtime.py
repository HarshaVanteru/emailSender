"""Account-scoped WebSocket notifications from committed sync state.

Short database snapshots work across API/worker processes without lossy pub/sub.
No database session is held while waiting on the network.
"""
import asyncio
import json

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from app.core import config
from app.core.database import SessionLocal
from app.core.security import get_current_user
from app.features.mail_sync.service import check_read_access, owned_account
from app.features.mailbox.models import SyncJob, MessageTriage

router = APIRouter(tags=["sync"])
POLL_SECONDS = 3


def sync_snapshot(token, account_id):
    with SessionLocal() as db:
        user = get_current_user(token=token, db=db)
        account = owned_account(db, user.id, account_id)
        check_read_access(account)
        job = db.query(SyncJob.id).filter_by(
            account_id=account_id, status="succeeded"
        ).order_by(SyncJob.id.desc()).first()
        revision = job[0] if job else None
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
        revision = await run_in_threadpool(sync_snapshot, token, account_id)
        await websocket.send_json({"type": "ready", "account_id": account_id, "revision": revision})
        while True:
            # Also detects disconnects promptly; the client sends no further data.
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=POLL_SECONDS)
                await websocket.close(code=1008)
                return
            except asyncio.TimeoutError:
                pass
            # Recheck token expiry, account ownership and access on every snapshot.
            current = await run_in_threadpool(sync_snapshot, token, account_id)
            await websocket.send_json({
                "type": "mailbox.updated" if current != revision else "heartbeat",
                "account_id": account_id, "revision": current,
            })
            revision = current
    except WebSocketDisconnect:
        pass
    except (HTTPException, ValueError, asyncio.TimeoutError):
        await websocket.close(code=1008)
    except SQLAlchemyError:
        await websocket.close(code=1013)
