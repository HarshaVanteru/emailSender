#!/usr/bin/env bash
# Run on the Docker host from an uploaded, immutable release bundle.
set -euo pipefail
: "${DEPLOY_DIR:?DEPLOY_DIR is required}"
: "${BACKEND_IMAGE:?BACKEND_IMAGE is required}"
release_dir=$(cd -- "$(dirname -- "$0")" && pwd -P)
cd "$DEPLOY_DIR"
DEPLOY_DIR=$(pwd -P)
test -f .env

# Preserve the existing Compose project and its Redis volume. Refuse an
# ambiguous working directory rather than starting a second scheduler.
project_list=$(docker ps -a \
  --filter "label=com.docker.compose.project.working_dir=$DEPLOY_DIR" \
  --format '{{.Label "com.docker.compose.project"}}' | sort -u)
projects=()
if [[ -n "$project_list" ]]; then mapfile -t projects <<< "$project_list"; fi
if (( ${#projects[@]} > 1 )); then
  echo "Multiple Compose projects use $DEPLOY_DIR; resolve this before deploying." >&2
  exit 1
fi
# A prior deployment records this even if all containers were later removed.
recorded_project=$(awk -F= '$1 == "COMPOSE_PROJECT_NAME" {print substr($0, index($0, "=") + 1)}' .env | tail -n 1)
project=${projects[0]:-${recorded_project:-${DEPLOY_DIR##*/}}}
if [[ ! "$project" =~ ^[a-z0-9][a-z0-9_-]*$ ]]; then
  echo "Invalid Compose project name." >&2
  exit 1
fi
# Build a runtime manifest so an existing database network can be reused
# without adding MySQL to the application services managed by this release.
runtime_compose="$release_dir/compose.runtime.yaml"
cp -- "$release_dir/compose.yaml" "$runtime_compose"
export COMPOSE_REMOVE_ORPHANS=false
compose=(docker compose --project-directory "$DEPLOY_DIR" --env-file "$DEPLOY_DIR/.env" \
  --project-name "$project" -f "$runtime_compose")
export BACKEND_IMAGE
"${compose[@]}" config --quiet

report_failure() {
  result=$?
  if (( result != 0 )); then
    echo "Deployment failed. Database migrations are not rolled back automatically." >&2
    "${compose[@]}" ps -a || true
    "${compose[@]}" logs --since=15m --tail=100 || true
  fi
}
trap report_failure EXIT

# Pull first so an unavailable image cannot interrupt the running release.
"${compose[@]}" pull

# Include old split workers and the former local API name. Redis stays up,
# preserving queued jobs while all database writers drain before migration.
container_list=$(docker ps --filter "label=com.docker.compose.project=$project" --format '{{.ID}}')
containers=()
if [[ -n "$container_list" ]]; then mapfile -t containers <<< "$container_list"; fi
writers=()
retired=()
mysql_containers=()
for container in "${containers[@]}"; do
  service=$(docker inspect --format '{{index .Config.Labels "com.docker.compose.service"}}' "$container")
  case "$service" in
    emailsender|worker|scheduler) writers+=("$container") ;;
    api|maintenance-worker|ai-worker) writers+=("$container"); retired+=("$container") ;;
    redis) ;;
    mysql) mysql_containers+=("$container") ;;
    *) echo "Unexpected service $service in project $project; refusing deployment." >&2; exit 1 ;;
  esac
done

if (( ${#mysql_containers[@]} > 1 )); then
  echo "Multiple MySQL containers found; refusing to choose a database network." >&2
  exit 1
fi
if (( ${#mysql_containers[@]} == 1 )); then
  network_list=$(docker inspect --format '{{range $name, $_ := .NetworkSettings.Networks}}{{println $name}}{{end}}' "${mysql_containers[0]}")
  networks=()
  if [[ -n "$network_list" ]]; then mapfile -t networks <<< "$network_list"; fi
  mysql_network=""
  for network in "${networks[@]}"; do
    if [[ "$network" == "${project}_default" ]]; then mysql_network="$network"; fi
  done
  if [[ -z "$mysql_network" && ${#networks[@]} == 1 ]]; then mysql_network=${networks[0]}; fi
  if [[ ! "$mysql_network" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]*$ || "$mysql_network" == "bridge" || "$mysql_network" == "host" || "$mysql_network" == "none" ]]; then
    echo "Cannot safely identify the existing MySQL network; no writers were stopped." >&2
    exit 1
  fi
  mysql_host=$(docker inspect --format '{{.Name}}' "${mysql_containers[0]}")
  mysql_host=${mysql_host#/}
  if [[ ! "$mysql_host" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]*$ ]]; then
    echo "Invalid MySQL container hostname; no writers were stopped." >&2
    exit 1
  fi
  export DATABASE_HOST_OVERRIDE="$mysql_host"
  printf '\nnetworks:\n  default:\n    external: true\n    name: %s\n' "$mysql_network" >> "$runtime_compose"
  "${compose[@]}" config --quiet
  echo "Preserving the existing MySQL container on network $mysql_network."
fi
# Use the same release image, network, credentials, and host override as the
# migration and running services. This is read-only and precedes downtime.
"${compose[@]}" run -T --rm --no-deps emailsender python - < "$release_dir/database_preflight.py"
if (( ${#writers[@]} )); then
  docker stop --time 1860 "${writers[@]}"
fi

if [[ "${BASELINE_LEGACY_DATABASE:-false}" == "true" ]]; then
  # This heredoc is only the Python input, not an SSH deployment script.
  "${compose[@]}" run -T --rm --no-deps emailsender python - <<'PY'
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect
from app.core.config import DATABASE_URL

engine = create_engine(DATABASE_URL)
with engine.connect() as connection:
    inspector = inspect(connection)
    revisions = MigrationContext.configure(connection).get_current_heads()
    tables = set(inspector.get_table_names()) - {"alembic_version"}
    expected = {"id", "email", "name", "google_token", "signature", "preferences", "bio"}
    if revisions or tables != {"users"}:
        raise SystemExit("Refusing legacy stamp: database must be unversioned with only the users table.")
    columns = {column["name"] for column in inspector.get_columns("users")}
    if columns != expected:
        raise SystemExit("Refusing legacy stamp: users columns do not match migration 0001.")
command.stamp(Config("alembic.ini"), "0001")
PY
fi

"${compose[@]}" run -T --interactive=false --rm --no-deps emailsender python -m alembic upgrade head < /dev/null
"${compose[@]}" run -T --interactive=false --rm --no-deps emailsender python -m alembic current < /dev/null

# Publish configuration only after migrations succeed; never print .env.
next_env=$(mktemp "$DEPLOY_DIR/.env.XXXXXX")
chmod 600 "$next_env"
awk '!/^BACKEND_IMAGE=/ && !/^COMPOSE_PROJECT_NAME=/ && !/^DATABASE_HOST_OVERRIDE=/' .env > "$next_env"
printf '\nBACKEND_IMAGE=%s\nCOMPOSE_PROJECT_NAME=%s\n' "$BACKEND_IMAGE" "$project" >> "$next_env"
printf 'DATABASE_HOST_OVERRIDE=%s\n' "${DATABASE_HOST_OVERRIDE:-}" >> "$next_env"
mv -- "$next_env" .env
if [[ -f compose.yaml ]]; then cp -- compose.yaml "$release_dir/compose.previous.yaml"; fi
cp -- "$runtime_compose" compose.yaml

# MySQL may share this Compose project but is managed by the existing server.
# Never use --remove-orphans: it would delete that live database container.
"${compose[@]}" up -d --no-build --pull never --wait --wait-timeout 180 < /dev/null
# Delete only the retired application containers identified and stopped above.
if (( ${#retired[@]} )); then docker rm "${retired[@]}"; fi

# Health checks cover API, Redis, and worker responsiveness. Also verify every
# queue so mail updates or AI review cannot silently remain unconsumed.
"${compose[@]}" exec -T worker python - <<'PY'
import socket
from app.workers.celery_app import celery_app
node = "mailbox@" + socket.gethostname()
queues = celery_app.control.inspect(destination=[node], timeout=5).active_queues() or {}
actual = {queue["name"] for queue in queues.get(node, [])}
expected = {"gmail-sync", "gmail-maintenance", "gmail-ai"}
if actual != expected:
    raise SystemExit("Worker queue mismatch: " + repr(actual))
print("Worker is consuming all three mailbox queues.")
PY
for service in emailsender worker scheduler; do
  container=$("${compose[@]}" ps --quiet "$service")
  test -n "$container"
  actual=$(docker inspect --format '{{.Config.Image}}' "$container")
  if [[ "$actual" != "$BACKEND_IMAGE" ]]; then
    echo "$service is not running the requested release image." >&2
    exit 1
  fi
done
"${compose[@]}" ps
