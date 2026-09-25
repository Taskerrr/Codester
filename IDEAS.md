# Dashboard ideas and decisions

This is the persistent record of dashboard ideas and agreed direction. Agreed items
are planned, not shipped. `PRODUCT.md` describes product principles; `DESIGN.md`
describes implemented behavior. Move entries as decisions change and record the
reason rather than leaving conflicting requirements behind.

## Exploring

- Broaden Codester into a configurable workspace for development and home use.
  Work/Home profiles could select their own apps, layouts, accounts and notification
  preferences. This is exploration, not a shipped profile or marketplace feature.
- A plugin ecosystem could provide compact overview widgets, full workspaces and
  settings through a shared interface. Start with a few first-party plugins and a
  curated catalog before public marketplace distribution. Permission boundaries,
  credential access, compatibility and isolation need design before third-party code.
- Development candidates: project launchers linking repositories/ports/logs/databases;
  Docker logs and health details; PR/review/CI status; an API request scratchpad;
  saved SQL; deployment history and release comparisons; local process/port lookup.
- Home candidates: Spotify controls, TradingView charts/watchlists, Home Assistant
  scenes/sensors, weather/travel, NAS/backups/media status and personal routines.
  Calendar, email summaries, notes/tasks, timers and notifications could serve both.
  Provider API availability and supported embedding must be checked per integration.

- Saved SQL queries and persistent query history may make repeated tasks easier.
  Neither is part of the current runner. Current drafts and results live only in
  browser memory and survive workspace switching, not page reloads.
- Table/column autocomplete and an optional schema browser could help discover tables.
  Prefer autocomplete in the query bar before adding another permanent tab; this is
  exploring, not implemented. Multi-statement script support is also a separate possibility.

## Agreed

- Use the shared workspace shell for future app features. Left-rail icons select
  the task; Home-panel heading icons change what is monitored.
- Each workspace can use the full content area without three equal-panel constraints.
- Add functionality inside the appropriate workspace rather than crowding Home.

## Later

### Dedicated tools for the remaining workspaces

Codex, Dagster, SigNoz, Linux servers, Docker, and GitHub now open in the shared
shell using their existing overview content. Their richer, app-specific layouts
and tools remain to be planned. Existing dedicated Docker and service-command
pages remain accessible through their header links.

## Shipped

### Quiet Windows background commands, 25 September 2026

- Native Windows launches SSH, Codex, Docker, Git, PowerShell and other background
  helpers without creating transient console windows. Saving settings, refreshing
  integrations and connecting several tunnels no longer causes window flashes.
- Foreground installation commands retain their console so setup failures remain visible.

### Docker port visibility, 23 September 2026

- Compose members and standalone containers now show Docker-reported ports in all
  three views. Published mappings retain host addresses and TCP/UDP protocols;
  unbound exposed ports are labelled internal. Missing mappings are explicit.
- Corrected socket formatting for internal ports and bracketed IPv6 bindings.
  Ports do not imply HTTP support or independently verified reachability.

### Repository deployment scripts, 23 September 2026

- Added Repository script alongside existing custom SSH commands. Settings stores
  the server checkout, relative script path and optional fast-forward pull. New UI
  entries default to script mode; existing custom commands remain unchanged.
- Deploy uses the existing persisted runner/output and optional confirmation.
  A clean checkout, tracked regular script, server-side checkout lock and printed
  commit make the execution reproducible and prevent overlapping Codester deploys
  into that same checkout. Script runs have a 30-minute timeout.
- Added an adaptable Docker/pytest example: build a commit-tagged image, test the
  exact image, replace production only after successful tests, check health and
  retain the previous image. No staging environment is required.
- Tests and deployment policy live in each website repository; Codester does not
  infer that arbitrary script success proves tests or health checks ran. Website
  setup, database migrations and automatic rollback are not supplied by the runner.
- Backend and browser validation covers persistence, legacy configuration,
  confirmation/revision boundaries, path quoting, lock contention and failure gates.

### SigNoz debugging workspace, 22 September 2026

- Expanded the log feed into a full-height Debug workspace; existing charts are
  available on demand and Home is unchanged.
- Upstream message, app, user, severity and trace filters; five-minute through
  24-hour ranges, with explicit Search and keyboard submission.
- Click app/user values to filter. Inspect messages and supplied attributes in a
  detail pane; selection pauses updates. Copy a message or debugging context and
  follow a supplied trace into SigNoz. Trace filtering clears competing filters.
- Browse 100-row pages in a fixed time window, up to 1,000 rows. Live polling remains
  bounded and visible-only. Search caches are isolated and limited to 16 entries.
- Filters and investigation state remain in browser memory; logs are not persisted.
- Backend fixtures and isolated-browser checks cover filtering, paging, clipboard,
  malformed inputs, stale/error states, escaping, response races and responsive layouts.
  Live work-server compatibility still needs verification.

### Shared workspaces and configurable Home, 20 September 2026

- Every launcher opens its app across the main content area with the clock, SSH
  controls and launcher visible. Home returns to three independently selected apps.
- The active workspace is indicated. Browser back/forward supports workspace navigation.
- Home-panel heading icons open an app picker with icons and names. Selecting an
  app replaces that slot and saves the same configuration used by Settings.
- Three unique apps are required. Occupied apps are disabled and labelled
  "Already shown." The picker supports touch, keyboard, Escape and outside clicks.
- PostgreSQL is the first dedicated workspace; the others expand existing content.

### PostgreSQL SQL workspace, 20 September 2026

- Compact full-width query bar above results, superseding the original side-by-side layout
  for the 2560 × 720 display. Grows up to ten lines; short viewports cap editor height.
