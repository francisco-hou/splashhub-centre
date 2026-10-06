"""SplashHub run log: every AI / tool run the SplashHub Zendesk app records.

One row per run -- the fix for the Zendesk store, which keeps a whole day in a
single 22 KB record (busy days drop their oldest runs; two agents logging at the
same moment can overwrite each other).

One connection abstraction, two backends (the Mockup Hub's history.py pattern):
  - Spluki: PostgreSQL through the platform's SPLUKI_POSTGRES grant. The six
    DATABASE_* variables are injected; there is no DATABASE_URL, so one is
    composed here with the password URL-encoded.
  - Local: SQLite in app/runs.db (gitignored), so the preview needs no database.
Passing locally on SQLite does not prove the PostgreSQL path.

A row has the same fields as an entry SplashHub's logSharedRun() writes today:
when (epoch ms), agent, kind, model, topic, tickets, input/output tokens, cost.
Two are added here: `tool` (the Logs-page bucket, derived from kind at insert so
filtering is plain SQL) and `event_id` (unique; lets the webhook pickup and the
one-off Zendesk import insert idempotently).
"""
import hashlib, os, threading
from urllib.parse import quote

APP = os.path.dirname(os.path.abspath(__file__))
SQLITE_FILE = os.environ.get("RUNS_SQLITE") or os.path.join(APP, "runs.db")
LOCK = threading.Lock()

# Logs-page buckets, in chip order. SplashHub's runCategory() (dashboard.js) is
# the source of truth for the mapping; two buckets it computes but never shows
# as tabs -- Trends and Transfer -- get their own here.
TOOLS = [
    ("jira", "Jira"),
    ("feature", "Feature Request"),
    ("scan", "SOS Scan"),
    ("reply", "Reply Tools"),
    ("po", "PO"),
    ("sso", "SSO"),
    ("wrapup", "Wrap Up"),
    ("mockup", "Mockup"),
    ("transcribe", "Transcribe"),
    ("transfer", "Transfer"),
    ("trends", "Trends"),
    ("other", "Other"),
]
TOOL_KEYS = {k for k, _ in TOOLS}


def tool_for(kind):
    """Same buckets as SplashHub's runCategory(), plus transfer."""
    k = (kind or "").strip().lower()
    if k.startswith("overview") or k.startswith("deep dive"):
        return "trends"
    if k.startswith("jira"):
        return "jira"
    if k.startswith("feature"):
        return "feature"
    if k.startswith("brand scan") or k.startswith("scan"):
        return "scan"
    if k.startswith("transcribe"):
        return "transcribe"
    if k.startswith("translate") or k.startswith("spellcheck") or k.startswith("customer-ready tone"):
        return "reply"
    if k.startswith("transfer"):
        return "transfer"
    if k.startswith("po"):
        return "po"
    if k.startswith("sso"):
        return "sso"
    if k.startswith("wrap up"):
        return "wrapup"
    if k.startswith("mockup"):
        return "mockup"
    return "other"


# ---- connection ---------------------------------------------------------------

def _pg_env():
    return {k: os.environ.get("DATABASE_" + k) for k in ("WRITER_HOST", "READER_HOST", "PORT", "NAME", "USER", "PASSWORD")}


def backend():
    return "postgres" if _pg_env()["WRITER_HOST"] else "sqlite"


def _pg_url(host):
    e = _pg_env()
    return "postgresql://%s:%s@%s:%s/%s" % (quote(e["USER"] or "", safe=""), quote(e["PASSWORD"] or "", safe=""),
                                           host, e["PORT"] or "5432", e["NAME"] or "")


def connect(write=True):
    if backend() == "postgres":
        import psycopg
        e = _pg_env()
        host = e["WRITER_HOST"] if write else (e["READER_HOST"] or e["WRITER_HOST"])
        return psycopg.connect(_pg_url(host), connect_timeout=5)
    import sqlite3
    return sqlite3.connect(SQLITE_FILE, timeout=5)


