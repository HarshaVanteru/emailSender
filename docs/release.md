# Release verification and operations

The [setup guide](../backend/README.md) is the source of truth for local
services, configuration, migrations, and individual regression commands.

## Checks before release

- Run backend regression tests against isolated test databases.
- Run the frontend build, lint, and unit tests.
- Run relevant mocked desktop/mobile browser checks for changed user flows.
- Back up the production database before schema changes and pause worker writes.

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

## Verify and recover

Check the migration revision, current container status (including stopped
containers), and recent logs. Verify login, mailbox loading, draft review, and
the send confirmation flow. Use a designated test account for live send checks.

If migration fails, inspect the database and migration error before retrying.
MySQL schema changes may remain applied after a failure. Do not stamp an
arbitrary revision or automatically downgrade to make the error disappear.
Restoring an older application image does not undo a database migration.
