# Architecture review and phased implementation plan

Phase 0, reviewed 2026-10-31 against all 1,791 lines of
[`custom_gmail_application_codex_spec.md`](../custom_gmail_application_codex_spec.md).
That specification is the architectural contract. This document describes the
current source tree and proposes changes; it does not declare future phases complete.

## Current implementation

This is already a feature-oriented modular monolith. Preserve `backend/app/features`
and `frontend/src/features`; renaming them to the specification's example tree
would add churn without improving the boundaries.

| Area | Existing implementation |
| --- | --- |
| Frontend | React 19, TypeScript 6, Vite 8, Tailwind 4, DOMPurify, Lucide; feature folders for mailbox, compose, drafts, Google login, profile, sync and AI. |
| Backend | FastAPI, Pydantic 2, SQLAlchemy 2, Alembic, PyMySQL, Google API/OAuth clients, cryptography, Celery/Redis, Groq and LangChain. Runtime dependencies are pinned in `backend/requirements.txt`; `backend/pyproject.toml` is currently empty. |
| HTTP | `/api/v1` routers in `backend/app/main.py`, with compatibility aliases under `/api`. Feature routes delegate substantial workflows to services, though persistence and provider calls remain mixed in some services. |
| Authentication | Google authorization-code flow, PKCE, short-lived persisted OAuth attempts, browser-bound single-use state and an application JWT. The browser stores the JWT in localStorage. |
| Credentials | Fernet-encrypted credential JSON, row-locked refresh, preserved refresh tokens on reconnection, reauthorization flags, account list and provider revocation on disconnect. |
| Mail cache | Account-scoped threads, messages, labels, mappings and attachment metadata. Composite foreign keys prevent cross-account thread/label/attachment links. Gmail IDs have account-scoped uniqueness. |
| Read API | Local keyset pagination using date and ID, batched label/attachment loading, body projection for lists, thread reading and local substring search. Browser cursors are application data, not Gmail page tokens. |
| Sync | Durable MySQL sync jobs act as an outbox. Leased claims, one active job per account, retries, crash recovery, transactional cache/cursor commits and scheduled reconciliation already exist. |
| Push and updates | Verified Google push identity/audience/subscription, watch renewal, history hints and incremental history processing. Redis publishes committed account updates to authenticated WebSockets, with browser polling fallback. |
| Client operations | Account selectors, category views, read/unread, star, archive, compose, Gmail-backed draft autosave, replies/forwards and attachment downloads. Replies preserve threading headers and check reviewed context hashes. |
| AI | Primary-only automatic Mybox triage runs on a Celery queue with leases and bounded attempts. Conversation suggestions are persisted but generated synchronously in API requests. A separate writing assistant also exists. |
| Rendering | DOMPurify and an email iframe, external images blocked by default; compose HTML is sanitized in browser and backend. |
| Deployment | Local Compose: API, Redis, shared worker and beat scheduler; external MySQL and separate Vite frontend. Production: four backend services plus nginx-served frontend artifacts and an existing/external database. CI tests, publishes an ARM64 backend image, drains writers, migrates explicitly, and checks the deployed worker. |

Configuration lives in `backend/.env.example` and `backend/app/core/config.py`.
Existing names include `SECRET_KEY`, `GROQ_API_KEY`, `GMAIL_PUSH_TOPIC` and a
single `REDIS_URL`. Keep supported names while introducing documented aliases
only where useful; the specification's example names do not require a breaking rename.
No real `.env`, credentials, personal messages or live database were inspected.

## Schema and migrations

The Alembic chain is linear:

| Revision | Existing responsibility |
| --- | --- |
| 0001 | Legacy users baseline. |
| 0002 | Connected accounts, OAuth attempts, explicit encryption/import of legacy credentials. |
| 0003 | Threads, messages, labels, mappings, attachments, sync jobs, audit logs and tenant constraints. |
| 0004 | Persist requested OAuth scopes. |
| 0005 | Durable job dispatch, active-account uniqueness, worker leases and account scheduling. |
| 0006 | Stored conversation AI suggestions. |
| 0007 | Watch-renewal scheduling. |
| 0008 | Message triage and recovery state. |
| 0009 | Resumable **full-mailbox** import and automatic backfill of existing accounts. |