def _ph():
    return "%s" if backend() == "postgres" else "?"


def _q(sql):
    """Write SQL with %s placeholders; SQLite gets ?."""
    return sql if backend() == "postgres" else sql.replace("%s", "?")


_ready = False

# Columns added after a table first shipped. Additive only: on Spluki every
# release runs against whatever the previous one left.
ADDED_COLUMNS = [
    ("sos_scans", "description", "TEXT"),     # the ticket's first message, as sent
    ("sos_scans", "gallery_json", "TEXT"),    # every image on the ticket + where its copy is stored
    ("sos_scans", "ai_review", "TEXT"),       # 'on' / 'off': the switch when the request ARRIVED; 'manual': the panel's button
    ("sos_scans", "reviewed_ms", "BIGINT"),   # when the AI review finished
    ("sos_scans", "translation_json", "TEXT"),  # the Translate button's English, saved so it runs once
    ("sos_scans", "note_json", "TEXT"),       # the internal note added to Zendesk: when, which style
    ("sos_scans", "ticket_status", "TEXT"),   # the Zendesk ticket's own status (new/open/pending/hold/solved/closed)
    ("sos_scans", "ticket_status_ms", "BIGINT"),  # when that was last read
]


def _add_columns(cur):
    for table, col, typ in ADDED_COLUMNS:
        if backend() == "postgres":
            cur.execute("ALTER TABLE %s ADD COLUMN IF NOT EXISTS %s %s" % (table, col, typ))
        else:
            cur.execute("PRAGMA table_info(%s)" % table)
            if col not in [r[1] for r in cur.fetchall()]:
                cur.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, col, typ))

# Custom SOS package brand scans (sosscan.py). One row per scan request; the
# JSON columns hold what the review saw and said, as text in both backends.
# verdict: the worst of the per-image verdicts and the ticket review --
# suspicious > needs_review > normal; '' while queued/running or on error.
SCANS_DDL = """CREATE TABLE IF NOT EXISTS sos_scans (
    id {ID},
    ticket_id {INT} NOT NULL,
    requested_ms {INT} NOT NULL,
    finished_ms {INT},
    source TEXT NOT NULL DEFAULT 'webhook',
    requested_by TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    verdict TEXT,
    subject TEXT,
    creator_email TEXT, creator_domain TEXT, creator_source TEXT, organization TEXT,
    attach_key TEXT,
    images_json TEXT, fields_json TEXT, result_json TEXT,
    error TEXT,
    model TEXT,
    input_tokens {INT} NOT NULL DEFAULT 0, output_tokens {INT} NOT NULL DEFAULT 0,
    cost {REAL} NOT NULL DEFAULT 0)"""


# SSO method validation requests (ssocheck.py). One row per ticket.
# status: needs_details (no domain / TXT value yet) | pending (never checked)
# | not_found | verified | error (the DNS lookup itself failed).
SSO_DDL = """CREATE TABLE IF NOT EXISTS sso_requests (
    id {ID},
    ticket_id {INT} NOT NULL UNIQUE,
    requested_ms {INT} NOT NULL,
    source TEXT NOT NULL DEFAULT 'webhook',
    subject TEXT, description TEXT, requester_email TEXT, organization TEXT,
    domain TEXT, txt_name TEXT, txt_value TEXT, parse_note TEXT,
    status TEXT NOT NULL DEFAULT 'needs_details',
    checks {INT} NOT NULL DEFAULT 0,
    last_checked_ms {INT}, verified_ms {INT},
    last_result_json TEXT, history_json TEXT, note_json TEXT)"""


