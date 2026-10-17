"""Authenticated, wrapped Pub/Sub push endpoint."""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from app.core.database import get_db
from app.features.mail_sync.push import accept_notification, parse_push, verify_push_token

router = APIRouter(tags=["Gmail push"])


@router.post("/webhooks/gmail/pubsub", status_code=204)
async def gmail_pubsub_push(request: Request, db=Depends(get_db)):
    await run_in_threadpool(verify_push_token, request.headers.get("authorization"))
    body = await request.body()
    if len(body) > 16384:
        raise HTTPException(413, "Pub/Sub push envelope is too large.")
    email, cursor = parse_push(body)
    try:
        await run_in_threadpool(accept_notification, db, email, cursor)
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(503, "Push could not be persisted; retry delivery.") from None
    return Response(status_code=204)
