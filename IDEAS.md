# Dashboard ideas and decisions

This is the persistent record of dashboard ideas and agreed direction. Agreed items
are planned, not shipped. `PRODUCT.md` describes product principles; `DESIGN.md`
describes implemented behavior. Move entries as decisions change and record the
reason rather than leaving conflicting requirements behind.

## Exploring

- Saved SQL queries and persistent query history may make repeated tasks easier.
  Neither is part of the current runner. Current drafts and results live only in
  browser memory and survive workspace switching, not page reloads.
- Consider richer database exploration only if everyday query use warrants it.
  Keep the overview quiet and avoid recreating a full database administration tool.

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

- Side-by-side query editor and results table on wide screens; stacked on narrow screens.
- Up to 20 named development/production connections, with credentials in the existing
  private credential store. Connection and environment are always visible.
- The configured monitoring connection is also available without copying its password.
  Named connections are managed inside the workspace, independently of Home monitoring.
- SSH connections use the existing tunnel's local host/port. Opening SQL never starts
  a tunnel automatically.
- Read-only transactions by default; explicit write mode with target confirmation.
  Writes use database-role permissions and commit on successful single-statement execution.
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