def ensure_schema():
    """Idempotent and additive only -- on Spluki the schema is whatever the
    previous release left, so every release must run against that."""
    global _ready
    if _ready:
        return
    with LOCK:
        if _ready:
            return
        c = connect(True)
        try:
            cur = c.cursor()
            if backend() == "postgres":
                cur.execute("SELECT pg_advisory_lock(716572)")
                cur.execute("""CREATE TABLE IF NOT EXISTS runs (
                    id BIGSERIAL PRIMARY KEY,
                    event_id TEXT UNIQUE,
                    ts_ms BIGINT NOT NULL,
                    agent TEXT, kind TEXT NOT NULL, tool TEXT NOT NULL, model TEXT, topic TEXT,
                    tickets INTEGER NOT NULL DEFAULT 1,
                    input_tokens BIGINT NOT NULL DEFAULT 0, output_tokens BIGINT NOT NULL DEFAULT 0,
                    cost DOUBLE PRECISION NOT NULL DEFAULT 0,
                    source TEXT NOT NULL DEFAULT 'webhook',
                    received_ms BIGINT)""")
                cur.execute("CREATE INDEX IF NOT EXISTS runs_ts ON runs (ts_ms DESC)")
                cur.execute("CREATE INDEX IF NOT EXISTS runs_tool_ts ON runs (tool, ts_ms DESC)")
                cur.execute(SCANS_DDL.replace("{ID}", "BIGSERIAL PRIMARY KEY").replace("{INT}", "BIGINT")
                            .replace("{REAL}", "DOUBLE PRECISION"))
                cur.execute("CREATE INDEX IF NOT EXISTS sos_scans_ts ON sos_scans (requested_ms DESC)")
                cur.execute("CREATE INDEX IF NOT EXISTS sos_scans_ticket ON sos_scans (ticket_id)")
                cur.execute(SSO_DDL.replace("{ID}", "BIGSERIAL PRIMARY KEY").replace("{INT}", "BIGINT"))
                cur.execute("CREATE INDEX IF NOT EXISTS sso_requests_ts ON sso_requests (requested_ms DESC)")
                cur.execute("SELECT pg_advisory_unlock(716572)")
            else:
                cur.execute("""CREATE TABLE IF NOT EXISTS runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT UNIQUE,
                    ts_ms INTEGER NOT NULL,
                    agent TEXT, kind TEXT NOT NULL, tool TEXT NOT NULL, model TEXT, topic TEXT,
                    tickets INTEGER NOT NULL DEFAULT 1,
                    input_tokens INTEGER NOT NULL DEFAULT 0, output_tokens INTEGER NOT NULL DEFAULT 0,
                    cost REAL NOT NULL DEFAULT 0,
                    source TEXT NOT NULL DEFAULT 'webhook',
                    received_ms INTEGER)""")
                cur.execute("CREATE INDEX IF NOT EXISTS runs_ts ON runs (ts_ms)")
                cur.execute("CREATE INDEX IF NOT EXISTS runs_tool_ts ON runs (tool, ts_ms)")
                cur.execute(SCANS_DDL.replace("{ID}", "INTEGER PRIMARY KEY AUTOINCREMENT").replace("{INT}", "INTEGER")
                            .replace("{REAL}", "REAL"))
                cur.execute("CREATE INDEX IF NOT EXISTS sos_scans_ts ON sos_scans (requested_ms)")
                cur.execute("CREATE INDEX IF NOT EXISTS sos_scans_ticket ON sos_scans (ticket_id)")
                cur.execute(SSO_DDL.replace("{ID}", "INTEGER PRIMARY KEY AUTOINCREMENT").replace("{INT}", "INTEGER"))
                cur.execute("CREATE INDEX IF NOT EXISTS sso_requests_ts ON sso_requests (requested_ms)")
            _add_columns(cur)
            c.commit()
        finally:
            c.close()
        _ready = True


# ---- writing ------------------------------------------------------------------

def run_id(run):
    """A run's identity, from its own content. SplashHub writes the same entry
    object to Zendesk and to the webhook, so a run that arrives live and again
    through the history import hashes the same and is stored once."""
    key = "|".join(str(run.get(k) or "") for k in ("when", "agent", "kind", "topic"))
    return "run-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


