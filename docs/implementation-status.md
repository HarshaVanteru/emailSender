# Implementation and verification handoff

The [architectural specification](../custom_gmail_application_codex_spec.md) is the
contract. The [Phase 0 review](architecture-review.md) records the original gaps.
This document describes the implemented changes and the evidence for them.

## Phase 1 — Foundation and multiple accounts

Inspected the existing OAuth handlers, browser state, credential refresh, ownership
checks and account selectors. Preserved the Google authorization-code flow, PKCE,
single-use browser-bound state, registered callback URLs and existing API aliases.

Implemented separate login identities, revocable application sessions and
authenticated mailbox connection/reconnection. Connection attempts retain the
initiating user/session and optional reconnect target. The callback checks session
validity before exchanging a code and again before saving the connection. Another
mailbox cannot silently replace the selected reconnect target or become another
user's connection. One Google subject has one application owner; automatic mailbox
transfers are not supported. Existing subject-less accounts are backfilled on
verified reconnection, without synthesizing subjects from email addresses.

Credential ciphertext now lives in `oauth_credentials`, with key-version metadata.
The legacy account column is retained as a read fallback and for controlled
downgrades, but migration 0014 clears its contents. Fernet remains the authenticated
encryption format; previous keys can be supplied during a controlled rotation.
App JWTs use persisted sessions; session-less legacy JWTs are rejected by default.
Browser bearer storage is limited to sessionStorage, with migration of an existing
localStorage token. OAuth credentials never go to the browser. Settings includes
Add Gmail account, targeted reconnect, reviewed disconnect and server-side logout.

Files: `backend/app/features/google_login/`, `core/security.py`, `core/token_crypto.py`,
`features/profile/routes.py`, frontend login/profile controls and selected-account
send checks. Migrations: **0010, 0014**. Tests: connection security, real callback
state transitions for two mailboxes, cross-user ownership, revoked-session rejection,
refresh preservation, credential migration round-trips and browser connection flows.
Next dependency was the adapter/schema work in Phase 2.

## Phase 2 — Database and Gmail adapter

Kept the working feature layout, account-scoped uniqueness, composite tenant foreign
keys, recursive MIME parser and message/thread upserts. Added a provider adapter
that owns Gmail request construction for sync, watch, labels, attachments, drafts,
replies and sends. Existing resource-shaped fake providers exercise the same adapter.

Numeric identifiers use unsigned BIGINT on MySQL, with SQLite INTEGER variants for
isolated tests. Public job/session cursors stay random strings; the new job and
history tables have separate numeric primary keys. **0015** widens existing numeric
keys together after checking values, then recreates foreign keys. This migration
was explicitly approved for preparation and disposable-database validation. It was
not run against the configured application database. A downgrade refuses values
that would overflow signed INT. Existing typed SQLAlchemy 2 mappings are used for
new operation records; working legacy Column declarations remain valid SQLAlchemy
2 models and were not rewritten just for style.

Tests verify MySQL clean/legacy upgrades, metadata parity, wide IDs and downgrade
overflow refusal, plus SQLite migration round-trips, tenant constraints and MIME
fixtures. A small fix to the legacy **0006 downgrade** avoids dropping an index
that MySQL uses for a foreign key; its upgrade behavior is unchanged.
Next dependency was independent recent/history synchronization in Phase 3.

## Phase 3 — Recent and on-demand historical synchronization

Replaced automatic full-mailbox backfill with a configurable recent-window scan,
defaulting to 30 days. The boundary is fixed during pagination and includes the
supported mailbox views, including Spam/Trash. Existing cached old messages remain.
Recent listings never infer deletion from absence. Repair fetches previously cached
messages in bounded pages and removes a message only after a provider deletion/404.
Incremental history changes continue while recent repair pages are imported.

Added durable historical sessions with account/view ownership, seven-day expiration,
encrypted provider continuation tokens and repeated-token detection. A request
records work; a sync worker fetches one page and atomically commits messages and the
checkpoint. Continuing requires the session ID. Replaying a start request does not
consume the next page. Expired provider tokens restart the bounded listing safely;
older snapshots cannot overwrite newer message history state. Historical workers
never advance the incremental history cursor. Gmail draft pagination also wraps
provider tokens in expiring, owner/account-bound encrypted application cursors.

