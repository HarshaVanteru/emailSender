# emailSender

React/Vite email workspace with a FastAPI backend and Gmail integration.

## Project structure

Application code is grouped by feature. Start with the feature folder when
changing a workflow; its routes, services, schemas, API calls, types, and
components live together.

```text
backend/
  app/
    main.py                      # FastAPI setup and router registration
    features/
      google_login/              # Google OAuth, connections, users, credentials
      compose_email/             # Sending, replies, forwarding, email formatting
      drafts/                    # Gmail draft storage and reviewed draft sending
      mailbox/                   # Reading, search, labels, actions, cache models
      ai_assistant/              # Draft generation and thread AI suggestions
      profile/                   # Profile and writing preferences
      mail_sync/                 # Gmail sync, durable jobs, push notifications
    core/                        # Configuration, database, session security, encryption
    integrations/gmail/          # Shared Gmail API client and MIME parsing
    workers/                     # Celery setup, tasks, and rate limiting
  migrations/                    # Alembic database migrations
  tests/                         # Backend regression tests and fixtures
frontend/
  src/
    main.tsx                     # React entry point
    app/App.tsx                  # Application shell and workspace state
    features/
      google-login/              # Google connection API, session, account types
      compose-email/             # Email and thread composers, sending API, formatting
      drafts/                    # Gmail draft API and types
      mailbox/                   # Mail list, thread reader, body rendering, styles
      ai-assistant/              # Copilot and thread AI panels, API, types
      profile/                   # Settings dialog, profile API and types
      mail-sync/                 # Sync API and job types
    shared/
      api/                       # API URL building and authenticated HTTP helpers
      components/                # Shared application header
    index.css                    # Global styles
  tests/                         # Frontend unit and browser regression tests
```

Frontend features import their own `api.ts` and `types.ts` directly. Backend
features expose routers through `routes.py`, with additional modules for larger
workflows. Shared mailbox persistence models remain in `features/mailbox/models.py`
so the API, sync workers, and migrations use the same SQLAlchemy definitions.
Python uses underscores in feature names; TypeScript folders use hyphens.

Configuration stays in `backend/.env`. Existing API URLs, OAuth callback URLs,
database tables are preserved by this reorganization.

## Run the project

Use Docker Compose for the API, Redis, Gmail workers, and scheduler, and run
Vite in a separate terminal. The service configuration lives in `backend/compose.yaml`.
Install Docker Desktop and Node.js 22.12+ (or a supported newer LTS release),
and open Docker Desktop before starting. MySQL runs separately; create the
`email_sender` database and a database user before applying migrations.
No local Python environment is needed for this workflow.

### First-time setup

Run these commands in PowerShell from the project root. Copy the environment
example only if `backend/.env` does not already exist:

```powershell
if (-not (Test-Path backend/.env)) { Copy-Item backend/.env.example backend/.env }
docker compose -f backend/compose.yaml build
```

Configure `backend/.env` using [the environment example](.env.example)
and [Google Cloud setup](docs/google-cloud-setup.md). Set `DATABASE_URL` to your
MySQL database; for MySQL running on Windows, use `host.docker.internal` as the
hostname instead of `localhost`. Set the Google OAuth credentials, provider API
key, `FRONTEND_URL=http://localhost:5173`, and the two independent secrets described
below. Compose supplies the internal Redis URL automatically.

For a new empty database, apply migrations from the project root:

```powershell
docker compose -f backend/compose.yaml run --rm --no-deps api python -m alembic upgrade head
npm --prefix frontend ci
```

For an existing database, follow the database setup section below before migrating.

### Start

From the project root:

```powershell
docker compose -f backend/compose.yaml up --build -d --wait --wait-timeout 120
npm --prefix frontend run dev -- --port 5173 --strictPort
```

Keep the frontend terminal open. Visit http://localhost:5173;
API docs are at http://localhost:8000/docs. Restart with the same commands after
backend changes so Docker rebuilds the application source.

### Status, logs, and shutdown

In another terminal at the project root:

```powershell
docker compose -f backend/compose.yaml ps
docker compose -f backend/compose.yaml logs --tail 80 api worker maintenance-worker ai-worker scheduler
docker compose -f backend/compose.yaml logs -f worker maintenance-worker ai-worker scheduler
```

Press Ctrl+C to exit log following. To stop the frontend, press Ctrl+C in its
terminal. Stop the backend services with:

```powershell
docker compose -f backend/compose.yaml stop
```

Stopping retains containers and Redis data. `docker compose -f backend/compose.yaml down` also removes
containers and the network while retaining the Redis volume; `docker compose -f backend/compose.yaml down -v`
deletes that stored Redis data. MySQL data remains in your external database.
If startup fails, inspect `docker compose -f backend/compose.yaml ps` and logs; some containers may still
be running. Ensure no other API is using port 8000 and no other frontend is using
port 5173. Run only this stack so there is one scheduler.

The canonical implementation plan and ordered backlog are maintained in
[Linear](https://linear.app/harshagenai/document/master-implementation-plan-ai-powered-gmail-client-3c249799afc8).

## API compatibility

For Google Cloud scopes, consent setup, and the feature endpoint catalog, see
[Google Cloud setup and feature APIs](docs/google-cloud-setup.md). New logins
request `gmail.modify` plus Google identity scopes to enable all current Gmail
features. Existing connections need renewed authorization to gain that access.

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
| POST | `/api/v1/webhooks/gmail/pubsub` | Authenticated Gmail change notification |

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
server secret store, following [backend/.env.example](.env.example).
After building the Docker image, generate them from the project root:

```powershell
docker compose -f backend/compose.yaml run --rm --no-deps api python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
docker compose -f backend/compose.yaml run --rm --no-deps api python -c "import secrets; print(secrets.token_urlsafe(48))"
```

The first output is the encryption key; the second is the JWT signing key.
Back up the encryption key securely: losing it makes saved credentials unreadable.
All backend instances must share these secrets. Never use `VITE_` variables for them.

Schema changes are explicit through Alembic; starting the API no longer creates
or changes tables. From the project root, for a
**new empty database**, run `docker compose -f backend/compose.yaml run --rm --no-deps api python -m alembic upgrade head`.
For an **existing database matching the original users schema**, back up the
database and configure the encryption key, then run:

```powershell
docker compose -f backend/compose.yaml run --rm --no-deps api python -m alembic stamp 0001
docker compose -f backend/compose.yaml run --rm --no-deps api python -m alembic upgrade head
```

Revision `0002` moves legacy `users.google_token` values into encrypted connection
records and clears the plaintext column. Check `docker compose -f backend/compose.yaml run --rm --no-deps api python -m alembic current` and restart the
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

Apply Alembic migrations through the current head (`0007`) before using the updated backend. Revision `0004` persists the
exact OAuth scopes requested across redirects; existing pending send-only attempts
remain compatible. New connections request `gmail.modify`, covering mailbox
sync, drafts, sending, and mailbox actions. Google Cloud consent configuration
must allow this scope. Existing send-only or read-only users must reconnect and
approve the additional access. Legacy feature query flags are still accepted,
but all new authorizations use the full current scope set. Use
`/api/v1/auth/google?renew_consent=true` to explicitly request renewed consent.
If Google omits a refresh token and no saved token can be reused, the callback
returns to the app with a **Reconnect Gmail** link. This explicitly requests
renewed consent with the original permission selection; it creates no session
until the connection succeeds. Approve access on Google's consent screen to
finish connecting.
The callback records Google's actual granted scopes, including previously
approved permissions or partially declined consent; sync checks the actual grant.

With the app bearer token, `POST /api/v1/accounts/{account_id}/sync` queues a job
and returns `202 Accepted`. The worker imports up to 600 messages from the last
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

Gmail push is optional. To enable it, create a Pub/Sub topic in the **same Google
Cloud project** as the Gmail OAuth client and grant
`gmail-api-push@system.gserviceaccount.com` the Pub/Sub Publisher role on that
topic. Create an authenticated **wrapped** push subscription targeting the
public HTTPS URL `/api/v1/webhooks/gmail/pubsub`. Configure its OIDC service
account, grant the Pub/Sub service agent permission to mint tokens for it, and
set the audience to the exact URL (or the subscription's configured custom
audience). Set `GMAIL_PUSH_TOPIC`, `PUBSUB_PUSH_AUDIENCE`,
`PUBSUB_PUSH_SERVICE_ACCOUNT`, and `PUBSUB_SUBSCRIPTION` in `backend/.env`.
Resource names use `projects/PROJECT/topics/TOPIC` and
`projects/PROJECT/subscriptions/SUBSCRIPTION`. Restart API, maintenance worker,
and beat after configuration; apply migration `0007` first. The hourly renewal
task establishes watches for read-enabled accounts, renews them daily, and
retries failed registrations after an hour. Incoming notifications only queue
an incremental sync; they never advance the committed Gmail history cursor.
The existing five-minute sync and daily reconciliation remain active when push
is unconfigured or notifications are missed. A valid push is acknowledged once
the job is durable, including when Redis is briefly unavailable; the existing
maintenance outbox republishes it. See [Gmail push setup](https://developers.google.com/workspace/gmail/api/guides/push)
and [Pub/Sub authenticated push](https://docs.cloud.google.com/pubsub/docs/authenticate-push-subscriptions).

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
with exponential jittered backoff (initially 7.5â€“15 seconds, capped at 300
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

The `backend/compose.yaml` runs Redis with AOF persistence, API, two sync worker
processes, a separate maintenance worker, and one Celery beat scheduler. MySQL
stays external and uses `DATABASE_URL` from `backend/.env`. For MySQL on the host,
use `host.docker.internal` instead of `localhost` in that URL. Keep the existing
OAuth, encryption, JWT and provider settings in `backend/.env`; `.env.example`
documents required values. Environment files are excluded from the image.

Use the commands in **Run the project** above to start and inspect these services.
Before upgrading an existing database, back it up and run `docker compose -f backend/compose.yaml stop`.
Apply migrations with `docker compose -f backend/compose.yaml run --rm --no-deps api python -m alembic upgrade head`, then restart the stack. Use exactly one scheduler.

Operational checks include queued-job age, failed jobs, account `sync_paused`,
worker/beat availability and Redis persistence. Job status and account-list APIs
expose recovery state; the mailbox UI can submit sync and track its result.
See [Celery's Redis guidance](https://docs.celeryq.dev/en/stable/getting-started/backends-and-brokers/redis.html)
and [periodic task guidance](https://docs.celeryq.dev/en/stable/userguide/periodic-tasks.html).

Safety budgets are 100 history pages, 2000 distinct message IDs per operation,
10 MiB decoded text/HTML per message, 1000 MIME parts and 30 nesting levels. A
budget breach fails visibly without truncating data or advancing the cursor.
Large backlogs may require explicit reconciliation or a later worker/budget
configuration change. Historical messages beyond the initial window are not
bulk-imported. HTML is cached as untrusted source and sanitized at the mailbox
rendering boundary. Tests use isolated SQLite and mocked Gmail; live Google
permissions/sync and MySQL locking remain external integration checks.

## Inbox, search and conversations

The Mail workspace provides account selection, Inbox/Sent/Drafts/All mail,
label and unread filters, search, and conversation reading. Write opens the
existing composer and AI copilot without discarding its current draft. On smaller
screens, opening a conversation replaces the list; Back to messages restores
keyboard focus to the selected message. Loading, empty and retry states are
available for account, message and conversation requests.

Enable inbox access explicitly when prompted. This requests the additional
Gmail read permission; send-only accounts continue working with the composer.
Sync mail queues a job and polls its status, including saved jobs waiting for
Redis recovery. Cached mail remains readable by its owner after disconnecting;
disconnect removes the Google credentials, not the existing local cache.

| Method | Endpoint | Result |
| --- | --- | --- |
| GET | `/api/v1/emails?account_id=1` | Recent cached message summaries |
| GET | `/api/v1/search?account_id=1&q=meeting` | Literal cached-message search |
| GET | `/api/v1/emails/{message_id}?account_id=1` | Body and attachment metadata |
| GET | `/api/v1/threads/{thread_id}?account_id=1` | Cached conversation messages, oldest first |
| GET | `/api/v1/accounts/{account_id}/labels` | Cached system and custom labels |

All routes require the app bearer token and enforce account ownership. List and
search accept `label` (Gmail label ID), `unread`, `q`, `page_size` (1â€“100; default
30) and `page_token`. Thread pages accept `page_size` (1â€“25; default 10) and
`page_token`. Pass the returned `next_page_token` to continue. Tokens are bound to
the authenticated user, account and filters; changing those inputs requires a
fresh first page. Date/ID keyset ordering handles equal timestamps deterministically.
Messages arriving during pagination appear after refreshing the list.

Search matches a literal substring of sender, subject, snippet, plain-text body
or recipients in the local cache. It does not implement Gmail query operators or
search uncached history. Case matching uses the database's lowercase behavior.
Conversations include only synchronized messages, across their cached labels;
they may omit older messages outside the sync window. Reading does not change
Gmail's unread state. Attachment downloads remain a later delivery step.

## Gmail drafts and reviewed sending

The Write workspace can save a message to Gmail Drafts, reopen it, and send it
only after the separate review dialog's **Confirm send** action. New connections
request `gmail.modify`, which includes draft access. Previously granted
`gmail.compose` access also works. Send-only connections still use the existing direct composer send,
which now has the same review step. Gmail drafts can be saved before recipient,
subject, or body are complete. The writing workspace supports up to 20 attachments totaling 25 MB (including
inline images), and restores them when reopening an editable app draft. Inline
images support PNG, JPEG, GIF, and WebP up to 5 MB each. Thread replies keep
their existing single-attachment limit of 5 MB.

| Method | Endpoint | Effect |
| --- | --- | --- |
| GET | `/api/v1/accounts/{account_id}/drafts` | List Gmail drafts (20 per page; optional `page_token`) |
| POST | `/api/v1/accounts/{account_id}/drafts` | Create a Gmail draft from `to`, `cc`, `bcc`, `subject`, `body`, optional `body_html`, and `attachments` |
| GET | `/api/v1/accounts/{account_id}/drafts/{draft_id}` | Read the raw MIME draft for review |
| PUT | `/api/v1/accounts/{account_id}/drafts/{draft_id}` | Update with the latest `content_hash` and full content |
| POST | `/api/v1/accounts/{account_id}/drafts/{draft_id}/send` | Send only with the reviewed `content_hash` |
| DELETE | `/api/v1/accounts/{account_id}/drafts/{draft_id}` | Discard only with the latest `content_hash` in the JSON body |

All routes require the app bearer token, check account ownership and draft
permission, and return `Cache-Control: no-store`. An update or send rejects a
draft that changed in Gmail since it was opened. The editor disables edits and
send for external drafts whose complete content or recipients it cannot safely
preserve and review; those drafts can still be opened in Gmail. Gmail draft
requests use no automatic retries. If a save or send times out, check Gmail
Drafts or Sent before trying again to avoid duplicate messages.

## Threaded replies and forwarding

Open a cached conversation and choose **Reply**, **Reply all**, or **Forward** on
a message. Reply-all suggests the Reply-To sender and other To/Cc recipients,
excluding the connected mailbox and duplicates. You can edit To, Cc, body and
add one new attachment up to 5 MB. The review screen shows the final recipients,
subject, body and attachment before a separate **Confirm** action sends through
Gmail. Forwarding quotes the original message as text and starts a new
conversation; original attachments are identified but not silently copied.

| Method | Endpoint | Effect |
| --- | --- | --- |
| GET | `/api/v1/accounts/{account_id}/messages/{message_id}/compose?mode=reply` | Resolve reply, reply-all, or forward context from the cached message |
| POST | `/api/v1/accounts/{account_id}/messages/{message_id}/send` | Send reviewed `mode`, `context_hash`, `to`, `cc`, `body`, and optional `attachment` |

Replies set Gmail `threadId`, a matching `Re:` subject, `In-Reply-To` and
`References` from the original RFC Message-ID. A missing or invalid Message-ID
blocks a threaded reply. The send route checks ownership, Gmail send permission,
recipient validity and the current context hash before calling Gmail once with
automatic retries disabled. A successful send makes mailbox sync due; the UI
also requests and watches a sync job so the conversation refreshes. If Gmail
returns a different thread ID or the send result is ambiguous, check Sent before
trying again. Live Gmail threading remains an integration check.

## Contextual AI suggestions

Open **AI help with this conversation** in a cached thread to summarize it,
suggest a reply, rewrite pasted text, extract actions or classify it. The API
uses at most eight account-owned cached messages and 12,000 message-body
characters per request; the model receives the mail as untrusted source text.
Outputs have typed, bounded fields and are stored in `ai_suggestions`, separate
from Gmail messages and drafts. Only the owner can list the most recent 20
suggestions for a conversation. **Use in reply editor** copies suggested text
into the existing reply flow, where recipients and the final send still require
review and explicit confirmation. AI operations never call Gmail send or mail
mutation APIs.

| Method | Endpoint | Effect |
| --- | --- | --- |
| GET | `/api/v1/accounts/{account_id}/threads/{thread_id}/ai` | List recent stored suggestions |
| POST | `/api/v1/accounts/{account_id}/threads/{thread_id}/ai/{operation}` | Generate `summarize`, `generate_reply`, `rewrite`, `extract_actions`, or `classify` suggestion |

Apply revision `0006_ai_suggestions` to a **disposable** database during
pre-release verification; no configured/live database is migrated automatically.
The general writing copilot also limits user history to 12 messages and input
to 4,000 characters. Provider credentials and live model output remain
deployment integration checks.

Message HTML is returned as **untrusted JSON data**. The UI sanitizes it with
DOMPurify and displays it in a sandboxed iframe, preserving
email styles, tables, colors, and responsive CSS without affecting the app.
Scripts, forms, SVG, embeds, navigation metadata, and event handlers are removed.
A content security policy blocks scripts, external stylesheets, fonts, and
embedded content. HTTPS images and CSS backgrounds load only after **Show images**
is selected for that message; inline raster data images can display immediately.
**Hide images** stops displaying external images but cannot undo earlier requests.
Attachment-based `cid:` images and attachment downloads remain unsupported.
HTTP(S)/mailto links open without an opener or referrer. Plain-text mode uses
React text rendering. Messages retain their own colors in dark mode.
See [iframe sandbox guidance](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/iframe#sandbox)
and [DOMPurify configuration](https://github.com/cure53/DOMPurify).

## Mailbox actions

Mailbox changes require a granted `gmail.modify` permission, requested by
default for new connections. The Mail
workspace shows **Enable mail actions** for connected accounts with read-only
permission. The existing upgrade URL accepts `modify_access=true`; Gmail's modify scope
also covers mailbox reads, so it does not add the separate readonly scope. The
callback stores the actual grant, including partial consent. Send-only and
read-only grants cannot change messages.

| Method | Endpoint | Effect |
| --- | --- | --- |
| PATCH | `/api/v1/emails/{message_id}?account_id=1` | JSON `{ "read": true/false }` and/or `{ "starred": true/false }` |
| POST | `/api/v1/emails/{message_id}/archive?account_id=1` | Remove `INBOX` label |
| DELETE | `/api/v1/emails/{message_id}?account_id=1` | Move to Gmail Trash |

The DELETE route calls Gmail's `trash` method and never permanently deletes the
message. The UI requires confirmation. All changes use the authenticated user's
account and a locally cached message ID, then call Gmail with the provider ID.
Google remains authoritative: successful responses replace cached labels and
make the account due for a follow-up sync. A rejection leaves cache labels
unchanged and shows a safe error. If Google succeeds but the response or local
commit cannot be verified, refresh or sync before trying again. Mailbox changes
are not queued for automatic retry; each comes from an explicit UI action. A
shared per-account request limit applies to mutations and sync. See
[Gmail message modification](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/modify)
and [move to Trash](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/trash).

## Verification

Use [the release runbook](../docs/release.md) for the verification matrix, rollout
order, smoke checks, rollback, and remaining live-service checks. The test
commands below use mocks and disposable databases; they do not authorize a live
send, Google Cloud change, database migration, or deployment.

From `backend`, install test dependencies with
`myenv\Scripts\python.exe -m pip install -r requirements.txt`, then run
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
Run `node tests/mailbox.browser.cjs` against the same server for desktop/mobile
mailbox navigation, pagination, search/filters, sync recovery, account switching,
keyboard focus, and hostile-HTML checks. Screenshots are saved under
`frontend/artifacts/mailbox-*.png`. Run `node tests/html-mail.browser.cjs` for
newsletter CSS/table fidelity, responsive styles, image consent, script and
tracking blocking, long-message sizing, plain-text toggling, and dark mode.
It mocks both API and image requests; screenshots use `html-mail-*.png`.
Run `node tests/mail-actions.browser.cjs` for read/unread, star, archive, Trash
confirmation, permission upgrade and rejection recovery at desktop/mobile widths.
Run `node tests/drafts.browser.cjs` for Gmail draft save, reopen, review
cancellation, and confirmed send with mocked provider requests at both widths.
Run `node tests/thread-compose.browser.cjs` for reply-all and forwarding
recipients, review cancellation, attachment notice and explicit send.
Run `node tests/context-ai.browser.cjs` for all five contextual AI actions and
the suggestion-to-reply handoff without sending.

Routing follows [FastAPI's multiple-prefix support](https://fastapi.tiangolo.com/tutorial/bigger-applications/#include-the-same-router-multiple-times-with-different-prefix).
Frontend environment values are embedded at build time, as described in
[Vite's environment guide](https://vite.dev/guide/env-and-mode).

## Automatic mailbox updates

The mailbox opens an authenticated WebSocket at
`/api/v1/accounts/{account_id}/events`. Successful background syncs refresh the
message list and open conversation without discarding an unsent reply. The
connection retries after interruptions and refreshes after reconnecting.
Gmail Pub/Sub enables prompt sync; without it, scheduled sync runs every five
minutes by default. See [push and WebSocket setup](docs/google-cloud-setup.md).

Run `node tests/realtime.browser.cjs` against the same local production server
for mocked desktop/mobile incoming mail, reconnect, and unsent-reply preservation.

## Everyday compose tools

The writing workspace supports multiple comma-separated recipients, Cc/Bcc,
rich text (font, size, color, bold, italic, underline, strikethrough, alignment,
lists and quotes), links, inline images, emoji, plain-text mode, and insertion
of your saved profile signature. Attach or drop multiple files, with a combined
25 MB limit including inline images. Rich HTML is sanitized in the browser
and server; inline images are sent as CID MIME parts, not remote tracking URLs.

Autosave is enabled for accounts with Gmail draft permission. It saves two
seconds after editing stops, permits incomplete drafts, and preserves the latest
MIME hash to detect edits made elsewhere. Invalid recipients pause saving until
corrected. A save failure turns off autosave to avoid blindly retrying ambiguous
requests; check Gmail and use explicit Save or reopen the draft. Send-only
accounts can send directly but need upgraded access for Gmail draft autosave.

The review dialog shows the sending account, To/Cc/Bcc, formatted message,
inline images and attachments. Confirm send starts a ten-second browser-side
cancellation period. **Undo send** cancels before a Gmail request is made. Keep
the tab open until sending finishes; closing it during the countdown cancels
the pending send. After Gmail receives the request, there is no recall and
ambiguous sends are never retried automatically. This is not a scheduled-send
queue. Reset clears the editor while retaining saved Gmail drafts; Discard draft
confirms deletion of the current saved draft using its latest content hash.

Run `node tests/compose-features.browser.cjs` against the local production server
for mocked desktop/mobile compose, autosave, reopen, reviewed sending, undo,
and discard checks.

## Mybox: automatic incoming-mail review

Mybox appears above Inbox. The background AI worker reviews incoming cached
messages (including the existing cache), flags suspected spam, and assigns
critical/red, high/amber, normal/blue, or low/gray importance. Mybox contains
only successful non-spam classifications, excluding Gmail Spam, Trash, Sent,
and Drafts. Unreviewed or failed messages remain accessible in Inbox/All mail.
AI classifications are advisory; they do not delete mail or change Gmail labels.

The operator has authorized processing through Groq: each request shares the
sender, subject, and up to 6,000 characters of plain message text (or extracted
HTML text). Attachments, OAuth credentials, and other conversations are not sent.
Set `MYBOX_ENABLED=false` to stop future automatic review, and `MYBOX_MODEL`
to select the configured Groq model. `GROQ_API_KEY` must be configured.

Apply migration `0008` with the API and workers stopped, after reviewing and
backing up the configured database. From the project root:

```powershell
docker compose -f backend/compose.yaml stop
docker compose -f backend/compose.yaml build
docker compose -f backend/compose.yaml run --rm --no-deps api python -m alembic upgrade head
docker compose -f backend/compose.yaml up -d --wait --wait-timeout 120
```

Restart the frontend normally. No live database migration is run automatically
by development or test commands. The stack now includes `ai-worker`, listening
on the separate `gmail-ai` queue; deploy it and restart the single scheduler.

The scheduler scans for unreviewed mail every 30 seconds and processes up to
five messages per task, newest first. Classification follows Gmail sync; delayed
sync or a cache backlog delays Mybox visibility. Provider calls time out after
30 seconds. Leased attempts recover after worker loss; invalid output or provider
errors retry with backoff, up to five attempts. Mybox shows pending/failed counts
and an owned-account **Retry reviews** action. WebSocket notifications refresh
Mybox after classification commits, without waiting for another Gmail sync.

Run `node tests/mybox.browser.cjs` against the local production server for mocked
desktop/mobile navigation, importance markers, spam exclusion, search, and
classification-completion refresh. Backend `test_mybox.py` checks filtering,
account isolation, bounded provider input, failure recovery, and stale leases.