def _clean(run):
    def num(v, cast):
        try:
            return max(0, cast(v or 0))
        except (TypeError, ValueError):
            return 0
    kind = str(run.get("kind") or "other").strip()[:64]
    # SplashHub logs its $0 runs (PO, SSO, Mockup) with model "—": that is "no
    # model", not a model, so it must not appear in the Model filter.
    model = str(run.get("model") or "").strip()[:64]
    if model in ("—", "-", "–"):
        model = ""
    return (
        str(run.get("event_id") or run_id(run))[:128],
        int(run.get("when") or 0),
        (str(run.get("agent") or "").strip()[:120] or None),
        kind,
        tool_for(kind),
        model or None,
        (str(run.get("topic") or "").strip()[:500] or None),
        num(run.get("tickets", 1), int) or 1,
        num(run.get("input_tokens"), int),
        num(run.get("output_tokens"), int),
        num(run.get("cost"), float),
        str(run.get("source") or "webhook")[:32],
        run.get("received_ms"),
    )


def insert_many(runs):
    """Insert runs; a repeated event_id is skipped, so re-delivery is harmless."""
    ensure_schema()
    rows = [_clean(r) for r in runs if r and r.get("when")]
    if not rows:
        return 0
    sql = ("INSERT INTO runs (event_id, ts_ms, agent, kind, tool, model, topic, tickets, input_tokens, output_tokens, cost, source, received_ms) "
           "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)")
    sql += " ON CONFLICT (event_id) DO NOTHING" if backend() == "postgres" else ""
    if backend() == "sqlite":
        sql = sql.replace("INSERT INTO", "INSERT OR IGNORE INTO")
    c = connect(True)
    try:
        cur = c.cursor()
        cur.executemany(_q(sql), rows)
        added = cur.rowcount       # rows actually written; skipped duplicates are not counted
        c.commit()
    finally:
        c.close()
    return added if added is not None and added >= 0 else len(rows)


def count():
    ensure_schema()
    c = connect(False)
    try:
        cur = c.cursor()
        cur.execute("SELECT count(*) FROM runs")
        return cur.fetchone()[0]
    finally:
        c.close()


# ---- reading ------------------------------------------------------------------

def _where(f, skip_tool=False):
    """Filters shared by every read: since/until (epoch ms), tool, agent, model, q."""
    where, args = [], []
    if f.get("since") is not None:
        where.append("ts_ms >= %s"); args.append(int(f["since"]))
    if f.get("until") is not None:
        where.append("ts_ms < %s"); args.append(int(f["until"]))
    if f.get("tool") and not skip_tool:
        where.append("tool = %s"); args.append(f["tool"])
    if f.get("agent"):
        where.append("coalesce(agent, '') = %s"); args.append(f["agent"])
    if f.get("model"):
        where.append("coalesce(model, '') = %s"); args.append(f["model"])
    if f.get("q"):
        like = "%" + f["q"].lower() + "%"
        where.append("(lower(coalesce(topic,'')) LIKE %s OR lower(coalesce(agent,'')) LIKE %s OR lower(kind) LIKE %s)")
        args += [like, like, like]
    return (" WHERE " + " AND ".join(where)) if where else "", args


def _read(sql, args, fresh=False):
    """fresh=True reads from the WRITER. On Spluki the reader endpoint is a
    replica that can be a moment behind, so a read that decides something about
    a row written a moment ago (the scanner, the import, the AI switch) must not
    use it. Pages showing lists can: a second's lag there is harmless."""
    c = connect(fresh)
    try:
        cur = c.cursor()
        cur.execute(_q(sql), args)
        return cur.fetchall()
    finally:
        c.close()


COLS = ("id", "ts_ms", "agent", "kind", "tool", "model", "topic", "tickets", "input_tokens", "output_tokens", "cost")


