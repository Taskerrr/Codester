# Codester design

The dashboard is a full-height ultrawide instrument display with a narrow clock/overview rail on the left and three compact service channels. There is no dashboard header, marketing text, or freshness footer. Settings sits beside the wordmark in the overview rail.

Use a nearly black neutral background with subtle vertical dividers. Vibrant mint/cyan Codex data, purple Dagster data, and orange SigNoz data. Color belongs on graphs, meters, and activity indicators, not large panel backgrounds. Service logos carry identity. Clock and numbers have monospaced/tabular typography. Minimal labels identify units, usage windows, recent tasks, and errors. Stale and offline states remain explicit. Demo mode is managed from Settings without adding a label to the display.

At 2560 × 720 and equivalent scaled viewports, fill the display without page scroll. Codex uses two quota rings and a three-row activity list. Dagster uses running/queued rings above recent jobs and errors. SigNoz uses two current readings above five-minute Top apps and errors. Individual channels can scroll. On mobile, the clock rail becomes a horizontal summary above stacked channels. Touch targets remain at least 44px, keyboard focus is visible, and reduced-motion preferences stop spinners. Spinners indicate confirmed Dagster execution only; Codex local history remains labelled Recent activity.

Top apps uses incoming SERVER-span request rates from the last five minutes. Tapping an error expands details across the display with Back and a source link.
