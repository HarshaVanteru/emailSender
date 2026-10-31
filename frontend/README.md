# emailSender frontend

React and TypeScript Gmail workspace, built with Vite and Tailwind CSS.
See the [project setup guide](../backend/README.md) for backend services,
Google OAuth, environment configuration, and browser test scenarios.

## Development

Use Node.js 22.12+ and run from the project root:

```powershell
npm --prefix frontend ci
npm --prefix frontend run dev -- --port 5173 --strictPort
```

Vite proxies `/api` to the backend. `VITE_API_BASE_URL` overrides the backend
origin and is embedded at build time.

## Source layout

- `src/app/`: application shell and workspace state.
- `src/features/`: mailbox, compose, drafts, Google login, AI, profile, and sync.
- `src/shared/api/client.ts`: authenticated JSON requests and API errors.
- `src/shared/api/apiUrl.ts`: API URL normalization.
- `src/shared/components/`: shared UI.

Keep endpoints and types in their feature folder. Use `apiRequest` for JSON
requests so authentication, response parsing, and errors stay consistent.

## Verification

From `frontend/`:

```powershell
npm run build
npm run lint
node --test tests/*.test.mjs
```

Browser checks in `tests/*.browser.cjs` use Playwright with Microsoft Edge.
Serve the production build on port 4174, or set `APP_URL` to a local server.
Set `PLAYWRIGHT_MODULE` if Playwright is installed outside this project.
Most browser checks mock provider requests; `live-readonly.browser.cjs`
is a separate live-account diagnostic.
That diagnostic requires an operator-provided `LIVE_READONLY_TOKEN` from an
existing signed-in test session; it no longer mints a token for the first database
user. Screenshots containing live mailbox data require the explicit
`LIVE_READONLY_SCREENSHOTS=true` opt-in. It was not run during isolated verification.

`spec-workflows.browser.cjs` checks explicit historical fetches, Gmail labels,
attachment downloads, uncertain-send reconciliation and authenticated add-account.
AI generation and current sending flows use durable job status APIs; review and
the browser undo countdown still happen before a send is submitted. See the
[implementation handoff](../docs/implementation-status.md) for migration and
backend/frontend rollout compatibility requirements.
