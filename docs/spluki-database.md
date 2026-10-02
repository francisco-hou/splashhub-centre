# Spluki database — splashhub (app_37268f73f0d0)

Requested 2026-10-02 as `SPLUKI_POSTGRES` (`perm_8b682b7dba0b`), granted as filed
(review channel: none — an administrator can still reject it).

Written by hand: this project was not scaffolded with `spluki init`, so the tool
could not save its own record here. The lifecycle below is what the platform
stated when the grant was filed.

## Lifecycle

- The platform supplies all six connection values itself once provisioning
  finishes (`none → pending → provisioning → ready`; `failed` needs a Spluki
  administrator). Nobody types them, and no route accepts them by hand.
- Once it exists, **only deleting the whole app drops it** — not removing it from
  `service.yaml`, not pausing, not any redeploy. Deleting the app asks first
  whether to dump it.
- The schema is whatever the **previous** release left. Every release must run
  against that, so schema changes are additive only (`CREATE … IF NOT EXISTS`,
  new nullable columns) — see `app/store.py` `ensure_schema()`.

## Variables

`DATABASE_WRITER_HOST`, `DATABASE_READER_HOST`, `DATABASE_PORT`, `DATABASE_NAME`,
`DATABASE_USER`, `DATABASE_PASSWORD`. There is no `DATABASE_URL`; `store.py`
composes one with the password URL-encoded. Writes use the writer host; reads use
the reader host (read-only).

## Schema log

| Release | Change |
|---|---|
| 0.1.0 | `runs` table: id, event_id (unique), ts_ms, agent, kind, tool, model, topic, tickets, input_tokens, output_tokens, cost, source, received_ms. Indexes `runs_ts (ts_ms DESC)`, `runs_tool_ts (tool, ts_ms DESC)`. |
