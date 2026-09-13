# Integration references

Checked during implementation, 13 September 2026. Work deployments may be older.

- [OpenAI app-server documentation](https://learn.chatgpt.com/docs/app-server): initialization, account limits and runtime thread visibility. Only account reads are used; independent app-server loaded threads do not establish VS Code runtime state.
- [Dagster GraphQL documentation](https://docs.dagster.io/api/graphql): runs, filtering and bounded logs. Overview/detail queries were validated against the installed Dagster GraphQL schema during development.
- [SigNoz trace API](https://signoz.io/docs/apm-and-distributed-tracing/traces-api/), [aggregation](https://signoz.io/docs/traces-management/trace-api/aggregate-traces/), [payload model](https://signoz.io/docs/traces-management/trace-api/payload-model/), and [search](https://signoz.io/docs/traces-management/trace-api/search-traces/).
- [SigNoz native v5 types](https://github.com/SigNoz/signoz/blob/main/frontend/src/types/api/v5/queryRange.ts) and [response conversion](https://github.com/SigNoz/signoz/blob/main/frontend/src/api/v5/queryRange/convertV5Response.ts): scalar columns/data and raw timestamp/data rows. Codester decodes native responses directly.
- [Corsair display guide](https://www.corsair.com/uk/en/explorer/gamer/monitors/corsair-xeneon-edge/): 2560 × 720 target. Browser rendering and hardware touch support are separate.
