"""Cases: every Zendesk ticket created since 1 January 2026, kept here so the AI
can answer "any cases similar to #12345?" or "how many cases talked about a
black screen in September?".

What is kept per ticket -- and what is not:
  kept   subject, the first message (cleaned, first 1,500 characters), tags,
         status, type, priority, channel, created / updated dates
  NOT    who asked or who answered: no requester, no agent, no organization,
         no later replies. The first message is cleaned before it is saved:
         e-mail addresses, phone numbers, greetings ("Hi Anna,") and the
         signature block are removed (scrub). The AI is told to refuse
         questions about specific people too (askai.py); this is the second wall.

Getting them (Settings > Cases, admin): "Download" walks Zendesk's search
export a week at a time from 1 January 2026, saving each week before the next,
so a restart carries on from the week it was on (setting cases_next). After
that, "Update" (and the hourly loop) reads only tickets updated since the last
update. Reads only -- nothing is written to Zendesk. The SOS package and SSO
validation tickets are left out: they have their own pages.

Search: PostgreSQL full-text search (a generated tsvector, subject weighted
above the message); locally on SQLite a plain word count does the same job.
"""
import calendar, json, re, sys, threading, time

import store
import zendesk

START = "2026-01-01"
BEFORE = "2025-12-31"          # Zendesk search has > and <, not >=
BODY_CHARS = 1500
WEEK = 7 * 86400
SYNC_EVERY = 3600
SKIP_SUBJECTS = ("New SOS package created by", "Here comes a new request to validate SSO method")

COLS = ("ticket_id", "created_ms", "updated_ms", "status", "type", "priority", "channel", "subject", "body", "tags")

DDL_PG = """CREATE TABLE IF NOT EXISTS cases (
    ticket_id BIGINT PRIMARY KEY,
    created_ms BIGINT NOT NULL, updated_ms BIGINT,
    status TEXT, type TEXT, priority TEXT, channel TEXT,
    subject TEXT, body TEXT, tags TEXT,
    saved_ms BIGINT,
    tsv tsvector GENERATED ALWAYS AS (
        setweight(to_tsvector('english', coalesce(subject, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(tags, '')), 'B') ||
        setweight(to_tsvector('english', coalesce(body, '')), 'C')) STORED)"""
DDL_SQLITE = """CREATE TABLE IF NOT EXISTS cases (
    ticket_id INTEGER PRIMARY KEY,
    created_ms INTEGER NOT NULL, updated_ms INTEGER,
    status TEXT, type TEXT, priority TEXT, channel TEXT,
    subject TEXT, body TEXT, tags TEXT,
    saved_ms INTEGER)"""

_ready = False


def _pg():
    return store.backend() == "postgres"


def ensure():
    global _ready
    if _ready:
        return
    store.ensure_schema()
    c = store.connect(True)
    try:
        cur = c.cursor()
        if _pg():
            cur.execute(DDL_PG)
            cur.execute("CREATE INDEX IF NOT EXISTS cases_tsv ON cases USING GIN (tsv)")
            cur.execute("CREATE INDEX IF NOT EXISTS cases_created ON cases (created_ms DESC)")
        else:
            cur.execute(DDL_SQLITE)
            cur.execute("CREATE INDEX IF NOT EXISTS cases_created ON cases (created_ms)")
        c.commit()
    finally:
        c.close()
    _ready = True


def _now():
    return int(time.time() * 1000)


def _ms(iso):
    try:
        return int(calendar.timegm(time.strptime((iso or "")[:19], "%Y-%m-%dT%H:%M:%S")) * 1000)
    except ValueError:
        return None


def _day(ms):
    return time.strftime("%Y-%m-%d", time.gmtime(ms / 1000))


# ---- the wall: nothing that identifies a person is kept ----------------------------------

_EMAIL = re.compile(r"[\w.+'-]+@[\w-]+(\.[\w-]+)+")
_PHONE = re.compile(r"(\+\d[\d\s().-]{7,}\d)|(\(\d{3}\)\s*\d{3}[\s.-]\d{4})|(\b\d{3}[.-]\d{3}[.-]\d{4}\b)")
_URL = re.compile(r"https?://([^/\s]+)\S*")
_GREETING = re.compile(r"^\s*(hi|hello|hey|dear|good (morning|afternoon|evening)|greetings)\b[^\n]{0,60}$", re.I)
_SIGNOFF = re.compile(r"^\s*(best|kind|warm|many)?\s*(regards|wishes)\b|^\s*(sincerely|cheers|thanks|thank you|thx|"
                      r"respectfully|br|mvg|saludos|cordialement|mit freundlichen)\b[\s,.!-]*(so much|again|in advance)?[\s,.!]*$"
                      r"|^\s*sent from my\b|^\s*-- ?$|^\s*_{5,}|^\s*from:\s", re.I)


