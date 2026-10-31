# Custom Gmail Application --- Architecture & Implementation Specification

**Document purpose:** This document is the implementation contract for
Codex. Use it as the source of truth when inspecting, designing,
implementing, testing, and documenting the custom mail application.

**Status:** Proposed architecture\
**Backend:** Python + FastAPI\
**Frontend:** React\
**Database:** MySQL 8\
**ORM / migrations:** SQLAlchemy 2.x + Alembic\
**Background jobs:** Celery\
**Broker / cache:** Redis\
**Email provider:** Gmail API\
**Authentication:** Google OAuth 2.0\
**Deployment:** Docker Compose

------------------------------------------------------------------------

## 1. Product goals

Build a web-based email client that connects multiple Gmail accounts to
one application user.

The application must:

1.  Allow one application user to connect multiple Gmail accounts.
2.  Keep all data isolated by application user and Gmail account.
3.  Use Gmail as the authoritative source for mailbox state.
4.  Maintain a local MySQL representation for fast inbox access and
    application features.
5.  Import a limited recent window when an account is first connected.
6.  Retrieve older email history only when the user requests it.
7.  Keep already imported messages current using Gmail incremental
    synchronization.
8.  Show all relevant mailbox categories in the application.
9.  Route only Primary emails into the AI processing pipeline by
    default.
10. Support reading, searching, composing, replying, drafting, sending,
    archiving, starring, and label operations.
11. Handle retries, interrupted jobs, duplicate notifications, token
    expiration, and partial failures safely.

### Non-goals for the first release

-   Building an SMTP server.
-   Replacing Gmail as the system of record.
-   Implementing microservices.
-   Importing every historical email immediately on account connection.
-   Downloading every attachment automatically.
-   Processing Promotions, Social, Updates, Forums, or Spam through AI
    by default.
-   Implementing a custom mail protocol or IMAP server.

------------------------------------------------------------------------

## 2. Core architectural decisions

### 2.1 Architecture style

Use a **modular monolith** for the API and separate Celery worker
processes for asynchronous work.

Keep domain boundaries explicit in the codebase:

-   Users and application authentication
-   Connected Gmail accounts and OAuth
-   Gmail API integration
-   Email and thread management
-   Synchronization
-   Labels and user organization
-   Drafts and sending
-   AI processing
-   Notifications
-   Audit and operational tooling

Do not split these into separately deployed microservices during the
initial implementation.

### 2.2 Source of truth

Gmail is authoritative for provider-owned data:

-   Message existence
-   Gmail message and thread identifiers
-   Gmail labels
-   Read/unread state
-   Starred state
-   Archive state
-   Spam and trash state
-   Sent messages
-   Gmail drafts, if synchronized

MySQL is the local application read model and stores:

-   Synchronized message metadata and bodies
-   Local thread representation
-   Gmail label snapshots and mappings
-   Sync cursors and job state
-   AI classifications and generated results
-   Application-only preferences and labels
-   Drafts and send-job state
-   Audit and operational records

Do not silently treat local state as authoritative when Gmail is the
source of truth. For user actions, call Gmail and reconcile the response
into MySQL. Optimistic UI updates are allowed, but they must be
reversible if the provider operation fails.

### 2.3 Multi-account isolation

The ownership hierarchy is:

`users -> gmail_accounts -> email_threads -> emails`

Every account-owned query must be scoped by:

-   Authenticated application user ID
-   Selected Gmail account ID

Never trust an `account_id` supplied by the browser without verifying
that the authenticated user owns it.

Use internal numeric primary keys. Store Gmail identifiers as strings.
Gmail identifiers are scoped to a mailbox; therefore, uniqueness
constraints must include `account_id`.

### 2.4 Initial sync and on-demand history

Recommended initial import: last **30 days** of relevant mailbox
messages. Make this configurable per account.

When the user requests older messages, fetch additional pages from Gmail
and persist them locally. Do not download the complete mailbox at
connection time.

New changes to an already connected mailbox must be synchronized
independently of historical backfill. On-demand historical sync does not
mean new-message sync is on demand.

### 2.5 AI boundary

Email synchronization must never wait for an LLM response.

The sync worker persists the email first. A separate routing step
determines whether the email is eligible for AI processing. Only
eligible Primary messages are queued.

Use Gmail's system category label `CATEGORY_PERSONAL` as the provider
signal for Primary. Other known category labels include:

-   `CATEGORY_PROMOTIONS`
-   `CATEGORY_SOCIAL`
-   `CATEGORY_UPDATES`
-   `CATEGORY_FORUMS`

Do not invent a Gmail system label named `CATEGORY_PRIMARY`. If Gmail
category labels are absent or ambiguous, use an explicit fallback
classification policy and record the classification source and
confidence. Do not automatically classify every message without a
category label as Primary.

------------------------------------------------------------------------

## 3. High-level system architecture

``` text
                         +----------------------+
                         |      React UI        |
                         | Inbox / Threads / AI |
                         +----------+-----------+
                                    |
                                    | HTTPS REST
                                    v
                         +----------------------+
                         |     FastAPI API      |
                         | Auth / Authorization|
                         +----------+-----------+
                                    |
                +-------------------+-------------------+
                |                   |                   |
                v                   v                   v
        +---------------+   +---------------+   +---------------+
        | Email Domain  |   | Account/OAuth |   | AI Domain     |
        | Threads       |   | Gmail Client  |   | Routing       |
        | Labels        |   | Token Manager |   | Results       |
        | Drafts/Send   |   | Sync Services  |   | Reply/Summary |
        +-------+-------+   +-------+-------+   +-------+-------+
                |                   |                   |
                +-------------------+-------------------+
                                    |
                     +--------------+--------------+
                     |                             |
                     v                             v
              +-------------+                +-------------+
              |   MySQL     |                |    Redis    |
              | Local data  |                | Broker/cache|
              +-------------+                +------+------+
                                                     |
                                                     v
                                              +-------------+
                                              | Celery      |
                                              | Workers     |
                                              +------+------+
                                                     |
                          +--------------------------+------------------+
                          |                          |                  |
                          v                          v                  v
                    +-----------+              +-----------+      +-----------+
                    | Gmail API |              | LLM API   |      | Pub/Sub   |
                    +-----------+              +-----------+      +-----------+
```

### Runtime processes

1.  **frontend** --- React development or production web application.
2.  **backend** --- FastAPI application and REST API.
3.  **celery-worker-sync** --- Gmail initial, historical, and
    incremental synchronization.
4.  **celery-worker-ai** --- Classification, summaries, action
    extraction, and reply generation.
5.  **celery-worker-send** --- Draft sending and provider-side
    operations where asynchronous execution is needed.
6.  **celery-beat** --- Scheduled watch renewal, reconciliation, and
    cleanup.
7.  **mysql** --- Persistent relational database.
8.  **redis** --- Celery broker and short-lived cache/locks.

Workers may initially share one Celery deployment, but queues should be
separated logically so sync work cannot be starved by slow AI tasks.

------------------------------------------------------------------------

## 4. Repository structure

Use this structure unless the existing repository already has a sound
equivalent. Inspect the existing project before moving or replacing
files. Preserve working code and conventions.

