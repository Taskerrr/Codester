# Codester

A private, local dashboard for Codex subscription usage, Dagster runs, and SigNoz service health. Designed for a 2560 × 720 touchscreen, with responsive layouts for other screens. Each developer runs their own instance and saves their own connections.

## Start locally

Install **Python 3.12+** or [uv](https://docs.astral.sh/uv/getting-started/installation/). Clone this repository and run:

**macOS / Linux**

```sh
./scripts/start.sh
```

**Windows PowerShell** (Python fallback uses the Python 3.12 launcher)

```powershell
.\scripts\start.ps1
```

Open **http://localhost:8765**. The app starts in clearly labelled demo mode. Open Settings, enter connections, save, test each saved connection, then turn off demo mode. Enabling a service is independent of demo mode; demo makes no automatic upstream requests. Explicit connection tests always use real saved settings.

The server uses Waitress, not Flask's development server. No JavaScript build or database service is needed. Startup uses the committed lockfile when uv is available. The pip fallback resolves compatible package ranges.

Move the browser onto your secondary display and use the expand icon below the clock or your browser's fullscreen command. The settings cog is in the top-right corner. Touch errors to read details, then open the source service if needed. Browser tab placement is managed by your OS, not Codester. Monitor/touch-driver compatibility, particularly on macOS, is separate from this web app.

## Docker

With Docker Desktop running:

```sh
docker compose up --build -d
```

Visit the same localhost URL. Settings persist in the `codester-data` volume across container updates. `docker compose down` preserves settings; `docker compose down -v` deletes them. To update, pull changes and run the build command again.

Docker packaging supports Dagster and SigNoz directly. **Codex is optional and unavailable in the default image**: it contains neither your host's Codex executable nor credentials. Use native startup for Codex account and VS Code activity monitoring. Do not mount a macOS/Windows executable into a Linux container or expect it to run. There is no host helper in v1.

Docker still requires host memory for Docker Desktop. Native startup is the lightest option, particularly when using existing localhost tunnels.

## Connections through SSH tunnels

| Runtime | API URL example | Browser URL example |
| --- | --- | --- |
| Native Flask | `http://localhost:8000` | Leave blank |
| Docker Desktop | `http://host.docker.internal:8000` | `http://localhost:8000` |

These are examples; use your actual forwarded ports. The API URL must be reachable from the process running Flask. The browser URL is only for source links. Base paths are preserved. TLS verification stays enabled and redirects are not followed.

A loopback-only SSH forward is not guaranteed to be reachable from Docker. If a connection test fails, verify the tunnel and try native startup. Do not expose your tunnels to the LAN just to make Docker work. Codester does not create or alter SSH forwarding. Proxy logins and SSO are not supported by these v1 adapters.

### Codex

Sign into Codex with your **ChatGPT account** on the same machine/user as Codester. The app finds `codex` on PATH, or the VS Code extension's bundled executable. Account limits use the documented app-server `account/rateLimits/read` method. This is not general ChatGPT chat usage or OpenAI API billing. No paid model request is made.

If discovery fails, set `CODESTER_CODEX_BIN` to the absolute executable path before starting. It is a path, not a command with flags. Keep sign-in in Codex; Codester has no password/token paste form. The app starts its own short-lived app-server process for account reads and never starts, resumes, cancels, or subscribes to work threads.

Recent activity is opt-in. It reads six unarchived VS Code thread titles, project folder names and update timestamps from `CODEX_HOME/state_*.sqlite` in SQLite read-only mode. Default home: `~/.codex`. It does not read prompts, messages, session bodies, or tool outputs. Database metadata is undocumented and schema-checked. **It does not prove a task is running.** Account limits work without activity access. Remote VS Code / WSL may store state under a different user or operating system; point `CODEX_HOME` at the correct local home or run Codester there. Do not change an actively used Codex home to troubleshoot this app.

### Dagster

Targets a self-hosted deployment with no login. Uses `/graphql`, exact queued/running counts, up to 12 displayed rows per group, and recent failed runs. Starting and cancelling runs are included in the running total, with their actual status shown.

Oldest queue age follows up to two additional 100-run pages. If that cannot cover the queue, age is shown as unavailable rather than guessed from the newest runs. Details fetch the first 100 log events (up to 32KB displayed); open Dagster if the failure occurred later in a long run. No run configuration or secrets are requested.

### SigNoz

Requires the **v5 query API** and a read-capable API key, not an ingestion key. Save the URL/key, use **Find services**, then choose up to three service/measurement pairs. Disable a numbered row to show fewer measurements. Services are discovered from traces in the last 24 hours, limited to 200. A saved service stays selected even when absent from discovery.

Measurements cover the last 15 minutes of incoming SERVER spans (`kind = 2`):

- Request rate: span count / 900 seconds.
- Error rate: failed server spans / all server spans × 100. No requests means unavailable.
- p95 latency: p95 duration in nanoseconds, converted to milliseconds.

These are trace-derived values. Sampling, missing instrumentation, and services that only emit internal/consumer spans affect coverage. This version does not query arbitrary infrastructure metrics. Recent errors show failed spans (all kinds) filtered by the separately selected service. Details fetch up to 30 trace spans from the last day; use the source link for complete exception details.

The adapters are fixture/schema-tested, but your work-server versions, permissions, units, and deep links must be compared with the actual interfaces before relying on live values. Unsupported response shapes are explicit failures, never empty healthy dashboards.

## Storage and privacy

Native storage is `.data/` in the project directory (ignored by Git). Docker storage is `/data`. Override with `CODESTER_DATA_DIR`. SQLite holds preferences; SigNoz keys are encrypted with Fernet using a per-installation `secret.key`. POSIX directories/files use 0700/0600. On Windows, startup removes inherited directory grants and grants the current user access through `icacls`; use a new private directory, since existing explicit grants are not removed. Windows ACL behavior still needs validation on your work machine. Encryption does not protect against someone with access to both database and key. Back up both together and keep them out of Git.

Blank key fields preserve the saved key; the removal checkbox explicitly deletes it. Credentials are never returned by settings APIs or logged. Live monitoring data is cached in memory, not saved as history. Task titles and source errors may contain work information and are visible on your screen.

The server binds to loopback by default. Docker publishes only `127.0.0.1`. Host validation, origin checks, CSRF tokens, response size limits, and a restrictive content security policy protect the local app. This is a single-user local tool with **no multi-user authentication**; do not publish it on a shared network. The process can access configured private URLs by design.

The display has a clock/overview rail and three compact service channels. Mint quota meters, purple pipeline indicators and orange health graphs carry the service colors. Live mini-graphs collect up to 30 successful readings per browser tab; they start with one point, reset when connection settings change, and do not invent historical data. Demo mode uses sample curves. Dagster spinners stop on stale connections or when reduced motion is enabled.

Polling is shared across browser tabs: Dagster 10s, SigNoz 30s, Codex 60s. Failures back off to at most 5 minutes, preserve the last successful snapshot, and display its age. Each service has a separate worker; upstream requests have time/size limits. Settings changes discard in-flight old results. Demo data is never used as a fallback for a failed live connection.

## Development and checks

```sh
uv sync --frozen
uv run pytest -q
uv run ruff check .
uv run ty check
uv run python -m codester
```

Environment: `CODESTER_PORT` (8765), `CODESTER_HOST` (127.0.0.1), `CODESTER_DATA_DIR`, optional `CODESTER_CODEX_BIN` and `CODEX_HOME`. Both scripts forward `--port` and `--host` arguments. Run one application process per storage directory so pollers and the encryption key are not duplicated.

See [validation notes](docs/VALIDATION.md), [API and adapter sources](docs/SOURCES.md), and [third-party marks](docs/THIRD_PARTY.md).
