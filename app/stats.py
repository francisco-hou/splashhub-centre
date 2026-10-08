"""Statistics (admin): how often the Wrap Up note is on the tickets the team solves.

Every ticket solved (or closed) in Zendesk from a month before this was first
switched on, and from then on, read in the background:
  - Chat (chat and messaging) or Ticket (email, web form, API...); phone calls
    and voicemails are left out -- they aren't counted at all.
  - Its Assignee: the agent it is counted for.
  - Whether its conversation has the Wrap Up note: an INTERNAL note in the
    team's shape ("Inquiry: ... / Solutions: ... / Resolved: ..."), as the
    SplashHub sidebar's Wrap Up button writes it (a note typed by hand in that
    shape counts too). Read from the ticket itself, so only notes that were
    actually submitted count.
Counts only: no list of tickets. Nothing is written to Zendesk. Per agent, so
admin only -- and never given to Ask AI or Spark (they don't discuss agents).

A ticket is read again when Zendesk says it changed after it was read
(re-opened and solved again, a note added late). Gentle on Zendesk: one
comment read at a time, a short pause between.
"""
import re, sys, threading, time

import store

KEY_SINCE = "stats_since"
EVERY = 900                    # a round every 15 minutes
PER_ROUND = 1500               # conversations read per round, at most
PAUSE = 0.25                   # between Zendesk calls (~240 a minute)
COLS = ("ticket_id", "solved_ms", "updated_ms", "kind", "channel", "assignee_id", "assignee", "status",
        "wrap", "wrap_by", "wrap_ms", "checked_ms")
DDL = """CREATE TABLE IF NOT EXISTS stat_tickets (
    ticket_id BIGINT PRIMARY KEY, solved_ms BIGINT, updated_ms BIGINT, kind TEXT, channel TEXT,
    assignee_id BIGINT, assignee TEXT, status TEXT, wrap INTEGER, wrap_by TEXT, wrap_ms BIGINT, checked_ms BIGINT)"""
WRAP_RE = re.compile(r"(?im)^\s*inquiry\s*:.*?^\s*solutions?\s*:.*?^\s*resolved\s*:", re.S)
_ready = False
_lock = threading.Lock()
STATE = {"busy": False, "last_ms": None, "error": None, "found": 0, "read": 0, "to_read": 0}
_NAMES = {}


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
        cur.execute(DDL)
        cur.execute("CREATE INDEX IF NOT EXISTS stat_tickets_solved ON stat_tickets (solved_ms)")
        c.commit()
    finally:
        c.close()
    _ready = True


def since():
    """The first day counted: a month before Statistics first ran (kept from then on)."""
    s = store.get_setting(KEY_SINCE, "")
    if not s:
        s = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 30 * 86400))
        store.set_setting(KEY_SINCE, s, "stats")
    return s


# ---- reading Zendesk -----------------------------------------------------------------------------

def _names(ids):
    """Agents' names by user id (cached), 100 to a call."""
    import zendesk
    want = [i for i in {int(x) for x in ids if x} if i not in _NAMES]
    for i in range(0, len(want), 100):
        d = zendesk.get_json("/api/v2/users/show_many.json?ids=" + ",".join(str(x) for x in want[i:i + 100]))
        for u in d.get("users") or []:
            _NAMES[int(u["id"])] = u.get("name") or ("user %s" % u["id"])
        time.sleep(PAUSE)
    return _NAMES


def _wrap_note(ticket_id):
    """(found?, author id, when) -- an internal note in the Wrap Up shape, the latest one."""
    import zendesk
    url, pages, hit = "/api/v2/tickets/%d/comments.json?page[size]=100" % int(ticket_id), 0, (False, None, None)
    while url and pages < 5:
        d = zendesk.get_json(url)
        pages += 1
        for c in d.get("comments") or []:
            if c.get("public") is False and WRAP_RE.search(c.get("plain_body") or c.get("body") or ""):
                hit = (True, c.get("author_id"), _ms(c.get("created_at")))
        nxt = (d.get("links") or {}).get("next") if (d.get("meta") or {}).get("has_more") else None
        url = nxt[len(zendesk.base_url()):] if nxt and nxt.startswith(zendesk.base_url()) else None
        if url:
            time.sleep(PAUSE)
    return hit


def _ms(iso):
    import calendar
    try:
        return int(calendar.timegm(time.strptime((iso or "")[:19], "%Y-%m-%dT%H:%M:%S")) * 1000)
    except ValueError:
        return None


