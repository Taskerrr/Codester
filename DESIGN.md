# Codester design

Settings uses labelled icon tabs for Display, Codex, Dagster, SigNoz, GitHub, Docker, PostgreSQL and SSH tunnels. On tablets and desktop, tabs form a left rail; below 650px they form two compact rows above the selected panel. Only the selected panel scrolls. Navigation and the shared Save settings action stay visible. Display keeps the three ordered dashboard app choices together with visible app names. Switching tabs preserves edits, and validation reveals the section containing an invalid field. All tab targets are at least 44px and support arrow keys, Home and End.

The dashboard is a full-height ultrawide instrument display with a narrow clock/launcher rail on the left and three configurable app channels. There is no dashboard header, marketing text, or freshness footer. Settings sits beside fullscreen at the bottom of the overview rail.

The rail's Home button returns to the three selected channels. Each launcher opens its app across the content area and indicates the selected workspace; the clock, SSH controls and rail remain visible. Home selections are independent of workspace navigation. Apps initially expand their existing overview content, with PostgreSQL providing the first dedicated workspace. Error details also retain the rail. Browser back/forward follows workspace navigation.

On Home, each channel's heading icon opens a compact app picker containing icons and names. Choosing an app replaces that slot and saves the existing layout configuration, also used by Settings. Already shown apps and the current app are disabled and labelled. The picker supports touch, keyboard navigation, visible focus, Escape, and outside-click dismissal.

The PostgreSQL workspace puts Query and Activity & locks tabs beside its heading, with a single connection dropdown for selecting, adding and editing connections. With no saved connections it reads New connection. The selected option shows name, environment and database; its tooltip includes the endpoint and username. A full-width, single-line SQL bar grows with content up to ten lines (capped at 35% of viewport height on short displays), leaving the remaining height for results. Read/write is always enabled; Play executes directly without a mode selector or separate confirmation. The green play icon becomes a red pause icon that requests cancellation, with elapsed time beside it. Empty results show no instructional copy. Results preserve duplicate column names, distinguish NULL from empty text, escape content, and report row count and preview truncation. Drafts, results and duration remain in browser memory per connection while switching workspaces; they are not persistent query history. Activity & locks uses the selected connection with the existing session confirmation controls. New/Edit connection opens an inline form; passwords are never returned. The monitoring connection is offered when configured and is edited through Settings.

Use a nearly black neutral background with subtle vertical dividers. Vibrant mint/cyan Codex data, purple Dagster data, and orange SigNoz data. Color belongs on graphs, meters, and activity indicators, not large panel backgrounds. Service logos carry identity. Clock and numbers have monospaced/tabular typography. Minimal labels identify units, usage windows, recent tasks, and errors. Stale and offline states remain explicit. Demo mode is managed from Settings without adding a label to the display.

At 2560 × 720 and equivalent scaled viewports, fill the display without page scroll. Settings chooses three unique apps and their left-to-right order; Codex, Dagster, and SigNoz are the defaults. Codex uses two quota rings and a three-row activity list. Dagster uses running/queued rings above recent jobs and errors. SigNoz uses two current readings above five-minute Top apps and errors. Docker can show a compact overview and opens a dedicated container-management screen. Individual channels can scroll. On mobile, the clock rail becomes a horizontal summary above stacked channels. Touch targets remain at least 44px, keyboard focus is visible, and reduced-motion preferences stop spinners. Spinners indicate confirmed Dagster execution only; Codex local history remains labelled Recent activity.

Top apps uses incoming SERVER-span request rates from the last five minutes. Tapping an error expands details across the display with Back and a source link.

SSH tunnels use collapsible rows with name, server, forwarding ports and live SSH status. Saved rows start closed; new and duplicated rows open for editing. Test, Duplicate and Delete stay accessible while collapsed. Duplication reuses credentials securely and selects a different local port. Expanding or duplicating a row does not initiate a connection.

Dashboard ring arcs retain their position across refreshes and ease to the new value in either direction, respecting reduced motion. Small SSH status dots below the date open a shared vertical list on hover, keyboard focus or tap, with names and status on the left and individual switches on the right. Long lists scroll inside the panel. Each tunnel can be connected independently; an All switch sits at the top of the list. Grey means off, green connected, amber connecting or reconnecting, red failed, and a hollow dot means status unavailable. Opening controls never connects or disconnects a tunnel.

