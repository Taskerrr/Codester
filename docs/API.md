# Local interfaces

All routes are private to the local single-user app. JSON responses are `no-store`; no CORS access is granted. Mutating requests need the `X-Codester-CSRF` value from the page's `csrf-token` meta tag. Hostnames are limited to localhost and loopback literals.

| Method | Route | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Process health, independent of upstream services |
| GET | `/api/dashboard` | Cached normalized snapshots, per-service status/message/last_success/data and demo/revision flags |
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
