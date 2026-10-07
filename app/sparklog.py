"""Spark activity: every decision Spark makes behind the scenes, kept 30 days
(Settings > AI > Spark activity, admin only).

One row per Spark call made with log= (spark.chat): the area, the ticket(s),
what Spark was given (the question and the text it read), its raw answer, its
reasoning when Settings > Spark lets it think, how long it took -- and what
SplashHub Centre then did with it (decide()), e.g. "Not SSO: moved out of the
list" or "#90001 Japanese (held)".

Areas: sso_relevance, sso_stage, autotag, ad_filter, teams_languages,
sos_translate, sos_dashboard, customers.
"""
import json, re, sys, threading, time

import store

KEEP_DAYS = 30
AREAS = {"sso_relevance": "SSO · is it an SSO request?", "sso_stage": "SSO · where it stands",
         "autotag": "AutoTag · language", "teams_languages": "Teams · language routing",
         "sos_translate": "SOS Scans · translation", "sos_dashboard": "SOS Scans · dashboard notes",
         "customers": "Customers · summary", "ad_filter": "Ad filter · ad or spam?"}
DDL = """CREATE TABLE IF NOT EXISTS spark_log (
    id {ID}, ts_ms {INT} NOT NULL, area TEXT NOT NULL, tickets TEXT, question TEXT, input TEXT, answer TEXT,
    thinking TEXT, decision TEXT, changed {INT} NOT NULL DEFAULT 0, ms {INT}, model TEXT, error TEXT,
    tokens_in {INT}, tokens_out {INT}, n_tickets {INT})"""
_ready = False
_pruned = {"ms": 0}


def _now():
    return int(time.time() * 1000)


def ensure():
    global _ready
    if _ready:
        return
    store.ensure_schema()
    c = store.connect(True)
    try:
        cur = c.cursor()
        if store.backend() == "postgres":
            cur.execute(DDL.replace("{ID}", "BIGSERIAL PRIMARY KEY").replace("{INT}", "BIGINT"))
        else:
            cur.execute(DDL.replace("{ID}", "INTEGER PRIMARY KEY AUTOINCREMENT").replace("{INT}", "INTEGER"))
        cur.execute("CREATE INDEX IF NOT EXISTS spark_log_ts ON spark_log (ts_ms)")
        c.commit()
    finally:
        c.close()
    _ready = True


def _tickets(t):
    if t is None:
        return None
    ids = t if isinstance(t, (list, tuple, set)) else [t]
    ids = [str(int(i)) for i in ids if str(i).strip().isdigit()]
    return (" " + " ".join(ids) + " ") if ids else None    # spaced, so "#123" never matches 1234


def record(area, tickets, question, user_text, answer, thinking, ms, model, error=None, tokens_in=None, tokens_out=None):
    """One Spark call; returns its id (None if it couldn't be kept -- logging never breaks the work)."""
    try:
        ensure()
        c = store.connect(True)
        try:
            cur = c.cursor()
            tk = _tickets(tickets)
            vals = (_now(), area, tk, (question or "")[:4000], (user_text or "")[:6000], (answer or "")[:6000],
                    (thinking or "")[:12000] or None, ms, model, (error or "")[:400] or None,
                    tokens_in, tokens_out, len(tk.split()) if tk else None)
            sql = ("INSERT INTO spark_log (ts_ms, area, tickets, question, input, answer, thinking, ms, model, error, "
                   "tokens_in, tokens_out, n_tickets) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)")
            if store.backend() == "postgres":
                cur.execute(sql + " RETURNING id", vals)
                rid = cur.fetchone()[0]
            else:
                cur.execute(store._q(sql), vals)
                rid = cur.lastrowid
            c.commit()
        finally:
            c.close()
        _prune()
        return rid
    except Exception as e:
        sys.stderr.write("[sparklog] not kept: %s\n" % type(e).__name__)
        return None


def decide(rid, decision, changed=True):
    """What SplashHub Centre did with the answer."""
    if not rid:
        return
    try:
        c = store.connect(True)
        try:
            c.cursor().execute(store._q("UPDATE spark_log SET decision = %s, changed = %s WHERE id = %s"),
                               ((decision or "")[:1000], 1 if changed else 0, int(rid)))
            c.commit()
        finally:
            c.close()
    except Exception as e:
        sys.stderr.write("[sparklog] decision not kept: %s\n" % type(e).__name__)