``` text
custom-mail/
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   ├── components/
│   │   ├── features/
│   │   │   ├── accounts/
│   │   │   ├── inbox/
│   │   │   ├── email-viewer/
│   │   │   ├── threads/
│   │   │   ├── drafts/
│   │   │   ├── search/
│   │   │   ├── categories/
│   │   │   ├── attachments/
│   │   │   ├── ai-assistant/
│   │   │   └── settings/
│   │   ├── hooks/
│   │   ├── services/
│   │   ├── store/
│   │   ├── types/
│   │   └── utils/
│   ├── Dockerfile
│   └── package.json
│
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── api/
│   │   │   └── router.py
│   │   ├── core/
│   │   │   ├── config.py
│   │   │   ├── database.py
│   │   │   ├── security.py
│   │   │   ├── encryption.py
│   │   │   ├── logging.py
│   │   │   └── dependencies.py
│   │   ├── modules/
│   │   │   ├── users/
│   │   │   ├── accounts/
│   │   │   ├── oauth/
│   │   │   ├── emails/
│   │   │   ├── threads/
│   │   │   ├── labels/
│   │   │   ├── attachments/
│   │   │   ├── drafts/
│   │   │   ├── sending/
│   │   │   ├── search/
│   │   │   ├── sync/
│   │   │   ├── ai/
│   │   │   ├── notifications/
│   │   │   └── audit/
│   │   ├── integrations/
│   │   │   ├── gmail/
│   │   │   │   ├── client.py
│   │   │   │   ├── oauth.py
│   │   │   │   ├── messages.py
│   │   │   │   ├── threads.py
│   │   │   │   ├── labels.py
│   │   │   │   ├── history.py
│   │   │   │   └── watch.py
│   │   │   └── llm/
│   │   │       ├── client.py
│   │   │       └── prompts.py
│   │   ├── workers/
│   │   │   ├── celery_app.py
│   │   │   ├── sync_tasks.py
│   │   │   ├── historical_sync_tasks.py
│   │   │   ├── incremental_sync_tasks.py
│   │   │   ├── ai_tasks.py
│   │   │   ├── send_tasks.py
│   │   │   ├── watch_tasks.py
│   │   │   └── maintenance_tasks.py
│   │   └── shared/
│   │       ├── enums.py
│   │       ├── exceptions.py
│   │       └── utils.py
│   ├── migrations/
│   ├── tests/
│   │   ├── unit/
│   │   ├── integration/
│   │   └── contract/
│   ├── Dockerfile
│   └── requirements.txt
│
├── infra/
│   └── docker/
├── docker-compose.yml
├── .env.example
├── .gitignore
└── README.md
```

Each business module should normally contain:

``` text
module/
├── router.py       # HTTP endpoints only
├── schemas.py      # Pydantic request/response models
├── models.py       # SQLAlchemy ORM models, if owned here
├── repository.py   # Database access
└── service.py      # Business logic
```

Keep provider-specific Gmail API request/response handling in
`integrations/gmail`. Business services should depend on an integration
interface, not construct raw Gmail API requests everywhere.

------------------------------------------------------------------------

## 5. Database design

Database name: `custom_mail`

Use InnoDB, `utf8mb4`, UTC timestamps, foreign keys, and Alembic
migrations. Prefer `DATETIME(6)` for timestamps if microsecond precision
is useful. Store timestamps in UTC and convert only at the presentation
boundary.

### 5.1 Entity relationship overview

``` mermaid
erDiagram
    USERS ||--o{ GMAIL_ACCOUNTS : connects
    GMAIL_ACCOUNTS ||--|| OAUTH_CREDENTIALS : authenticates
    GMAIL_ACCOUNTS ||--|| GMAIL_SYNC_STATES : tracks
    GMAIL_ACCOUNTS ||--o{ SYNC_JOBS : runs
    GMAIL_ACCOUNTS ||--o{ EMAIL_THREADS : owns
    EMAIL_THREADS ||--o{ EMAILS : contains
    EMAILS ||--o{ EMAIL_HEADERS : has
    EMAILS ||--o{ EMAIL_ATTACHMENTS : has
    GMAIL_ACCOUNTS ||--o{ GMAIL_LABELS : defines
    EMAILS ||--o{ EMAIL_LABEL_MAPPING : assigned
    GMAIL_LABELS ||--o{ EMAIL_LABEL_MAPPING : maps
    USERS ||--o{ USER_LABELS : creates
    USERS ||--o{ EMAIL_USER_STATES : configures
    EMAILS ||--o| EMAIL_CLASSIFICATIONS : classified
    EMAILS ||--o{ AI_PROCESSING_JOBS : processed
    EMAILS ||--o{ EMAIL_AI_RESULTS : produces
    GMAIL_ACCOUNTS ||--o{ EMAIL_DRAFTS : owns
    EMAIL_DRAFTS ||--o{ EMAIL_SEND_JOBS : sends
    GMAIL_ACCOUNTS ||--o{ GMAIL_PUSH_EVENTS : receives
```

### 5.2 Common conventions

-   Primary keys: `BIGINT UNSIGNED AUTO_INCREMENT`.
-   Foreign keys: same type as referenced primary key.
-   Gmail IDs and history IDs: `VARCHAR`, never integer.
-   Email addresses: `VARCHAR(320)`.
-   Message body: `LONGTEXT` initially; object storage can be introduced
    later.
-   Flexible provider metadata: `JSON`, but do not put frequently
    queried relational data only inside JSON.
-   Every account-owned table should include `account_id` directly where
    practical to simplify tenant scoping and indexing.
-   Add unique constraints that include `account_id`.
-   Use soft-delete or tombstone fields only where their semantics are
    explicit. Do not confuse a locally hidden message with a
    Gmail-deleted message.

### 5.3 Tables

#### `users`

Application identities.

  Column          Type              Constraints / purpose
  --------------- ----------------- -----------------------------
  id              BIGINT UNSIGNED   PK
  email           VARCHAR(255)      UNIQUE, NOT NULL
  password_hash   VARCHAR(255)      NULL if external login only
  full_name       VARCHAR(150)      NULL
  is_active       BOOLEAN           NOT NULL DEFAULT TRUE
  created_at      DATETIME(6)       NOT NULL
  updated_at      DATETIME(6)       NOT NULL

If Google is also used to sign into the application, model application
login identities separately from connected Gmail mailboxes. Do not
assume the login Google account and a connected mailbox are necessarily
the same identity.

#### `gmail_accounts`

One row per connected Gmail mailbox.

  Column            Type              Constraints / purpose
  ----------------- ----------------- ----------------------------------------------
  id                BIGINT UNSIGNED   PK
  user_id           BIGINT UNSIGNED   FK users.id, NOT NULL
  google_sub        VARCHAR(255)      Stable Google account subject
  gmail_address     VARCHAR(320)      NOT NULL
  display_name      VARCHAR(255)      NULL
  status            VARCHAR(30)       active, disconnected, reauth_required, error
  sync_enabled      BOOLEAN           DEFAULT TRUE
  connected_at      DATETIME(6)       NOT NULL
  disconnected_at   DATETIME(6)       NULL
  created_at        DATETIME(6)       NOT NULL
  updated_at        DATETIME(6)       NOT NULL

Constraints:

-   UNIQUE `(user_id, google_sub)`
-   INDEX `(user_id, status)`

