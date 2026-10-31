# emailSender

React/Vite email workspace with a FastAPI backend and Gmail integration.

- [Backend setup, configuration, API, workers, migrations, and tests](backend/README.md)
- [Frontend](frontend/README.md)
- [Release verification and operations](docs/release.md)
- [Architectural specification](custom_gmail_application_codex_spec.md)
- [Repository analysis and phased implementation plan](docs/architecture-review.md)
- [Implemented phases, compatibility notes, and verification](docs/implementation-status.md)

All backend source, dependencies, configuration, Docker Compose services, documentation,
and runtime logs live in `backend/`. Frontend source and tests live in `frontend/`.
GitHub Actions workflows live in `.github/workflows/` as required by GitHub.

Run backend Compose commands from the repository root with
`docker compose -f backend/compose.yaml <command>`, or from `backend/` with
`docker compose <command>`. See the backend setup guide before first startup.

For an optional fully containerized local stack, configure independent random hex
passwords in a root `.env` copied from [.env.example](.env.example), and configure
OAuth/signing/encryption settings in `backend/.env` as documented. Then run:

```powershell
docker compose -f compose.yaml build
docker compose -f compose.yaml up -d mysql redis --wait
docker compose -f compose.yaml run --rm --no-deps api python -m alembic upgrade head
docker compose -f compose.yaml up -d --wait
```

Visit `http://localhost:5173`. This stack has its own MySQL volume and does not
replace the existing backend-only Compose or production deployment. Do not point
an existing production environment at it. MySQL and Redis are not published to
host ports. Keep `.env` files untracked.
