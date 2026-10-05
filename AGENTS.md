# SplashHub Centre — decisions

- **Deploy only through Spluki**, and only when the owner asks. As of 0.1.0 the app
  has never been created on the platform; `app.name` (`splashhub`) is not yet
  fixed and can still change. The page is branded "SplashHub Centre" regardless
  of the app name.
- **One row per run.** The Zendesk store keeps a whole day in one 22 KB record and
  drops runs on busy days; this table must never go back to that shape.
- **Row shape = SplashHub's `logSharedRun()` entry** (when, agent, kind, model,
  topic, tickets, input/output tokens, cost), plus `tool` (derived at insert) and
  `event_id` (unique, for idempotent webhook pickup and the Zendesk import).
- **Tool buckets follow SplashHub's `runCategory()`** in
  `SplashHub/Workspace/assets/dashboard.js`. Change both together.
- **Admin pages** (Logs, Settings; under Admin in the left menu) need `ADMIN_PASSWORD` (sealed secret); every other page is open to the team.
  On PostgreSQL a missing password locks the data rather than opening it.
- **Schema changes are additive** (`CREATE … IF NOT EXISTS`, new nullable
  columns): on Spluki every release runs against whatever the last one left.
- **Sample data is local-only**: the image sets `SAMPLE_DATA=0`, and seeding
  only ever happens on the SQLite backend.
- **Zendesk logging stays** until the owner decides otherwise.
