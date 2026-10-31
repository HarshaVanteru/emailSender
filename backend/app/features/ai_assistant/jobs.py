"""Versioned independent AI tasks; synchronization never waits for a model."""
from fastapi import HTTPException
from app.features.ai_assistant.context_schemas import ContextAiRequest
from app.features.ai_assistant.context_service import TASKS, load_context, generate, PROMPT_VERSION
from app.workers import operations



def version(db, user_id, account_id, thread_id, request):
    _, _, _, records = load_context(db, user_id, account_id, thread_id, request.message_id)
    from app.core.config import AI_MODEL
    return operations.fingerprint({"messages": records, "prompt": PROMPT_VERSION, "model": AI_MODEL})


def enqueue(db, user_id, account_id, thread_id, operation, request):
    if operation not in TASKS:
        raise HTTPException(422, "Unsupported AI operation.")
    if operation == "rewrite" and not request.text.strip():
        raise HTTPException(422, "Select text to rewrite first.")
    current = version(db, user_id, account_id, thread_id, request)
    data = {"thread_id": thread_id, "request": request.model_dump(), "version": current}
    key = operations.fingerprint({"operation": operation, "data": data})
    row = operations.submit(db, "ai", user_id, account_id, operation, data, key, thread_id=thread_id)
    if row.status == 'failed':
        from app.core.time import utcnow
        row.status, row.attempts, row.error_code, row.available_at = 'pending', 0, None, utcnow()
        db.commit()  # An explicit user request can retry exhausted AI work.
    return row


def execute_job(db, row, data, model=None):
    if row.operation == 'write':
        from app.features.google_login.user import User
        from app.features.ai_assistant.schemas import GenerateEmailRequest
        from app.features.ai_assistant.service import ai_service
        user = db.get(User, row.user_id)
        request = GenerateEmailRequest.model_validate(data['request'])
        return ai_service.generate_email(instruction=request.instruction, history=request.messages,
            name=user.name, signature=user.signature, preferences=user.preferences, bio=user.bio).model_dump()
    request = ContextAiRequest.model_validate(data["request"])
    if version(db, row.user_id, row.account_id, row.thread_id, request) != data["version"]:
        raise HTTPException(409, "Conversation changed. Request a fresh suggestion.")
    return generate(db, row.user_id, row.account_id, row.thread_id, row.operation, request, model=model)