def runs(f, page=0, per_page=100):
    ensure_schema()
    w, args = _where(f)
    total = _read("SELECT count(*) FROM runs" + w, args)[0][0]
    per_page = max(1, min(int(per_page), 1000))
    page = max(0, int(page))
    rows = _read("SELECT " + ", ".join(COLS) + " FROM runs" + w +
                 " ORDER BY ts_ms DESC, id DESC LIMIT %d OFFSET %d" % (per_page, page * per_page), args)
    return {"total": total, "page": page, "per_page": per_page,
            "rows": [dict(zip(COLS, r)) for r in rows]}


def all_runs(f, limit=100000):
    ensure_schema()
    w, args = _where(f)
    rows = _read("SELECT " + ", ".join(COLS) + " FROM runs" + w + " ORDER BY ts_ms DESC, id DESC LIMIT %d" % limit, args)
    return [dict(zip(COLS, r)) for r in rows]


def summary(f, tz_offset_min=0):
    """Totals, per-day and per-tool aggregates for the filtered slice.

    Days are the VIEWER's calendar days: the page sends its UTC offset, so a
    run at 23:30 in Taipei lands on the Taipei day, not the server's UTC one.
    The per-tool breakdown ignores the tool filter on purpose -- it shows where
    the selected tool sits among the others rather than a single bar.
    """
    ensure_schema()
    w, args = _where(f)
    tot = _read("SELECT count(*), coalesce(sum(cost),0), coalesce(sum(input_tokens),0), "
                "coalesce(sum(output_tokens),0), count(DISTINCT agent) FROM runs" + w, args)[0]
    shift = int(tz_offset_min) * 60000
    day_expr = "((ts_ms - (%d)) / 86400000)" % shift      # integer division in both backends
    by_day = _read("SELECT " + day_expr + " AS d, count(*), coalesce(sum(cost),0) FROM runs" + w +
                   " GROUP BY d ORDER BY d", args)
    top = _read("SELECT agent, count(*) AS n FROM runs" + w + (" AND" if w else " WHERE") +
                " agent IS NOT NULL GROUP BY agent ORDER BY n DESC, agent LIMIT 1", args)
    wt, targs = _where(f, skip_tool=True)
    by_tool = {k: (n, c) for k, n, c in _read(
        "SELECT tool, count(*), coalesce(sum(cost),0) FROM runs" + wt + " GROUP BY tool", targs)}
    return {
        "runs": tot[0], "cost": float(tot[1]), "input_tokens": int(tot[2]), "output_tokens": int(tot[3]),
        "agents": tot[4], "top_agent": top[0][0] if top else None, "top_agent_runs": top[0][1] if top else 0,
        "by_day": [{"day": int(d), "runs": n, "cost": float(c)} for d, n, c in by_day],
        "by_tool": [{"key": k, "label": lbl, "runs": by_tool.get(k, (0, 0))[0], "cost": float(by_tool.get(k, (0, 0))[1])}
                    for k, lbl in TOOLS],
    }


def facets():
    """Every agent and model in the log, for the filter selects -- from the
    whole log, so an option never vanishes because other filters exclude it."""
    ensure_schema()
    agents = [r[0] for r in _read("SELECT DISTINCT agent FROM runs WHERE agent IS NOT NULL ORDER BY agent", [])]
    models = [r[0] for r in _read("SELECT DISTINCT model FROM runs WHERE model IS NOT NULL ORDER BY model", [])]
    span = _read("SELECT min(ts_ms), max(ts_ms) FROM runs", [])[0]
    return {"agents": agents, "models": models, "first": span[0], "last": span[1]}


# ---- SOS package scans ------------------------------------------------------------

SCAN_COLS = ("id", "ticket_id", "requested_ms", "finished_ms", "source", "requested_by", "status", "verdict",
             "subject", "creator_email", "creator_domain", "creator_source", "organization", "attach_key",
             "images_json", "fields_json", "result_json", "error", "model", "input_tokens", "output_tokens", "cost",
             "description", "gallery_json", "ai_review", "reviewed_ms", "translation_json", "note_json", "ticket_status", "ticket_status_ms")
