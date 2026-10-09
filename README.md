# emailSender

React/Vite email workspace with a FastAPI backend and Gmail integration.

The canonical implementation plan and ordered backlog are maintained in
[Linear](https://linear.app/harshagenai/document/master-implementation-plan-ai-powered-gmail-client-3c249799afc8).

## API compatibility

The frontend uses `/api/v1`. Existing `/api/gmail/*`, `/api/ai/*` and
`/api/health` URLs remain available for older builds and registered OAuth callbacks.
OpenAPI documents the versioned routes at `/docs`.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET | `/api/v1/health` | Health check |
| GET | `/api/v1/auth/google` | Connect Gmail |
| GET | `/api/v1/auth/google/callback` | OAuth callback |
| GET | `/api/v1/accounts` | List your Gmail connections without credentials |
| DELETE | `/api/v1/accounts/{account_id}` | Revoke Google access and disconnect |
| POST | `/api/v1/accounts/{account_id}/sync` | Run manual initial/incremental sync |
| GET | `/api/v1/accounts/{account_id}/sync-jobs` | List the latest 20 sync jobs |
| GET | `/api/v1/accounts/{account_id}/sync-jobs/{job_id}` | Read an owned sync job's status |
| GET | `/api/v1/gmail/profile` | Current account and writing preferences |
| PUT | `/api/v1/gmail/profile` | Update writing preferences |
| POST | `/api/v1/gmail/send` | Explicitly send a reviewed email |
| POST | `/api/v1/ai/generate-email` | Generate a draft without sending |

The versioned `/api/v1/gmail/auth` and `/api/v1/gmail/auth/google/callback`
aliases also use the same OAuth handlers.

Set `VITE_API_BASE_URL` to your backend origin, e.g. `http://localhost:8000`,
or leave it empty for same-origin hosting. In Vite development, `/api` is proxied
to the backend. Trailing `/api` or `/api/v1` in this setting is normalized to avoid
duplicate prefixes. Rebuild the frontend after changing environment settings.

Keep the existing `GOOGLE_REDIRECT_URI` registered with Google Cloud while
migrating. To use the new callback, register its exact URL in Google Cloud before
changing the backend setting; both callback paths remain supported. `FRONTEND_URL`
must point to the frontend origin. Existing OAuth scopes are unchanged by API versioning.

## Secure connections and database setup

The server now requires `TOKEN_ENCRYPTION_KEY` (Fernet) and a strong `SECRET_KEY`
of at least 32 characters. Keep independent values in `backend/.env` or your
server secret store, following [backend/.env.example](backend/.env.example).
Generate them locally with the backend Python interpreter:

```powershell
myenv\Scripts\python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
myenv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
```

The first output is the encryption key; the second is the JWT signing key.
Back up the encryption key securely: losing it makes saved credentials unreadable.
All backend instances must share these secrets. Never use `VITE_` variables for them.

Schema changes are explicit through Alembic; starting the API no longer creates
or changes tables. Install backend requirements first. From `backend`, for a
**new empty database**, run `myenv\Scripts\python.exe -m alembic upgrade head`.
For an **existing database matching the original users schema**, back up the
database and configure the encryption key, then run:

```powershell
myenv\Scripts\python.exe -m alembic stamp 0001
myenv\Scripts\python.exe -m alembic upgrade head
```

Revision `0002` moves legacy `users.google_token` values into encrypted connection
records and clears the plaintext column. Check `alembic current` and restart the
backend after setup. These commands affect the configured database; migration
tests use isolated SQLite databases. MySQL DDL is not transactional: take a
backup and stop API/worker writes before applying a migration.

An explicit `alembic downgrade 0001` restores legacy credential storage and
removes connection/state tables. This rollback requires the same encryption key
and restores **plaintext tokens**, so use it only for a controlled rollback to
the old backend. It refuses credentials larger than the old 2048-character column.

OAuth state expires after ten minutes, is single-use across workers, and is bound
to an HttpOnly SameSite browser cookie. PKCE uses S256. Successful callbacks hand
the app session to the frontend via a URL fragment, which the frontend removes.
Use HTTPS outside local development. Existing send-only grants remain supported;
Gmail profile identity/history lookup runs only with a compatible granted scope.
The profile history snapshot is separate from a future synchronization cursor.
See [Google's Gmail profile scope requirements](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users/getProfile).

Settings now offers a reviewed disconnect action. Google access is revoked before
stored credentials are removed. A revocation failure retains the connection for
retry. Revoked/expired access disables sending and offers reconnect. Normal
authorization does not force consent; reconnect can explicitly request renewed
offline consent when a refresh token is missing. Refreshes are serialized per
account and persisted encrypted. Send failures are never automatically retried.
This follows [Google's OAuth lifecycle guidance](https://developers.google.com/identity/protocols/oauth2/web-server).

## Mailbox cache schema

Revision `0003` adds the local cache foundation. Gmail remains the source of truth;
this migration creates no remote mail or synchronization jobs. For a database
already at `0002`, back it up and run `alembic upgrade head` using the backend
interpreter. Do not stamp an already versioned database back to the legacy revision.
Use MySQL 8.0.16+ with InnoDB for enforced foreign keys and check constraints.

| Table | Cached data |
| --- | --- |
| `email_threads` | Account/Gmail thread identity, subject, snippet, last message time |
| `email_messages` | Gmail message identity, recipients, repeated RFC headers, text/HTML, timestamps |
| `email_labels` / `message_labels` | Account labels and message membership |
| `email_attachments` | MIME part identity, filename, type and size; no attachment binaries |
| `sync_jobs` | Sync kind, status, attempts, timestamps and sanitized error code |
| `audit_logs` | User/account ownership, action, resource and outcome; no tokens or email bodies |

Composite foreign keys enforce that a message's thread, label links and attachment
metadata belong to the same account. Account/Gmail-ID unique constraints prevent
duplicate cache records; the same Gmail ID may exist in another account. Repository
lookups additionally check the authenticated owner's user ID. MySQL cache tables
use binary UTF-8 collation to preserve provider ID case. Large email bodies use
LONGTEXT on MySQL; recipients and headers use JSON. HTML remains untrusted content
and must be sanitized before any future UI renders it.
See [SQLAlchemy's composite constraint guidance](https://docs.sqlalchemy.org/en/21/core/constraints.html).

`connected_accounts.history_id` is the last **committed sync cursor**, initially
null. `profile_history_id` is only the OAuth profile snapshot. Dates are UTC;
message `internal_date` and thread `last_message_at` retain Gmail epoch milliseconds.
Watch expiration and last successful sync time have separate nullable columns.

`alembic downgrade 0002` removes mailbox cache, jobs, audit records and committed
sync cursor fields while retaining encrypted connections, OAuth attempts and user
preferences. Back up operational records before rollback; re-upgrade creates an
empty cache for later reconciliation. It does not call Gmail or delete remote mail.
The migration suite exercises fresh and legacy upgrades, rollback/re-upgrade,
model/schema parity, foreign-key isolation and owned lookups using SQLite with
foreign keys enabled. MySQL DDL generation is also checked; execution against a
disposable MySQL server remains required before a production rollout.

## Gmail synchronization

Apply Alembic migrations through `0005` before using the updated backend. Revision `0004` persists the
exact OAuth scopes requested across redirects; existing pending send-only attempts
remain compatible. Default connection scopes stay send-only. Explicitly open
`/api/v1/auth/google?mailbox_access=true` to grant `gmail.readonly` for mailbox
sync. Google Cloud consent configuration must allow this scope; existing users
need this additional permission only when enabling mailbox features. Use
`&renew_consent=true` only if renewed offline consent is needed.
The callback records Google's actual granted scopes, including previously
approved permissions or partially declined consent; sync checks the actual grant.

With the app bearer token, `POST /api/v1/accounts/{account_id}/sync` queues a job
and returns `202 Accepted`. The worker imports up to 500 messages from the last
30 days, with pagination and spam/trash included. It
captures the profile cursor before scanning so changes during import replay on
the next sync. Later calls consume every history page and refresh the current
Gmail state for each changed ID, including message additions, label changes and
permanent deletions from the local cache. Replayed changes preserve local message
and attachment IDs. Text/HTML MIME parts and repeated RFC headers are normalized;
files are metadata-only. External text-body parts may be fetched from Gmail, but
remote images/links in HTML are never requested by the sync service.

Expired history triggers reconciliation: import recent messages and revalidate
every previously cached ID, even if it was archived or aged outside the initial
window. This retains valid older cached messages and removes confirmed 404s.
An explicit JSON body `{"reconcile": true}` also requests reconciliation.
Cache changes, thread metadata and the cursor commit in one transaction. Failures
roll them back, then record a retry or terminal failure with a sanitized error
code. A MySQL account row lock serializes writers; lock contention can return 409.
Job endpoints enforce ownership and never return Google credentials or message
contents. This follows [Google's sync guidance](https://developers.google.com/workspace/gmail/api/guides/sync)
and [history pagination/recovery rules](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.history/list).

Inspect `GET /api/v1/accounts/{account_id}/sync-jobs/{job_id}` or the latest 20
jobs at `GET /api/v1/accounts/{account_id}/sync-jobs`. Status is `queued`,
`running`, `succeeded` or `failed`; `available_at` is the earliest next attempt
time in UTC. Repeated submissions reuse the active job without resetting backoff.
A queued job can be upgraded to reconciliation; upgrading a running job returns
409 with its ID. If Redis publication fails, the API returns 503 with
`detail.accepted=true` and `detail.job_id`: the job is saved and maintenance will
redeliver it. A 202 means accepted, not completed; inspect status before retrying.

## Redis workers and scheduled sync

Revision `0005` adds a durable database outbox, one active job per account,
attempt leases and scheduling fields. Stop old API/worker processes before
migrating; legacy unfinished jobs become failed with `migration_interrupted`.
Downgrading to `0004` also marks unfinished jobs failed; stop all workers and the
scheduler first. Cache data and encrypted connections are retained.

Celery transports job IDs through Redis; credentials and message bodies are not
task arguments. Publication can repeat safely. A worker commits cache changes,
the Gmail cursor and job success together. Expired leases are recovered after a
worker crash; attempt tokens and account locks prevent an older worker from
overwriting newer work. Database rows remain authoritative if Redis loses a task.

Transport failures, rate limits and provider 5xx responses retry the same job
with exponential jittered backoff (initially 7.5–15 seconds, capped at 300
seconds). Permission/payload errors and exhausted attempts fail visibly and pause
that account's automatic schedule. Resolve the cause and submit a manual sync to
resume. Workers only read Gmail; **sending is never automatically retried**.

The scheduler scans every 30 seconds. Connected accounts with granted read access
receive an initial import, then incremental sync every five minutes and daily
reconciliation by default. Send-only, disconnected, reauthorization-required and
paused accounts are excluded. Redis enforces a shared per-account request budget.
If the limiter is unavailable, workers retry without making unthrottled requests.

| Setting | Default |
| --- | --- |
| `REDIS_URL` | `redis://localhost:6379/0` |
| `SYNC_MAX_ATTEMPTS` | `4` |
| `SYNC_INTERVAL_SECONDS` | `300` |
| `SYNC_RECONCILE_SECONDS` | `86400` |
| `SYNC_TASK_TIME_LIMIT` | `1800` seconds; lease adds 60 seconds |
| `SYNC_REQUESTS_PER_SECOND` | `10` per account, fixed one-second windows |

The root `compose.yaml` runs Redis with AOF persistence, API, two sync worker
processes, a separate maintenance worker, and one Celery beat scheduler. MySQL
stays external and uses `DATABASE_URL` from `backend/.env`. For MySQL on the host,
use `host.docker.internal` instead of `localhost` in that URL. Keep the existing
OAuth, encryption, JWT and provider settings in `backend/.env`; `.env.example`
documents required values. Environment files are excluded from the image.

After backing up the configured database and stopping existing writers, run
from the repository root:

```powershell
docker compose build
docker compose run --rm api python -m alembic upgrade head
docker compose up -d
docker compose logs -f worker maintenance-worker scheduler
```

Run the Vite frontend separately as described above. Use exactly one scheduler.
Without Compose, start Redis, the API, and these processes from `backend` in a
Linux/WSL environment with backend requirements installed (Celery's prefork worker
is not supported natively on Windows):

```sh
celery -A app.workers.celery_app:celery_app worker -Q gmail-sync --concurrency=2 --loglevel=INFO
celery -A app.workers.celery_app:celery_app worker -Q gmail-maintenance --concurrency=1 --loglevel=INFO
celery -A app.workers.celery_app:celery_app beat --loglevel=INFO
```

Operational checks include queued-job age, failed jobs, account `sync_paused`,
worker/beat availability and Redis persistence. Job status and account-list APIs
expose recovery state; the inbox UI is the next implementation step.
See [Celery's Redis guidance](https://docs.celeryq.dev/en/stable/getting-started/backends-and-brokers/redis.html)
and [periodic task guidance](https://docs.celeryq.dev/en/stable/userguide/periodic-tasks.html).

Safety budgets are 100 history pages, 2000 distinct message IDs per operation,
10 MiB decoded text/HTML per message, 1000 MIME parts and 30 nesting levels. A
budget breach fails visibly without truncating data or advancing the cursor.
Large backlogs may require explicit reconciliation or a later worker/budget
configuration change. Historical messages beyond the initial window are not
bulk-imported. HTML is cached as untrusted source and still requires safe rendering
in the upcoming inbox UI. Tests use isolated SQLite and mocked Gmail; live Google
permissions/sync and MySQL locking remain external integration checks.

## Verification

From `backend`, install test dependencies with
`myenv\Scripts\python.exe -m pip install -r requirements-dev.txt`, then run
`myenv\Scripts\python.exe -m unittest discover -s tests -v`.
Worker tests use isolated SQLite, fake Gmail and fakeredis executing the Lua
rate limiter. They cover queue outages, retry rollback, worker loss, stale attempt
tokens, scheduled sync and shared request limits. Real Redis/Celery processes,
MySQL row-lock contention and live Gmail remain deployment integration checks.

From `frontend`: `npm run build`, `npm run lint`, and
`node --test tests/*.test.mjs` (Node 24).

For the mocked desktop/mobile connection flow, serve `frontend/dist` on port
4174, install Playwright with Edge available, then run from `frontend`:
`node tests/connections.browser.cjs`. `APP_URL` can select another local server;
`PLAYWRIGHT_MODULE` can point to an existing Playwright installation. The test
mocks every API request and never sends mail or revokes a real Google grant.

Routing follows [FastAPI's multiple-prefix support](https://fastapi.tiangolo.com/tutorial/bigger-applications/#include-the-same-router-multiple-times-with-different-prefix).
Frontend environment values are embedded at build time, as described in
[Vite's environment guide](https://vite.dev/guide/env-and-mode).