def scrub(text):
    """The first message without the things that say who someone is."""
    lines = (text or "").replace("\r", "").split("\n")
    out = []
    for i, line in enumerate(lines):
        if i < 3 and _GREETING.match(line):
            continue
        if _SIGNOFF.match(line) and sum(len(l) for l in out) > 40:
            break                                     # the signature block (and quoted mail below it)
        out.append(line)
    t = "\n".join(out)
    t = _EMAIL.sub("[email]", t)
    t = _PHONE.sub("[phone]", t)
    t = _URL.sub(lambda m: "[link: %s]" % m.group(1), t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n\s*\n+", "\n", t).strip()
    return t[:BODY_CHARS]


# NUL and the other control characters (tab and newline aside): PostgreSQL
# refuses a NUL in text outright (DataError), and some tickets carry them.
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _txt(v, n):
    v = _CTRL.sub("", str(v or ""))[:n]
    return v or None


def _row(t):
    via = ((t.get("via") or {}).get("channel") or "")
    return (int(t["id"]), _ms(t.get("created_at")) or _now(), _ms(t.get("updated_at")), _txt(t.get("status"), 20),
            _txt(t.get("type"), 20), _txt(t.get("priority"), 20), _txt(via, 40),
            _txt(_EMAIL.sub("[email]", _CTRL.sub("", t.get("subject") or "")), 300),
            _txt(scrub(_CTRL.sub("", t.get("description") or "")), BODY_CHARS),
            _txt(" ".join(str(x) for x in t.get("tags") or []), 1000))


def _wanted(t):
    subj = str(t.get("subject") or "")
    return t.get("id") and not any(subj.startswith(s) for s in SKIP_SUBJECTS) and (_ms(t.get("created_at")) or 0) >= _ms(START + "T00:00:00")


def _insert(rows, now):
    c = store.connect(True)
    try:
        cur = c.cursor()
        if _pg():
            cur.executemany("INSERT INTO cases (%s, saved_ms) VALUES (%s) ON CONFLICT (ticket_id) DO UPDATE SET %s"
                            % (", ".join(COLS), ", ".join(["%s"] * (len(COLS) + 1)),
                               ", ".join("%s = EXCLUDED.%s" % (k, k) for k in COLS[1:] + ("saved_ms",))),
                            [r + (now,) for r in rows])
        else:
            cur.executemany("INSERT OR REPLACE INTO cases (%s, saved_ms) VALUES (%s)" % (", ".join(COLS), ",".join(["?"] * (len(COLS) + 1))),
                            [r + (now,) for r in rows])
        c.commit()
    finally:
        c.close()


def save(tickets):
    rows = []
    for t in tickets:
        try:
            if _wanted(t):
                rows.append(_row(t))
        except (ValueError, TypeError, KeyError):
            JOB["skipped"] = JOB.get("skipped", 0) + 1
    if not rows:
        return 0
    ensure()
    now = _now()
    try:
        _insert(rows, now)
        return len(rows)
    except Exception:
        pass
    # One ticket the database won't take must not stop the week: one at a time, skipping it.
    saved = 0
    for r in rows:
        try:
            _insert([r], now)
            saved += 1
        except Exception as e:
            JOB["skipped"] = JOB.get("skipped", 0) + 1
            # the database's own reason (no ticket text, no connection details)
            why = (getattr(getattr(e, "diag", None), "message_primary", None) or "")[:120]
            sys.stderr.write("[cases] #%s not saved: %s%s\n" % (r[0], type(e).__name__, (" -- " + why) if why else ""))
    return saved


# ---- download / update jobs (background, one at a time) ----------------------------------

JOB = {"running": False, "kind": None, "saved": 0, "week": None, "error": None, "finished_ms": None, "stop": False}
_lock = threading.Lock()


def _search(query):
    """Every ticket the query matches, retrying a rate limit (429) a few times."""
    for attempt in range(4):
        try:
            return list(zendesk.search_tickets(query))
        except zendesk.ZendeskError as e:
            if "429" not in str(e) or attempt == 3:
                raise
            time.sleep(30 * (attempt + 1))


def _download():
    nxt = store.get_setting("cases_next", "") or START
    if not store.get_setting("cases_synced", ""):
        # Updates later pick up everything that changed from the moment the download began.
        store.set_setting("cases_synced", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "cases")
    week = _ms(nxt + "T00:00:00")
    while week < _now() and not JOB["stop"]:
        end = week + WEEK * 1000
        JOB["week"] = _day(week)
        # Zendesk compares whole days: created>(the day before) created<(the day after the week)
        JOB["saved"] += save(_search("type:ticket created>%s created<%s" % (_day(week - 86400000), _day(end))))
        week = end
        store.set_setting("cases_next", _day(week), "cases")      # this week is done: a restart starts after it
    if not JOB["stop"]:
        store.set_setting("cases_downloaded", str(_now()), "cases")


def _update():
    since = store.get_setting("cases_synced", "")
    if not since:
        return
    began = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 600))   # a little overlap: search lags
    JOB["week"] = None
    JOB["saved"] += save(_search("type:ticket created>%s updated>%s" % (BEFORE, since)))
    store.set_setting("cases_synced", began, "cases")