Mailbox local exhaustion offers **Load older mail from Gmail**, with session status
polling only while that explicit fetch is pending. API configuration is
`PATCH /api/v1/accounts/{id}/sync/settings` with `initial_sync_days` from 1 to 365.
Committed sync counters and watch errors are persisted for diagnostics.

Files: `mail_sync/service.py`, `historical.py`, `history_models.py`, routes and workers;
frontend `HistoryControl.tsx`; draft cursor handling. Migrations: **0011, 0016**.
Tests cover the exact configured time query, commit counters, page/checkpoint
recovery, idempotent imports, account isolation and explicit browser history loading.
Next dependency was durable push ingestion in Phase 4.

## Phase 4 — Incremental synchronization and push

Preserved verified Google JWT issuer/audience/service-account checks, subscription
validation, watch renewal, leased sync jobs, account row locks and transactional
history-cursor updates. Added the **0012** durable push inbox, keyed by Pub/Sub
message ID. Acceptance persists the event and durable work before acknowledgement;
the worker marks events processed once its committed cursor covers them. Unknown
mailboxes and obsolete events are recorded without triggering unauthorized work.

Retained scheduled reconciliation for missed notifications and bounded history-404
repair. Renewal errors are now durable. Retry policy distinguishes rate-limit 403s
from permanent errors, honors Retry-After, uses bounded backoff and applies both
per-account and global Gmail request budgets. The authenticated transport refreshes
once on 401; sync/history workers persist refreshed credentials while preserving
refresh tokens.

Tests cover duplicate events, stale cursors, queue loss, worker loss, watch renewal,
rate-limit reasons and account isolation. Browser realtime and polling-fallback
suites pass. Next dependency was durable sending and client gaps in Phase 5.

## Phase 5 — Client operations and durable sending

Preserved mailbox views, local search, threading, Gmail draft autosave, MIME-rich
compose, review, the pre-submission undo countdown and explicit user confirmation.
Sending and reply controls follow the selected account's permissions.

New compose, reply and draft submissions create durable **email_send_jobs** under
**0013**. The request requires an Idempotency-Key and stores encrypted work before
dispatch. A dedicated worker claims the job. Completed/failed/unknown sends discard
the queued payload. A crash or ambiguous transport failure becomes `unknown` and
is never automatically requeued. Compose/reply MIME includes a correlation
Message-ID. An owned reconciliation endpoint searches Sent for that ID; absence
does not prove non-delivery. Settings/composer status makes uncertain jobs visible
after reload. Legacy synchronous send URLs retain their response shape, but now
journal their outcomes; they never enter the pending send dispatcher.

Added Gmail user-label create/rename/delete and assignment/removal with provider
reconciliation, ownership checks and system-label protection. Added on-demand
attachment downloads, a 25 MB limit, validated base64, safe filenames, no-store,
nosniff and forced download disposition. Provider HTML/MIME types are never used
to render an attachment inline. No background attachment downloads were introduced.

Files: `compose_email/send_jobs.py`, `send_job_routes.py`, `inline_receipt.py`,
`workers/operations.py`, `operation_models.py`, mailbox attachment/label modules,
and corresponding frontend controls. Tests cover send idempotency, ambiguity,
crash recovery, cross-account denial, preserved threading/drafts, and desktop/mobile
review, undo, labels, downloads and reconciliation. Next dependency was asynchronous
AI in Phase 6.

## Phase 6 — Independent AI jobs

Kept strict `CATEGORY_PERSONAL` eligibility and exclusion of conflicting categories,
Spam, Trash, Sent, Drafts and unclassified messages. Kept Mybox's independent retry
and lease behavior. Conversation summary, action extraction, classification,
rewrite and suggested replies now use durable **ai_processing_jobs**. Keys include
the operation, bounded conversation version, prompt version and model. Unchanged
completed suggestions are reused; stale context is rejected, and explicit user
requests may retry exhausted AI work. Standalone writing requests are also queued
as user-owned jobs without requiring a selected mailbox.

All AI HTTP generation routes return **202 with a job**; the frontend follows the
owned status endpoint. This response-contract change is deliberate and requires
deploying the rebuilt frontend with the backend. No request handler invokes an
LLM. Model construction is lazy so an unset Groq key cannot break API startup or
mail synchronization. Model calls have explicit timeouts and no hidden SDK retries.
AI output remains advisory and cannot send or mutate messages.