- Up to 20 named development/production connections, with credentials in the existing
  private credential store. A single dropdown selects, adds and edits connections, showing
  the selected connection, environment and database. No first-run instructional copy.
- The configured monitoring connection is also available without copying its password.
  Named connections are managed inside the workspace, independently of Home monitoring.
- SSH connections use the existing tunnel's local host/port. Opening SQL never starts
  a tunnel automatically.
- Read/write is the fixed workspace mode, replacing read-only and per-run confirmation
  at the user’s request. Green Play executes directly and becomes red Pause to cancel;
  elapsed time is shown beside it. Writes use database-role permissions and commit on
  successful single-statement execution. The API still supports explicit read-only requests.
- One SQL statement per request, one running SQL request per instance, a 30-second
  statement timeout, three-second lock timeout, cancellation, and a 35-second cancellation
  deadline. Demo mode never executes SQL.
- Stream results into a bounded preview: at most 500 rows, 4,000 characters per cell,
  and approximately 2 MB of text. Truncation is labelled; the query itself is not rewritten.
- SQL drafts and results survive switching workspaces and connections in the current page.
- Activity and blocking locks use the selected connection and retain session confirmations.

### Docker project grouping, 20 September 2026

- Treat a Compose project as the primary unit of interaction, matching the user's
  preference to run multi-component applications together.
- Projects start collapsed; expanding shows component status without individual
  power controls. Standalone containers and one-off jobs remain separate.
- Whole-project start/stop uses existing containers. Partial states offer Start all
  and Stop all; failures identify affected containers rather than claiming total success.
- Expansion and focus survive refreshes. Stop retains an explicit confirmation.
- Prefer small, borderless play/pause icons over power buttons and text labels.
  Show counts as a pill beside the name (1/2) and times as 4m or 2h; retain detailed accessible labels,
  exit codes, unhealthy states, and full-status tooltips.
- Align desktop summary and list-row heights across modules; keep project names
  and count pills on one line and action feedback below the list.
- No Compose file mounting is required. Rebuilds, missing-service creation and
  dependency-health orchestration remain outside these controls.

### Compact SSH controls

Small status dots beneath the date open a shared tunnel list with individual
switches and an All switch. This establishes the preference for compact controls
that reveal detail on demand rather than adding persistent dashboard clutter.

### Validation

Automated checks cover layout persistence without unrelated setting changes,
credential storage and removal, named-connection activity/control routing, demo
and confirmation boundaries, stale connection revisions, and cancellation.
Disposable PostgreSQL checks cover real reads/writes, read-only enforcement,
single-statement rejection, duplicate column names, NULL, Unicode, large values,
empty results, truncation and recovery after errors. Browser checks cover Home
replacement, workspace switching, preserved drafts/results, connection forms,
SQL execution/cancellation, keyboard use, and wide/narrow layouts.

### PostgreSQL activity heading cleanup, 20 September 2026

- Removed the duplicate title/logo inside the workspace Activity & locks tab.
  The standalone activity page retains its heading.

### GitHub repository updates, 20 September 2026

- Added Update to configured repository rows in the GitHub workspace, reusing the
  service-command SSH runner and credential store. The SSH tunnel can remain off.
- Settings selects a server, folder, multiline update script and optional confirmation.
  Local checkout actions remain available; remote-only repositories need no local path.
- Updating shows elapsed time; completion/failure expands persisted command output.
  Duplicate executions, demo execution and changed target/script revisions are rejected.
- Configured repositories remain visible even outside the three most recent GitHub rows.
- Restart/rollback menus and automatic deployment health verification remain outside this feature.

### Native Python startup, 20 September 2026

- Native installation is now the recommended default for local/work laptops.
- Per-user macOS LaunchAgent and Windows Startup shortcut start the installed
  Python server at login, without Docker or dependency downloads at startup.
- Install, restart, stop and remove-startup commands preserve local settings.
- Optional Docker migration stops Codester, disables its container restart, copies
  data and backs up previous native data. The Docker volume remains a recovery copy.
- Native activity hooks replace Docker hook commands while preserving unrelated
  hooks; changed commands still require Codex's normal trust review.
- macOS installs its runnable copy in Application Support, outside protected Documents/Desktop folders.
- Windows login startup needs validation on a Windows machine.

### Startup preferences in Settings, 22 September 2026

- Display now provides login-start and browser-opening preferences with a dedicated save action.
- Disabling login startup removes next-login registration without stopping the current session.
- Browser opening uses the default browser after the native server is listening,
  on each native start (including a manual restart). It defaults off until chosen.
- Installer updates preserve these preferences. Container/foreground instances
  show a native-installer hint instead of attempting to change host startup.
- Windows registration generation is tested; a live Windows login remains unverified.

### SigNoz log feed, 22 September 2026

- Expanded SigNoz workspace now shows logs below the existing charts, with Recent
  and Errors views, app name, optional user.id, timestamp, level and message.
- Queries the v5 Logs API independently of trace errors. Errors uses severity
  number 17+ or common error/fatal severity names, filtered upstream.
- A five-second, on-demand shared cache bounds reads across tabs. Paused/hidden
  workspaces stop requesting; errors back off and retain visibly stale same-source data.
- Latest 100 logs in 15 minutes, not a lossless stream. Bodies are capped at 4,000
  characters and truncation is labelled. No local persistent log history.
- Log response normalization and browser behavior are fixture/demo tested. A live
  server response still needs verification because this installation has SigNoz disabled.

### Dagster job readability and run details, 22 September 2026

- Job labels use spaces in place of underscores; source names and IDs are unchanged.
- All displayed recent job rows open run details, including running/queued jobs.
- Detail lookups remain restricted to known snapshot run IDs; demo running jobs
  show a running example rather than a fabricated failure.
