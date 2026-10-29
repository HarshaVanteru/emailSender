"""Exercise the real deployment script with Docker mocked; no server or DB access."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
BASH = os.environ.get("TEST_BASH", "bash")

MOCK_DOCKER = r'''#!/usr/bin/env bash
set -eu
printf '%s\n' "$*" >> "$DOCKER_LOG"
if [[ "$1" == "ps" ]]; then
  if [[ "$*" == *project.working_dir* ]]; then
    printf '%s\n' original-project
  else
    printf '%s\n' old-api old-worker old-maintenance old-ai old-scheduler old-redis old-mysql
  fi
elif [[ "$1" == "inspect" ]]; then
  if [[ "$*" == *NetworkSettings.Networks* ]]; then
    echo original-project_database
  elif [[ "$*" == *'{{.Name}}'* ]]; then
    echo /emailsender-mysql
  elif [[ "$*" == *Config.Labels* ]]; then
    case "${@: -1}" in
      old-api) echo emailsender ;;
      old-worker) echo worker ;;
      old-maintenance) echo maintenance-worker ;;
      old-ai) echo ai-worker ;;
      old-scheduler) echo scheduler ;;
      old-redis) echo redis ;;
      old-mysql) echo mysql ;;
    esac
  else
    printf '%s\n' "$BACKEND_IMAGE"
  fi
elif [[ "$1" == "compose" ]]; then
  if [[ "$*" == *' pull' && "${SCENARIO:-}" == "pull-fails" ]]; then exit 9; fi
  if [[ "$*" == *'emailsender python -' ]]; then
    cat >/dev/null
    if [[ "${SCENARIO:-}" == "database-unreachable" ]]; then exit 12; fi
  fi
  if [[ "$*" == *'alembic upgrade head'* && "${SCENARIO:-}" == "migration-fails" ]]; then exit 10; fi
  if [[ "$*" == *' exec -T worker '* ]]; then
    cat >/dev/null
    if [[ "${SCENARIO:-}" == "queues-fail" ]]; then exit 11; fi
  fi
  if [[ "$*" == *' ps --quiet '* ]]; then printf 'new-%s\n' "${@: -1}"; fi
fi
'''


class DeploymentTests(unittest.TestCase):
    def run_deployment(self, scenario="success"):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        work = Path(self.temp.name)
        deploy = work / "emailsender"
        deploy.mkdir()
        self.original_env = "DATABASE_URL=unchanged-placeholder\nBACKEND_IMAGE=previous-image\n"
        (deploy / ".env").write_text(self.original_env)
        (deploy / "compose.yaml").write_text("previous-manifest\n")
        release = deploy / ".deploy" / "release"
        release.mkdir(parents=True)
        for name in ("backend.sh", "compose.yaml", "database_preflight.py"):
            shutil.copyfile(ROOT / ".github" / "deploy" / name, release / name)
        binary = work / "bin"
        binary.mkdir()
        docker = binary / "docker"
        docker.write_text(MOCK_DOCKER, newline="\n")
        docker.chmod(0o755)
        log = work / "docker.log"
        env = {**os.environ, "DEPLOY_DIR": deploy.as_posix(),
               "BACKEND_IMAGE": "ghcr.io/example/backend:commit", "SCENARIO": scenario,
               "DOCKER_LOG": log.as_posix(), "BASELINE_LEGACY_DATABASE": "false"}
        # Pass PATH inside Bash too, so Git Bash can run the same mocks on Windows.
        result = subprocess.run([BASH, "-c", 'mockbin=$(cd "$1" && pwd -P); export PATH="$mockbin:$PATH"; hash -r; test "$(command -v docker)" = "$mockbin/docker" || exit 99; bash "$2"',
                                 "deployment-test", binary.as_posix(), (release / "backend.sh").as_posix()],
                                env=env, capture_output=True, text=True, timeout=20)
        self.assertNotEqual(result.returncode, 99, "Docker mock did not resolve; refusing real Docker access")
        commands = log.read_text().splitlines() if log.exists() else []
        return result, commands, deploy, release

    def test_success_drains_old_workers_migrates_then_starts_four_service_stack(self):
        result, commands, deploy, release = self.run_deployment()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        pull = next(i for i, command in enumerate(commands) if command.endswith(" pull"))
        preflight = next(i for i, command in enumerate(commands) if command.endswith("emailsender python -"))
        stop = next(i for i, command in enumerate(commands) if command.startswith("stop "))
        migrate = next(i for i, command in enumerate(commands) if "alembic upgrade head" in command)
        start = next(i for i, command in enumerate(commands) if " up -d " in command)
        self.assertLess(pull, preflight)
        self.assertLess(preflight, stop)
        self.assertLess(stop, migrate)
        self.assertLess(migrate, start)
        self.assertIn("old-maintenance", commands[stop])
        self.assertIn("old-ai", commands[stop])
        self.assertNotIn("old-redis", commands[stop])
        self.assertIn("--wait", commands[start])
        self.assertNotIn("--remove-orphans", commands[start])
        self.assertTrue(any("exec -T worker" in command for command in commands))
        self.assertEqual((deploy / "compose.yaml").read_text(), (release / "compose.runtime.yaml").read_text())
        self.assertEqual((release / "compose.previous.yaml").read_text(), "previous-manifest\n")
        self.assertIn("COMPOSE_PROJECT_NAME=original-project", (deploy / ".env").read_text())
        self.assertIn("DATABASE_URL=unchanged-placeholder", (deploy / ".env").read_text())
        self.assertIn("DATABASE_HOST_OVERRIDE=emailsender-mysql", (deploy / ".env").read_text())

    def test_existing_mysql_container_and_network_survive_deployment(self):
        result, commands, deploy, _ = self.run_deployment()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        mutations = [command for command in commands if command.startswith(("stop ", "rm ", "network ", "volume "))]
        self.assertFalse(any("old-mysql" in command for command in mutations))
        self.assertFalse(any("old-redis" in command for command in mutations))
        self.assertFalse(any("--remove-orphans" in command or " down" in command for command in commands))
        cleanup = next(command for command in commands if command.startswith("rm "))
        self.assertIn("old-maintenance", cleanup)
        self.assertIn("old-ai", cleanup)
        self.assertNotIn("old-api", cleanup)
        runtime = (deploy / "compose.yaml").read_text()
        self.assertIn("external: true", runtime)
        self.assertIn("name: original-project_database", runtime)
        self.assertIn("DATABASE_URL=unchanged-placeholder", (deploy / ".env").read_text())
        self.assertIn("DATABASE_HOST_OVERRIDE=emailsender-mysql", (deploy / ".env").read_text())

    def test_unreachable_database_fails_before_stopping_any_application(self):
        result, commands, deploy, _ = self.run_deployment("database-unreachable")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(command.startswith(("stop ", "rm ")) for command in commands))
        self.assertFalse(any("alembic upgrade head" in command for command in commands))
        self.assertEqual((deploy / ".env").read_text(), self.original_env)
        self.assertEqual((deploy / "compose.yaml").read_text(), "previous-manifest\n")

    def test_failed_pull_does_not_stop_running_services(self):
        result, commands, deploy, _ = self.run_deployment("pull-fails")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(command.startswith("stop ") for command in commands))
        self.assertFalse(any("alembic upgrade head" in command for command in commands))
        self.assertEqual((deploy / ".env").read_text(), self.original_env)

    def test_failed_migration_never_restarts_writers_or_publishes_configuration(self):
        result, commands, deploy, _ = self.run_deployment("migration-fails")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(any(command.startswith("stop ") for command in commands))
        self.assertFalse(any(" up -d " in command for command in commands))
        self.assertEqual((deploy / "compose.yaml").read_text(), "previous-manifest\n")
        self.assertEqual((deploy / ".env").read_text(), self.original_env)

    def test_worker_queue_failure_fails_deployment(self):
        result, commands, _, _ = self.run_deployment("queues-fail")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(any("exec -T worker" in command for command in commands))