def run_once(limit=PER_ROUND):
    import zendesk, autotag
    ensure()
    if zendesk.configured():
        raise RuntimeError("SplashHub Centre can't read Zendesk yet")
    first = since()
    found = list(zendesk.search_tickets("status>=solved solved>=%s" % first, max_pages=300))
    STATE["found"] = len(found)
    have = {int(r[0]): (r[1], r[2]) for r in store._read("SELECT ticket_id, updated_ms, checked_ms FROM stat_tickets", [], fresh=True)}
    rows = []
    for t in found:
        ch = ((t.get("via") or {}).get("channel") or "")
        if autotag._is_call(ch, t.get("subject"), t.get("tags")):        # calls aren't counted
            continue
        tid, upd = int(t["id"]), _ms(t.get("updated_at"))
        solved = upd                                                       # until its metrics say when it was solved
        old = have.get(tid)
        if old and old[0] == upd:
            continue                                                       # unchanged since read
        rows.append({"ticket_id": tid, "solved_ms": solved, "updated_ms": upd, "kind": "chat" if autotag._chat_kind(t) else "ticket",
                     "channel": ch, "assignee_id": t.get("assignee_id"), "status": t.get("status")})
    for i in range(0, len(rows), 100):                                    # when each was solved: its metrics, 100 to a call
        part = rows[i:i + 100]
        d = zendesk.get_json("/api/v2/tickets/show_many.json?include=metric_sets&ids=" + ",".join(str(r["ticket_id"]) for r in part))
        when = {int(m["ticket_id"]): _ms(m.get("solved_at")) for m in d.get("metric_sets") or [] if m.get("ticket_id")}
        for r in part:
            r["solved_ms"] = when.get(r["ticket_id"]) or r["solved_ms"]
        time.sleep(PAUSE)
    names = _names([r["assignee_id"] for r in rows]) if rows else _NAMES
    c = store.connect(True)
    try:
        cur = c.cursor()
        for r in rows:
            cur.execute(store._q("INSERT INTO stat_tickets (ticket_id, solved_ms, updated_ms, kind, channel, assignee_id, assignee, status) "
                                 "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (ticket_id) DO UPDATE SET solved_ms = EXCLUDED.solved_ms, "
                                 "updated_ms = EXCLUDED.updated_ms, kind = EXCLUDED.kind, channel = EXCLUDED.channel, "
                                 "assignee_id = EXCLUDED.assignee_id, assignee = EXCLUDED.assignee, status = EXCLUDED.status"),
                        (r["ticket_id"], r["solved_ms"], r["updated_ms"], r["kind"], r["channel"], r["assignee_id"],
                         names.get(int(r["assignee_id"])) if r["assignee_id"] else None, r["status"]))
        c.commit()
    finally:
        c.close()
    # conversations not read yet, or changed since: is the Wrap Up note there?
    todo = [int(r[0]) for r in store._read("SELECT ticket_id FROM stat_tickets WHERE checked_ms IS NULL OR updated_ms > checked_ms "
                                           "ORDER BY solved_ms DESC", [], fresh=True)]
    STATE["to_read"], STATE["read"] = len(todo), 0
    for tid in todo[:limit]:
        try:
            ok, by, when = _wrap_note(tid)
        except Exception as e:
            if "HTTP 404" in str(e):                                       # gone from Zendesk: not counted
                c = store.connect(True)
                try:
                    c.cursor().execute(store._q("DELETE FROM stat_tickets WHERE ticket_id = %s"), (tid,))
                    c.commit()
                finally:
                    c.close()
                continue
            raise
        who = _names([by]).get(int(by)) if by else None
        c = store.connect(True)
        try:
            c.cursor().execute(store._q("UPDATE stat_tickets SET wrap = %s, wrap_by = %s, wrap_ms = %s, checked_ms = %s WHERE ticket_id = %s"),
                               (1 if ok else 0, who, when, _now(), tid))
            c.commit()
        finally:
            c.close()
        STATE["read"] += 1
        time.sleep(PAUSE)


def _round():
    if not _lock.acquire(blocking=False):
        return
    STATE.update(busy=True, error=None)
    try:
        run_once()
        STATE["last_ms"] = _now()
    except Exception as e:
        STATE.update(last_ms=_now(), error=str(e)[:200] if "Zendesk" in str(e) else "a round failed (%s)" % type(e).__name__)
        sys.stderr.write("[stats] %s\n" % STATE["error"])
    finally:
        STATE["busy"] = False
        _lock.release()


def kick():
    threading.Thread(target=_round, name="stats-now", daemon=True).start()


def boot():
    def loop():
        time.sleep(60)
        while True:
            _round()
            time.sleep(EVERY)
    threading.Thread(target=loop, name="stats-loop", daemon=True).start()


# ---- the page --------------------------------------------------------------------------------------

def _week(ms):
    """The Monday (UTC) of a timestamp's week, as YYYY-MM-DD."""
    t = time.gmtime(ms / 1000)
    return time.strftime("%Y-%m-%d", time.gmtime(ms / 1000 - t.tm_wday * 86400))


def overview(period="30"):
    """Counts for the page: totals (Chat / Ticket), per agent, per week. Only
    tickets whose conversation has been read are counted (others: to_read)."""
    ensure()
    first = since()
    now = _now()
    start = {"7": now - 7 * 86400000, "30": now - 30 * 86400000}.get(str(period)) or _ms(first + "T00:00:00") or 0
    rows = store._read("SELECT solved_ms, kind, assignee, wrap, checked_ms FROM stat_tickets WHERE solved_ms >= %s", [start], fresh=True)
    blank = lambda: {"chat": [0, 0], "ticket": [0, 0]}
    total, agents, pending = blank(), {}, 0
    for solved, kind, who, wrap, checked in rows:
        if checked is None:
            pending += 1
            continue
        k = "chat" if kind == "chat" else "ticket"
        for bucket in (total, agents.setdefault(who or "(no assignee)", blank())):
            bucket[k][0] += 1
            bucket[k][1] += 1 if wrap else 0
    weeks = {}
    for solved, kind, who, wrap, checked in store._read("SELECT solved_ms, kind, assignee, wrap, checked_ms FROM stat_tickets "
                                                        "WHERE checked_ms IS NOT NULL AND solved_ms >= %s", [_ms(first + "T00:00:00") or 0], fresh=True):
        if not solved:
            continue
        w = weeks.setdefault(_week(solved), [0, 0])
        w[0] += 1
        w[1] += 1 if wrap else 0
    pack = lambda b: {k: {"solved": v[0], "wrapped": v[1]} for k, v in b.items()}
    return {"period": str(period), "since": first, "start_ms": start, "total": pack(total),
            "agents": sorted(({"agent": a, **pack(b)} for a, b in agents.items()),
                             key=lambda x: -(x["chat"]["solved"] + x["ticket"]["solved"])),
            "weeks": [{"week": w, "solved": v[0], "wrapped": v[1]} for w, v in sorted(weeks.items())],
            "pending": pending, "state": dict(STATE)}
