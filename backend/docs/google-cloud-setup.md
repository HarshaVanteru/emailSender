# Google Cloud setup

## Gmail OAuth

1. Select a Google Cloud project and enable Gmail API.
2. Configure Google Auth Platform branding, audience, and test users while the app is in testing.
3. Add `https://www.googleapis.com/auth/gmail.modify`, `openid`,
   `https://www.googleapis.com/auth/userinfo.email`, and
   `https://www.googleapis.com/auth/userinfo.profile` to Data Access.
4. Create a Web application OAuth client. Register the exact callback URL from
   `GOOGLE_REDIRECT_URI`, normally `http://localhost:8000/api/v1/auth/google/callback` locally.
5. Set the client ID, client secret, callback, and frontend origin in `backend/.env`.
   Reconnect older accounts to grant mailbox access. Production requires HTTPS
   and the applicable Google consent verification before public distribution.

## Automatic incoming mail

WebSockets notify the browser after a successful background sync. They do not
connect directly to Gmail. With no push configuration, Celery schedules sync
approximately every `SYNC_INTERVAL_SECONDS` (default 300), plus queue/runtime delays.
After commit, connected browsers observe the change within about three seconds.

For prompt Gmail-triggered sync:

1. Create a Pub/Sub topic in the same project as the OAuth client.
2. Grant `gmail-api-push@system.gserviceaccount.com` Pub/Sub Publisher on that topic.
3. Create a dedicated push-authentication service account and an authenticated,
   wrapped Pub/Sub push subscription targeting the public HTTPS URL
   `/api/v1/webhooks/gmail/pubsub`. Configure the subscription's OIDC audience
   to match `PUBSUB_PUSH_AUDIENCE`. Configure the Pub/Sub service agent permissions
   needed to mint the service-account token per Google's authenticated push guide.
4. Set `GMAIL_PUSH_TOPIC=projects/PROJECT/topics/TOPIC`,
   `PUBSUB_SUBSCRIPTION=projects/PROJECT/subscriptions/SUBSCRIPTION`,
   `PUBSUB_PUSH_SERVICE_ACCOUNT=SERVICE_ACCOUNT_EMAIL`, and
   `PUBSUB_PUSH_AUDIENCE=EXACT_CONFIGURED_AUDIENCE` in `backend/.env`.
5. Restart API, both workers, and the scheduler. The maintenance worker renews
   Gmail watches; renewal runs hourly. Scheduled sync remains a recovery path
   for delayed/dropped push notifications. Check watch expiration in the database
   and worker logs before expecting immediate updates.

The topic and subscription must exist before enabling these settings. Localhost
is not a public push endpoint. These instructions do not create cloud resources.

## WebSocket hosting

The frontend connects to `/api/v1/accounts/{account_id}/events` using the configured
API origin (WSS for HTTPS). Set `FRONTEND_URL` to the exact browser origin; other
browser origins are rejected. The first frame contains the app bearer token;
credentials are never placed in the URL. Expiry and account access are rechecked
through short database snapshots. Reconnect refreshes recover missed changes.

Vite proxies WebSocket upgrades automatically. For nginx, add upgrade forwarding
inside your existing `/api/` proxy location:

```nginx
proxy_http_version 1.1;
proxy_set_header Upgrade $http_upgrade;
proxy_set_header Connection "upgrade";
proxy_read_timeout 60s;
```

Keep the existing `proxy_pass` pointing at the API. Configure other proxies/load
balancers to support WebSocket upgrades and long-lived connections as appropriate.
Open conversations refresh without discarding an active reply editor.

## API map

FastAPI `/docs` is the complete HTTP endpoint catalog. Features live under
`/api/v1`: `auth/google`, `accounts`, `gmail/profile`, `gmail/send`,
`accounts/{id}/sync`, `accounts/{id}/sync-jobs`, `emails`,
`accounts/{id}/labels`, `accounts/{id}/threads`, `accounts/{id}/drafts`,
`ai/generate-email`, and `webhooks/gmail/pubsub`. Thread compose and AI endpoints
are documented in the root README. WebSocket endpoints are not in OpenAPI.

References: [Gmail push](https://developers.google.com/workspace/gmail/api/guides/push),
[authenticated Pub/Sub push](https://cloud.google.com/pubsub/docs/authenticate-push-subscriptions),
[OAuth web server flow](https://developers.google.com/identity/protocols/oauth2/web-server).