def _run(kind):
    try:
        if zendesk.configured():
            raise zendesk.ZendeskError("SplashHub Centre has no Zendesk login yet")
        ensure()
        if kind == "download":
            _download()
            if not JOB["stop"]:
                _update()
        else:
            _update()
    except zendesk.ZendeskError as e:
        JOB["error"] = str(e)[:300]
    except Exception as e:
        JOB["error"] = "internal error (%s) -- see the app log" % type(e).__name__
        why = (getattr(getattr(e, "diag", None), "message_primary", None) or "")[:120]     # a database error's own reason
        sys.stderr.write("[cases] %s failed: %s%s\n" % (kind, type(e).__name__, (" -- " + why) if why else ""))
    finally:
        JOB.update(running=False, finished_ms=_now(), stopped=JOB["stop"])
        if kind == "download":
            try:
                store.set_setting("cases_running", "", "cases")
            except Exception:
                pass
        sys.stderr.write("[cases] %s finished: %d saved%s\n" % (kind, JOB["saved"], (" -- " + JOB["error"]) if JOB["error"] else ""))


def start(kind):
    with _lock:
        if JOB["running"]:
            return False
        JOB.update(running=True, kind=kind, saved=0, skipped=0, week=None, error=None, finished_ms=None, stop=False, stopped=False)
    if kind == "download":
        store.set_setting("cases_running", "yes", "cases")
    threading.Thread(target=_run, args=(kind,), name="cases-" + kind, daemon=True).start()
    return True


def stop():
    if JOB["running"]:
        JOB["stop"] = True
        return True
    return False


def boot():
    """At start-up: carry on a download a restart interrupted, then update hourly."""
    def loop():
        try:
            if store.get_setting("cases_running", "") == "yes":
                sys.stderr.write("[cases] carrying on the download after a restart\n")
                start("download")
        except Exception as e:
            sys.stderr.write("[cases] could not resume: %s\n" % type(e).__name__)
        while True:
            time.sleep(SYNC_EVERY)
            try:
                if store.get_setting("cases_downloaded", "") and not zendesk.configured():
                    start("update")
            except Exception as e:
                sys.stderr.write("[cases] hourly update skipped: %s\n" % type(e).__name__)
    threading.Thread(target=loop, name="cases-loop", daemon=True).start()


def status():
    ensure()
    n, first, last = store._read("SELECT count(*), min(created_ms), max(created_ms) FROM cases", [])[0]
    synced = store.get_setting("cases_synced", "")
    return dict(JOB, count=n, first=_day(first) if first else None, last=_day(last) if last else None,
                next_week=store.get_setting("cases_next", "") or START,
                downloaded=bool(store.get_setting("cases_downloaded", "")),
                updated=synced or None)


def zendesk_count():
    """How many tickets Zendesk has from 2026 (search count; one call)."""
    from urllib.parse import quote
    d = zendesk.get_json("/api/v2/search/count.json?query=" + quote("type:ticket created>" + BEFORE))
    return d.get("count")


# ---- what the AI asks ------------------------------------------------------------------

STOP = set("""a about above after again against all am an and any are aren't as at be because been before being below
between both but by can can't cannot could couldn't did didn't do does doesn't doing don't down during each few for from
further had hadn't has hasn't have haven't having he her here hers herself him himself his how i if in into is isn't it
it's its itself let's me more most mustn't my myself no nor not of off on once only or other ought our ours ourselves out
over own same she should shouldn't so some such than that that's the their theirs them themselves then there there's these
they this those through to too under until up very was wasn't we were weren't what when where which while who whom why
with won't would wouldn't you your yours yourself yourselves hi hello thanks thank please regards issue problem help
need able get getting got use using used also still just like case cases ticket tickets customer splashtop dear team
know want would could one two see seems try tried trying however anything something""".split())