Do not make `gmail_address` the primary key. Decide explicitly whether
the product permits the same Google identity to be connected by more
than one application user. If not, add a global uniqueness rule on
`google_sub`; otherwise enforce ownership according to product policy.

#### `oauth_credentials`

Keep secrets separate from general account metadata.

  Column                     Type              Constraints / purpose
  -------------------------- ----------------- -----------------------------
  id                         BIGINT UNSIGNED   PK
  account_id                 BIGINT UNSIGNED   UNIQUE FK gmail_accounts.id
  access_token_ciphertext    BLOB              Encrypted
  refresh_token_ciphertext   BLOB              Encrypted
  token_expires_at           DATETIME(6)       NULL
  scopes                     JSON              Granted scopes
  encryption_key_version     VARCHAR(50)       Key rotation metadata
  updated_at                 DATETIME(6)       NOT NULL

Security:

-   Use authenticated encryption such as AES-256-GCM.
-   Prefer envelope encryption backed by a managed KMS in production.
-   Never send tokens to React.
-   Never log tokens, authorization headers, OAuth codes, or secrets.
-   Handle refresh-token rotation safely.
-   Do not overwrite a stored refresh token with null if a refresh
    response omits a new refresh token.
-   Restrict database access to the backend and worker identities that
    need it.

#### `gmail_sync_states`

One row per Gmail account.

  Column                    Type              Constraints / purpose
  ------------------------- ----------------- -------------------------------------
  id                        BIGINT UNSIGNED   PK
  account_id                BIGINT UNSIGNED   UNIQUE FK gmail_accounts.id
  history_id                VARCHAR(100)      Last committed Gmail history cursor
  initial_sync_completed    BOOLEAN           DEFAULT FALSE
  initial_sync_started_at   DATETIME(6)       NULL
  last_synced_at            DATETIME(6)       NULL
  last_push_received_at     DATETIME(6)       NULL
  sync_status               VARCHAR(30)       idle, running, failed
  last_error_code           VARCHAR(100)      NULL
  last_error_message        TEXT              NULL
  updated_at                DATETIME(6)       NOT NULL

Treat `history_id` as an opaque string. Advance the cursor only after
all changes up to that cursor have been safely persisted. Use a
transaction or a carefully designed checkpoint strategy so a failed
batch cannot cause changes to be skipped.

#### `sync_jobs`

Operational record of sync requests.

  -----------------------------------------------------------------------
  Column                  Type                    Constraints / purpose
  ----------------------- ----------------------- -----------------------
  id                      BIGINT UNSIGNED         PK

  account_id              BIGINT UNSIGNED         FK gmail_accounts.id

  requested_by_user_id    BIGINT UNSIGNED         FK users.id, NULL for
                                                  system jobs

  job_type                VARCHAR(30)             initial, incremental,
                                                  historical, repair

  status                  VARCHAR(30)             pending, running,
                                                  completed, failed,
                                                  cancelled

  idempotency_key         VARCHAR(150)            UNIQUE or scoped unique

  messages_seen           INT UNSIGNED            DEFAULT 0

  messages_inserted       INT UNSIGNED            DEFAULT 0

  messages_updated        INT UNSIGNED            DEFAULT 0

  started_at              DATETIME(6)             NULL

  completed_at            DATETIME(6)             NULL

  error_code              VARCHAR(100)            NULL

  error_message           TEXT                    NULL

  created_at              DATETIME(6)             NOT NULL
  -----------------------------------------------------------------------

Use account-scoped idempotency keys if the key is not globally unique.

#### `sync_sessions`

Tracks a user-initiated historical backfill session.

  Column                  Type              Constraints / purpose
  ----------------------- ----------------- ------------------------------------
  id                      BIGINT UNSIGNED   PK
  account_id              BIGINT UNSIGNED   FK gmail_accounts.id
  sync_job_id             BIGINT UNSIGNED   FK sync_jobs.id
  query_type              VARCHAR(40)       inbox, all_mail, sent, label
  query_value             VARCHAR(255)      NULL
  page_token_ciphertext   BLOB              NULL; protect opaque token
  next_before_date        DATETIME(6)       NULL
  status                  VARCHAR(30)       active, completed, expired, failed
  expires_at              DATETIME(6)       NOT NULL
  created_at              DATETIME(6)       NOT NULL
  updated_at              DATETIME(6)       NOT NULL

Never expose Gmail page tokens directly to the browser. Return an
application-generated opaque cursor or session ID. Validate ownership on
every continuation request.

#### `gmail_push_events`

Deduplicated Pub/Sub event inbox.

  -----------------------------------------------------------------------
  Column                  Type                    Constraints / purpose
  ----------------------- ----------------------- -----------------------
  id                      BIGINT UNSIGNED         PK

  account_id              BIGINT UNSIGNED         FK gmail_accounts.id,
                                                  nullable until resolved

  pubsub_message_id       VARCHAR(255)            UNIQUE

  history_id              VARCHAR(100)            NOT NULL

  received_at             DATETIME(6)             NOT NULL

  processed_at            DATETIME(6)             NULL

  status                  VARCHAR(30)             pending, processed,
                                                  failed

  error_message           TEXT                    NULL
  -----------------------------------------------------------------------

Acknowledge Pub/Sub only after the event has been durably accepted into
the application. Event handling must be idempotent.

#### `email_threads`

One local row per Gmail thread per account.

  Column            Type              Constraints / purpose
  ----------------- ----------------- -----------------------
  id                BIGINT UNSIGNED   PK
  account_id        BIGINT UNSIGNED   FK gmail_accounts.id
  gmail_thread_id   VARCHAR(255)      NOT NULL
  subject           VARCHAR(998)      NULL
  snippet           TEXT              NULL
  last_message_at   DATETIME(6)       NULL
  message_count     INT UNSIGNED      DEFAULT 0
  created_at        DATETIME(6)       NOT NULL
  updated_at        DATETIME(6)       NOT NULL

Constraints:

-   UNIQUE `(account_id, gmail_thread_id)`
-   INDEX `(account_id, last_message_at, id)`

#### `emails`

One row per Gmail message.

  Column             Type              Constraints / purpose
  ------------------ ----------------- -----------------------
  id                 BIGINT UNSIGNED   PK
  account_id         BIGINT UNSIGNED   FK gmail_accounts.id
  thread_id          BIGINT UNSIGNED   FK email_threads.id
  gmail_message_id   VARCHAR(255)      NOT NULL
  gmail_history_id   VARCHAR(100)      NULL
  sender_email       VARCHAR(320)      NULL
  sender_name        VARCHAR(255)      NULL
  to_recipients      JSON              NOT NULL
  cc_recipients      JSON              NULL
  bcc_recipients     JSON              NULL
  subject            VARCHAR(998)      NULL
  snippet            TEXT              NULL
  body_text          LONGTEXT          NULL
  body_html          LONGTEXT          NULL
  internal_date      DATETIME(6)       NOT NULL
  size_estimate      BIGINT UNSIGNED   NULL
  is_deleted         BOOLEAN           DEFAULT FALSE
  imported_at        DATETIME(6)       NOT NULL
  updated_at         DATETIME(6)       NOT NULL

Constraints:

-   UNIQUE `(account_id, gmail_message_id)`
-   INDEX `(account_id, internal_date, id)`
-   INDEX `(thread_id, internal_date, id)`