Account credentials, sync cursors and watch state currently share
`connected_accounts`. Missing specification entities include login identities,
revocable user sessions, historical sync sessions, durable push-event records,
send jobs and local draft/send workflow records. Mybox has a narrower job/result
model than the proposed versioned, independent AI task model. Existing audit and
sync-job tables are useful equivalents; do not introduce duplicate outbox tables
without a transactional need.

Models use legacy `Column`/`db.query` declarations, signed `Integer` primary keys,
and epoch-millisecond message dates. These work with the installed SQLAlchemy 2
dependency but differ from the requested typed conventions and unsigned BIGINT
schema. Composite tenant constraints and existing indexes must survive any change.
Do not rewrite revisions 0001–0009 or rename existing tables to match examples.

## Architectural conflicts and gaps

1. **Login identity and connected mailbox are conflated (Phase 1 blocker).**
   `google_login/routes.py` looks up or creates the application user from the
   callback email. `accounts.find_account` matches both owner ID and the owner's
   email; `save_connection` creates a mailbox using that same email. OAuth state
   contains no initiating user, session, connection purpose or reconnect target.
   Connecting another Google account therefore signs into another application
   identity instead of attaching a mailbox to the existing user. There is no
   stored stable Google `sub`. The UI selectors and account-scoped services can
   be preserved, but the connection lifecycle must change.

2. **Sync imports all history automatically (direct specification conflict).**
   `mail_sync/service.reconciliation_messages` lists without a date query and
   includes Spam/Trash. `jobs.process_job` immediately queues continuation pages;
   migration 0009 also makes existing accounts eligible for automatic backfill.
   Incremental processing requires `mail_import_complete`, so a long import can
   delay independent new-message updates. There is no per-account initial window,
   historical session or local-exhaustion workflow. Preserve cached old messages,
   but replace automatic full backfill with a 30-day configurable initial import
   and explicit resumable historical sessions in Phase 3. A limited scan must
   never run the current full-listing stale-message deletion sweep.

3. **Sending has no durable ambiguity/reconciliation model.**
   Compose, reply and draft sends call Gmail in the request path. Errors tell the
   user to check Sent and avoid automatic retries, which is valuable, but there
   is no persisted `unknown` outcome, operation idempotency key or reconciliation
   worker. Keep review/undo behavior and add durable send intent and status;
   reconcile ambiguous acceptance before any retry. Gmail-backed drafts already
   exist and should retain their provider IDs and content-hash conflict checks.

4. **Authenticated push is not a durable event inbox.**
   `push.parse_push` validates `messageId` but returns only email and history ID.
   `accept_notification` coalesces work into sync jobs; it does not persist the
   notification or deduplicate by Pub/Sub message ID. Preserve current verification
   and coalescing while adding durable event acceptance and processing status.

5. **AI isolation is only partially complete.**
   `mailbox/categories.py` correctly uses `CATEGORY_PERSONAL` and rejects other,
   missing or conflicting categories and Spam/Trash/Sent/Drafts. Retain this.
   Automatic triage is asynchronous, but `context_service.generate` invokes the
   model during the HTTP request. Move conversation tasks behind durable,
   versioned AI jobs; summary, actions and reply generation need independent
   retry/idempotency policies and thread-version invalidation.

6. **Queues share execution capacity.**
   `gmail-sync`, `gmail-maintenance` and `gmail-ai` are logical queues consumed by
   one worker with concurrency 2. Two slow AI tasks can occupy that capacity;
   there is no send queue. Reserve sync capacity through separate worker processes
   when adding AI/send jobs. Changing Compose service counts also requires changing
   deployment scripts, health checks and CI assertions that currently require
   exactly four backend services. Separate frontend hosting and external MySQL
   are sound production equivalents; add a reproducible full local stack without
   replacing existing production infrastructure.

