# Codester

GitHub settings include an optional **Organisation** name. When set, the calendar counts
your authored default-branch commits over 182 days across repositories visible to the token
in that organisation, excluding personal repositories. The three most recently pushed
repositories have charts; local repository actions do not limit the organisation calendar.
Empty repositories count as zero activity. Queries are capped at 1,000 repositories and
300 commits per repository; reaching either cap marks the results as partial. This is a
commit calendar, not GitHub's full contribution calendar (issues, reviews and pull requests).
The token needs access to the organisation's repositories and Contents read permission.

A private, local dashboard for Codex subscription usage, Dagster runs, SigNoz service health, and local Docker containers. Designed for a 2560 × 720 touchscreen, with responsive layouts for other screens. Each developer runs their own instance and saves their own connections.

## Start locally

Weather is optional: **Settings > Display > Weather**, search for a town, choose a
result and units, then save. The rail shows current modelled conditions and a
**Next 6 hours** toggle. Forecasts refresh roughly hourly while the dashboard is
visible. Home is beside Settings. Weather uses [MET Norway](https://api.met.no/)
under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), summarised for
display; town search uses [Photon](https://github.com/komoot/photon) and
[OpenStreetMap contributors](https://www.openstreetmap.org/copyright). No API key
or GPS permission is needed. Providers receive your public IP and town search or
selected rounded coordinates. The selected location is saved as ordinary local
settings, not a secret. Use a town, not a private address.

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

## Install once and start at login (recommended)

Install Python 3.12+ or uv, then run from this checkout:

```sh
# macOS
./scripts/install.sh
```

```powershell
# Windows PowerShell
.\scripts\install.ps1
```

This installs Python dependencies in `.venv`, registers startup for your user, and
starts the dashboard at **http://127.0.0.1:8765**. No Docker, terminal window,
JavaScript build or administrator elevation is needed. macOS uses a LaunchAgent;
Windows uses a shortcut in your Startup folder and `pythonw.exe`. Company policies
can still restrict Python or scripts; the installer does not bypass those policies.
Windows startup is implemented but still needs verification on a Windows machine.
Linux users can continue using `scripts/start.sh` in the foreground.

macOS installs a runnable copy under `~/Library/Application Support/Codester` so
login startup does not depend on access to protected Documents/Desktop folders.
Windows runs from this checkout; keep it and its `.venv` in place.
Login startup runs the installed Python
directly, without downloading dependencies. The installer captures your PATH so
locally installed Docker, Git, SSH and Codex commands remain discoverable. Re-run it
after moving the checkout or changing tool locations. macOS SSH agent access uses
the login session's agent; passwords are stored in the OS credential vault.

### Choose startup behaviour in Settings

For a native Git checkout, **Settings > Display > Codester updates** can pull
fast-forward changes from your branch's configured upstream. Commit or review local
edits first: this action will not stash, reset or discard them. It leaves saved
settings and credentials alone and refuses tracked local-data paths. It updates
source only. Restart Codester afterwards (`.venv\Scripts\python.exe -m codester.native restart`
on Windows); if dependencies changed, rerun the native installer instead. The UI
reports which step is needed. Packaged/copied installations use their installer.

Open **Settings > Display > Startup**. Choose **Start Codester when I log in** and,
optionally, **Open the dashboard in my browser when Codester starts**, then press
**Save startup preferences**. These preferences save separately from service settings.
Turning off login startup leaves the current session running. The browser opens
in your default browser after the local server is listening, including manual
native restarts. Browser opening defaults off; installer updates preserve your choices.
The controls require the native installer. Docker and foreground runs show a setup hint.

### Switch an existing Docker installation

Leave Docker running for this one-time migration, then run:

```sh
./scripts/install.sh --from-docker
```

```powershell
.\scripts\install.ps1 --from-docker
```

Migration stops only the Codester container, disables its automatic restart, and
copies its complete `/data` directory to the native installation’s `.data` folder. Existing native data is renamed
to `.data.before-native-<timestamp>`; the original Docker volume is retained.
Saved credentials migrate to your OS vault and are verified before the copied
encryption key is removed. If migration/startup fails, the Docker volume remains
available: stop native startup and use `docker compose up -d codester` to return.
Do not run both instances on the same port.

Review Docker-specific saved paths (`/repos/...`, certificate paths) and
`host.docker.internal` addresses in Settings: native installations use host paths
and usually `127.0.0.1` for host-local services. Your existing host Codex login is
used; Docker's copied login is not installed over it. Docker container controls
still require Docker Desktop, but the rest of Codester can run without it.

### Restart, stop, remove startup and update

On macOS:

```sh
"$HOME/Library/Application Support/Codester/.venv/bin/python" -m codester.native restart
"$HOME/Library/Application Support/Codester/.venv/bin/python" -m codester.native stop
"$HOME/Library/Application Support/Codester/.venv/bin/python" -m codester.native uninstall
```

On Windows, use `.venv\Scripts\python.exe -m codester.native restart` (or `stop` / `uninstall`) from the checkout.
`stop` stops the current instance; `uninstall` also removes login startup. Both
preserve settings and activity hooks. Disable activity in Settings if you no longer
want hooks recording activity. To update, stop Codester, pull the repository updates,
then re-run the installer. Logs are in the installation’s `.data/native.log` (plus `.data/startup.log`
on macOS); the native log rotates at startup once it exceeds 5 MB.

### Live Codex activity

The installer registers native Python hooks for all local projects, preserving
other hooks and backing up the previous file as `hooks.json.before-codester-native`.
It enables live activity and switches off demo mode. Other saved settings remain.

**One-time review:** changed hook commands require review and trust in Codex's Hooks
settings or CLI `/hooks`, then a new turn. The installer never changes trust records.
See the [official hooks documentation](https://developers.openai.com/codex/hooks).

Hooks record only lifecycle metadata, never prompt or response bodies. They use an
absolute Python path and data directory, so work from any project. Native hooks can
record while the dashboard is stopped. Account usage is a separate connection;
remote SSH/WSL environments need installation where their Codex runtime runs.

Docker remains optional: `scripts/install-docker.sh` / `scripts/install-docker.ps1`
retain the container installer and Docker activity hooks.

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

Compose also mounts `CODESTER_REPOS_PATH` at `/repos` for repository actions. It defaults to the Codester checkout. Set it to the parent directory containing your checkouts before starting Compose, then use paths such as `/repos/Codester` in Settings:

```sh
CODESTER_REPOS_PATH=/Users/you/Documents/GitHub docker compose up --build -d
```

On Windows PowerShell, set it first with `$env:CODESTER_REPOS_PATH = "C:\\Users\\you\\Documents\\GitHub"`. Native startup uses each repository's normal absolute path.

The Docker container-management screen uses the local Docker CLI during native startup and the Docker socket from Compose. Socket access effectively grants the Codester process control of Docker, so keep the app loopback-only and run only trusted builds. Override `DOCKER_SOCKET_PATH` when the host socket uses a nonstandard path. Docker Desktop presents the mounted socket as group `0`; Linux users whose socket has another group should set `DOCKER_SOCKET_GID` to its numeric group ID. Codester exposes listing, live CPU/memory reads, start, and graceful stop; it cannot control its own container.

Docker still requires host memory for Docker Desktop. Native startup is the lightest option, particularly when using existing localhost tunnels.

## Managed SSH tunnels

Add each local forward in **Settings → SSH tunnels**, save, then use the tunnel switch beside the Settings button. Codester starts every forward together with OpenSSH keepalives and automatically reconnects a dropped established session with bounded backoff. Hover or focus the switch to inspect each connection. Turn the green switch off to disconnect them all; an initial connection failure stops and displays the OpenSSH error for correction.

Each tunnel card has a Test action. It saves the current form, creates a temporary forward on an unused local port, and confirms both SSH authentication and access to the configured remote service.

Each forward can use either the operating system's SSH agent or a password entered in Settings. Passwords use the operating system credential store in native installations (encrypted file storage in Docker) and are never returned by its API, written into the OpenSSH command, or logged. A small local askpass helper decrypts the selected password only when OpenSSH requests it. Private keys are never copied into Codester. The first connection records the server key in Codester's private data directory; a changed key is rejected.

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

Recent activity is opt-in. It reads six unarchived VS Code thread titles, project folder names and update timestamps from `CODESTER_CODEX_ACTIVITY_HOME/state_*.sqlite`, falling back to `CODEX_HOME/state_*.sqlite`, in SQLite read-only mode. Default native home: `~/.codex`. It scans backwards from each rollout file’s current end (up to 32 MiB), extracting `task_started`, `task_complete`, and `turn_aborted` to distinguish active, idle, and stopped turns. Each poll reads the file again rather than retaining an earlier active state; records spanning read boundaries are supported. The visible dashboard polls activity every 500 ms. If no lifecycle event is available, it falls back to a three-minute recency estimate. The activity API reports `activity_source` as `rollout` or `recency` so this distinction is observable. Message bodies and tool outputs are not returned or stored. Local metadata is undocumented and schema-checked. Account limits work without activity access. Remote VS Code / WSL may store state under a different user or operating system; point `CODESTER_CODEX_ACTIVITY_HOME` at the correct local home or run Codester there. Do not change an actively used Codex home to troubleshoot this app.

### Dagster

Targets a self-hosted deployment with no login. Uses `/graphql`, exact queued/running counts, up to 12 fetched rows per group, and recent failed runs. The three-row job feed shows running work first, then queued work, then the latest completed runs so it remains useful while idle. Starting and cancelling runs are included in the running total, with their actual status shown.

Oldest queue age follows up to two additional 100-run pages. If that cannot cover the queue, age is shown as unavailable rather than guessed from the newest runs. Details fetch the first 100 log events (up to 32KB displayed); open Dagster if the failure occurred later in a long run. No run configuration or secrets are requested.

### SigNoz

Requires the **v5 query API** and a read-capable API key, not an ingestion key. Save the URL/key, use **Find services**, then choose up to three service/measurement pairs. Disable a numbered row to show fewer measurements. Services are discovered from traces in the last 24 hours, limited to 200. A saved service stays selected even when absent from discovery.

Measurements cover incoming SERVER spans (`kind = 2`) over the window selected in Settings:
5 minutes, 15 minutes, 1 hour (default), 6 hours, or 24 hours. The same window applies
to request totals and recent errors. Total requests is available alongside request rate,
error rate, and p95 latency:

- Total requests: incoming server span count within the selected window.
- Request rate: span count / selected window in seconds.
- Error rate: failed server spans / all server spans × 100. No requests means unavailable.
- p95 latency: p95 duration in nanoseconds, converted to milliseconds.

These are trace-derived values. Sampling, missing instrumentation, and services that only emit internal/consumer spans affect coverage. This version does not query arbitrary infrastructure metrics. Recent errors show failed spans (all kinds) filtered by the separately selected service. Details fetch up to 30 trace spans from the last day; use the source link for complete exception details.

Requests by app ranks up to 200 services by their total recorded incoming requests within
the selected window. It is independent of the configured measurement rows. Trace sampling
can reduce these totals; they are not a replacement for an unsampled request counter.
If the grouped query fails, the dashboard keeps the other measurements and marks totals unavailable.

### GitHub

Choose GitHub in one of the three dashboard slots, then enable it in Settings and save a personal access token. The panel shows the last six months of contributions with month markers and three repository rows, with a 14-day commit sparkline for each. Without configured repositories these are the three most recently pushed repositories. Add local checkouts to pin the rows and enable repository actions.

Each local checkout reports its branch, uncommitted file count, and commits ahead of or behind its currently recorded upstream. The arrow button runs `git push` for committed changes. The rocket runs the repository's saved deploy command in that checkout, asynchronously, with a ten-minute limit. Codester records the commit after a successful deploy and marks a later commit or working-tree change as needing deployment. The first deploy state is unknown because Codester has no history for deployments launched elsewhere.

Deploy commands are trusted local configuration and can run anything available to the Codester process. Keep credentials in the SSH agent, environment, operating-system credential store, or the deployment tool itself; do not paste secrets into commands. Docker runs commands inside the Codester container and can use its forwarded SSH agent. Native startup can use locally installed deployment tools. Ahead/behind uses the checkout's existing remote-tracking ref and does not automatically fetch.

For private repositories, give a fine-grained token access to the repositories you want to display with **Metadata: read** and **Contents: read**. The token is saved in the operating system credential store for native installations and is never returned to the browser after saving.

The adapters are fixture/schema-tested, but your work-server versions, permissions, units, and deep links must be compared with the actual interfaces before relying on live values. Unsupported response shapes are explicit failures, never empty healthy dashboards.

### Docker Desktop

Expand a Compose project to see each service's ports beneath its name/image;
standalone containers show ports beneath their heading. For example,
`127.0.0.1:8080 → 80/tcp` maps host port 8080 to container port 80. Ports labelled
`internal` have no published host binding. `Ports not reported` means Docker
returned no port mappings, not proof the process has no listening sockets.
The display preserves bind addresses, IPv6 and TCP/UDP; it does not assume HTTP.

Docker shows Compose projects as collapsed rows, in both the Home panel/workspace and the larger Docker page. Expand a project to inspect its component containers and their status. Grouping uses Docker's Compose project labels; similarly named standalone containers remain separate. One-off Compose jobs stay separate so starting a project does not rerun them.

Small play/pause controls start or gracefully stop all existing containers in a project. Partially running projects show a count such as `1/2` and offer both icons. Component times use compact units such as `4m` or `2h`; full status is available on hover, and exit codes and unhealthy states remain visible. Stop requires a second tap within five seconds and requests a ten-second graceful stop. Expanded rows survive polling. Failed components are named explicitly, and the list refreshes to show the resulting state. Project membership is checked again before an action; changed projects must be refreshed first.

Codester itself is omitted from workload gauges and standalone controls. A mixed project containing Codester is visible but cannot be controlled here. Project actions support up to 50 containers and start/stop existing containers through Docker's API; they do not rebuild, create missing services, remove resources, or wait for Compose dependency health conditions. Resource reads cover at most 50 running containers. Individual container controls remain available through the API; the project rows are the primary UI controls.

Docker Desktop must be running and the current user must already have permission to use it. Native Windows/macOS startup uses the Docker CLI installed with Docker Desktop. Set `CODESTER_DOCKER_SOCKET` only when a nonstandard Unix socket should be used and the Docker CLI is unavailable.

## Storage and privacy

Native storage is `.data/` in the project directory (ignored by Git) for foreground/Windows startup, or `~/Library/Application Support/Codester/.data/` for the macOS installer. Docker storage is `/data`. Override with `CODESTER_DATA_DIR`. SQLite holds preferences, cached GitHub activity, deployment markers and credential references. Native installations save GitHub/SigNoz tokens and SSH passwords through Windows Credential Manager, macOS Keychain or Linux Secret Service. Enter secrets normally in Settings; no manual credential-store setup is required on Windows. Native storage never silently falls back to files when the OS vault is unavailable. Windows entries are scoped to the current user and local machine. Linux requires an available Secret Service keyring. POSIX directories/files use 0700/0600. On Windows, startup removes inherited directory grants and grants the current user access through `icacls`; use a new private directory, since existing explicit grants are not removed. Windows ACL behavior still needs validation on your work machine. On native startup, legacy encrypted credentials are copied to the OS vault and read back for verification before their database values and local encryption key are removed. A failed migration preserves the original credentials. Replaced/deleted vault entries are cleaned up, with failed cleanup retried on the next save or startup. Stop older Codester processes before upgrading. Database backups do not include OS credentials: moving to another machine/account requires re-entering secrets. Old backups may still contain legacy encrypted credentials and their key; protect or retire those separately. OS storage does not protect against malware running as your user.

The Docker image explicitly sets `CODESTER_SECRET_STORAGE=file` and retains Fernet-encrypted storage with a per-installation `secret.key` in its private volume; it cannot access the host OS vault. Headless users can explicitly select this mode, accepting that possession of both database and key permits decryption. There is no automatic downgrade of existing native references to file storage. Back up Docker database and key together and keep them out of Git.

Blank key and saved-password fields preserve their existing secrets. Switching a tunnel back to agent authentication or removing it deletes its saved password. Credentials are never returned by settings APIs or logged. Most monitoring data is cached in memory; GitHub activity is also persisted locally. Task titles and source errors may contain work information and are visible on your screen.

The server binds to loopback by default. Docker publishes only `127.0.0.1`. Host validation, origin checks, CSRF tokens, response size limits, and a restrictive content security policy protect the local app. This is a single-user local tool with **no multi-user authentication**; do not publish it on a shared network. The process can access configured private URLs by design.

The display has a clock/launcher rail and three configurable app channels. Settings stores three unique choices and their left-to-right order. Codex, Dagster, SigNoz, GitHub, and PostgreSQL have live overview renderers; Docker has a compact container summary and a full management screen. The Linux server tile remains a metrics placeholder; its launcher opens saved service commands. Dagster spinners stop on stale connections or when reduced motion is enabled.

Polling is shared across browser tabs: Dagster 10s, SigNoz 30s, Codex 60s, GitHub sparklines 60s, and PostgreSQL 10s (configurable to 30s or 60s). Sparkline reads fetch only the three displayed repositories and their last 14 days of commits. Local checkout status is cached centrally for four seconds. Failures back off to at most 5 minutes, preserve the last successful snapshot, and display its age. Each service has a separate worker; upstream requests have time/size limits. Settings changes discard in-flight old results. Demo data is never used as a fallback for a failed live connection.

Settings > SigNoz can keep the Home overview or replace it with Latest logs or Errors only. Log modes request the newest six rows every five seconds only while the Home panel is visible. Each row shows the app, shortened user ID and structured HTTP status/method/path when supplied, falling back to severity and message. Selecting a row opens its full in-memory detail in Debug. These Home rows are not saved to SQLite and are not a lossless log stream.

GitHub history and the last successful snapshot persist in the private local SQLite database.
Saved data appears immediately after a restart, marked stale until checked. A separate history
worker builds the initial calendar without blocking the repository charts and saves a checkpoint
after each repository. Its hourly refresh skips unchanged repositories and replaces the last
seven days of counts in changed repositories, preserving older history without double-counting.
After longer downtime, it also fetches the missing period. A full reconciliation every 30 days
accounts for rewritten or backdated history. Settings unrelated to GitHub do not discard history;
cache entries are isolated by API, account token, organisation and repository selection.

Each integration's header shows a muted grey countdown beside its title until the next scheduled refresh.
Intervals start after the previous fetch finishes. Refreshing, retrying, and a disconnected
browser are distinct states; hover or focus the countdown to see the last successful read.
The initial GitHub history job scans up to 182 days of commits across visible repositories
in the background. If interrupted, completed repository checkpoints survive a restart.

## Development and checks

```sh
uv sync --frozen
uv run pytest -q
uv run ruff check .
uv run ty check
uv run python -m codester
```

Environment: `CODESTER_PORT` (8765), `CODESTER_HOST` (127.0.0.1), `CODESTER_DATA_DIR`, optional `CODESTER_CODEX_BIN`, `CODEX_HOME`, `CODESTER_DOCKER_SOCKET`, `CODESTER_REPOS_PATH` for Compose, and standard `SSH_AUTH_SOCK`. Both scripts forward `--port` and `--host` arguments. Run one application process per storage directory so pollers, managed tunnels, and the encryption key are not duplicated.

See [validation notes](docs/VALIDATION.md), [API and adapter sources](docs/SOURCES.md), and [third-party marks](docs/THIRD_PARTY.md).


### Saved service commands

Open **Service commands** from Settings > Commands, the dashboard Linux launcher, or the Dagster header arrow. Add a service, choose an existing SSH connection and set its server folder. Commands are editable shell scripts, each with an optional confirmation checkbox. They run independently in that folder on the selected server, using the saved SSH identity without opening or changing a tunnel. Saving or viewing a service never executes its commands.

For a checkout at `/srv/Dagster`, save `git pull` as Pull latest, then use Open Dagster to reload the appropriate code location manually. This is command execution, not a verified deployment: exit zero means the command finished, not that the service is healthy. Health checks, log queries and rollback procedures can be added as named commands. Each click starts a separate shell; changes to the working folder or environment do not carry between commands.

Compare Git reads the **server** checkout, showing modified files, HEAD, and ahead/behind counts against its upstream and `origin/<comparison branch>`. These use the server's cached remote refs. Add/run `git fetch origin` when you want fresh refs; Compare Git does not fetch, pull, reload, or inspect a developer's local checkout. Git ownership and repository authentication errors are shown without automatically changing trust settings or credentials.

The last command, output and result are saved locally in SQLite; output is limited to the last 64 KB. Do not place secrets in commands or log output. The saved SSH password is masked from captured output, but arbitrary application secrets cannot be reliably identified. One command per service can run at a time in this Codester instance; this is not a lock shared with another person's instance. Commands run without an interactive terminal and cannot answer sudo/password prompts. After a ten-minute timeout, SSH interruption or Codester restart, the outcome is marked unknown; a remote command may still be running. Inspect the server before retrying. No server-side deployment agent or automatic rollback is installed.


### PostgreSQL activity and blocking locks

In Settings > PostgreSQL, enter the host, port, database, username and database password, then enable monitoring and choose Save & test. The password uses the existing credential store and never returns to the browser. For an SSH forward, select the saved tunnel to fill `127.0.0.1` and its local port; start the tunnel separately. SSH and database credentials are different. TLS defaults to requiring encryption. Use certificate verification for authenticated TLS, or explicitly disable database TLS when relying on an encrypted SSH tunnel to a server without PostgreSQL TLS. CA paths refer to the machine/container running Codester.

Select PostgreSQL in Settings > Display to show active queries, waiting sessions and blockers in one of the three dashboard columns. Click through to the activity page for SQL text, PID, user, application, query/transaction age, lock modes and blocker relationships. Idle transactions show their **last** query. Normal held locks are counted separately from blocked sessions. Monitoring covers the configured database, not every database on the server. Other-database and prepared-transaction blockers can be visible but are not controllable from this database's page.

Reads use `pg_stat_activity`, `pg_locks` and `pg_blocking_pids`, with one shared background worker, autocommit connections, a four-second statement timeout, at most 50 query rows and blocker inspection for at most 20 waiting sessions per refresh. Browser polling reads the cache. Query text is capped at 4,000 characters (PostgreSQL may truncate it further) and retained only in the in-memory snapshot, not stored as query history. Short queries between samples may not appear. These system-view queries are modest for typical deployments, but are not free; increase the refresh interval on busy servers.

For visibility into other users' activity, use a role with `pg_read_all_stats` or `pg_monitor`. PostgreSQL enforces cancellation/termination privileges; `pg_signal_backend` allows signalling other non-superuser sessions, while superuser sessions require a superuser. Codester does not grant roles. Limited visibility is explicitly labelled instead of treating hidden activity as zero workload.

The activity page offers **Cancel query** and **End session**, each with a confirmation naming the PID and showing the SQL. Cancellation does not guarantee that an open transaction releases its locks. Ending a session rolls back its open transaction, and the application may reconnect. Successful responses report a signal request, not proof all locks disappeared. Controls are unavailable for demo, disabled or stale connections. Short-lived signed tokens bind the target connection, backend start, query start, transaction start, state and query fingerprint; a single SQL statement rechecks that identity before signalling. PostgreSQL signalling cannot eliminate every race with concurrently changing queries. No live work-database sessions were terminated during development; integration tests use an isolated local PostgreSQL container.

### App workspaces and quick SQL

Use any left-rail app icon to open that app across the main content area. The
clock, SSH dots and launchers stay visible; **Home** returns to your three panels.
Click a panel's heading icon on Home to replace that slot. The picker and
Settings > Display share the same saved layout and require three unique apps.
Workspace navigation does not alter that layout. PostgreSQL has the first
purpose-built workspace; other apps currently expand their overview content.

Open **PostgreSQL** to add named development and production connections and run
SQL. The existing monitoring connection is available automatically when its
host/database/user are configured; edit it in Settings. Named SQL connections
are separate from the Home monitoring configuration. Passwords use the existing
credential store and are never returned to the browser. For SSH, use the local
forwarded host/port and connect through the usual SSH controls.

The compact editor grows from one line to ten above the full-width results table.
Use the connection dropdown to select, add or edit a connection. The editor always
runs in **Read & write** mode; Play executes directly. Each run uses a new connection and accepts one
statement; multi-statement scripts, persistent transactions, interactive commands
and COPY streams are not supported. Database permissions still apply. Successful
writes commit immediately; cancelling or losing a response does not prove that a
write was rolled back, so inspect the data before retrying.

Run with the green play icon or Ctrl/Command+Enter. Elapsed time appears beside it. One SQL request can run at a time per
Codester instance. Statement and lock timeouts are 30 and 3 seconds, respectively,
with cancellation requested after 35 seconds as a backstop. While running, the icon
becomes a red pause button that sends a cancellation request. There are no automatic retries. Demo mode disables SQL
execution. The query runner uses the database role's normal schema search path;
the separate monitoring adapter continues to use `pg_catalog`.

Results retain text representations (including large integers), duplicate column
names, and explicit NULL values. The preview holds up to 500 rows, 4,000 characters
per cell and approximately 2 MB of text; truncation is labelled. Results are
streamed and drained to completion, so limiting the preview does not limit the
query's work or the number of rows a write changes. Add SQL LIMIT clauses when
appropriate. Drafts and results survive workspace/connection switches in the
current page, but are not saved across reloads. **Activity & locks** inspects the
selected connection; existing session-control permissions and confirmations apply.

### Remote repository updates

For repository-owned deployments, choose **Repository script** under **Settings >
GitHub > Repository actions**. Select the SSH connection, enter the absolute checkout
root and a relative script path such as `scripts/deploy.sh`. Optionally enable
**Pull latest before running** for a fast-forward update from the current branch's
upstream. Save, then use **Deploy** in the GitHub workspace. No staging server is needed.

The server needs Bash, Git and `flock`. Codester requires a clean checkout, holds a
server-side lock for that checkout, and runs the committed script with Bash error
and pipeline failure handling. It prints the commit and exports `CODESTER_DEPLOY_COMMIT`.
The script owns build, pytest, production replacement and health checks. A script
path is configuration, not a copy of the script; future changes stay in the website repo.

See the [Docker + pytest deployment example](examples/deployment/README.md), including
an adaptable script and Compose file. It tests the same image it deploys and retains
the previous image. Each website needs its own Dockerfile/test dependencies, Compose
settings and health endpoint. Codester does not add these to other repositories.

Repository-script runs have a 30-minute limit. Failed scripts report failure; SSH
interruption, timeout or app restart can leave an unknown remote outcome. Inspect the
server before retrying. Exit zero only confirms the script's own result. Staging,
automatic rollback and database migration recovery are not built into this runner.

**Custom command** keeps the existing multiline-script workflow below:

In **Settings > GitHub > Repository actions**, add a repository, select an existing
SSH connection, enter its absolute server folder and save an update script. For
example, `git pull --ff-only && docker compose up -d --build`. Multiline scripts
are supported; use `&&` when later steps should only run after a successful step.
**Confirm before updating** is optional. Local checkout fields can remain blank.

Open the GitHub workspace and press **Update**. The saved SSH identity runs the
script in the server folder without starting a forwarding tunnel. Updating shows
elapsed time; tap the status to expand the exact script and command output. The
latest result survives reloads. Success means the command exited successfully,
not that deployment health was checked. Interrupted SSH sessions and commands
still running when Codester restarts report an unknown outcome. Demo mode never
runs remote repository updates. Existing local Push/Deploy controls remain separate.

### SigNoz debugging workspace

Open **SigNoz** from the left rail for the full-height Debug screen. **Charts** reveals
the existing overview charts. **All logs** and **Errors** select the feed; use the
labelled fields to search message substrings (case-sensitive), exact app/user/trace,
severity and a range from five minutes to 24 hours. Press **Search** or Ctrl/Command+Enter
to apply filters upstream. Clicking an app or user searches that value immediately.

Select a message to pause updates and inspect its timestamp, identities, message,
stack text and supplied attributes. **Copy debug context** includes the source, log
and trace IDs, filters, message and attributes; **Copy message** copies just the body.
**Open trace** links to SigNoz when a valid trace ID is supplied. **Logs for this trace**
clears other filters and searches all levels within the selected range. On narrow
screens, details replace the list; **Close** or Escape returns to the selected log.

Uses the saved SigNoz URL and query API key with the
[v5 Logs API](https://signoz.io/docs/logs-management/logs-api/search-logs/).
Logs must already be ingested into SigNoz; trace instrumentation alone does not
supply them. The app must send user.id for it to appear, otherwise the column shows
an em dash. There is no user identity inference.

Checks every five seconds while the workspace is visible, sharing identical searches
across tabs. **Older/Newer** browse 100-row pages with a fixed time window, up to 1,000
rows. **Resume live** returns to latest. Busy periods can skip live entries; late
ingestion may change historical pages. Use SigNoz for the full history. Messages
are capped at 4,000 characters; attributes at 60 fields, 1,000 characters each and
12,000 total characters. Truncation is labelled. Content is rendered as text.
Logs and investigation state stay in memory. Failed searches retain only same-search
stale data and do not interrupt trace charts. Demo filters work without contacting
SigNoz. Live compatibility with the work server still needs verification.