Use Gmail `internalDate` for mailbox ordering. Parse MIME recursively
and handle multipart/alternative, multipart/mixed, transfer encodings,
and character sets. Sanitize HTML before rendering it in the browser. Do
not render email HTML as trusted application HTML.

#### `email_headers`

  Column         Type              Constraints / purpose
  -------------- ----------------- -----------------------
  id             BIGINT UNSIGNED   PK
  email_id       BIGINT UNSIGNED   FK emails.id
  header_name    VARCHAR(255)      NOT NULL
  header_value   TEXT              NOT NULL

Index `(email_id, header_name)`. Preserve headers needed for replies,
threading, list-unsubscribe, and diagnostics. Avoid logging sensitive
header values unnecessarily.

#### `email_attachments`

  Column                Type              Constraints / purpose
  --------------------- ----------------- ------------------------------------
  id                    BIGINT UNSIGNED   PK
  account_id            BIGINT UNSIGNED   FK gmail_accounts.id
  email_id              BIGINT UNSIGNED   FK emails.id
  gmail_attachment_id   VARCHAR(255)      NULL
  filename              VARCHAR(500)      NULL
  mime_type             VARCHAR(255)      NULL
  size_bytes            BIGINT UNSIGNED   NULL
  storage_path          TEXT              NULL
  download_status       VARCHAR(30)       not_downloaded, downloaded, failed
  created_at            DATETIME(6)       NOT NULL

Store attachment metadata first. Download bytes on demand or when a
feature explicitly requires them. Validate file types and sizes, and
never trust the filename or MIME type supplied by an email.

#### `gmail_labels`

  Column                    Type              Constraints / purpose
  ------------------------- ----------------- -----------------------
  id                        BIGINT UNSIGNED   PK
  account_id                BIGINT UNSIGNED   FK gmail_accounts.id
  gmail_label_id            VARCHAR(255)      NOT NULL
  name                      VARCHAR(255)      NOT NULL
  label_type                VARCHAR(30)       system, user
  label_list_visibility     VARCHAR(50)       NULL
  message_list_visibility   VARCHAR(50)       NULL
  updated_at                DATETIME(6)       NOT NULL

Constraint UNIQUE `(account_id, gmail_label_id)`.

#### `email_label_mapping`

  Column       Type              Constraints / purpose
  ------------ ----------------- -----------------------
  email_id     BIGINT UNSIGNED   FK emails.id
  label_id     BIGINT UNSIGNED   FK gmail_labels.id
  created_at   DATETIME(6)       NOT NULL

Composite primary key `(email_id, label_id)`. Add index
`(label_id, email_id)`. Ensure the email and label belong to the same
Gmail account in service validation or through additional database
constraints where feasible.

#### `user_labels`

Application-only labels. These must not be confused with Gmail labels.

  Column       Type              Constraints / purpose
  ------------ ----------------- -----------------------
  id           BIGINT UNSIGNED   PK
  user_id      BIGINT UNSIGNED   FK users.id
  name         VARCHAR(100)      NOT NULL
  color        VARCHAR(20)       NULL
  created_at   DATETIME(6)       NOT NULL

Constraint UNIQUE `(user_id, name)`.

#### `email_user_states`

Application-only state. Provider-owned state such as read, starred, and
archived should normally be derived from Gmail labels.

  Column            Type              Constraints / purpose
  ----------------- ----------------- -----------------------
  id                BIGINT UNSIGNED   PK
  user_id           BIGINT UNSIGNED   FK users.id
  account_id        BIGINT UNSIGNED   FK gmail_accounts.id
  email_id          BIGINT UNSIGNED   FK emails.id
  is_pinned         BOOLEAN           DEFAULT FALSE
  is_hidden         BOOLEAN           DEFAULT FALSE
  custom_category   VARCHAR(50)       NULL
  updated_at        DATETIME(6)       NOT NULL

Constraint UNIQUE `(user_id, email_id)`. Validate that user owns the
account and email.

#### `email_classifications`

  Column          Type              Constraints / purpose
  --------------- ----------------- ------------------------
  id              BIGINT UNSIGNED   PK
  email_id        BIGINT UNSIGNED   UNIQUE FK emails.id
  category        VARCHAR(50)       NOT NULL
  confidence      DECIMAL(5,4)      NULL
  source          VARCHAR(30)       gmail, rules, ai, user
  model_name      VARCHAR(150)      NULL
  classified_at   DATETIME(6)       NOT NULL

Keep provider category labels and AI classification distinct. Preserve
the source so the UI and routing logic can explain why a message was
categorized.

#### `email_ai_results`

  Column           Type              Constraints / purpose
  ---------------- ----------------- ------------------------------------------
  id               BIGINT UNSIGNED   PK
  email_id         BIGINT UNSIGNED   FK emails.id
  result_type      VARCHAR(50)       summary, action_items, importance, reply
  result_json      JSON              NOT NULL
  model_name       VARCHAR(150)      NULL
  prompt_version   VARCHAR(50)       NULL
  created_at       DATETIME(6)       NOT NULL

Index `(email_id, result_type, created_at)`. Consider retaining multiple
versions for auditability and model upgrades.

#### `ai_processing_jobs`

  -----------------------------------------------------------------------
  Column                  Type                    Constraints / purpose
  ----------------------- ----------------------- -----------------------
  id                      BIGINT UNSIGNED         PK

  account_id              BIGINT UNSIGNED         FK gmail_accounts.id

  email_id                BIGINT UNSIGNED         FK emails.id

  task_type               VARCHAR(50)             NOT NULL

  status                  VARCHAR(30)             pending, processing,
                                                  completed, failed,
                                                  skipped

  attempts                INT UNSIGNED            DEFAULT 0

  idempotency_key         VARCHAR(200)            UNIQUE

  error_message           TEXT                    NULL

  created_at              DATETIME(6)             NOT NULL

  completed_at            DATETIME(6)             NULL
  -----------------------------------------------------------------------

Use a defined retry policy and record failure reason. A repeated Gmail
notification must not enqueue duplicate AI work for the same email and
task version.

#### `email_drafts`

  Column           Type              Constraints / purpose
  ---------------- ----------------- --------------------------------------
  id               BIGINT UNSIGNED   PK
  user_id          BIGINT UNSIGNED   FK users.id
  account_id       BIGINT UNSIGNED   FK gmail_accounts.id
  gmail_draft_id   VARCHAR(255)      NULL
  thread_id        BIGINT UNSIGNED   NULL FK email_threads.id
  to_recipients    JSON              NOT NULL
  cc_recipients    JSON              NULL
  bcc_recipients   JSON              NULL
  subject          VARCHAR(998)      NULL
  body_text        LONGTEXT          NULL
  body_html        LONGTEXT          NULL
  status           VARCHAR(30)       local, synced, sending, sent, failed
  created_at       DATETIME(6)       NOT NULL
  updated_at       DATETIME(6)       NOT NULL

Decide whether drafts are local-only or synchronized with Gmail drafts.
If synchronized, retain Gmail draft IDs and reconcile changes.

