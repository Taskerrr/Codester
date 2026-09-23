# Validation record

Implementation checked on macOS (Apple Silicon), 13 September 2026.

## Completed

- 56 pytest cases: encrypted credential storage/restart/isolation, dashboard selection persistence and validation, managed SSH agent/password command, test, and control boundaries, first-connection failure handling, Docker list/control boundaries, host/origin/CSRF protections, demo isolation, real-connection service discovery, transport authentication/errors/size limits/timeouts, Dagster counts/pagination/detail bounds, SigNoz native v5 payloads and response decoding, metric units and missing data, Codex process lifecycle and read-only metadata, polling stale retention/backoff, and in-flight settings changes including URL/key pairing.
- Ruff lint and ty type checks pass. Source and wheel builds succeed, with templates and static files included.
- `scripts/start.sh` launches the actual local Waitress server. Demo-mode resident memory measured around 49 MB with idle CPU at 0% in a single sample; this excludes browser/Docker and is not a sustained benchmark.
- Live account read succeeded using the VS Code extension's bundled Codex `0.154.0-alpha.6.2`, returning two usage windows. Only normalized usage data is exposed by the adapter.
- Read-only local inspection found six recent VS Code threads using the current `state_5.sqlite` schema. No running-state claim is made from timestamps. No prompts or session bodies are read.
- Dagster overview and detail queries validate against the Dagster GraphQL 1.13.22 schema.
- Browser checks include the current four-column design at 2560×720 and its 1707×480 (150% equivalent) viewport. Both fit without page scroll; the narrow responsive layout stacks and scrolls.
- Browser checks cover the default columns, a non-default Docker/PostgreSQL/GitHub layout, selected launcher states, and the Docker unavailable screen at 2560×720.
- Browser interactions: error expansion, Back and restored keyboard focus, saved settings, encrypted-key non-return, mocked service discovery and dropdown choices, persistence across reload, and desktop/mobile settings. No browser console errors observed.
- Docker Compose configuration validates. Dockerfile uses a non-root user; only loopback is published.
- The rebuilt Docker container is healthy with OpenSSH installed, and Docker Desktop exposes its SSH-agent socket inside the container. This machine's agent currently has no loaded identities, so an authenticated live tunnel was not attempted.

Local screenshots are in ignored `artifacts/` so work screenshots cannot accidentally enter Git. All captured dashboard screenshots use demo data.

## Still requires the work environment

- Windows native startup and NTFS permission handling. The PowerShell script and code paths are implemented but were not executed on Windows here.
- Live Docker container listing and start/stop behavior: Docker Desktop's daemon was unavailable. The adapter and HTTP controls are fixture-tested, while the Docker screen's unavailable state was browser-tested.
- Actual Dagster/SigNoz installed versions, read permissions, values and source links. The adapters are not certified against the company's servers yet.
- Physical touchscreen reach, readability and touch-driver behavior. Browser dimensions simulate resolution/scaling, not hardware.
- Reliable live VS Code task state. This release deliberately exposes recent local metadata only. A separate app-server cannot establish what the extension is currently executing.

## Work acceptance steps

1. Start natively on each machine, open Settings, and test the saved Codex connection while signed into ChatGPT through Codex.
2. Add the real SSH forwards, choose agent or saved-password authentication, and tap the link button. Save `127.0.0.1` Dagster and SigNoz URLs. Test each; discover services and choose measurements.
3. Disable demo mode. Compare queue/running/failed counts with Dagster. Compare the 15-minute measurements and five-minute Top apps ranking with the matching trace filters in SigNoz.
4. Tap one known failure from each source and verify its source link and detail window.
5. Temporarily close a tunnel. Confirm the service becomes stale/offline while the other services keep updating; reopen and confirm recovery.
6. Choose three different overview apps, save, restart Codester, and verify their order persists.
7. Start Docker Desktop, open the Docker screen, and compare its list with Docker Desktop. Start a safe stopped test container, then use the two-tap stop control.
8. On the physical display, check fullscreen at your preferred OS scaling.

## Display redesign

The display removes the header/footer and explanatory copy, adds a clock rail, radial service summaries, split activity lists, and five-minute SigNoz traffic rankings. Settings and error-detail flows remain available. Current screenshots are `artifacts/codester-new-2560x720.png` and `artifacts/codester-scaled-1707x480.png`.

## Codex lifecycle integration — 15 September 2026

- Added Docker installers for macOS/Linux and PowerShell; Python and runtime libraries remain in the existing container.
- Verified on macOS with the VS Code extension's `codex-cli 0.154.0-alpha.6.2`. Its `hooks/list` API discovers all four user hooks with no warnings or errors. Trust approval is still required; this is not yet proof of a completed real VS Code turn.
- Exact installed hook command → Docker event store → live API → Playwright: simulated completion stored in 114 ms and rendered as a tick in 911 ms. A second project remained active; interruption rendered correctly; the tick remained through the next five-second dashboard refresh. Temporary verification sessions were removed afterward.
- Re-running the installer preserves identical hook configuration bytes, avoiding unnecessary trust changes. Existing unrelated handlers are preserved in regression tests.
- Full suite: 79 passing tests. Ruff and focused type checks pass. The pre-existing full-project type error in `codester/demo.py` is outside this change.
- Windows installer is provided but has not been executed on Windows. Remote SSH/WSL sessions and platform-specific approval flows remain unverified.

## Usage-limit recovery and PostgreSQL logo — 15 September 2026

