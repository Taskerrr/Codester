# Codester

A private, local dashboard for Codex subscription usage, Dagster runs, SigNoz service health, and local Docker containers. Designed for a 2560 × 720 touchscreen, with responsive layouts for other screens. Each developer runs their own instance and saves their own connections.

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

Open **http://localhost:8765**. The app starts in demo mode. Open Settings, choose the three apps shown in the overview, enter connections, save, test each saved connection, then turn off demo mode. Codex, Dagster, and SigNoz are the default columns. Enabling a service is independent of demo mode; demo makes no automatic upstream requests. Explicit connection tests always use real saved settings.

The server uses Waitress, not Flask's development server. No JavaScript build or database service is needed. Startup uses the committed lockfile when uv is available. The pip fallback resolves compatible package ranges.

Move the browser onto your secondary display and use the expand icon below the clock or your browser's fullscreen command. The settings cog is in the top-right corner. Touch errors to read details, then open the source service if needed. Browser tab placement is managed by your OS, not Codester. Monitor/touch-driver compatibility, particularly on macOS, is separate from this web app.

## Docker

With Docker Desktop running:

```sh
docker compose up --build -d
```

Visit the same localhost URL. Settings persist in the `codester-data` volume across container updates. `docker compose down` preserves settings; `docker compose down -v` deletes them. To update, pull changes and run the build command again.

Docker packaging includes the Linux Codex CLI. To reuse the ChatGPT login already held by Codex on your computer, import its local authentication cache once after starting the container:

**macOS / Linux**

```sh
./scripts/docker-import-codex.sh
```

**Windows PowerShell**

```powershell
.\scripts\docker-import-codex.ps1
```

The copied login stays inside the private `codester-data` volume and Codex can refresh it there. Treat both the source `~/.codex/auth.json` and Docker volume as credentials. The helper never prints the file. If Codex stores credentials only in the operating-system keychain, run `codex login` with file credential storage first or use native Codester startup. Enable Codex monitoring in Settings after importing.

Compose mounts the host's `~/.codex` directory at `/host-codex` read-only so the optional recent-activity view can see current VS Code thread metadata without changing it. Set `CODEX_HOST_HOME` before running Compose if the host uses a different Codex home. Authentication remains in the separate writable data volume; the app only queries the mounted SQLite thread index and never reads session bodies.

The Docker container-management screen uses the local Docker CLI during native startup and the Docker socket from Compose. Socket access effectively grants the Codester process control of Docker, so keep the app loopback-only and run only trusted builds. Override `DOCKER_SOCKET_PATH` when the host socket uses a nonstandard path. Docker Desktop presents the mounted socket as group `0`; Linux users whose socket has another group should set `DOCKER_SOCKET_GID` to its numeric group ID. Codester exposes listing, live CPU/memory reads, start, and graceful stop; it cannot control its own container.

Docker still requires host memory for Docker Desktop. Native startup is the lightest option, particularly when using existing localhost tunnels.

## Managed SSH tunnels

Add each local forward in **Settings → SSH tunnels**, save, then use the tunnel switch beside the Settings button. Codester starts every forward together with OpenSSH keepalives and automatically reconnects a dropped established session with bounded backoff. Hover or focus the switch to inspect each connection. Turn the green switch off to disconnect them all; an initial connection failure stops and displays the OpenSSH error for correction.

Each tunnel card has a Test action. It saves the current form, creates a temporary forward on an unused local port, and confirms both SSH authentication and access to the configured remote service.

Each forward can use either the operating system's SSH agent or a password entered in Settings. Passwords are encrypted in Codester's local secret store and are never returned by its API, written into the OpenSSH command, or logged. A small local askpass helper decrypts the selected password only when OpenSSH requests it. Private keys are never copied into Codester. The first connection records the server key in Codester's private data directory; a changed key is rejected.

Use `http://127.0.0.1:LOCAL_PORT` as a Dagster or SigNoz API URL for a Codester-managed forward. Under Docker, the forward and Flask both run inside the Codester container. A browser cannot open that container-local address directly, so set the service's Browser URL to an address your host browser can reach when source links are needed.