#### `email_send_jobs`

  Column             Type              Constraints / purpose
  ------------------ ----------------- --------------------------------------------
  id                 BIGINT UNSIGNED   PK
  account_id         BIGINT UNSIGNED   FK gmail_accounts.id
  draft_id           BIGINT UNSIGNED   NULL FK email_drafts.id
  idempotency_key    VARCHAR(100)      UNIQUE
  status             VARCHAR(30)       pending, processing, sent, failed, unknown
  gmail_message_id   VARCHAR(255)      NULL
  attempts           INT UNSIGNED      DEFAULT 0
  last_error         TEXT              NULL
  created_at         DATETIME(6)       NOT NULL
  sent_at            DATETIME(6)       NULL

Do not blindly retry a send request after an ambiguous network timeout.
Gmail may have accepted the message even if the application did not
receive the response. Reconcile against Gmail before deciding whether to
retry.

#### Additional production tables

Add these as part of the implementation:

-   `user_sessions` --- application session lifecycle and revocation.
-   `audit_logs` --- account connection, disconnection, send actions,
    and sensitive operations.
-   `gmail_watch_subscriptions` --- topic name, watch expiration, last
    renewal, and renewal status.
-   `email_filter_rules` --- user-defined rules, if filters are included
    in the product.
-   `outbox_events` --- reliable dispatch of database-committed events
    to Celery or other workers.

Use an outbox pattern for important jobs: commit the business record and
an outbox event in the same MySQL transaction, then have a dispatcher
publish the event. This prevents a database commit succeeding while task
publication is lost.

------------------------------------------------------------------------

## 6. Gmail OAuth design

Use the server-side OAuth authorization-code flow.

### Connection flow

1.  Authenticated user chooses **Add Gmail account**.
2.  Backend creates a cryptographically random OAuth `state`, binds it
    to the user/session, and stores it with a short expiration.
3.  Backend redirects to Google's authorization endpoint.
4.  User grants consent.
5.  Google redirects to the backend callback with an authorization code
    and state.
6.  Backend validates state and exchanges the code server-side.
7.  Backend retrieves the stable Google identity and Gmail address.
8.  Backend creates or updates the connected account.
9.  Backend encrypts and stores credentials.
10. Backend creates a sync-state record.
11. Backend queues initial synchronization.
12. UI shows the account as connected and sync progress separately.

### Scopes

Request the smallest set of scopes that supports the product. For a
client that reads and modifies messages and sends mail, evaluate
`gmail.modify` and any additional scopes genuinely required. Do not
request the full-mail scope unless permanent deletion or another
capability requires it.

OAuth restricted-scope verification and security assessment requirements
must be evaluated before public production launch.

### Token handling

-   Request offline access where a refresh token is needed.
-   Store refresh tokens encrypted.
-   Refresh access tokens server-side.
-   Serialize refresh operations per account to avoid concurrent refresh
    races.
-   Preserve an existing refresh token if a refresh response does not
    return a new one.
-   On invalid/revoked refresh token, mark account `reauth_required`.
-   Do not delete mailbox data automatically when credentials are
    revoked.
-   Support explicit account disconnect and credential
    deletion/revocation according to the product's retention policy.

------------------------------------------------------------------------

## 7. Synchronization design

There are three separate sync workflows.

### 7.1 Initial synchronization

Default window: last 30 days. Make the window configurable.

1.  Create a sync job with type `initial`.
2.  Acquire a distributed lock for the Gmail account.
3.  Ensure valid OAuth credentials.
4.  Fetch Gmail labels and persist them.
5.  List messages in the chosen time window and required mailbox views.
6.  Retrieve message details with `messages.get`.
7.  Parse MIME content and headers.
8.  Upsert threads and messages.
9.  Upsert label mappings.
10. Store a valid Gmail history cursor.
11. Commit data and cursor safely.
12. Route eligible Primary messages to AI.
13. Mark the initial sync complete.
14. Release the lock.

Do not query only `INBOX` if the application promises to show Sent,
Drafts, Spam, Trash, or All Mail. Define exactly which Gmail system
labels and views are supported in the UI.

Use Gmail pagination and batch requests where supported and safe.
Respect API quotas and retry guidance.

### 7.2 Historical synchronization

Triggered when the user requests older messages.

1.  Frontend requests another page from the local inbox.
2.  Backend checks for locally cached older messages.
3.  If local data is exhausted, backend creates or resumes a
    `sync_session`.
4.  Worker calls Gmail `messages.list` with the saved page token or
    query boundary.
5.  Worker fetches full details for the returned messages.
6.  Worker upserts messages, threads, and labels.
7.  Worker saves the next page token and session progress.
8.  Frontend polls the session status or receives a push update.
9.  Newly persisted messages become available from the local API.

Requirements:

-   Page tokens are opaque and must be protected from client
    modification.
-   Expire abandoned sessions.
-   Use a per-account lock or controlled concurrency.
-   Avoid duplicate inserts using `(account_id, gmail_message_id)`.
-   Historical sync must not overwrite a newer incremental state with an
    older snapshot.
-   A thread may contain messages outside the requested date range;
    fetch missing thread messages only when needed by product behavior.
-   A historical sync failure must be resumable.

### 7.3 Incremental synchronization

Use Gmail `users.watch` and Google Cloud Pub/Sub for mailbox change
notifications.

1.  Register or renew Gmail watch for each connected account.
2.  Receive Pub/Sub notification.
3.  Validate the push request and persist the event.
4.  Deduplicate by Pub/Sub message ID.
5.  Resolve the account and enqueue an incremental sync.
6.  Acquire the account lock.
7.  Read the last committed `history_id`.
8.  Call Gmail `history.list` with that cursor.
9.  Process message additions, deletions, and label changes.
10. Fetch message details when required.
11. Update local records and label mappings.
12. Advance the cursor only after successful persistence.
13. Release the lock.

Handle Gmail history cursor expiration (HTTP 404) by scheduling a
repair/resynchronization workflow. Do not simply reset the cursor and
continue as if no changes were missed.

Watch subscriptions expire. Persist the returned expiration and renew
ahead of expiration; a daily renewal schedule is a sensible operational
default. Also run periodic reconciliation because push notifications may
be delayed or missed.

### 7.4 Sync concurrency and ordering

-   Use one distributed lock per Gmail account for operations that
    mutate its sync cursor.
-   Use a lock lease with renewal or a robust lock implementation.
-   Use database transactions for each persisted batch.
-   Make all upserts idempotent.
-   Do not let historical backfill advance the incremental history
    cursor.
-   Do not let an older historical response overwrite newer message
    label state without comparing source/version information.
-   Keep a sync job's progress counters accurate and monotonic.
-   Ensure a worker crash leaves a recoverable job state.

------------------------------------------------------------------------

## 8. Inbox and historical pagination API

Prefer cursor-based pagination over large OFFSET queries.

Example:

`GET /api/v1/accounts/{account_id}/emails?view=inbox&limit=30&cursor=<opaque-cursor>`

Response:

``` json
{
  "items": [],
  "next_cursor": "opaque-application-cursor",
  "has_more_local": true,
  "historical_sync": {
    "status": "idle",
    "session_id": null
  }
}
```

When the local cache has no more rows, the API may return a response
indicating that historical fetch has started:

``` json
{
  "items": [],
  "next_cursor": null,
  "has_more_local": false,
  "historical_sync": {
    "status": "pending",
    "session_id": "application-generated-session-id"
  }
}
```