- Confirmed the real rollout ended at 15:04:40.740 UTC (16:04:40 London) with `task_complete.error.codex_error_info = usage_limit_exceeded`.
- Added same-turn terminal reconciliation so a missing Stop hook cannot permanently mask a visible completion. New turns and later continuations remain active. No hook configuration change or renewed approval is needed.
- 84 tests pass, including actual failure-payload shape and all terminal states. Browser checks show the usage-limit label without a spinner through the dashboard refresh. Docker file synchronization can still delay fallback detection.
- Replaced the PostgreSQL outline/circular treatment with the official three-color SVG. Checked launcher and settings image loading in Playwright.

## Shared workspaces and SQL runner, 20 September 2026

- Full suite with `CODESTER_TEST_PG_PORT` set to a disposable PostgreSQL 17 container:
  188 passed, four existing integration tests skipped. The new SQL integration
  cases run against a loopback-only container and never use saved user connections.
- New coverage includes layout-only updates and rejection of duplicates, unchanged
  unrelated settings/credentials, named connection save/edit/delete and secret
  non-disclosure, CSRF, demo isolation, explicit write confirmation, stale target
  rejection, selected-connection activity/control routing, and cancellation.
- Real database checks cover read-only enforcement, writes and RETURNING, multi-statement
  rejection without partial execution, Unicode, duplicate column names, NULL, integers
  beyond JavaScript's exact range, empty results, row/cell/byte preview limits, cancellation
  before dispatch and during execution, and recovery after SQL errors.
- Ruff and focused ty checks pass; JavaScript modules pass Node syntax checks.
- Playwright verified every launcher, Home replacement and persistence after reload,
  keyboard picker navigation/Escape/focus return, SQL draft/results retention, separate
  drafts for development/production connections, connection forms and deletion,
  selected-connection activity, blocking-lock tabs, write confirmation and cancellation.
- SQL results render HTML-like content as text. Browser checks produced no JavaScript
  exceptions. The expected cancelled SQL request returns an error response.
- SQL workspace fits at 2560×720, 1707×480 and 1000×650 without page overflow.
  At 390×844, editor/results stack and the page scrolls vertically without horizontal
  overflow. Physical touchscreen and Windows testing remain outstanding.

## Docker Compose project grouping, 20 September 2026

- Full suite: 189 passed, 10 skipped (including optional SQL tests requiring the
  disposable PostgreSQL instance). Docker/app subset: 42 passed.
- New checks cover Compose label parsing from CLI and socket responses, isolated
  membership, one-off jobs, partial/paused states, idempotent target selection,
  membership changes before execution, protection for Codester's project, partial
  failures, project API validation and CSRF.
- Playwright with an isolated simulated Docker inventory verified collapsed
  projects, preserved expansion through polling, project start/stop and confirmation,
  partial failure messages, Home-panel grouping, standalone page grouping, Escape
  dismissal and narrow-screen overflow. No real user containers were started or stopped.
- Ruff, focused type checks and JavaScript syntax checks passed.

## Compact PostgreSQL workspace, 20 September 2026

- SQL/app subset: 43 passed, six optional real-database tests skipped. JavaScript syntax checks pass.
- Playwright with intercepted SQL responses verified fixed write-mode requests, Play/Pause,
  elapsed time, cancellation dispatch, per-connection draft/result restoration, connection
  editing, empty-connection creation and activity navigation, with no JavaScript exceptions.
- One-line editor is 44px high at 2560×720, leaving 572px for the empty results area.
  Ten lines grow to 240px. Desktop checks at 2560×720, 1707×480 and 1000×650
  have no page overflow; 390×844 scrolls vertically without horizontal overflow.
- Database execution was simulated for these UI checks; no saved user database was queried.

## GitHub remote updates, 20 September 2026

- Full suite: 200 passed, 10 optional integration tests skipped. Ruff and focused
  type checks pass. Modified JavaScript modules pass syntax checks.
- New backend tests cover remote-only configuration, validation, CSRF, read-only
  snapshots, saved SSH identity and quoted working directory, optional confirmation,
  stale revisions, demo rejection, duplicate runs, output, success/failure/unknown
  exit states and persisted results after restart.
- Playwright against an isolated settings store verified saving server/script choices,
  a configured repository outside the recent three, confirmation before dispatch,
  disabled running controls, elapsed time, escaped output and expansion across polling.
- Desktop layouts fit 2560×720 and 1707×480 without page overflow; 390×844 has no
  horizontal overflow. Browser execution responses were simulated and runner tests
  used local subprocesses; no remote server was updated during verification.

## SigNoz Debug workspace, 22 September 2026

- `uv run pytest -q`: 243 passed, 10 skipped. New log fixtures cover escaped
  upstream filters, anchored page ranges, invalid-input rejection, bounded and
  isolated search caches, trace links, attribute truncation and demo filtering.
- `uv run ruff check .`: passed. Targeted `ty check` for `signoz.py`,
  `signoz_logs.py` and `test_signoz_logs.py`: passed. Full `ty check` reports 18
  diagnostics in unchanged demo/PostgreSQL code and other existing tests.
- Isolated Chrome checks at 2560×720, 1920×720, 1280×720, 768×1024 and 390×844:
  no horizontal page overflow; desktop fits without page scroll. Detail panes,
  clipboard copy, filter submission, empty searches, trace filtering, charts toggle,
  mobile Close and restored keyboard focus were exercised.
- Mocked-browser searches verified fixed-window Older/Newer/Latest paging,
  out-of-order response rejection, stale/unavailable states, escaped markup in
  messages/attributes and source trace links. No browser JavaScript errors.
- Used a temporary demo data directory, without modifying the user's settings.
  No live work-server SigNoz queries were made; installed-server API compatibility
  remains to be verified.