Docker Desktop passes its host SSH agent socket into Codester when agent authentication is selected. Native startup uses the current `SSH_AUTH_SOCK`. Password authentication works without an agent. SSO, MFA prompts, jump-host, and bastion flows are not supported by the managed button; keep using an externally managed tunnel for those setups.

### Externally managed tunnels

| Runtime | API URL example | Browser URL example |
| --- | --- | --- |
| Native Flask | `http://localhost:8000` | Leave blank |
| Docker Desktop | `http://host.docker.internal:8000` | `http://localhost:8000` |

These are examples; use your actual forwarded ports. The API URL must be reachable from the process running Flask. The browser URL is only for source links. Base paths are preserved. TLS verification stays enabled and redirects are not followed.

A loopback-only host forward is not guaranteed to be reachable from Docker. If an externally managed connection test fails, verify the tunnel and try native startup. Do not expose your tunnels to the LAN just to make Docker work.

### Codex

Sign into Codex with your **ChatGPT account** on the same machine/user as Codester. The app finds `codex` on PATH, or the VS Code extension's bundled executable. Account limits use the documented app-server `account/rateLimits/read` method. This is not general ChatGPT chat usage or OpenAI API billing. No paid model request is made.

If discovery fails, set `CODESTER_CODEX_BIN` to the absolute executable path before starting. It is a path, not a command with flags. Keep sign-in in Codex; Codester has no password/token paste form. The app starts its own short-lived app-server process for account reads and never starts, resumes, cancels, or subscribes to work threads.

Recent activity is opt-in. It reads six unarchived VS Code thread titles, project folder names and update timestamps from `CODESTER_CODEX_ACTIVITY_HOME/state_*.sqlite`, falling back to `CODEX_HOME/state_*.sqlite`, in SQLite read-only mode. Default native home: `~/.codex`. It does not read prompts, messages, session bodies, or tool outputs. Database metadata is undocumented and schema-checked. **It does not prove a task is running.** Account limits work without activity access. Remote VS Code / WSL may store state under a different user or operating system; point `CODESTER_CODEX_ACTIVITY_HOME` at the correct local home or run Codester there. Do not change an actively used Codex home to troubleshoot this app.

### Dagster

Targets a self-hosted deployment with no login. Uses `/graphql`, exact queued/running counts, up to 12 fetched rows per group, and recent failed runs. The three-row job feed shows running work first, then queued work, then the latest completed runs so it remains useful while idle. Starting and cancelling runs are included in the running total, with their actual status shown.

Oldest queue age follows up to two additional 100-run pages. If that cannot cover the queue, age is shown as unavailable rather than guessed from the newest runs. Details fetch the first 100 log events (up to 32KB displayed); open Dagster if the failure occurred later in a long run. No run configuration or secrets are requested.

### SigNoz

Requires the **v5 query API** and a read-capable API key, not an ingestion key. Save the URL/key, use **Find services**, then choose up to three service/measurement pairs. Disable a numbered row to show fewer measurements. Services are discovered from traces in the last 24 hours, limited to 200. A saved service stays selected even when absent from discovery.

Measurements cover the last 15 minutes of incoming SERVER spans (`kind = 2`):

- Request rate: span count / 900 seconds.
- Error rate: failed server spans / all server spans × 100. No requests means unavailable.
- p95 latency: p95 duration in nanoseconds, converted to milliseconds.

These are trace-derived values. Sampling, missing instrumentation, and services that only emit internal/consumer spans affect coverage. This version does not query arbitrary infrastructure metrics. Recent errors show failed spans (all kinds) filtered by the separately selected service. Details fetch up to 30 trace spans from the last day; use the source link for complete exception details.

Top apps ranks the three services with the most incoming SERVER spans over the last five minutes and displays each count as requests per second. It is independent of the configured measurement rows. If the installed SigNoz version cannot run that grouped query, the dashboard keeps the other measurements and shows Top apps as unavailable.

### GitHub