7. **Gmail integration boundary is incomplete.**
   A shared client and MIME parser exist, but sync, actions, drafts, watch and
   thread services construct raw Gmail resource requests. Introduce a typed
   adapter interface and deterministic fake behind the working client. Existing
   resource-shaped test fakes and representative MIME fixtures are a good start.

8. **Security and operations need additional work.**
   CORS currently allows `*`; JWTs have no persisted revocable session lifecycle.
   Credentials have no explicit key-version metadata and share account rows.
   Audit coverage is incomplete for connection lifecycle and sends. Retry policy
   has bounded jitter and reason-aware 403 handling, but does not honor
   `Retry-After`; a provider 401 is not uniformly refreshed once and retried.
   Structured request/task correlation, metrics, diagnostics, tested restoration,
   and sensitive-route throttling need completion. Address session/CORS changes
   with Phase 1 rather than deferring those foundations to production hardening.

9. **API coverage is partial, not absent.**
   Existing `/messages`, `/sync`, `/sync-jobs` and webhook URLs differ from the
   sample API. Add required contracts and historical/session status responses
   without removing working routes or changing registered Google callbacks.
   Local substring search currently covers cached mail only; do not represent it
   as a complete Gmail search. Gmail label mutation/management, application-only
   labels, classifications with provenance and thread-list APIs need a complete
   endpoint inventory during their relevant phases.

10. **Existing documentation has competing authority.**
    The backend README calls an external Linear document canonical and describes
    full-mailbox import as desired behavior. The supplied specification now
    controls architecture. The full-import section remains an accurate description
    of current behavior until Phase 3 changes it; label it accordingly instead of
    claiming the requested behavior already exists.

## Proposed decisions

- Preserve the feature-oriented monolith, Gmail-backed drafts, current routes,
  UI behavior, tenant foreign keys, tests and deployment protections.
- Keep application login separate from authenticated mailbox connection. Bind
  connection state to a persisted session, user, purpose and reconnect target;
  store verified provider subject IDs. A reconnect must not silently substitute
  another mailbox or change the application login.
- Proposed mailbox ownership policy: one Google subject belongs to one
  application user, matching today's globally unique mailbox email behavior.
  Confirm before implementing cross-user reassignment; no automatic transfers.
  Existing accounts need a staged subject backfill/reauthorization strategy;
  never synthesize subjects from email addresses.
- Preserve authenticated Fernet ciphertext during transition. The specification
  allows authenticated encryption and cites AES-GCM as an example; replacing
  working encryption is less urgent than separating credentials and adding key
  rotation metadata. Use versioned reads/writes and verify legacy decryption.
- Treat database name, table names, epoch dates and deployment topology as
  compatibility decisions. Assess any required BIGINT conversion against actual
  MySQL foreign keys and index limits in a separate migration step.
- Do not purge older cached mail when introducing recent-only sync. No live
  migration, deployment, provider permission expansion or external write is part
  of this inspection.

## Implementation sequence and gates

Each numbered phase is a separate reviewable change. Reuse working features and
report files, migrations, tests, commands, limitations and the next phase after
each. These are completion gates, not a proposal to scaffold the entire system.