def keywords(text, n=12):
    """The words that carry a text's meaning: no stop words, the most frequent first."""
    count = {}
    text = re.sub(r"\[(email|phone|link: [^\]]*)\]", " ", text or "")       # scrub()'s placeholders
    for w in re.findall(r"[a-z0-9][a-z0-9.+-]*[a-z0-9]|[a-z0-9]", text.lower()):
        if len(w) < 3 or w in STOP or w.isdigit():
            continue
        count[w] = count.get(w, 0) + 1
    return [w for w, _ in sorted(count.items(), key=lambda x: (-x[1], x[0]))][:n]


def _words(query):
    ws = [w for w in re.findall(r"[a-z0-9]+", (query or "").lower()) if w not in STOP and len(w) > 1]
    return list(dict.fromkeys(ws))[:16]


def _filters(from_date, to_date, status, tag):
    where, args = [], []
    for col, op, v in (("created_ms", ">=", from_date), ("created_ms", "<", to_date)):
        ms = _ms((v or "")[:10] + "T00:00:00") if v else None
        if ms:
            where.append("%s %s %%s" % (col, op))
            args.append(ms + (86400000 if op == "<" else 0))          # to_date is inclusive
    if status:
        where.append("status = %s")
        args.append(str(status).lower().strip())
    if tag:
        where.append("(' ' || coalesce(tags, '') || ' ') LIKE %s")
        args.append("% " + str(tag).lower().strip() + " %")
    return where, args


def _snippet(body, words):
    b = body or ""
    low = b.lower()
    hits = [low.find(w) for w in words if low.find(w) >= 0]
    at = max(0, min(hits) - 80) if hits else 0
    s = b[at:at + 260].replace("\n", " ")
    return ("…" if at else "") + s + ("…" if at + 260 < len(b) else "")


def _out(r, words):
    d = dict(zip(COLS, r))
    return {"ticket": d["ticket_id"], "date": _day(d["created_ms"]), "status": d["status"], "subject": d["subject"],
            "tags": (d["tags"] or "").split()[:8], "snippet": _snippet(d["body"], words)}


def search(query, from_date=None, to_date=None, status=None, tag=None, limit=10, exclude=None):
    """Cases matching any of the query's words, best first, with how many match
    in all and per month."""
    ensure()
    words = _words(query)
    if not words and not (from_date or to_date or status or tag):
        return {"error": "give some words to look for"}
    limit = max(1, min(int(limit or 10), 20))
    where, args = _filters(from_date, to_date, status, tag)
    if exclude:
        where.append("ticket_id <> %s")
        args.append(int(exclude))
    cols = ", ".join(COLS)
    if _pg():
        if words:
            where.append("tsv @@ q")
        w = (" WHERE " + " AND ".join(where)) if where else ""
        qsrc = (", to_tsquery('english', %s) q") if words else ""
        qarg = [" | ".join(words)] if words else []
        rank = "ts_rank_cd(tsv, q)" if words else "created_ms"
        rows = store._read("SELECT %s FROM cases%s%s ORDER BY %s DESC, created_ms DESC LIMIT %d" % (cols, qsrc, w, rank, limit), qarg + args)
        total = store._read("SELECT count(*) FROM cases%s%s" % (qsrc, w), qarg + args)[0][0]
        months = store._read("SELECT to_char(to_timestamp(created_ms / 1000), 'YYYY-MM') m, count(*) FROM cases%s%s GROUP BY m ORDER BY m"
                             % (qsrc, w), qarg + args)
    else:
        if words:
            where.append("(" + " OR ".join(["lower(coalesce(subject,'') || ' ' || coalesce(tags,'') || ' ' || coalesce(body,'')) LIKE %s"] * len(words)) + ")")
            args += ["%" + x + "%" for x in words]
        w = (" WHERE " + " AND ".join(where)) if where else ""
        cand = store._read("SELECT %s FROM cases%s" % (cols, w), args)

        def score(r):
            d = dict(zip(COLS, r))
            subj, rest = (d["subject"] or "").lower(), ((d["tags"] or "") + " " + (d["body"] or "")).lower()
            return sum(3 * subj.count(x) + rest.count(x) for x in words) + (len(set(x for x in words if x in subj + rest)) * 5)
        cand.sort(key=lambda r: (-score(r), -r[1]))
        rows, total = cand[:limit], len(cand)
        mm = {}
        for r in cand:
            mm[_day(r[1])[:7]] = mm.get(_day(r[1])[:7], 0) + 1
        months = sorted(mm.items())
    return {"looked_for": words, "matching_cases": total, "by_month": dict(months),
            "best_matches": [_out(r, words) for r in rows]}