Choose GitHub in one of the three dashboard slots, then enable it in Settings and save a personal access token. The panel shows the last 12 weeks of contributions and the three most recently pushed repositories, with a 14-day commit sparkline for each. It refreshes every five minutes.

For private repositories, give a fine-grained token access to the repositories you want to display with **Metadata: read** and **Contents: read**. The token is encrypted in Codester's local data directory and is never returned to the browser after saving.

The adapters are fixture/schema-tested, but your work-server versions, permissions, units, and deep links must be compared with the actual interfaces before relying on live values. Unsupported response shapes are explicit failures, never empty healthy dashboards.

### Docker Desktop

When Docker is selected as one of the three dashboard columns, that column shows running and memory gauges plus a scrollable list of power controls. Its header arrow opens the larger container screen with the same controls. Both the gauges and control lists omit Codester because it cannot restart itself after stopping; zero running therefore means no manageable workload containers are active. Controllable containers are ordered with running containers first and then alphabetically within each state. Start is immediate. Stop requires a second tap within four seconds and asks Docker for a ten-second graceful stop. Requests are bounded, resource reads cover at most 50 running containers, and container identifiers are validated against the current local list. No image removal, container deletion, shell access, or compose operations are exposed.

Docker Desktop must be running and the current user must already have permission to use it. Native Windows/macOS startup uses the Docker CLI installed with Docker Desktop. Set `CODESTER_DOCKER_SOCKET` only when a nonstandard Unix socket should be used and the Docker CLI is unavailable.

## Storage and privacy

Native storage is `.data/` in the project directory (ignored by Git). Docker storage is `/data`. Override with `CODESTER_DATA_DIR`. SQLite holds preferences; SigNoz keys and saved SSH passwords are encrypted with Fernet using a per-installation `secret.key`. POSIX directories/files use 0700/0600. On Windows, startup removes inherited directory grants and grants the current user access through `icacls`; use a new private directory, since existing explicit grants are not removed. Windows ACL behavior still needs validation on your work machine. Encryption does not protect against someone with access to both database and key. Back up both together and keep them out of Git.

Blank key and saved-password fields preserve their existing secrets. Switching a tunnel back to agent authentication or removing it deletes its saved password. Credentials are never returned by settings APIs or logged. Live monitoring data is cached in memory, not saved as history. Task titles and source errors may contain work information and are visible on your screen.

The server binds to loopback by default. Docker publishes only `127.0.0.1`. Host validation, origin checks, CSRF tokens, response size limits, and a restrictive content security policy protect the local app. This is a single-user local tool with **no multi-user authentication**; do not publish it on a shared network. The process can access configured private URLs by design.

The display has a clock/launcher rail and three configurable app channels. Settings stores three unique choices and their left-to-right order. Codex, Dagster, and SigNoz have live overview renderers; Docker has a compact container summary and a full management screen. PostgreSQL, Linux servers, and GitHub currently provide selectable placeholders for later integrations. Dagster spinners stop on stale connections or when reduced motion is enabled.

Polling is shared across browser tabs: Dagster 10s, SigNoz 30s, Codex 60s. Failures back off to at most 5 minutes, preserve the last successful snapshot, and display its age. Each service has a separate worker; upstream requests have time/size limits. Settings changes discard in-flight old results. Demo data is never used as a fallback for a failed live connection.

## Development and checks

```sh
uv sync --frozen
uv run pytest -q
uv run ruff check .
uv run ty check
uv run python -m codester
```

Environment: `CODESTER_PORT` (8765), `CODESTER_HOST` (127.0.0.1), `CODESTER_DATA_DIR`, optional `CODESTER_CODEX_BIN`, `CODEX_HOME`, `CODESTER_DOCKER_SOCKET`, and standard `SSH_AUTH_SOCK`. Both scripts forward `--port` and `--host` arguments. Run one application process per storage directory so pollers, managed tunnels, and the encryption key are not duplicated.

See [validation notes](docs/VALIDATION.md), [API and adapter sources](docs/SOURCES.md), and [third-party marks](docs/THIRD_PARTY.md).
