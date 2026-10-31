# Release verification and operations

The [setup guide](../backend/README.md) is the source of truth for local
services, configuration, migrations, and individual regression commands.

## Checks before release

- Run backend regression tests against isolated test databases.
- Run the frontend build, lint, and unit tests.
- Run relevant mocked desktop/mobile browser checks for changed user flows.
- Back up the production database before schema changes and pause worker writes.

The current migration head is **0016**. The optional identifier widening in **0015**
was specifically approved and rehearsed on disposable MySQL. It alters primary and
foreign-key types with MySQL's implicit DDL commits: stop every writer, retain a
verified backup, and allow a maintenance window. If it fails partway through, inspect
the schema before continuing; do not assume rollback restored the former schema.
Downgrading refuses IDs that do not fit the older signed INT columns.

Deploy the backend/schema first, then the rebuilt frontend. AI generation endpoints
now return `202` job records, so old frontend artifacts cannot interpret their new
response shape. Current send flows also require the new durable job endpoints.
Legacy synchronous send URLs retain their response shape and record outcomes.
Users with old session-less JWTs sign in again unless a short-lived compatibility
window explicitly enables `ALLOW_LEGACY_SESSIONS`.

## Deployment workflows

`.github/workflows/backend.yml` tests the backend, publishes its Docker image
to GHCR, and deploys through SSH using the server's Compose configuration.
The API stops before migrations. After `alembic upgrade head` succeeds,
the workflow starts the API and checks its health inside the container.
Migration failures stop deployment; the API may remain stopped until recovery.

The manual `baseline_legacy_database` option is only for adopting an
unversioned database matching migration `0001`. Back up first. Leave this
option disabled for databases already managed by Alembic.

The production Compose file lives on the server and must supply the configured
backend image, database access, secrets, Redis, and any worker services.
Deploy and restart workers with the same image as the API when their code changes.

`.github/workflows/frontend.yml` builds the static frontend, uploads a release
directory, and atomically switches the server's `frontend/dist` symlink.
It retains the live release and two previous releases. Nginx serves the frontend
and proxies `/api` to the backend, including WebSocket upgrades.

Worker health checks verify three independent worker node/queue groups inside the
existing worker service. Run `python -m app.workers.health` inside that container
to verify reserved sync/maintenance, AI and send capacity. Keep only one scheduler.

## Backup and restoration drill

Use a dedicated backup identity and an access-restricted client configuration
mounted from the production secrets manager. Do not put a real password on a
command line or commit that client file. For example, with the configured database
name substituted for `custom_mail`:

```sh
mysqldump --defaults-extra-file=/run/secrets/mysql-backup.cnf \
  --single-transaction --no-tablespaces --set-gtid-purged=OFF custom_mail > backup.sql
```

Store the dump encrypted outside the application host, retain the relevant token
encryption keys separately, and record the Alembic revision and image digest.
Restore into a **separate empty test database**, not the running application DB:

```sh
mysql --defaults-extra-file=/run/secrets/mysql-restore.cnf custom_mail_restore_test < backup.sql
```

Verify the Alembic revision, user/account counts, foreign keys and representative
mailbox/draft/job reads against the restored instance before calling the backup
usable. The repository's opt-in `test_backup_restore.py` ran an actual dump/restore
of fixture data in a labeled disposable MySQL container; no production dump was used.

## Configuration and secrets

Use HTTPS, an exact `FRONTEND_URL`, independent random signing/encryption keys and
a least-privilege database identity. Supply deployment secrets through your secrets
manager; `.env` is a local-development mechanism. The production Compose manifest
enables API limits unless explicitly overridden; set `RATE_LIMIT_ENABLED=true`
when adopting an older environment file that explicitly sets it false.

For a planned token-key rotation, set a new `TOKEN_ENCRYPTION_KEY` and increment
`TOKEN_ENCRYPTION_KEY_VERSION`; retain previous keys in
`TOKEN_ENCRYPTION_PREVIOUS_KEYS` while old credentials, OAuth attempts, history
checkpoints and queued work remain. New writes use the new key. Remove an old key
only after all retained ciphertext has been migrated or expired; keep a tested
rollback copy in the secrets manager. Changing a signing key invalidates sessions.

Disable access logging for OAuth/API callback URLs in the external nginx/load
balancer as well. Backend structured logs omit query strings, headers, OAuth codes,
mail contents and exception bodies. Never enable body/debug tracing in production
without a separate data-handling review.

## Diagnostics and ambiguous sends

Settings exposes owned connection diagnostics, reauthorization needs, renewal
errors, failed sync jobs and send/AI backlogs. The matching API is
`GET /api/v1/accounts/{id}/diagnostics`; it never returns credentials or mail bodies.
Failed sync can resume through the existing owned sync request. An exhausted AI
job may be retried by an explicit generation request.

An `unknown` send is not a failed delivery. Use **Recent send status → Check Gmail
Sent** to reconcile its correlation Message-ID. A missing search result, unavailable
index or draft without a Message-ID does not authorize an automatic retry. Inspect
Gmail manually before creating another reviewed send. Stale send-worker leases also
become unknown, never pending. Inspect the failed-job records before intervention;
do not repair them by manually changing a send status to pending.

## Verify and recover

Check the migration revision, current container status (including stopped
containers), and recent logs. Verify login, mailbox loading, draft review, and
the send confirmation flow. Use a designated test account for live send checks.

If migration fails, inspect the database and migration error before retrying.
MySQL schema changes may remain applied after a failure. Do not stamp an
arbitrary revision or automatically downgrade to make the error disappear.
Restoring an older application image does not undo a database migration.