Expose a status endpoint:

`GET /api/v1/accounts/{account_id}/sync/sessions/{session_id}`

Do not make the browser hold an HTTP request open while Gmail pages are
downloaded.

Use stable ordering such as `(internal_date DESC, id DESC)` and encode
both values in the opaque cursor.

------------------------------------------------------------------------

## 9. Email categories and AI processing

### Category routing

Persist Gmail labels before AI routing.

Default routing policy:

  -----------------------------------------------------------------------
  Gmail category label    UI category             AI by default
  ----------------------- ----------------------- -----------------------
  CATEGORY_PERSONAL       Primary                 Yes

  CATEGORY_PROMOTIONS     Promotions              No

  CATEGORY_SOCIAL         Social                  No

  CATEGORY_UPDATES        Updates                 No

  CATEGORY_FORUMS         Forums                  No

  SPAM                    Spam                    No

  TRASH                   Trash                   No

  No recognized category  Unclassified / fallback No until policy
                                                  resolves
  -----------------------------------------------------------------------

A user may explicitly change application classification or enable
processing for another category in settings. Keep that policy explicit
and auditable.

### AI task pipeline

``` text
Message persisted
       |
       v
Category routing
       |
       +---- Not eligible ----> Store only
       |
       v
Create idempotent AI job
       |
       v
Celery AI queue
       |
       +--> Summary
       +--> Action items
       +--> Importance
       +--> Optional semantic indexing
```

Use independent task types. A failure in summary generation must not
prevent action extraction from being retried.

For thread summaries, maintain a thread-level summary version and update
it when new messages arrive. Avoid resending the entire conversation to
the model unnecessarily.

AI output must be treated as untrusted generated content. Do not
automatically execute actions such as sending a reply, archiving,
deleting, or opening links without explicit user authorization.

------------------------------------------------------------------------

## 10. Gmail operations and local reconciliation

For provider-owned operations, call Gmail and reconcile the result.

  -----------------------------------------------------------------------
  User action             Gmail operation concept Local behavior
  ----------------------- ----------------------- -----------------------
  Mark read               Modify message labels;  Update label mapping
                          remove `UNREAD`         

  Mark unread             Modify message labels;  Update label mapping
                          add `UNREAD`            

  Star                    Add `STARRED`           Update label mapping

  Unstar                  Remove `STARRED`        Update label mapping

  Archive                 Remove `INBOX`          Update label mapping

  Move to spam            Add `SPAM`, remove      Update label mapping
                          `INBOX` as appropriate  

  Restore from spam       Remove `SPAM`, add      Update label mapping
                          `INBOX` as appropriate  

  Send                    Gmail `messages.send`   Store/reconcile sent
                                                  message

  Reply                   Send MIME message with  Reconcile sent message
                          correct thread headers  and thread

  Delete                  Use the intended Gmail  Update local state
                          trash/delete operation  after confirmation
  -----------------------------------------------------------------------

Use Gmail's thread semantics for replies. Construct valid MIME messages
and preserve `In-Reply-To` and `References` headers where applicable.
Validate recipients and encode MIME content correctly.

Do not use permanent deletion unless the user explicitly invokes that
feature and the OAuth scope supports it.

------------------------------------------------------------------------

## 11. API design

Prefix routes with `/api/v1`.

### Accounts

  Method   Route                                Purpose
  -------- ------------------------------------ -------------------------------
  GET      `/accounts`                          List connected Gmail accounts
  POST     `/accounts/google/connect`           Begin OAuth
  GET      `/accounts/google/callback`          OAuth callback
  GET      `/accounts/{account_id}`             Account details
  DELETE   `/accounts/{account_id}`             Disconnect account
  POST     `/accounts/{account_id}/reconnect`   Reauthorization

### Emails and threads

  ----------------------------------------------------------------------------------------------------
  Method                  Route                                                Purpose
  ----------------------- ---------------------------------------------------- -----------------------
  GET                     `/accounts/{account_id}/emails`                      Paginated email view

  GET                     `/accounts/{account_id}/emails/{email_id}`           Email details

  GET                     `/accounts/{account_id}/threads`                     Thread list

  GET                     `/accounts/{account_id}/threads/{thread_id}`         Thread details

  GET                     `/accounts/{account_id}/categories/{category}`       Category view

  GET                     `/accounts/{account_id}/labels`                      Gmail labels

  POST                    `/accounts/{account_id}/emails/{email_id}/read`      Mark read/unread

  POST                    `/accounts/{account_id}/emails/{email_id}/star`      Star/unstar

  POST                    `/accounts/{account_id}/emails/{email_id}/archive`   Archive
  ----------------------------------------------------------------------------------------------------

### Sync

  -----------------------------------------------------------------------------------------------------
  Method                  Route                                                 Purpose
  ----------------------- ----------------------------------------------------- -----------------------
  POST                    `/accounts/{account_id}/sync/initial`                 Start initial sync

  POST                    `/accounts/{account_id}/sync/historical`              Request older history

  POST                    `/accounts/{account_id}/sync/incremental`             Admin/manual
                                                                                incremental sync

  GET                     `/accounts/{account_id}/sync/status`                  Current sync state

  GET                     `/accounts/{account_id}/sync/jobs/{job_id}`           Job status

  GET                     `/accounts/{account_id}/sync/sessions/{session_id}`   Historical session
                                                                                status
  -----------------------------------------------------------------------------------------------------

### Drafts and sending

  Method   Route                                                Purpose
  -------- ---------------------------------------------------- ------------------
  POST     `/accounts/{account_id}/drafts`                      Create draft
  PATCH    `/accounts/{account_id}/drafts/{draft_id}`           Update draft
  GET      `/accounts/{account_id}/drafts`                      List drafts
  POST     `/accounts/{account_id}/drafts/{draft_id}/send`      Send draft
  POST     `/accounts/{account_id}/emails/send`                 Compose and send
  POST     `/accounts/{account_id}/threads/{thread_id}/reply`   Reply

### AI

  ---------------------------------------------------------------------------------------------------------
  Method                  Route                                                     Purpose
  ----------------------- --------------------------------------------------------- -----------------------
  GET                     `/accounts/{account_id}/threads/{thread_id}/ai/summary`   Thread summary

  POST                    `/accounts/{account_id}/threads/{thread_id}/ai/reply`     Generate reply
                                                                                    suggestion

  GET                     `/accounts/{account_id}/ai/actions`                       Extracted action items

  GET                     `/accounts/{account_id}/ai/important`                     Important messages
  ---------------------------------------------------------------------------------------------------------

### Notifications

  Method   Route                       Purpose
  -------- --------------------------- -----------------------
  POST     `/webhooks/google/pubsub`   Pub/Sub push endpoint

The webhook must validate the expected Pub/Sub authentication mechanism
and must not accept arbitrary unauthenticated events.

All endpoints must enforce authentication, account ownership, request
validation, rate limiting where appropriate, and consistent error
responses.

------------------------------------------------------------------------

## 12. Security requirements

1.  Enforce account ownership in every account-scoped API and database
    query.
2.  Use secure, HTTP-only, SameSite cookies or a carefully designed
    token session model.
3.  Protect OAuth state against CSRF and replay.
4.  Encrypt OAuth credentials at rest.
5.  Keep secrets in environment variables for local development and a
    secrets manager in production.