Files: `ai_assistant/jobs.py`, routes/services, shared operation workers and frontend
job helpers. Migration: **0013**. Tests cover Primary eligibility, deferred model
invocation, completed-job deduplication, isolated thread history, bounded input and
no-send behavior. Next dependency was operational hardening in Phase 7.

## Phase 7 — Runtime and operational hardening

The existing backend service names and four-container production stack are retained.
The worker service supervises **three separate Celery worker processes**: sync and
maintenance, AI, and send. Slow AI no longer consumes sync execution slots. All
three queue groups are checked by container health and deployment verification.
Only one beat scheduler runs. Deployment tests preserve pull/preflight/drain/migrate/
health sequencing and leave the existing database container/network intact.

An optional root Compose stack adds local MySQL and a containerized frontend;
production can continue using external MySQL and nginx/static frontend releases.
MySQL and Redis have no host ports in that optional stack. Configuration examples
cover independent secrets, key rotation metadata, recent window, quotas and model.

Added pre-ping/pool timeouts, restricted CORS, request IDs, sanitized structured
request logs and no-store security headers. Uvicorn API access logging is disabled
to keep OAuth codes out of URL logs. Optional Redis-backed mutation/OAuth-start rate
limits share a user budget across sessions; production Compose enables them by
default unless explicitly overridden. Owner-only diagnostics show failed jobs,
reauthorization, renewal errors and send/AI backlogs, with a safe resume action.

Validation includes a real disposable MySQL dump/restore drill, migration rehearsals,
deployment sequencing tests under Git Bash, all Compose configuration variants and
a synthetic SQLite read-model smoke benchmark (5,000 messages, 100 requests).
The benchmark measured p50 **2.54 ms**, p95 **2.84 ms** in this environment; these
are not production Gmail/AI capacity or SLO guarantees.

## Validation and limits

Verification completed during this implementation:

| Check | Result |
| --- | --- |
| Final backend regression suite | 198 tests, passing; 2 opt-in Docker/MySQL checks skipped on the resumed run |
| Earlier backend run with disposable MySQL and restore enabled | 197 tests, all passing, no skips (before the final stale-snapshot regression was added) |
| Frontend unit tests | 10 passing |
| Frontend production build and lint | Passing, repeated after resuming |
| Mocked browser suites | 14 passing on desktop and mobile |
| Deployment regression tests | 10 passing |
| Compose configurations | Local backend, production backend and optional full stack validated |
| Built container smoke | API health through frontend proxy, migration head 0016, reserved worker queues and scheduled maintenance passed |

The final regression rejects an older message snapshot before creating thread or
label rows. The optional live diagnostic now requires an existing operator-provided
session and explicit screenshot opt-in; it was syntax-checked, not run against live mail.

On resumption Docker Desktop's Linux daemon was unavailable. The earlier container,
MySQL migration and restore results above remain the recorded evidence; they were
not repeated after the final service-only fix. Disposable containers labeled
`emailsender.task=architecture-review` and network `emailsender-spec-testnet` may
remain stopped in Docker Desktop and should be removed after restarting its daemon.
No application containers should be removed as part of that cleanup.

Reproduce the provider-independent backend suite from `backend` with
`DATABASE_URL=sqlite://`, a dummy `GROQ_API_KEY`, and
`myenv/Scripts/python.exe -m unittest discover -s tests -v`. From `frontend`, run
`npm run build` and `npm run lint`. Deployment tests use
`backend/myenv/Scripts/python.exe -m unittest discover -s .github/tests -v`
with `TEST_BASH` pointing to Git Bash on Windows.

MySQL tests require an explicitly named
test database; the restore test additionally requires the labeled disposable
container. Ordinary tests require no live Gmail, Groq or production database.

No production database was migrated, no live mail was sent, no secrets were changed,
and no deployment was published. Live Google consent, restricted-scope verification,
Pub/Sub delivery, provider quotas and production load still require the operator's
configured environment. Gmail-backed drafts can lack a Message-ID; ambiguous sends
of those drafts remain unknown until manually checked rather than being guessed
safe to retry. Local search covers cached mail, with older history loaded explicitly;
it does not claim the full Gmail search language. Antivirus scanning and attachment
preview are not enabled; downloads remain explicit and are never rendered inline.

The next operational step is a backed-up, stopped-writer migration and coordinated
backend/frontend rollout, followed by a designated-account live smoke check. See
[release and restore procedures](release.md). Deployment approval is separate from
the code and disposable-database validation completed here.
