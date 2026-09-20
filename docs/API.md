# Local interfaces

All routes are private to the local single-user app. JSON responses are `no-store`; no CORS access is granted. Mutating requests need the `X-Codester-CSRF` value from the page's `csrf-token` meta tag. Hostnames are limited to localhost and loopback literals.

| Method | Route | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Process health, independent of upstream services |
| GET | `/api/dashboard` | Cached normalized snapshots, per-service status/message/last_success/data and demo/revision flags |
| GET | `/api/codex/activity` | Recent tasks with `activity_source` (`hook`, `rollout`, or `recency`); direct-event integration status and last receipt time |
| GET | `/api/settings` | Saved preferences and `signoz.has_key`; never the key |
| PUT | `/api/settings` | Replace validated preferences; optional `signoz.api_key` replaces key, blank preserves, `clear_key: true` removes |
| POST | `/api/connections/{codex,dagster,signoz}/test` | Test saved real connection even in demo mode |
| POST | `/api/signoz/services` | Discover trace service names using saved connection |
| GET | `/api/tunnels` | Managed SSH-forward status without credentials or process details |
| POST | `/api/tunnels/connect` | Start every saved forward and keep reconnecting until disconnected |
| POST | `/api/tunnels/disconnect` | Stop every managed forward and disable reconnecting |
| POST | `/api/tunnels/{id}/test` | Test a saved SSH login and remote target through a temporary local forward |
| GET | `/api/errors/{dagster,signoz}/{id}` | Bounded details for an ID in the current error snapshot |

Settings use `demo` plus `codex` (`enabled`, `activity`), `dagster` (`enabled`, `api_url`, `browser_url`), `signoz` (`enabled`, `api_url`, `browser_url`, `error_service`, `panels`), and up to 20 `tunnels`. Each tunnel has an opaque ID, display name, authentication mode, SSH host/user/port, and local/remote host/port. Local ports, IDs, and names must be unique. A submitted tunnel `password` is encrypted separately; reads expose only `has_password`. Each SigNoz panel has `service` and one of `request_rate`, `error_rate`, `p95`. An empty service means all services. Up to three panels are accepted. The HTML settings form is the intended configuration interface.

Snapshot status is one of `loading`, `disabled`, `demo`, `connected`, `stale`, `error`. Last-success timestamps use Unix seconds. A stale snapshot retains the previous data, with its original timestamp. Changing settings invalidates all snapshots and wakes polling workers. Unknown or expired error IDs return 404; settings changes during a detail fetch return 409.

The dashboard `revision` changes when local settings change; clients use it to discard chart observations from previous connections. It is process-local, not a persisted configuration version.

## Codex event delivery

`python -m codester.codex_hook` accepts Codex hook JSON on stdin and stores allowed lifecycle metadata in `CODESTER_DATA_DIR/codex-activity.sqlite`. For Docker installs, the global hook runs it with `docker exec -i`; there is no new public ingestion endpoint. Delivery requires the user's existing permission to access Docker. Both dashboard and activity routes merge these deliveries over mounted history. A completion for an older turn cannot stop a newer recorded turn. Activity settings disable recording as well as display. Only the latest event per session is retained, up to 100 sessions.

`integration.connected` means at least one valid event has been received; it is not a current heartbeat or proof that hooks remain trusted. Check `last_received_at` and a new start/stop pair when validating a connection. Existing local-history titles are retained; a new session without readable history initially displays “Codex session” and its project name.

Terminal rollout events carry `activity_turn_id` and `activity_timestamp`. A terminal event for the same turn, recorded after the latest hook delivery, overrides a stale active hook. A failed `task_complete` with `usage_limit_exceeded` reports `activity_state: limited` and `status: Usage limit reached`; other terminal errors report `error` / `Turn failed`. This recovery depends on rollout visibility and can be delayed by Docker file sharing. It never infers failure from a zero credit balance alone.

## Workspaces and SQL

All mutations below require the existing CSRF header and same-origin checks.
SQL connection passwords are accepted only on save and never returned.

- `PUT /api/dashboard/layout`: `{apps: [app, app, app]}` updates only the three
  unique overview choices, preserving all other settings and credentials.
- `GET /api/sql/connections`: returns `{connections, demo}`. Each connection
  includes its ID, name, environment, endpoint, TLS options, `has_password` and
  a `revision` used to reject execution against an edited target. A configured
  monitoring connection appears as the read-only configuration entry `monitor`.
- `PUT /api/sql/connections/<id>`: save a UUID connection with `name`,
  `environment` (`development` or `production`), `host`, `port`, `database`,
  `username`, `sslmode`, optional `sslrootcert`, optional `password`, and optional
  `clear_password`. Blank passwords preserve the existing secret. At most 20
  named connections; duplicate names are rejected.
- `DELETE /api/sql/connections/<id>`: removes the saved connection and credential.
- `POST /api/sql/run`: `{connection_id, revision, query, mode, request_id,
  confirmed}`. Mode is `read` or `write`; writes require `confirmed: true`.
  Request IDs are UUIDs. Queries accept at most 20,000 characters and one statement.
  Demo mode rejects execution. One execution runs at a time per instance.
  Returns `columns`, positional `rows` (text or null), `row_count`, `affected_rows`,
  `status`, `truncated`, `row_limit`, `elapsed_ms`, `connection_name` and `environment`.
  Duplicate column names remain separate. Preview truncation does not change SQL semantics.
- `POST /api/sql/cancel/<request_id>`: requests cancellation of the active request;
  returns `{cancelled}`. A false value means the request is no longer active, not
  that a write failed. Never automatically retry a write after an interrupted response.
- `GET /api/sql/connections/<id>/activity`: reads activity for the selected
  connection using the existing monitoring adapter, or the demo snapshot in demo mode.
- `POST /api/sql/connections/<id>/<action>`: `cancel` or `terminate` with a signed
  session `token`. Tokens are validated against the selected connection and session
  identity; demo mode rejects controls.

The existing `/postgres` activity page and monitoring APIs remain available.
Workspace navigation uses `/#workspace/<app>` and `/#home` without reloading the page.

## Docker project grouping

`GET /api/docker/containers` still returns the flat container list and resource
summary, and now adds `groups`. Containers include Compose `project`, `service`
and `oneoff` metadata. A group includes `id`, `kind` (`project` or `container`),
`name`, `containers`, `total`, `running`, `active`, `state` and `manageable`.
Compose project IDs are SHA-256 hashes of the exact project label; names alone do
not establish membership. One-off Compose jobs remain standalone.

`POST /api/docker/projects/<project_id>/<start|stop>` requires CSRF and
`{container_ids: [...]}` containing the exact membership shown by the latest
read, at most 50 IDs. Membership is resolved again from Docker before any action.
Projects containing Codester are rejected. Containers already in the requested
state are skipped; other members run with bounded concurrency. The response
contains `ok`, `succeeded`, `failed` (ID/name/error), and a display `message`.
Partial failure returns `ok: false` with HTTP 200 so successful and failed members
can be reported together. Refresh the inventory for the resulting live state.
These actions start/stop existing containers, without Compose configuration or
health/dependency orchestration. Existing individual container routes remain.