| Phase | Scoped work | Required validation before completion |
| --- | --- | --- |
| 1 — Foundation/accounts | Separate login from connect/reconnect; subject identity and explicit ownership; session lifecycle; user/session-bound state; encrypted credential separation and migration compatibility; restrict CORS; adapt existing account controls as needed. | One user connects two distinct fake Gmail accounts without changing application identity; another user cannot list/read/mutate them; wrong-session, replay, expired-state and wrong-mailbox reconnect tests; no OAuth secrets in responses/logs; clean and existing-data migration tests. |
| 2 — Database/adapter | Typed Gmail adapter and fake; retain parser/upserts; fill schema/index/provenance gaps; adopt SQLAlchemy 2 typed conventions incrementally rather than mass rewriting working modules. | Repeated provider IDs deduplicate per account and can repeat across accounts; tenant FK rejection, label/thread/MIME fixtures, clean migrations and MySQL integration checks. |
| 3 — Initial/history | Per-account default 30-day window, independent incremental baseline, durable resumable history sessions, protected continuation tokens, progress counters and local-exhaustion API/UI. Replace automatic full backfill with non-destructive transition. | Date cutoff asserted in fake-provider calls; no autonomous older-page fetch; restart and duplicate-request recovery; no cursor regression, newer-label overwrite or cached-history deletion; incremental updates continue during backfill. |
| 4 — Incremental/push | Durable deduplicated push inbox; transactional dispatch; retain authenticated webhook, watch renewal and history logic; bounded repair after cursor expiry and observable renewal failures. | Duplicate/out-of-order pushes, commit/publish failure, worker loss, missed push reconciliation, history 404 and persisted cursor atomicity tests. |
| 5 — Client/send | Fill client/label/search gaps; retain draft/reply/attachment behavior; durable send intent/status, send queue and unknown-outcome reconciliation with explicit review preserved. | Provider/local reconciliation, MIME threading and draft conflicts; duplicate submits and accepted-send timeouts; unknown sends never blindly retried; browser flow coverage. |
| 6 — AI | Keep strict Primary eligibility and Mybox behavior; durable independent summary/action/importance/reply tasks, versioned idempotency, bounded context and job status UI. Reserve worker capacity. | Excluded/unclassified mail never reaches the model; AI failures cannot block sync; repeated events/model versions behave correctly; no send or mailbox mutation without user action. |
| 7 — Hardening | Complete structured logs/metrics, diagnostics, rate limits, backup/restore drills, secrets rotation, load checks and reproducible deployment documentation. Coordinate worker topology with CI/deployment tests. | Disposable MySQL restore and migration rehearsal, measured sync/AI contention, account-isolation suite, secret-redaction checks and safe failed-deployment recovery. |

Before provider-specific implementation, verify the relevant behavior against
the specification's official Google references. Before a frontend implementation,
apply the repository's modern-web-guidance skill. Neither is needed to change
application behavior during this documentation-only phase.

## Phase 0 validation and handoff

Inspected frontend/backend feature source, package manifests, configuration example,
all migration responsibilities, representative regression fixtures, local/production
Compose, both CI workflows and backend deployment sequencing. No AGENTS.md was
found in the repository. This is a source and isolated-test review, not proof of
live Gmail, production database, browser or infrastructure behavior.

- Backend: **171 tests passed** using `backend/myenv/Scripts/python.exe`, with
  `DATABASE_URL=sqlite://` and a fake Groq key. This includes isolated Alembic
  migration tests; the configured application database was not migrated.
- Frontend: **10 unit tests passed** (`apiUrl.test.mjs`, `emailLayout.test.mjs`).
- Deployment database preflight: **4 tests passed** when rerun with the project
  Python environment; these tests use isolated fakes, not the live database.
- Initial system-Python attempt could not import backend dependencies; the
  existing project environment resolved the backend run.
- Deployment sequencing tests invoked from system Python were not a valid green
  baseline: dependencies were missing and Windows resolved Bash to an unavailable
  WSL `/bin/bash`. These failures do not establish deployment-script defects.
  Linux CI remains the authoritative environment for shell sequencing checks.
- No browser suite, live provider calls, production migration or deployment run.
- No feature tests were added because Phase 0 changes documentation only.

Reproduce the backend baseline from the repository root in PowerShell:

```powershell
$env:DATABASE_URL = 'sqlite://'
$env:GROQ_API_KEY = 'test-not-real'
Push-Location backend
try { .\myenv\Scripts\python.exe -m unittest discover -s tests -v }
finally { Pop-Location }
node --test frontend/tests/apiUrl.test.mjs frontend/tests/emailLayout.test.mjs
```

Use an environment installed from `backend/requirements.txt` if `myenv` is absent.
Deployment tests should run with backend dependencies and a working POSIX Bash:
`python -m unittest discover -s .github/tests -v`.

Phase 0 changes: this review, the root README navigation, and backend README
architecture authority/current-import clarification. No application code, schema,
configuration or workflow changes. Next phase: **Phase 1 — foundation and accounts**.