def read(ticket_id):
    ensure()
    try:
        tid = int(str(ticket_id).lstrip("#"))
    except (TypeError, ValueError):
        return None
    rows = store._read("SELECT %s FROM cases WHERE ticket_id = %%s" % ", ".join(COLS), [tid])
    if not rows:
        return None
    d = dict(zip(COLS, rows[0]))
    return {"ticket": tid, "created": _day(d["created_ms"]), "updated": _day(d["updated_ms"]) if d["updated_ms"] else None,
            "status": d["status"], "type": d["type"], "priority": d["priority"], "channel": d["channel"],
            "subject": d["subject"], "first_message": d["body"], "tags": (d["tags"] or "").split()}


def similar(ticket_id, limit=8):
    """Cases like one ticket: its own words, searched for."""
    me = read(ticket_id)
    if not me:
        try:                                         # not kept (yet): read it from Zendesk, keep nothing personal
            t = zendesk.ticket(int(str(ticket_id).lstrip("#")))
            me = {"ticket": t["id"], "subject": t["subject"], "first_message": scrub(t["description"]), "tags": []}
        except (zendesk.ZendeskError, ValueError, TypeError):
            return {"error": "ticket #%s isn't among the downloaded cases and couldn't be read from Zendesk" % ticket_id}
    words = list(dict.fromkeys(keywords(me["subject"], 6) + keywords(me["first_message"], 10) +
                               [t for t in me.get("tags") or [] if len(t) > 3][:4]))[:16]
    res = search(" ".join(words), limit=limit, exclude=me["ticket"])
    res["about"] = {"ticket": me["ticket"], "subject": me["subject"]}
    return res


def overview(from_date=None, to_date=None):
    """The general picture over a period: totals, per month, status, channel,
    the most used tags and the words most used in subjects."""
    ensure()
    where, args = _filters(from_date, to_date, None, None)
    w = (" WHERE " + " AND ".join(where)) if where else ""
    total = store._read("SELECT count(*) FROM cases" + w, args)[0][0]
    by_status = dict(store._read("SELECT coalesce(status,'?'), count(*) FROM cases%s GROUP BY 1 ORDER BY 2 DESC" % w, args))
    by_channel = dict(store._read("SELECT coalesce(channel,'?'), count(*) FROM cases%s GROUP BY 1 ORDER BY 2 DESC LIMIT 8" % w, args))
    if _pg():
        months = store._read("SELECT to_char(to_timestamp(created_ms / 1000), 'YYYY-MM') m, count(*) FROM cases%s GROUP BY m ORDER BY m" % w, args)
        tags = store._read("SELECT t, count(*) FROM cases, unnest(string_to_array(coalesce(tags,''), ' ')) t%s%s GROUP BY t "
                           "ORDER BY 2 DESC LIMIT 25" % (w if w else " WHERE true", " AND t <> ''"), args)
        subj = store._read("SELECT t, count(*) FROM cases, unnest(tsvector_to_array(to_tsvector('english', coalesce(subject,'')))) t%s "
                           "GROUP BY t ORDER BY 2 DESC LIMIT 40" % w, args)
    else:
        rows = store._read("SELECT created_ms, tags, subject FROM cases" + w, args)
        mm, tg, sw = {}, {}, {}
        for ms, tags_, subject in rows:
            mm[_day(ms)[:7]] = mm.get(_day(ms)[:7], 0) + 1
            for t in (tags_ or "").split():
                tg[t] = tg.get(t, 0) + 1
            for x in set(keywords(subject, 50)):
                sw[x] = sw.get(x, 0) + 1
        months = sorted(mm.items())
        tags = sorted(tg.items(), key=lambda x: -x[1])[:25]
        subj = sorted(sw.items(), key=lambda x: -x[1])[:40]
    subj = [(t, n) for t, n in subj if t not in STOP and len(t) > 2][:25]
    return {"cases": total, "from": from_date or START, "to": to_date or _day(_now()), "by_month": dict(months),
            "by_status": by_status, "by_channel": by_channel, "top_tags": dict(tags), "top_subject_words": dict(subj)}
