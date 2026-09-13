# Validation record

Implementation checked on macOS (Apple Silicon), 13 September 2026.

## Completed

- 44 pytest cases: encrypted credential storage/restart/isolation, dashboard selection persistence and validation, Docker list/control boundaries, host/origin/CSRF protections, demo isolation, real-connection service discovery, transport authentication/errors/size limits/timeouts, Dagster counts/pagination/detail bounds, SigNoz native v5 payloads and response decoding, metric units and missing data, Codex process lifecycle and read-only metadata, polling stale retention/backoff, and in-flight settings changes including URL/key pairing.
- Ruff lint and ty type checks pass. Source and wheel builds succeed, with templates and static files included.
- `scripts/start.sh` launches the actual local Waitress server. Demo-mode resident memory measured around 49 MB with idle CPU at 0% in a single sample; this excludes browser/Docker and is not a sustained benchmark.
- Live account read succeeded using the VS Code extension's bundled Codex `0.154.0-alpha.6.2`, returning two usage windows. Only normalized usage data is exposed by the adapter.
- Read-only local inspection found six recent VS Code threads using the current `state_5.sqlite` schema. No running-state claim is made from timestamps. No prompts or session bodies are read.
- Dagster overview and detail queries validate against the Dagster GraphQL 1.13.22 schema.
- Browser checks include the current four-column design at 2560×720 and its 1707×480 (150% equivalent) viewport. Both fit without page scroll; the narrow responsive layout stacks and scrolls.
- Browser checks cover the default columns, a non-default Docker/PostgreSQL/GitHub layout, selected launcher states, and the Docker unavailable screen at 2560×720.
- Browser interactions: error expansion, Back and restored keyboard focus, saved settings, encrypted-key non-return, mocked service discovery and dropdown choices, persistence across reload, and desktop/mobile settings. No browser console errors observed.
- Docker Compose configuration validates. Dockerfile uses a non-root user; only loopback is published.

Local screenshots are in ignored `artifacts/` so work screenshots cannot accidentally enter Git. All captured dashboard screenshots use demo data.

## Still requires the work environment

- Windows native startup and NTFS permission handling. The PowerShell script and code paths are implemented but were not executed on Windows here.
- Live Docker container listing and start/stop behavior: Docker Desktop's daemon was unavailable. The adapter and HTTP controls are fixture-tested, while the Docker screen's unavailable state was browser-tested.
- Actual Dagster/SigNoz installed versions, read permissions, values and source links. The adapters are not certified against the company's servers yet.
- Physical touchscreen reach, readability and touch-driver behavior. Browser dimensions simulate resolution/scaling, not hardware.
- Reliable live VS Code task state. This release deliberately exposes recent local metadata only. A separate app-server cannot establish what the extension is currently executing.

## Work acceptance steps

1. Start natively on each machine, open Settings, and test the saved Codex connection while signed into ChatGPT through Codex.
2. Save the real localhost Dagster and SigNoz forwarded URLs and a SigNoz query key. Test each; discover services and choose measurements.
3. Disable demo mode. Compare queue/running/failed counts with Dagster. Compare the 15-minute measurements and five-minute Top apps ranking with the matching trace filters in SigNoz.
4. Tap one known failure from each source and verify its source link and detail window.
5. Temporarily close a tunnel. Confirm the service becomes stale/offline while the other services keep updating; reopen and confirm recovery.
6. Choose three different overview apps, save, restart Codester, and verify their order persists.
7. Start Docker Desktop, open the Docker screen, and compare its list with Docker Desktop. Start a safe stopped test container, then use the two-tap stop control.
8. On the physical display, check fullscreen at your preferred OS scaling.

## Display redesign

The display removes the header/footer and explanatory copy, adds a clock rail, radial service summaries, split activity lists, and five-minute SigNoz traffic rankings. Settings and error-detail flows remain available. Current screenshots are `artifacts/codester-new-2560x720.png` and `artifacts/codester-scaled-1707x480.png`.