SCAN_LIST_COLS = ("id", "ticket_id", "requested_ms", "finished_ms", "source", "requested_by", "status", "verdict",
                  "subject", "creator_email", "creator_domain", "organization", "error", "cost",
                  "ticket_status", "ticket_status_ms")


def scan_create(ticket_id, source, requested_by=None):
    ensure_schema()
    now = int(__import__("time").time() * 1000)
    c = connect(True)
    try:
        cur = c.cursor()
        sql = "INSERT INTO sos_scans (ticket_id, requested_ms, source, requested_by, status) VALUES (%s,%s,%s,%s,'queued')"
        if backend() == "postgres":
            cur.execute(sql + " RETURNING id", (int(ticket_id), now, source, requested_by))
            new_id = cur.fetchone()[0]
        else:
            cur.execute(_q(sql), (int(ticket_id), now, source, requested_by))
            new_id = cur.lastrowid
        c.commit()
        return new_id
    finally:
        c.close()


def scan_update(scan_id, **fields):
    ensure_schema()
    cols = [k for k in fields if k in SCAN_COLS and k != "id"]
    if not cols:
        return
    c = connect(True)
    try:
        c.cursor().execute(_q("UPDATE sos_scans SET " + ", ".join(k + " = %s" for k in cols) + " WHERE id = %s"),
                           [fields[k] for k in cols] + [int(scan_id)])
        c.commit()
    finally:
        c.close()


def sos_dash_rows(since_ms):
    """What the SOS Scans dashboard counts (sosdash.py): every request since then."""
    ensure_schema()
    cols = ("id", "ticket_id", "requested_ms", "source", "status", "verdict", "ticket_status", "ticket_status_ms",
            "creator_domain", "creator_email", "subject", "fields_json", "cost")
    return [dict(zip(cols, r)) for r in _read("SELECT " + ", ".join(cols) + " FROM sos_scans WHERE requested_ms >= %s "
                                              "ORDER BY requested_ms", [int(since_ms)])]


def scans_normal_reviewed():
    """Reviews stored as "normal", with what the team rules need to look at."""
    ensure_schema()
    cols = ["id", "verdict", "creator_domain", "creator_email", "result_json"]
    rows = _read("SELECT " + ", ".join(cols) + " FROM sos_scans WHERE verdict = %s AND result_json IS NOT NULL", ["normal"], True)
    return [dict(zip(cols, r)) for r in rows]


def scan_set_statuses(statuses, ms):
    """The Ticket status column, many rows in one go: {scan id: status or None}
    (None keeps the old status and only marks it as checked)."""
    if not statuses:
        return
    ensure_schema()
    c = connect(True)
    try:
        cur = c.cursor()
        for sid, st in statuses.items():
            if st:
                cur.execute(_q("UPDATE sos_scans SET ticket_status = %s, ticket_status_ms = %s WHERE id = %s"), (st, ms, int(sid)))
            else:
                cur.execute(_q("UPDATE sos_scans SET ticket_status_ms = %s WHERE id = %s"), (ms, int(sid)))
        c.commit()
    finally:
        c.close()


def scan_get(scan_id, fresh=False):
    ensure_schema()
    rows = _read("SELECT " + ", ".join(SCAN_COLS) + " FROM sos_scans WHERE id = %s", [int(scan_id)], fresh)
    return dict(zip(SCAN_COLS, rows[0])) if rows else None


def scan_done_for(ticket_id, attach_key):
    """A finished scan of exactly these images on this ticket, if one exists."""
    ensure_schema()
    rows = _read("SELECT id FROM sos_scans WHERE ticket_id = %s AND attach_key = %s AND status = 'done' "
                 "ORDER BY id DESC LIMIT 1", [int(ticket_id), attach_key], fresh=True)
    return rows[0][0] if rows else None


