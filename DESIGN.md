# Codester design

The user revised the direction toward the supplied Clawdeck reference: a full-height ultrawide instrument display with a narrow clock/overview rail on the left and three compact service channels. No dashboard header, marketing text, descriptive subtitles, or freshness footers. Settings is an icon in the top-right corner.

Use a nearly black neutral background with subtle vertical dividers. Vibrant mint/cyan Codex data, purple Dagster data, and orange SigNoz data. Color belongs on graphs, meters, and activity indicators, not large panel backgrounds. Service logos carry identity. Clock and numbers have monospaced/tabular typography. Minimal labels identify units, usage windows, recent tasks, and errors. Healthy connections are dots; stale/offline states remain explicit. A single small demo indicator identifies sample data.

At 2560 × 720 and equivalent scaled viewports, fill the display without page scroll. Individual channels can scroll. On mobile, the clock rail becomes a horizontal summary above stacked channels. Touch targets remain at least 44px, keyboard focus is visible, and reduced-motion preferences stop spinners. Spinners indicate confirmed Dagster execution only; Codex local history remains labelled Recent.

Live mini-graphs show collected observations, never invented history. Demo graphs use clearly identified sample series. Tapping an error expands details across the display with Back and a source link.
