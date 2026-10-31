from fastapi import HTTPException
from app.features.mailbox.models import EmailLabel, EmailMessage, AuditLog
from app.features.mailbox.actions import check_modify_access, apply_labels
from app.features.mailbox.reader import serialize_messages, list_labels
from app.features.mail_sync.service import owned_account, refresh_labels, utcnow
from app.features.google_login.accounts import credentials_for_account
from app.integrations.gmail.client import gmail_service
from app.integrations.gmail.adapter import GmailAdapter
from app.workers.rate_limit import GmailRateLimiter


def mutate(db, user_id, account_id, operation, *, label_id=None, name=None, message_id=None,
           add=None, remove=None, service=None, limiter=None):
    account = owned_account(db, user_id, account_id)
    check_modify_access(account)
    if service is None:
        credentials = credentials_for_account(db, user_id, account_id)
        service = gmail_service.get_gmail_service(credentials.to_json())
    adapter = GmailAdapter(service)
    try:
        account = owned_account(db, user_id, account_id, lock=True)
        check_modify_access(account)
        if label_id:
            label = db.query(EmailLabel).filter_by(account_id=account_id, gmail_label_id=label_id).first()
            if not label or label.type != 'user':
                raise HTTPException(404, 'User-defined Gmail label not found.')
        gate = limiter or GmailRateLimiter()
        if operation == 'assign':
            message = db.query(EmailMessage).filter_by(id=message_id, account_id=account_id).first()
            if not message:
                raise HTTPException(404, 'Message not found in this account.')
            ids = set((add or []) + (remove or []))
            found = {row.gmail_label_id for row in db.query(EmailLabel).filter(
                EmailLabel.account_id == account_id, EmailLabel.gmail_label_id.in_(ids), EmailLabel.type == 'user')}
            if found != ids:
                raise HTTPException(422, 'Choose user-defined labels from this account.')
            gate.wait(account_id)
            result = adapter.modify_message(message.gmail_message_id, add or [], remove or []).execute(num_retries=0)
            apply_labels(db, account_id, message, result)
            if result.get('historyId'):
                message.gmail_history_id = str(result['historyId'])
        else:
            request = adapter.create_label(name) if operation == 'create' else adapter.rename_label(label_id, name) if operation == 'rename' else adapter.delete_label(label_id)
            gate.wait(account_id)
            request.execute(num_retries=0)
            gate.wait(account_id)
            refresh_labels(db, service, account_id)
        account.next_sync_at = utcnow()
        db.add(AuditLog(user_id=user_id, account_id=account_id, action='label.' + operation,
            resource_type='message' if operation == 'assign' else 'label',
            resource_id=str(message_id or label_id or 'new'), outcome='success'))
        db.commit()
        from app.features.mail_sync.events import publish_update
        publish_update(account_id)
        return serialize_messages(db, account_id, [message], detail=True)[0] if operation == 'assign' else list_labels(db, user_id, account_id)
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(502, 'Gmail could not confirm the label operation. Refresh before trying again.') from None