Service commands use a dedicated two-column screen: service names on the left, named commands and their exact script on the right, with the latest output below. Settings has a Commands entry; the Linux launcher and Dagster header arrow open this screen. Edit reveals server identity, folder, comparison branch, notes and independent command rows. Confirmations are configurable per command. Command success never claims verified deployment health; manual reload notes remain visible.

PostgreSQL has a connection form in its Settings tab and a dedicated activity page with Queries and Blocking locks tabs. The dashboard shows real active/waiting counts and SQL previews. Use text and count summaries, not percentage rings without a denominator. Blocking rows identify waiter and blocker explicitly; prepared transactions have no session action. Cancel query and End session are distinct, require a confirmation naming the PID, and disable for stale/demo readings or missing role privileges. The full page keeps its heading, summary and tabs fixed while the activity list scrolls.

Docker uses collapsed Compose project rows in the Home panel, shared workspace and standalone Docker page. Each row shows the project name and running/total count; expansion reveals component service names, container names/images and live status. Expanded rows and keyboard focus survive refreshes. Small, borderless play/pause icons control all existing components, with both icons available for partial projects. Play starts and pause requests a graceful stop; accessible labels and tooltips name the actual action. Icons are 16px inside 44px touch targets. Project status is a compact count pill, such as 1/2, beside the name on the same line. Desktop panels share summary and list-row heights so their tables align; header icons have consistent sizing. Docker action feedback sits below the list to preserve its starting position. Uptime uses compact units such as 4m or 2h; full status is available in tooltips, while exit codes and unhealthy states remain visible. Stop asks for a second tap within five seconds with an inline message naming the project. Standalone containers and one-off jobs remain separate. Failures identify the affected components and persist through polling. Projects containing Codester have disabled controls. Opening a group never starts or stops anything.

The embedded Activity & locks view reuses the workspace heading; only the standalone PostgreSQL activity page renders its own title and logo. Database and freshness information remain available in both views.

The GitHub workspace adds a compact Update button beside each configured repository. Settings > GitHub > Repository actions selects an existing SSH connection, absolute server folder, multiline script and optional confirmation. Local checkout actions remain in a separate disclosure. A remote-only repository needs no local checkout or GitHub monitoring connection; configured repositories stay visible alongside recent repositories. Update runs the saved script directly using the SSH identity, independently of port forwarding. The button disables during execution and shows Updating with elapsed seconds. A Finished, Failed or Unknown indicator expands the exact script, target, timestamp and escaped output inline; expansion and log scroll position survive polling. Results persist through reloads. Demo mode disables execution, and changed target/script revisions require a fresh review. Command completion does not claim verified deployment health.

Native installation runs the dashboard at 127.0.0.1:8765 and starts at user login
(macOS LaunchAgent or Windows Startup shortcut). Docker is optional packaging;
Docker workload controls still require a running Docker engine. Migration preserves
settings and the source Docker volume. Settings > Display includes a Startup section with independent login-start and
browser-opening preferences. Save startup preferences applies them separately
from service settings; disabling login startup leaves the current session running.
The browser opens only after the local server is listening. Unsupported or
uninstalled instances show a native-installer hint with disabled controls.

The expanded SigNoz workspace keeps its charts above a log feed. Recent and Errors
buttons select separately queried feeds, with time, level, app (`service.name`),
`user.id` when supplied, and message columns. Messages expand inline; refreshes
preserve expansion, keyboard focus and scroll. Pause freezes the current view.
The feed checks every five seconds only while the workspace is visible. It shows
up to 100 logs from the last 15 minutes, explicitly noting that busy periods can
skip entries. Loading, empty, demo, stale and unavailable states are distinct.
The Home overview remains compact; log reads are independent of trace charts.

Dagster job and error labels display underscores as spaces, retaining the exact
job name in hover text. Recent job rows, including running and queued jobs, open
the shared run-detail view with a snapshot of events and a link to Dagster.