def scans(q=None, verdict=None, page=0, per_page=50):
    ensure_schema()
    where, args = [], []
    if verdict == "flagged":
        where.append("verdict IN ('suspicious', 'needs_review')")
    elif verdict in ("suspicious", "needs_review", "normal"):
        where.append("verdict = %s"); args.append(verdict)
    elif verdict in ("error", "skipped", "queued", "running", "waiting", "held"):
        where.append("status = %s"); args.append(verdict)
    if q:
        like = "%" + q.lower().lstrip("#") + "%"
        where.append("(CAST(ticket_id AS TEXT) LIKE %s OR lower(coalesce(subject,'')) LIKE %s OR "
                     "lower(coalesce(creator_email,'')) LIKE %s OR lower(coalesce(organization,'')) LIKE %s)")
        args += [like] * 4
    w = (" WHERE " + " AND ".join(where)) if where else ""
    total = _read("SELECT count(*) FROM sos_scans" + w, args)[0][0]
    per_page = max(1, min(int(per_page), 200))
    page = max(0, int(page))
    rows = _read("SELECT " + ", ".join(SCAN_LIST_COLS) + " FROM sos_scans" + w +
                 " ORDER BY requested_ms DESC, id DESC LIMIT %d OFFSET %d" % (per_page, page * per_page), args)
    counts = dict(_read("SELECT coalesce(verdict, status), count(*) FROM sos_scans GROUP BY coalesce(verdict, status)", []))
    return {"total": total, "page": page, "per_page": per_page,
            "rows": [dict(zip(SCAN_LIST_COLS, r)) for r in rows], "counts": counts}


# ---- SSO method validation requests (ssocheck.py) ------------------------------------

SSO_COLS = ("id", "ticket_id", "requested_ms", "source", "subject", "description", "requester_email", "organization",
            "domain", "txt_name", "txt_value", "parse_note", "status", "checks", "last_checked_ms", "verified_ms",
            "last_result_json", "history_json", "note_json")
SSO_LIST_COLS = ("id", "ticket_id", "requested_ms", "source", "subject", "requester_email", "organization",
                 "domain", "status", "checks", "last_checked_ms", "verified_ms", "note_json")


def sso_upsert(ticket_id, source, requested_ms):
    """The row for this ticket, made if it is new. Returns its id."""
    ensure_schema()
    rows = _read("SELECT id FROM sso_requests WHERE ticket_id = %s", [int(ticket_id)], fresh=True)
    if rows:
        return rows[0][0]
    c = connect(True)
    try:
        cur = c.cursor()
        sql = "INSERT INTO sso_requests (ticket_id, requested_ms, source) VALUES (%s,%s,%s)"
        if backend() == "postgres":
            cur.execute(sql + " ON CONFLICT (ticket_id) DO NOTHING RETURNING id", (int(ticket_id), int(requested_ms), source))
            got = cur.fetchone()
        else:
            cur.execute(_q(sql.replace("INSERT", "INSERT OR IGNORE")), (int(ticket_id), int(requested_ms), source))
            got = (cur.lastrowid,) if cur.rowcount else None
        c.commit()
    finally:
        c.close()
    if got:
        return got[0]
    return _read("SELECT id FROM sso_requests WHERE ticket_id = %s", [int(ticket_id)], fresh=True)[0][0]


def sso_update(sso_id, **fields):
    ensure_schema()
    cols = [k for k in fields if k in SSO_COLS and k != "id"]
    if not cols:
        return
    c = connect(True)
    try:
        c.cursor().execute(_q("UPDATE sso_requests SET " + ", ".join(k + " = %s" for k in cols) + " WHERE id = %s"),
                           [fields[k] for k in cols] + [int(sso_id)])
        c.commit()
    finally:
        c.close()


def sso_get(sso_id, fresh=False):
    ensure_schema()
    rows = _read("SELECT " + ", ".join(SSO_COLS) + " FROM sso_requests WHERE id = %s", [int(sso_id)], fresh)
    return dict(zip(SSO_COLS, rows[0])) if rows else None