6.  Never log access tokens, refresh tokens, OAuth codes, message
    bodies, or attachment contents by default.
7.  Sanitize email HTML before rendering.
8.  Treat email body content, links, attachments, and AI outputs as
    untrusted input.
9.  Validate attachment size and content type; consider malware scanning
    before downloads or previews.
10. Apply rate limits to sensitive routes and AI generation.
11. Use least-privilege Google OAuth scopes.
12. Provide account disconnect and credential revocation/deletion
    behavior.
13. Keep audit records for sensitive actions without storing unnecessary
    email content.
14. Use HTTPS in production.
15. Restrict CORS to known frontend origins.
16. Ensure background workers apply the same account authorization and
    ownership assumptions as API requests.

------------------------------------------------------------------------

## 13. Reliability and failure handling

### Gmail API

-   Handle HTTP 401 by refreshing credentials once, then mark
    reauthorization required if refresh fails.
-   Handle HTTP 403 according to the actual Gmail error reason; not
    every 403 is retryable.
-   Handle HTTP 404 for expired history cursors with a repair sync.
-   Handle HTTP 429 and transient 5xx responses with exponential backoff
    and jitter.
-   Respect `Retry-After` when supplied.
-   Apply per-account and global concurrency controls.
-   Avoid unbounded retries.

### Celery

-   Tasks must be idempotent.
-   Use bounded retries.
-   Separate queues for sync, AI, and send operations.
-   Persist job state in MySQL.
-   Handle worker crashes and stale `processing` jobs.
-   Use dead-letter or failed-job inspection for tasks that exhaust
    retries.
-   Do not rely on Redis as the only permanent record of work.

### Sending

A network timeout after sending is ambiguous. Mark the send operation
`unknown`, reconcile with Gmail, and only retry when the system has
enough evidence that the original send did not succeed. Do not promise
exactly-once delivery when the provider API does not guarantee it.

### Database

-   Use transactions for message/label persistence batches.
-   Use unique constraints for deduplication.
-   Add connection pooling and sensible timeouts.
-   Back up MySQL and test restoration.
-   Use Alembic for all schema changes.
-   Never modify production schema manually without a migration.

------------------------------------------------------------------------

## 14. Indexing and query performance

Required indexes:

``` sql
CREATE UNIQUE INDEX uq_gmail_account_message
ON emails (account_id, gmail_message_id);

CREATE INDEX idx_emails_account_date
ON emails (account_id, internal_date DESC, id DESC);

CREATE UNIQUE INDEX uq_gmail_account_thread
ON email_threads (account_id, gmail_thread_id);

CREATE INDEX idx_emails_thread_date
ON emails (thread_id, internal_date, id);

CREATE INDEX idx_sync_jobs_account_status
ON sync_jobs (account_id, status, created_at);

CREATE INDEX idx_ai_jobs_status_created
ON ai_processing_jobs (status, created_at);

CREATE INDEX idx_label_mapping_label_email
ON email_label_mapping (label_id, email_id);
```

Create these in Alembic migrations or adapt them if equivalent indexes
already exist. Do not blindly run duplicate index statements.

For inbox queries:

-   Use keyset pagination.
-   Filter by account and view/label.
-   Order by `internal_date DESC, id DESC`.
-   Fetch only fields needed for list rendering.
-   Load full body content only when opening a message.
-   Avoid N+1 queries for senders, labels, and thread counts.
-   Add MySQL full-text search only after defining supported search
    behavior. Gmail search can also be used for uncached messages when
    needed.

------------------------------------------------------------------------

## 15. Docker and configuration

Required services:

-   `frontend`
-   `backend`
-   `celery-worker-sync`
-   `celery-worker-ai`
-   `celery-worker-send`
-   `celery-beat`
-   `mysql`
-   `redis`

Production may use managed MySQL, Redis, object storage, and Google
Cloud Pub/Sub instead of self-hosted containers.

Example `.env.example`:

``` dotenv
APP_ENV=development
APP_SECRET_KEY=replace-me
FRONTEND_URL=http://localhost:5173
BACKEND_URL=http://localhost:8000

MYSQL_HOST=mysql
MYSQL_PORT=3306
MYSQL_DATABASE=custom_mail
MYSQL_USER=custom_mail_user
MYSQL_PASSWORD=replace-me
DATABASE_URL=mysql+pymysql://custom_mail_user:replace-me@mysql:3306/custom_mail

REDIS_URL=redis://redis:6379/0
CELERY_BROKER_URL=redis://redis:6379/1
CELERY_RESULT_BACKEND=redis://redis:6379/2

GOOGLE_CLIENT_ID=replace-me
GOOGLE_CLIENT_SECRET=replace-me
GOOGLE_REDIRECT_URI=http://localhost:8000/api/v1/accounts/google/callback
GOOGLE_PUBSUB_TOPIC=replace-me

TOKEN_ENCRYPTION_KEY=replace-me
LLM_API_KEY=replace-me
```

Do not commit a real `.env` file. Use a dedicated least-privilege MySQL
user. Add health checks and wait-for-healthy dependencies. Do not expose
MySQL or Redis publicly in production.

------------------------------------------------------------------------

## 16. Observability

Use structured logs with:

-   request ID
-   user ID (internal ID only)
-   Gmail account ID (internal ID only)
-   sync job ID
-   task ID
-   operation name
-   duration
-   outcome
-   sanitized error code

Do not log email content or OAuth secrets.

Track metrics:

-   Gmail API calls and error rates
-   Sync duration per account
-   Number of messages imported
-   Historical sync backlog
-   Incremental sync lag
-   Watch expiration and renewal failures
-   Celery queue depth
-   AI processing backlog and failures
-   Send success, failure, and unknown counts
-   Database connection pool saturation

Provide an admin diagnostic view for failed sync jobs and accounts
requiring reauthorization.

------------------------------------------------------------------------

## 17. Testing strategy

### Unit tests

-   OAuth state creation and validation
-   Token encryption/decryption
-   Token refresh behavior
-   MIME parsing
-   HTML sanitization
-   Gmail label category mapping
-   Cursor encode/decode
-   Account ownership checks
-   Message and thread upsert behavior
-   AI eligibility routing
-   Retry classification

### Integration tests

-   Connect two Gmail accounts to one user.
-   Connect separate users with separate Gmail accounts.
-   Verify no user can access another user's account or email.
-   Initial sync imports only the configured recent window.
-   Historical sync resumes after interruption.
-   Repeated message imports do not create duplicates.
-   Incremental sync updates labels and messages.
-   Expired history cursor triggers repair behavior.
-   Repeated Pub/Sub event is processed once logically.
-   Token refresh preserves the refresh token.
-   Send timeout becomes `unknown` and is reconciled.
-   AI failure does not block email visibility.

Use a Gmail API adapter interface and fake provider implementation for
deterministic tests. Do not require live Gmail access for ordinary unit
tests.

### Contract tests

Verify Gmail API adapter assumptions, response parsing, MIME payload
handling, and Pub/Sub message validation against representative
fixtures.

------------------------------------------------------------------------

## 18. Implementation phases and acceptance criteria

### Phase 0 --- Repository inspection

Codex must inspect the existing repository before changing anything.