def _prune():
    if _now() - _pruned["ms"] < 3600000:
        return
    _pruned["ms"] = _now()
    c = store.connect(True)
    try:
        c.cursor().execute(store._q("DELETE FROM spark_log WHERE ts_ms < %s"), (_now() - KEEP_DAYS * 86400000,))
        c.commit()
    finally:
        c.close()


COLS = ("id", "ts_ms", "area", "tickets", "decision", "changed", "ms", "model", "error", "tokens_in", "tokens_out", "n_tickets")


def stats():
    """The summary: the last 24 hours, and each area over 7 days (decisions,
    average / slowest time, per ticket, changed something, failed)."""
    now = _now()
    d1 = store._read("SELECT count(*), avg(ms), max(ms), sum(CASE WHEN error IS NULL THEN 0 ELSE 1 END), sum(changed), "
                     "sum(coalesce(n_tickets, 0)) FROM spark_log WHERE ts_ms >= %s", [now - 86400000], fresh=True)[0]
    areas = []
    for a, n, avg, mx, err, ch, tix, tin, tout in store._read(
            "SELECT area, count(*), avg(ms), max(ms), sum(CASE WHEN error IS NULL THEN 0 ELSE 1 END), sum(changed), "
            "sum(coalesce(n_tickets, 0)), sum(coalesce(tokens_in, 0)), sum(coalesce(tokens_out, 0)) "
            "FROM spark_log WHERE ts_ms >= %s GROUP BY area ORDER BY count(*) DESC", [now - 7 * 86400000], fresh=True):
        areas.append({"area": a, "label": AREAS.get(a, a), "n": int(n or 0), "avg_ms": int(avg or 0), "max_ms": int(mx or 0),
                      "failed": int(err or 0), "changed": int(ch or 0), "tickets": int(tix or 0),
                      "per_ticket_ms": int((avg or 0) * int(n or 0) / int(tix)) if tix else None,
                      "tokens_in": int(tin or 0), "tokens_out": int(tout or 0)})
    return {"day": {"n": int(d1[0] or 0), "avg_ms": int(d1[1] or 0), "max_ms": int(d1[2] or 0), "failed": int(d1[3] or 0),
                    "changed": int(d1[4] or 0), "tickets": int(d1[5] or 0)}, "areas": areas}


def search(area=None, ticket=None, changed=None, page=0, per_page=50):
    ensure()
    where, args = [], []
    if area:
        where.append("area = %s")
        args.append(area)
    t = re.sub(r"\D", "", str(ticket or ""))
    if t:
        where.append("tickets LIKE %s")
        args.append("% " + t + " %")
    if changed == "yes":
        where.append("changed = 1")
    elif changed == "no":
        where.append("changed = 0")
    elif changed == "error":
        where.append("error IS NOT NULL")
    w = (" WHERE " + " AND ".join(where)) if where else ""
    total = store._read("SELECT count(*) FROM spark_log" + w, args, fresh=True)[0][0]
    rows = store._read("SELECT %s FROM spark_log%s ORDER BY ts_ms DESC LIMIT %d OFFSET %d"
                       % (", ".join(COLS), w, per_page, page * per_page), args, fresh=True)
    out = []
    for r in rows:
        d = dict(zip(COLS, r))
        d["tickets"] = (d["tickets"] or "").split()
        d["area_label"] = AREAS.get(d["area"], d["area"])
        out.append(d)
    counts = dict(store._read("SELECT area, count(*) FROM spark_log GROUP BY area", [], fresh=True))
    return {"rows": out, "total": total, "page": page, "per_page": per_page, "areas": AREAS, "counts": counts,
            "stats": stats() if page == 0 else None}


def get(rid):
    ensure()
    cols = COLS + ("question", "input", "answer", "thinking")
    rows = store._read("SELECT %s FROM spark_log WHERE id = %%s" % ", ".join(cols), [int(rid)], fresh=True)
    if not rows:
        return None
    d = dict(zip(cols, rows[0]))
    d["tickets"] = (d["tickets"] or "").split()
    d["area_label"] = AREAS.get(d["area"], d["area"])
    return d