def sso_ticket_ids(ticket_ids):
    ids = [int(t) for t in ticket_ids if str(t).isdigit()]
    if not ids:
        return set()
    ensure_schema()
    return {r[0] for r in _read("SELECT ticket_id FROM sso_requests WHERE ticket_id IN (" + ",".join(["%s"] * len(ids)) + ")",
                                ids, fresh=True)}


def sso_waiting_ids():
    """Requests 'Check all waiting' looks at: a domain, and not verified yet."""
    ensure_schema()
    return [r[0] for r in _read("SELECT id FROM sso_requests WHERE domain IS NOT NULL AND status <> 'verified' "
                                "ORDER BY requested_ms DESC", [], fresh=True)]


def sso_list(q=None, status=None, page=0, per_page=50):
    ensure_schema()
    where, args = [], []
    if status in ("needs_details", "pending", "not_found", "verified", "error"):
        where.append("status = %s"); args.append(status)
    elif status == "waiting":
        where.append("status IN ('pending', 'not_found', 'error')")
    if q:
        like = "%" + q.lower().lstrip("#") + "%"
        where.append("(CAST(ticket_id AS TEXT) LIKE %s OR lower(coalesce(domain,'')) LIKE %s OR "
                     "lower(coalesce(requester_email,'')) LIKE %s OR lower(coalesce(organization,'')) LIKE %s)")
        args += [like] * 4
    w = (" WHERE " + " AND ".join(where)) if where else ""
    total = _read("SELECT count(*) FROM sso_requests" + w, args)[0][0]
    per_page = max(1, min(int(per_page), 200))
    page = max(0, int(page))
    rows = _read("SELECT " + ", ".join(SSO_LIST_COLS) + " FROM sso_requests" + w +
                 " ORDER BY requested_ms DESC, id DESC LIMIT %d OFFSET %d" % (per_page, page * per_page), args)
    counts = dict(_read("SELECT status, count(*) FROM sso_requests GROUP BY status", []))
    return {"total": total, "page": page, "per_page": per_page,
            "rows": [dict(zip(SSO_LIST_COLS, r)) for r in rows], "counts": counts}


# ---- settings (small team-wide switches set from the pages) ---------------------------

def _settings_table(cur):
    cur.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT, updated_ms %s, updated_by TEXT)"
                % ("BIGINT" if backend() == "postgres" else "INTEGER"))


def get_setting(key, default=None):
    ensure_schema()
    c = connect(True)          # the writer: a switch just flipped must read as flipped
    try:
        cur = c.cursor()
        _settings_table(cur)
        cur.execute(_q("SELECT value FROM settings WHERE key = %s"), [key])
        row = cur.fetchone()
        return row[0] if row else default
    finally:
        c.close()


def set_setting(key, value, by=None):
    ensure_schema()
    now = int(__import__("time").time() * 1000)
    c = connect(True)
    try:
        cur = c.cursor()
        _settings_table(cur)
        if backend() == "postgres":
            cur.execute("INSERT INTO settings (key, value, updated_ms, updated_by) VALUES (%s,%s,%s,%s) "
                        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_ms = EXCLUDED.updated_ms, "
                        "updated_by = EXCLUDED.updated_by", [key, value, now, by])
        else:
            cur.execute("INSERT OR REPLACE INTO settings (key, value, updated_ms, updated_by) VALUES (?,?,?,?)", [key, value, now, by])
        c.commit()
    finally:
        c.close()


def scan_ticket_ids(ticket_ids):
    """Which of these tickets already have a row (any status) -- the import skips them."""
    ids = [int(t) for t in ticket_ids if str(t).isdigit()]
    if not ids:
        return set()
    ensure_schema()
    marks = ",".join(["%s"] * len(ids))
    return {r[0] for r in _read("SELECT DISTINCT ticket_id FROM sos_scans WHERE ticket_id IN (" + marks + ")", ids, fresh=True)}