Deliverables:

-   Current frontend and backend structure
-   Existing dependencies and configuration
-   Existing database schema and migrations
-   Existing Gmail OAuth implementation, if any
-   Existing Docker setup
-   A short gap analysis

Do not replace working code merely to match the proposed folder tree.

### Phase 1 --- Foundation and accounts

Implement:

-   Application user authentication
-   Google OAuth authorization-code flow
-   OAuth state validation
-   Multiple connected Gmail accounts
-   Encrypted credential storage
-   Account list, disconnect, and reauthorization
-   Account ownership enforcement

Acceptance criteria:

-   One user can connect at least two Gmail accounts.
-   Each account has separate credentials and sync state.
-   A second user cannot access either account.
-   Tokens never appear in frontend responses or logs.

### Phase 2 --- Database and Gmail adapter

Implement:

-   SQLAlchemy models
-   Alembic migrations
-   Gmail API adapter
-   Label synchronization
-   Message and thread parsing
-   Idempotent upserts

Acceptance criteria:

-   A Gmail message is stored once per account.
-   A Gmail thread can contain multiple messages.
-   Gmail labels are represented correctly.
-   MIME bodies are parsed safely.
-   Database migrations can be applied from a clean database.

### Phase 3 --- Initial and historical synchronization

Implement:

-   Configurable recent-window initial sync
-   Background sync jobs
-   Progress tracking
-   On-demand historical sync sessions
-   Opaque cursors
-   Per-account locks
-   Resumable historical fetch

Acceptance criteria:

-   Connecting an account does not import all historical mail.
-   Initial sync imports the configured recent period.
-   Opening older history triggers a background fetch.
-   Repeating a historical request does not duplicate messages.
-   Interrupted historical sync can resume.

### Phase 4 --- Incremental synchronization

Implement:

-   Gmail watch setup and renewal
-   Pub/Sub webhook
-   Durable push-event ingestion
-   History API synchronization
-   Periodic reconciliation
-   History cursor recovery

Acceptance criteria:

-   A new message becomes visible after incremental sync.
-   Label changes are reflected locally.
-   Duplicate notifications do not cause duplicate effects.
-   Expired history cursor triggers a repair flow.
-   Watch renewal failures are observable.

### Phase 5 --- Email client functionality

Implement:

-   Account switcher
-   Inbox and category views
-   Thread viewer
-   Read/unread
-   Star/unstar
-   Archive
-   Search
-   Compose
-   Drafts
-   Reply and send
-   Attachment metadata and on-demand download

Acceptance criteria:

-   Actions update Gmail and local state consistently.
-   Thread replies preserve Gmail threading headers.
-   Send failures are visible.
-   Ambiguous send outcomes are not blindly retried.

### Phase 6 --- AI processing

Implement:

-   Category routing
-   Primary-only default eligibility
-   Idempotent AI jobs
-   Thread summaries
-   Action extraction
-   Importance detection
-   Suggested replies
-   User-controlled AI actions

Acceptance criteria:

-   Promotions, Social, Updates, Forums, Spam, and unclassified messages
    are not processed by default.
-   AI failure never blocks email synchronization.
-   Repeated events do not duplicate completed AI work.
-   AI suggestions do not send or modify emails without explicit user
    action.

### Phase 7 --- Production hardening

Implement:

-   Structured logs and metrics
-   Backup and restore procedure
-   Rate limiting
-   Secrets management
-   Security review
-   Load testing
-   Operational diagnostics
-   Deployment documentation

Acceptance criteria:

-   A backup can be restored in a test environment.
-   Failed jobs can be diagnosed and retried safely.
-   Account isolation tests pass.
-   No secrets appear in logs.
-   All schema changes are migration-managed.

------------------------------------------------------------------------

## 19. Codex working instructions

When implementing this project, follow these instructions.

1.  **Inspect before editing.** Read the repository, identify existing
    functionality, and report the current architecture before making
    changes.
2.  **Do not assume files are empty.** Preserve existing code and
    working behavior.
3.  **Work in small phases.** Implement one phase at a time and report
    changed files, migrations, tests, and remaining work.
4.  **Do not create the entire system in one unreviewable change.**
5.  **Use SQLAlchemy 2.x conventions** and Alembic migrations.
6.  **Use Pydantic schemas** for request and response validation.
7.  **Keep routers thin.** Business logic belongs in services; database
    operations belong in repositories.
8.  **Keep Gmail API calls in the integration layer.**
9.  **Use Celery for long-running or retryable operations.** Do not
    perform full synchronization or LLM processing in HTTP request
    handlers.
10. **Make all sync operations idempotent and resumable.**
11. **Enforce account ownership** in every API, worker, and repository
    path.
12. **Do not expose OAuth tokens or Gmail page tokens** to the frontend.
13. **Do not invent Gmail API fields or scopes.** Verify uncertain
    provider behavior against official Google documentation.
14. **Do not silently broaden OAuth permissions.** Explain why a new
    scope is needed before adding it.
15. **Do not automatically send AI-generated replies or perform
    destructive actions.**
16. **Add tests with each feature.** Do not defer all tests until the
    end.
17. **Run migrations and tests** after each relevant change.
18. **Update `.env.example` and README** when configuration or setup
    changes.
19. **Never commit secrets, real OAuth credentials, tokens, or personal
    email fixtures.**
20. If a requirement is ambiguous, identify the assumption and ask
    before implementing irreversible behavior.

### Required Codex response after each phase

Report:

-   What was inspected
-   What was implemented
-   Files created or changed
-   Database migrations added
-   Tests added and their results
-   Commands needed to run the feature
-   Known limitations
-   Next recommended phase

------------------------------------------------------------------------

## 20. Official technical references

Use current official documentation when implementing provider-specific
behavior:

-   Gmail API overview:
    https://developers.google.com/workspace/gmail/api/guides
-   Gmail synchronization:
    https://developers.google.com/workspace/gmail/api/guides/sync
-   Gmail push notifications:
    https://developers.google.com/workspace/gmail/api/guides/push
-   Gmail messages list:
    https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/list
-   Gmail messages get:
    https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/get
-   Gmail history list:
    https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.history/list
-   Gmail OAuth scopes:
    https://developers.google.com/workspace/gmail/api/auth/scopes
-   Google OAuth 2.0:
    https://developers.google.com/identity/protocols/oauth2
-   FastAPI: https://fastapi.tiangolo.com/
-   SQLAlchemy 2.x: https://docs.sqlalchemy.org/en/20/
-   Alembic: https://alembic.sqlalchemy.org/
-   Celery: https://docs.celeryq.dev/

------------------------------------------------------------------------

## Final architecture summary

The intended system is:

-   A modular FastAPI monolith.
-   Multiple Gmail accounts per application user.
-   Strict user and account data isolation.
-   MySQL as the persistent local read model.
-   Gmail as the provider source of truth.
-   Recent-window initial synchronization.
-   On-demand historical synchronization.
-   Gmail History API for incremental changes.
-   Pub/Sub for mailbox change notifications.
-   Redis and Celery for asynchronous work.
-   Separate Primary-only AI processing.
-   Explicit, safe reconciliation for send and mailbox operations.

**Implementation priority:** Build account isolation and reliable
synchronization before investing in advanced AI features or UI polish.
