"""Synthetic local read-model smoke benchmark; never uses the configured database."""
import argparse
import json
import statistics
import time
from sqlalchemy import create_engine, insert
from sqlalchemy.orm import Session
from app.core.database import Base
from app.features.google_login.user import User
from app.features.google_login.models import ConnectedAccount
from app.features.mailbox.models import EmailThread, EmailMessage
from app.features.mailbox.reader import list_messages


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--messages', type=int, default=5000)
    parser.add_argument('--iterations', type=int, default=100)
    args = parser.parse_args()
    if not 100 <= args.messages <= 100000 or not 10 <= args.iterations <= 1000:
        parser.error('Use 100-100000 messages and 10-1000 iterations.')
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(email='benchmark@example.invalid')
        db.add(user); db.flush()
        account = ConnectedAccount(user_id=user.id, gmail_email=user.email)
        db.add(account); db.flush()
        thread = EmailThread(account_id=account.id, gmail_thread_id='synthetic-thread')
        db.add(thread); db.flush()
        db.execute(insert(EmailMessage), [{'account_id': account.id, 'thread_id': thread.id,
            'gmail_message_id': f'synthetic-{number}', 'internal_date': number,
            'subject': f'Fixture {number}', 'body_text': 'Synthetic content. ' * 100,
            'headers': [], 'to_addresses': [], 'cc_addresses': [], 'bcc_addresses': []}
            for number in range(args.messages)])
        db.commit()
        samples = []
        cursor = None
        for _ in range(args.iterations):
            started = time.perf_counter()
            page = list_messages(db, user.id, account.id, page_size=30, page_token=cursor)
            samples.append((time.perf_counter() - started) * 1000)
            cursor = page['next_page_token']
        ordered = sorted(samples)
        print(json.dumps({'database': 'isolated SQLite', 'messages': args.messages,
            'requests': args.iterations, 'p50_ms': round(statistics.median(samples), 2),
            'p95_ms': round(ordered[int(len(ordered) * .95) - 1], 2),
            'note': 'Read-model smoke benchmark; not production Gmail/AI capacity.'}))
    engine.dispose()


if __name__ == '__main__':
    main()
