# SplashHub Centre

The Spluki home for SplashHub's run log: every AI and tool run from the SplashHub
Zendesk app — who ran which tool, when, on which model, with tokens and estimated
cost — on one Logs page with filters, per-day and per-tool charts and CSV export.

Live on Spluki: https://splashhub-37268f-dev.tperd.splashtop.dev (app `app_37268f73f0d0`),
admin-only behind `ADMIN_PASSWORD`. SplashHub keeps logging to Zendesk as well;
nothing there was removed.

## Run it locally

```
python app/server.py
```

Opens on <http://127.0.0.1:8795>. With no database configured it uses SQLite
(`app/runs.db`) and fills an empty log with ~90 days of generated sample runs —
the page says so in a banner. Delete `app/runs.db` to regenerate.

- `SAMPLE_DATA=0` — start with an empty log instead.
- `ADMIN_PASSWORD=…` (or `app/admin_password.txt`) — try the sign-in screen.
  Without one, the local preview is open.

No dependencies beyond Python 3 for the preview (`psycopg` is only needed for
PostgreSQL on Spluki).

## How it fits together

```
SplashHub (Zendesk)  --logSharedRun-->  Zendesk custom objects   (unchanged, still the full record)
                     --POST each run--> Spluki webhook intake (public, holds runs 24 h)
                                          | app/feed.py long-polls and takes them
                                          v
                                   SPLUKI_POSTGRES  runs table  -->  Logs page
```

A Spluki app can't be called from outside (the public load balancer is
default-deny), so SplashHub posts to the platform's `SPLUKI_WEBHOOK` intake and
`app/feed.py` collects from it.

- **Verification.** The intake checks nothing, so every post carries
  `X-SplashHub-Key`, which must equal `RUNLOG_SECRET` here (a secure setting on
  the SplashHub side, added by Zendesk's proxy). Anything else is discarded and
  counted. Without `RUNLOG_SECRET` the loop doesn't poll, so runs wait at the
  intake rather than being taken and lost.
- **No duplicates.** A run's id is a hash of when + agent + kind + topic, so the
  same run arriving live and again through SplashHub's "Send history" import is
  stored once. The import can be re-run to fill any gap.
- **Feed status** shows in the page header (Live / Feed problem / Feed off).

Body SplashHub posts: `{"v": 1, "source": "webhook" | "zendesk-import", "runs": [<logSharedRun entry>, ...]}`.

## SOS Scans

Custom SOS package requests ("New SOS package created by ..." tickets), one row each, opening into the request
(package, subscription, creator, what end users see, ACP / download links), a
gallery of every image on the ticket, and -- when it ran -- the AI review.

- **New requests** arrive by a Zendesk trigger + webhook (`feed.py` verifies
  Zendesk's signature with `ZENDESK_WEBHOOK_SECRET`). The trigger also sends the
  ticket's text and image links, so a request shows even before SplashHub
  Centre may call Zendesk itself.
- **With Zendesk access** (`OUTBOUND_HTTP` grant + `ZENDESK_EMAIL` /
  `ZENDESK_API_TOKEN`) it reads the ticket read-only and keeps copies of every
  image in its bucket (`SPLUKI_STORAGE`, `imagestore.py`). Nothing is written
  back to Zendesk.
- **AI review switch** (page header), **off** by default. It applies only to
  requests that arrive while it is on -- the decision is stamped on each request
  when it arrives. Same policy, schema and model as SplashHub's sidebar scan
  (`sosscan.py`; keep in step with SplashHub's `scan.js`). Needs the
  `CUSTOM_AI` grant.
- **Import past SOS requests** (button): searches Zendesk for every past
  request -- by subject only, since agents often change the requester from
  `be-admin@my-mail.splashtop.com` to the customer -- and lists it at its own
  date, with image copies. Never AI-reviewed.
  Tickets already listed are skipped, so it can be pressed again.

## Layout

```
app/server.py        routes, sign-in, CSV export
app/feed.py          webhook pickup: SplashHub's runs + Zendesk's SOS triggers, verified
app/sosscan.py       SOS package requests: details, image copies, AI review (switch), import
app/zendesk.py       read-only Zendesk API client
app/imagestore.py    image copies: Spluki bucket, or app/images locally
app/store.py         runs table: PostgreSQL on Spluki, SQLite locally
app/sample.py        sample runs for the preview (never on Spluki)
app/static/          Logs (index.html, app.js) and SOS Scans (scans.html, scans.js) pages
service.yaml         Spluki app definition (SPLUKI_POSTGRES, SPLUKI_WEBHOOK; ADMIN_PASSWORD, RUNLOG_SECRET)
Dockerfile           python:3.11-slim + psycopg, non-root — same as the Mockup Hub
```

## Tools

The tool buckets match SplashHub's `runCategory()` (dashboard.js), so a run lands
under the same tab in both places. Two buckets SplashHub computes but never shows
as tabs — **Trends** and **Transfer** — have their own chips here; today those runs
only appear under "All" in SplashHub.
