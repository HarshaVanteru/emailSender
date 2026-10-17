# emailSender

React/Vite email workspace with a FastAPI backend and Gmail integration.

- [Backend setup, configuration, API, workers, migrations, and tests](backend/README.md)
- [Frontend](frontend/README.md)
- [Release verification and operations](docs/release.md)

All backend source, dependencies, configuration, Docker Compose services, documentation,
and runtime logs live in `backend/`. Frontend source and tests live in `frontend/`.
GitHub Actions workflows live in `.github/workflows/` as required by GitHub.

Run backend Compose commands from the repository root with
`docker compose -f backend/compose.yaml <command>`, or from `backend/` with
`docker compose <command>`. See the backend setup guide before first startup.
