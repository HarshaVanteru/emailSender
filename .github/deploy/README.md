# Backend production deployment

The backend workflow uploads this bundle to
`/var/www/html/emailsender/.deploy/<commit>/`, then executes `backend.sh`.
The production API keeps its existing service name, `emailsender`. The other
three services are `redis`, `worker`, and `scheduler`.

The host must have Docker Compose v2 with `up --wait`, Bash, rsync, and the
existing production `.env` at `/var/www/html/emailsender/.env`. MySQL remains
outside the four managed application services. An existing `mysql` container
in the same Compose project is preserved, and the application reuses its Docker
network. Keep OAuth, JWT/encryption, provider, database, and Gmail push settings
in that file. No new GitHub secrets are required.

The API binds to `127.0.0.1:8000` for the existing nginx proxy by default.
Set `API_BIND_ADDRESS`, `API_PORT` (host port), and `PORT` (container port) in
`.env` if the production proxy uses another address or port.

Deployment pulls images before downtime, then stops the API, scheduler, and all
current or retired mailbox workers in the existing Compose project. Workers get
up to 31 minutes to finish their current task. Redis and any existing MySQL
container stay up; their data volumes are retained. The script refuses ambiguous projects or unrelated services
in the same project rather than stopping them.

Alembic upgrades to `head`, including migration `0009`, while database writers
are stopped. The manual legacy-baseline input retains the original users-only
schema checks; it is unnecessary for an already-versioned database. Keep normal
database backups before release migrations.

Only after successful migrations does the script publish `compose.yaml` and
persist the release image/project in `.env`. It starts all four services,
removes only the explicitly identified retired worker containers, waits for
API/Redis/worker health, checks all
three worker queues, and verifies that the API, worker, and scheduler use the
same commit-tagged image. The scheduler is checked as a running process.

A failed migration leaves application writers stopped and reports diagnostics;
it never starts old code against a partially upgraded schema or attempts an
automatic database rollback. A failed pull leaves the running release untouched.
The previous Compose manifest is retained in the release directory when present.

Local checks (no server access or live database changes):

```sh
bash -n .github/deploy/backend.sh
python -m unittest discover -s .github/tests -v
```

When MySQL already belongs to this Compose project, it remains an existing
server-managed container in addition to the four application services. The
runtime manifest declares its network external so it is not recreated or
removed by the application deployment. An ambiguous MySQL network fails before
any application writers are stopped. `DATABASE_URL` is retained unchanged.

Do not use `--remove-orphans` for this production project: MySQL is intentionally
outside the application manifest. The deployment script overrides automatic
orphan removal and deletes only the stopped `api`, `maintenance-worker`, and
`ai-worker` containers. The original Compose definition, including MySQL when
present, is backed up as `.deploy/<commit>/compose.previous.yaml`.
