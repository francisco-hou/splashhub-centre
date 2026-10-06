"""Cases: every Zendesk ticket created since 1 January 2026, kept here so the AI
can answer "any cases similar to #12345?", "what are customers running into
this month?", "how do we usually fix X?" or "how many 2FA cases in January,
by country?".

What is kept per ticket:
  the ticket   subject, tags, status, type, priority, channel, created / updated
  the customer requester's e-mail and domain, organization, a country guess
               (the e-mail's country domain, else the requester's time zone)
  the words    the first message, and the whole conversation: every public
               reply and internal note, each marked Customer / Support /
               Support (internal note), in order -- up to CONVO_CHARS, keeping
               the start and the end when a long ticket must be cut.
The wall (askai.py): nothing about individual SUPPORT AGENTS. So: replies are
marked "Support", never with a name; the names of the agents on a ticket are
replaced by "[agent]" in its text; Splashtop addresses and signature blocks
are removed; a ticket whose requester is an agent keeps no requester.

Getting them (Settings > Cases, admin). Two passes, both resumable:
  1. tickets  Zendesk's search export, a week at a time from 1 January 2026
              (setting cases_next), with the requesters and organizations
              looked up 100 at a time. Fast: about a page of calls per week.
  2. replies  each ticket's comments, one call per ticket, newest tickets
              first, gently (RATE per second, waiting out a 429). Slow: a few
              hours for a year. Search works from pass 1 on; replies fill in.
After that, "Update" (and the hourly loop) reads tickets updated since the
last update and re-reads their replies. Reads only -- nothing is written to
Zendesk. The SOS package and SSO validation tickets are left out.

Search: PostgreSQL full-text search (a generated tsvector: subject, tags,
first message, conversation, in that order of weight); locally on SQLite a
plain word count does the same job.
"""
import calendar, random, re, sys, threading, time

import store
import zendesk

START = "2026-01-01"
BEFORE = "2025-12-31"          # Zendesk search has > and <, not >=
BODY_CHARS = 2000
CONVO_CHARS = 9000
TURN_CHARS = 1500
WEEK = 7 * 86400
SYNC_EVERY = 3600
RATE = 3.0                     # comment reads per second, at most (Zendesk's limit is shared with every other app)
SCHEMA = "2"
SKIP_SUBJECTS = ("New SOS package created by", "Here comes a new request to validate SSO method")

COLS = ("ticket_id", "created_ms", "updated_ms", "status", "type", "priority", "channel", "subject", "body", "tags",
        "requester_email", "requester_domain", "organization", "country", "tz")
ADDED = (("requester_email", "TEXT"), ("requester_domain", "TEXT"), ("organization", "TEXT"), ("country", "TEXT"),
         ("tz", "TEXT"), ("convo", "TEXT"), ("convo_ms", "BIGINT"), ("convo_turns", "INTEGER"))

DDL_PG = """CREATE TABLE IF NOT EXISTS cases (
    ticket_id BIGINT PRIMARY KEY,
    created_ms BIGINT NOT NULL, updated_ms BIGINT,
    status TEXT, type TEXT, priority TEXT, channel TEXT,
    subject TEXT, body TEXT, tags TEXT,
    saved_ms BIGINT)"""
TSV_PG = """ALTER TABLE cases ADD COLUMN tsv tsvector GENERATED ALWAYS AS (
        setweight(to_tsvector('english', coalesce(subject, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(tags, '')), 'B') ||
        setweight(to_tsvector('english', coalesce(body, '')), 'C') ||
        setweight(to_tsvector('english', coalesce(convo, '')), 'D')) STORED"""
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
    """Additive, like store.py. Schema 2 added the requester, the conversation
    and a search index that covers it: the index is rebuilt once, and the next
    download goes through 2026 again to fill in the requesters."""
    global _ready
    if _ready:
        return
    store.ensure_schema()
    c = store.connect(True)
    try:
        cur = c.cursor()
        if _pg():
            cur.execute("SELECT pg_advisory_lock(716573)")
            cur.execute(DDL_PG)
            for col, typ in ADDED:
                cur.execute("ALTER TABLE cases ADD COLUMN IF NOT EXISTS %s %s" % (col, typ))
            cur.execute("SELECT pg_get_expr(d.adbin, d.adrelid) FROM pg_attribute a JOIN pg_attrdef d "
                        "ON d.adrelid = a.attrelid AND d.adnum = a.attnum WHERE a.attrelid = 'cases'::regclass AND a.attname = 'tsv'")
            row = cur.fetchone()
            if not row or "convo" not in (row[0] or ""):
                cur.execute("DROP INDEX IF EXISTS cases_tsv")
                cur.execute("ALTER TABLE cases DROP COLUMN IF EXISTS tsv")
                cur.execute(TSV_PG)
            cur.execute("CREATE INDEX IF NOT EXISTS cases_tsv ON cases USING GIN (tsv)")
            cur.execute("CREATE INDEX IF NOT EXISTS cases_created ON cases (created_ms DESC)")
            cur.execute("SELECT pg_advisory_unlock(716573)")
        else:
            cur.execute(DDL_SQLITE)
            cur.execute("PRAGMA table_info(cases)")
            have = {r[1] for r in cur.fetchall()}
            for col, typ in ADDED:
                if col not in have:
                    cur.execute("ALTER TABLE cases ADD COLUMN %s %s" % (col, typ))
            cur.execute("CREATE INDEX IF NOT EXISTS cases_created ON cases (created_ms)")
        c.commit()
    finally:
        c.close()
    if store.get_setting("cases_schema", "") != SCHEMA:
        # Tickets saved before schema 2 have no requester: the next download starts over (it only upserts).
        if store.get_setting("cases_next", ""):
            store.set_setting("cases_next", START, "cases")
            store.set_setting("cases_downloaded", "", "cases")
        store.set_setting("cases_schema", SCHEMA, "cases")
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


# ---- cleaning: the wall around support agents, and noise --------------------------------

_AGENT_EMAIL = re.compile(r"[\w.+'-]+@([\w-]+\.)*splashtop\.com\b", re.I)
_PHONE = re.compile(r"(\+\d[\d\s().-]{7,}\d)|(\(\d{3}\)\s*\d{3}[\s.-]\d{4})|(\b\d{3}[.-]\d{3}[.-]\d{4}\b)")
_URL = re.compile(r"https?://([^/\s]+)\S*")
_GREETING = re.compile(r"^\s*(hi|hello|hey|dear|good (morning|afternoon|evening)|greetings)\b[^\n]{0,60}$", re.I)
_SIGNOFF = re.compile(r"^\s*(best|kind|warm|many)?\s*(regards|wishes)\b|^\s*(sincerely|cheers|thanks|thank you|thx|"
                      r"respectfully|br|mvg|saludos|cordialement|mit freundlichen)\b[\s,.!-]*(so much|again|in advance)?[\s,.!]*$"
                      r"|^\s*sent from my\b|^\s*-- ?$|^\s*_{5,}|^\s*from:\s|^\s*on .{6,80} wrote:\s*$|^\s*>", re.I)
# NUL and the other control characters (tab and newline aside): PostgreSQL
# refuses a NUL in text outright (DataError), and some tickets carry them.
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# a chat transcript line: "(10:02:11 AM) Anna: text"
_CHAT = re.compile(r"^\(?\d{1,2}:\d{2}(?::\d{2})?\s*(?:[AP]M)?\)?\s*([^:\n]{1,40}):\s?", re.I | re.M)


def scrub(text, limit=BODY_CHARS, agents=()):
    """A message without greetings, signatures, quoted mail, Splashtop addresses,
    phone numbers and the names of the agents on the ticket."""
    lines = _CTRL.sub("", text or "").replace("\r", "").split("\n")
    out = []
    for i, line in enumerate(lines):
        if i < 3 and _GREETING.match(line):
            continue
        if _SIGNOFF.match(line) and sum(len(l) for l in out) > 40:
            break                                     # the signature block (and quoted mail below it)
        if re.match(r"^\s*(chat started|chat ended|chat transferred)\b", line, re.I):
            continue
        out.append(line)
    t = "\n".join(out)
    for name in agents:
        t = re.sub(r"(?<!\w)%s(?!\w)" % re.escape(name), "[agent]", t)
    t = _CHAT.sub(lambda m: ("Support: " if "[agent]" in m.group(1) else "Customer: "), t)
    t = _AGENT_EMAIL.sub("[agent email]", t)
    t = _PHONE.sub("[phone]", t)
    t = _URL.sub(lambda m: "[link: %s]" % m.group(1), t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n\s*\n+", "\n", t).strip()
    return t[:limit]


def _txt(v, n):
    v = _CTRL.sub("", str(v or ""))[:n]
    return v or None


# Where a customer is, roughly: the e-mail's country domain; else the requester's
# time zone (often just the account default, so the weaker of the two).
CCTLD = {"jp": "Japan", "kr": "South Korea", "cn": "China", "tw": "Taiwan", "hk": "Hong Kong", "sg": "Singapore",
         "in": "India", "au": "Australia", "nz": "New Zealand", "my": "Malaysia", "th": "Thailand", "id": "Indonesia",
         "ph": "Philippines", "vn": "Vietnam", "uk": "United Kingdom", "ie": "Ireland", "de": "Germany", "at": "Austria",
         "ch": "Switzerland", "fr": "France", "be": "Belgium", "nl": "Netherlands", "lu": "Luxembourg", "it": "Italy",
         "es": "Spain", "pt": "Portugal", "se": "Sweden", "no": "Norway", "dk": "Denmark", "fi": "Finland", "is": "Iceland",
         "pl": "Poland", "cz": "Czechia", "sk": "Slovakia", "hu": "Hungary", "ro": "Romania", "bg": "Bulgaria",
         "gr": "Greece", "tr": "Turkey", "il": "Israel", "ae": "UAE", "sa": "Saudi Arabia", "za": "South Africa",
         "eg": "Egypt", "ng": "Nigeria", "ke": "Kenya", "ca": "Canada", "us": "United States", "mx": "Mexico",
         "br": "Brazil", "ar": "Argentina", "cl": "Chile", "co": "Colombia", "pe": "Peru", "ru": "Russia", "ua": "Ukraine",
         "hr": "Croatia", "si": "Slovenia", "rs": "Serbia", "lt": "Lithuania", "lv": "Latvia", "ee": "Estonia"}
TZ_COUNTRY = {"Tokyo": "Japan", "Seoul": "South Korea", "Shanghai": "China", "Taipei": "Taiwan", "Hong_Kong": "Hong Kong",
              "Singapore": "Singapore", "Kolkata": "India", "Calcutta": "India", "Sydney": "Australia", "Melbourne": "Australia",
              "Brisbane": "Australia", "Perth": "Australia", "Auckland": "New Zealand", "London": "United Kingdom",
              "Dublin": "Ireland", "Berlin": "Germany", "Vienna": "Austria", "Zurich": "Switzerland", "Paris": "France",
              "Brussels": "Belgium", "Amsterdam": "Netherlands", "Rome": "Italy", "Madrid": "Spain", "Lisbon": "Portugal",
              "Stockholm": "Sweden", "Oslo": "Norway", "Copenhagen": "Denmark", "Helsinki": "Finland", "Warsaw": "Poland",
              "Prague": "Czechia", "Budapest": "Hungary", "Athens": "Greece", "Istanbul": "Turkey", "Jerusalem": "Israel",
              "Dubai": "UAE", "Johannesburg": "South Africa", "Toronto": "Canada", "Vancouver": "Canada",
              "Mexico_City": "Mexico", "Sao_Paulo": "Brazil", "Buenos_Aires": "Argentina", "New_York": "United States",
              "Chicago": "United States", "Denver": "United States", "Los_Angeles": "United States",
              "Phoenix": "United States", "Anchorage": "United States", "Honolulu": "United States"}


def country_of(email, tz):
    dom = (email or "").rsplit("@", 1)[-1].lower()
    tld = dom.rsplit(".", 1)[-1] if "." in dom else ""
    if tld in CCTLD:
        return CCTLD[tld]
    city = (tz or "").rsplit("/", 1)[-1]
    return TZ_COUNTRY.get(city)


def region_of(country, tz):
    apac = {"Japan", "South Korea", "China", "Taiwan", "Hong Kong", "Singapore", "India", "Australia", "New Zealand",
            "Malaysia", "Thailand", "Indonesia", "Philippines", "Vietnam"}
    amer = {"Canada", "United States", "Mexico", "Brazil", "Argentina", "Chile", "Colombia", "Peru"}
    if country:
        return "APAC" if country in apac else "Americas" if country in amer else "EMEA"
    head = (tz or "").split("/", 1)[0]
    return {"America": "Americas", "Europe": "EMEA", "Africa": "EMEA", "Asia": "APAC", "Australia": "APAC"}.get(head)


# ---- pass 1: the tickets, with requesters and organizations -------------------------------

_PEOPLE = {}      # user id -> (email, iana time zone, role)
_ORGS = {}        # organization id -> name


def _lookup(path, key, ids, into, make):
    ids = [i for i in dict.fromkeys(ids) if i and i not in into]
    for k in range(0, len(ids), 100):
        part = ids[k:k + 100]
        try:
            d = _get(path + ",".join(str(int(i)) for i in part))
        except zendesk.ZendeskError as e:
            sys.stderr.write("[cases] %s lookup skipped: %s\n" % (key, e))
            return
        for x in d.get(key) or []:
            into[x.get("id")] = make(x)
        for i in part:
            into.setdefault(i, None)
    if len(into) > 200000:
        into.clear()


def _people(tickets):
    _lookup("/api/v2/users/show_many.json?ids=", "users", [t.get("requester_id") for t in tickets], _PEOPLE,
            lambda u: ((u.get("email") or "").lower(), u.get("iana_time_zone") or "", u.get("role") or ""))
    _lookup("/api/v2/organizations/show_many.json?ids=", "organizations", [t.get("organization_id") for t in tickets], _ORGS,
            lambda o: o.get("name") or "")


def _row(t):
    via = ((t.get("via") or {}).get("channel") or "")
    email, tz, role = _PEOPLE.get(t.get("requester_id")) or ("", "", "")
    if role in ("agent", "admin") or _AGENT_EMAIL.fullmatch(email or ""):
        email = tz = ""                               # an agent's own ticket: no requester (the wall)
    return (int(t["id"]), _ms(t.get("created_at")) or _now(), _ms(t.get("updated_at")), _txt(t.get("status"), 20),
            _txt(t.get("type"), 20), _txt(t.get("priority"), 20), _txt(via, 40),
            _txt(_AGENT_EMAIL.sub("[agent email]", _CTRL.sub("", t.get("subject") or "")), 300),
            _txt(scrub(t.get("description") or ""), BODY_CHARS),
            _txt(" ".join(str(x) for x in t.get("tags") or []), 1000),
            _txt(email, 200), _txt(email.rsplit("@", 1)[-1] if "@" in email else "", 120),
            _txt(_ORGS.get(t.get("organization_id")) or "", 200), _txt(country_of(email, tz), 60), _txt(tz, 60))


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
            for r in rows:            # SQLite: keep the conversation columns on an update
                cur.execute("INSERT INTO cases (%s, saved_ms) VALUES (%s) ON CONFLICT (ticket_id) DO UPDATE SET %s"
                            % (", ".join(COLS), ",".join(["?"] * (len(COLS) + 1)),
                               ", ".join("%s = excluded.%s" % (k, k) for k in COLS[1:] + ("saved_ms",))), r + (now,))
        c.commit()
    finally:
        c.close()


def save(tickets):
    tickets = [t for t in tickets if _wanted(t)]
    _people(tickets)
    rows = []
    for t in tickets:
        try:
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
            why = (getattr(getattr(e, "diag", None), "message_primary", None) or "")[:120]
            sys.stderr.write("[cases] #%s not saved: %s%s\n" % (r[0], type(e).__name__, (" -- " + why) if why else ""))
    return saved


# ---- pass 2: the conversation -----------------------------------------------------------

def _get(path):
    """Zendesk, waiting out a rate limit (429) a few times."""
    for attempt in range(5):
        try:
            return zendesk.get_json(path)
        except zendesk.ZendeskError as e:
            if "429" not in str(e) or attempt == 4:
                raise
            time.sleep(30 * (attempt + 1))


def conversation(ticket_id):
    """(text, turns) for one ticket: every public reply and internal note, in order."""
    out, users, url, pages = [], {}, "/api/v2/tickets/%d/comments.json?include=users&page[size]=100" % int(ticket_id), 0
    while url and pages < 3:
        d = _get(url)
        for u in d.get("users") or []:
            users[u.get("id")] = u
        out.extend(d.get("comments") or [])
        nxt = (d.get("links") or {}).get("next") if (d.get("meta") or {}).get("has_more") else None
        url = nxt[len(zendesk.base_url()):] if nxt and nxt.startswith(zendesk.base_url()) else None
        pages += 1
    agents = set()
    for u in users.values():
        if u.get("role") in ("agent", "admin") and u.get("name"):
            agents.add(u["name"])
            first = u["name"].split()[0]
            if len(first) >= 3:
                agents.add(first)
    agents = sorted(agents, key=len, reverse=True)       # "Anna Lee" before "Anna"
    turns = []
    for cm in out:
        body = cm.get("plain_body") or cm.get("body") or ""
        if body.lstrip().startswith("SplashHub AI Review"):
            continue                                       # our own notes
        role = (users.get(cm.get("author_id")) or {}).get("role")
        who = ("Support" if cm.get("public", True) else "Support (internal note)") if role in ("agent", "admin") else "Customer"
        text = scrub(body, TURN_CHARS, agents)
        if text:
            # a chat transcript already says who spoke on each line
            turns.append(text if re.match(r"^(Customer|Support): ", text) else "%s: %s" % (who, text))
    if not turns:
        return "", 0
    # Long tickets: the start and the end matter most.
    keep, used = [turns[0]], len(turns[0])
    tail = []
    for t in reversed(turns[1:]):
        if used + len(t) > CONVO_CHARS:
            break
        tail.insert(0, t)
        used += len(t)
    left = len(turns) - 1 - len(tail)
    if left:
        keep.append("[... %d earlier replies left out ...]" % left)
    return "\n\n".join(keep + tail), len(turns)


def _save_convo(tid, text, turns):
    c = store.connect(True)
    try:
        cur = c.cursor()
        cur.execute(store._q("UPDATE cases SET convo = %s, convo_ms = %s, convo_turns = %s WHERE ticket_id = %s"),
                    [_txt(text, CONVO_CHARS + 200), _now(), turns, tid])
        c.commit()
    finally:
        c.close()


def _fill_convos():
    """Pass 2: newest tickets first; a ticket updated since its replies were read is read again."""
    while not JOB["stop"]:
        ids = [r[0] for r in store._read("SELECT ticket_id FROM cases WHERE convo_ms IS NULL OR convo_ms < updated_ms "
                                         "ORDER BY created_ms DESC LIMIT 100", [], fresh=True)]
        if not ids:
            return
        for tid in ids:
            if JOB["stop"]:
                return
            began = time.time()
            try:
                text, turns = conversation(tid)
            except zendesk.ZendeskError as e:
                if "HTTP 404" not in str(e) and "HTTP 403" not in str(e):
                    raise
                text, turns = "", 0                         # deleted or not readable: don't ask again
            try:
                _save_convo(tid, text, turns)
            except Exception as e:
                _save_convo(tid, "", 0)
                JOB["skipped"] = JOB.get("skipped", 0) + 1
                sys.stderr.write("[cases] #%s replies not saved: %s\n" % (tid, type(e).__name__))
            JOB["replies"] = JOB.get("replies", 0) + 1
            time.sleep(max(0, 1.0 / RATE - (time.time() - began)))


# ---- download / update jobs (background, one at a time) ----------------------------------

JOB = {"running": False, "kind": None, "saved": 0, "replies": 0, "week": None, "phase": None, "error": None,
       "finished_ms": None, "stop": False}
_lock = threading.Lock()


def _search(query):
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
    JOB["phase"] = "tickets"
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
    JOB["week"], JOB["phase"] = None, "updates"
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
        if not JOB["stop"]:
            JOB["phase"] = "replies"
            _fill_convos()
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
        sys.stderr.write("[cases] %s finished: %d tickets, %d conversations%s\n" % (
            kind, JOB["saved"], JOB.get("replies", 0), (" -- " + JOB["error"]) if JOB["error"] else ""))


def start(kind):
    with _lock:
        if JOB["running"]:
            return False
        JOB.update(running=True, kind=kind, saved=0, replies=0, skipped=0, week=None, phase=None, error=None,
                   finished_ms=None, stop=False, stopped=False)
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
    """At start-up: carry on a download a restart interrupted, then update hourly
    (which also carries on reading conversations)."""
    def loop():
        try:
            ensure()
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
    n, first, last, conv = store._read("SELECT count(*), min(created_ms), max(created_ms), "
                                       "sum(CASE WHEN convo_ms IS NOT NULL THEN 1 ELSE 0 END) FROM cases", [])[0]
    synced = store.get_setting("cases_synced", "")
    return dict(JOB, count=n, with_replies=int(conv or 0), first=_day(first) if first else None,
                last=_day(last) if last else None, next_week=store.get_setting("cases_next", "") or START,
                downloaded=bool(store.get_setting("cases_downloaded", "")), updated=synced or None)


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
# Words every ticket has (chat and form boilerplate): never a topic. Both plain and stemmed.
BOILER = set("""chat visitor visit offline offlin message messag messages conversation convers user users request requests
support help question questions ticket tickets new hello thank thanks pleas please regard regards issue issu problem
splashtop team need get use can would like know want tri try work also email time day one could still see us receiv
received sent repli reply contact inform information assist look best kind dear sincer follow updat update case custom
customer agent servic service level form submit submitted web widget phone call via re fw fwd www com http https link
attach attachment imag image screenshot hi hey ok okay good morning afternoon""".split())


def keywords(text, n=12):
    """The words that carry a text's meaning: no stop words, the most frequent first."""
    count = {}
    text = re.sub(r"\[(agent|agent email|phone|link: [^\]]*)\]", " ", text or "")
    for w in re.findall(r"[a-z0-9][a-z0-9.+-]*[a-z0-9]|[a-z0-9]", text.lower()):
        if len(w) < 3 or w in STOP or w in BOILER or w.isdigit():
            continue
        count[w] = count.get(w, 0) + 1
    return [w for w, _ in sorted(count.items(), key=lambda x: (-x[1], x[0]))][:n]


def _phrases(query):
    """'2fa, two-factor, authenticator app' -> [['2fa'], ['two', 'factor'], ['authenticator', 'app']]:
    a case matches when it has ALL the words of ANY one phrase."""
    out = []
    for part in re.split(r",|;|\||\bOR\b", query or ""):
        ws = [w for w in re.findall(r"[a-z0-9]+", part.lower()) if w not in STOP and len(w) > 1][:6]
        if ws and ws not in out:
            out.append(ws)
    return out[:10]


def _filters(from_date=None, to_date=None, status=None, tag=None, requester=None, country=None):
    where, args = [], []
    for col, op, v in (("created_ms", ">=", from_date), ("created_ms", "<", to_date)):
        ms = _ms((v or "")[:10] + "T00:00:00") if v else None
        if ms:
            where.append("%s %s %%s" % (col, op))
            args.append(ms + (86400000 if op == "<" else 0))          # to_date is inclusive
    if status:
        st = [s.strip() for s in str(status).lower().replace(" or ", ",").split(",") if s.strip()][:6]
        where.append("status IN (%s)" % ",".join(["%s"] * len(st)))
        args += st
    if tag:
        where.append("(' ' || coalesce(tags, '') || ' ') LIKE %s")
        args.append("% " + str(tag).lower().strip() + " %")
    if requester:
        r = "%" + str(requester).lower().strip().lstrip("@") + "%"
        where.append("(lower(coalesce(requester_email,'')) LIKE %s OR lower(coalesce(organization,'')) LIKE %s)")
        args += [r, r]
    if country:
        where.append("lower(coalesce(country,'')) = %s")
        args.append(str(country).lower().strip())
    return where, args


def _snippet(text, words):
    b = text or ""
    low = b.lower()
    hits = [low.find(w) for w in words if low.find(w) >= 0]
    at = max(0, min(hits) - 80) if hits else 0
    s = b[at:at + 240].replace("\n", " ")
    return ("…" if at else "") + s + ("…" if at + 240 < len(b) else "")


OUT = ("ticket_id", "created_ms", "status", "subject", "body", "tags", "requester_email", "organization", "country", "convo_turns")


def _out(r, words):
    d = dict(zip(OUT, r))
    return {"ticket": d["ticket_id"], "date": _day(d["created_ms"]), "status": d["status"], "subject": d["subject"],
            "requester": d["requester_email"], "organization": d["organization"], "country": d["country"],
            "replies": d["convo_turns"], "snippet": _snippet(d["body"], words)}


def _where_sql(where):
    return (" WHERE " + " AND ".join(where)) if where else ""


def _match(phrases, where, args):
    """FROM/WHERE pieces matching the phrases, for both backends: (from_sql, where, args, rank_sql)."""
    if not phrases:
        return "", where, args, "created_ms"
    if _pg():
        q = " || ".join(["plainto_tsquery('english', %s)"] * len(phrases))
        return (", (SELECT (%s) q) qq" % q), where + ["tsv @@ qq.q"], [" ".join(p) for p in phrases] + args, "ts_rank_cd(tsv, qq.q)"
    hay = "lower(coalesce(subject,'') || ' ' || coalesce(tags,'') || ' ' || coalesce(body,'') || ' ' || coalesce(convo,''))"
    ors = ["(" + " AND ".join([hay + " LIKE %s"] * len(p)) + ")" for p in phrases]
    return "", where + ["(" + " OR ".join(ors) + ")"], args + ["%" + w + "%" for p in phrases for w in p], "created_ms"


def _breakdowns(frm, w, args):
    """Per month, country, region, language (the SplashTags tag), status -- for the matching cases."""
    rows = store._read("SELECT created_ms, country, tz, tags, status FROM cases%s%s" % (frm, w), args)
    month, ctry, reg, lang, st = {}, {}, {}, {}, {}
    for ms, country, tz, tags, status in rows:
        for d, k in ((month, _day(ms)[:7]), (ctry, country or "unknown"), (reg, region_of(country, tz) or "unknown"),
                     (st, status or "?")):
            d[k] = d.get(k, 0) + 1
        lt = [t[9:] for t in (tags or "").split() if t.startswith("language_")]
        k = lt[0] if lt else "untagged"
        lang[k] = lang.get(k, 0) + 1
    top = lambda d, n: dict(sorted(d.items(), key=lambda x: -x[1])[:n])
    return {"by_month": dict(sorted(month.items())), "by_country": top(ctry, 12), "by_region": top(reg, 5),
            "by_language": top(lang, 10), "by_status": top(st, 6)}


def search(query=None, from_date=None, to_date=None, status=None, tag=None, requester=None, country=None,
           limit=10, exclude=None):
    """Cases with ALL the words of ANY one of the comma-separated phrases, best
    first, with how many match in all and breakdowns. If no case has all the
    words, it falls back to any of the words, and says so."""
    ensure()
    phrases = _phrases(query)
    where, args = _filters(from_date, to_date, status, tag, requester, country)
    if not phrases and not where:
        return {"error": "give some words to look for, or a filter"}
    if exclude:
        where.append("ticket_id <> %s")
        args.append(int(exclude))
    limit = max(1, min(int(limit or 10), 20))
    loose = False
    frm, w, a, rank = _match(phrases, where, args)
    total = store._read("SELECT count(*) FROM cases%s%s" % (frm, _where_sql(w)), a)[0][0]
    if not total and phrases and any(len(p) > 1 for p in phrases):
        loose = True
        phrases = [[x] for x in dict.fromkeys(x for p in phrases for x in p)]
        frm, w, a, rank = _match(phrases, where, args)
        total = store._read("SELECT count(*) FROM cases%s%s" % (frm, _where_sql(w)), a)[0][0]
    words = [x for p in phrases for x in p]
    if _pg():
        rows = store._read("SELECT %s FROM cases%s%s ORDER BY %s DESC, created_ms DESC LIMIT %d"
                           % (", ".join(OUT), frm, _where_sql(w), rank, limit), a)
    else:
        cand = store._read("SELECT %s, convo FROM cases%s%s" % (", ".join(OUT), frm, _where_sql(w)), a)

        def score(r):
            subj, rest = (r[3] or "").lower(), ((r[5] or "") + " " + (r[4] or "") + " " + (r[-1] or "")).lower()
            return sum(3 * subj.count(x) + rest.count(x) for x in words)
        cand.sort(key=lambda r: (-score(r), -r[1]))
        rows = [r[:-1] for r in cand[:limit]]
    res = {"phrases": [" ".join(p) for p in phrases], "matching_cases": total,
           "how_matched": ("no case had all the words of a phrase, so this counts cases with ANY of the words (loose)" if loose
                           else "cases containing all the words of at least one phrase")}
    if total:
        res.update(_breakdowns(frm, _where_sql(w), a))
    res["best_matches"] = [_out(r, words) for r in rows]
    return res


def themes(query=None, from_date=None, to_date=None, status=None, country=None, sample=50):
    """A random sample of the matching cases' own words (subject + start of the
    first message), for the AI to read and group into the actual problems."""
    ensure()
    phrases = _phrases(query)
    where, args = _filters(from_date, to_date, status, None, None, country)
    frm, w, a, _ = _match(phrases, where, args)
    total = store._read("SELECT count(*) FROM cases%s%s" % (frm, _where_sql(w)), a)[0][0]
    rnd = "random()"
    rows = store._read("SELECT ticket_id, created_ms, subject, body FROM cases%s%s ORDER BY %s LIMIT %d"
                       % (frm, _where_sql(w), rnd, max(10, min(int(sample or 50), 70))), a)
    items = []
    for tid, ms, subj, body in rows:
        s = subj or ""
        if re.match(r"^(chat with|offline message|conversation with|new message from)\b", s, re.I):
            s = ""                                        # chat boilerplate says nothing
        text = re.sub(r"\s+", " ", (body or ""))[:220]
        items.append("#%d %s | %s%s" % (tid, _day(ms), (s + " -- ") if s else "", text))
    return {"matching_cases": total, "sampled": len(items),
            "note": "a random sample; group it into problems and estimate each one's share of matching_cases",
            "sample": items}


def _support_turns(convo, n=2, chars=700):
    turns = [t for t in re.split(r"\n\n(?=Customer: |Support: |Support \(internal note\): )", convo or "") if t.startswith("Support")]
    return [t[:chars] for t in turns[-n:]]


def solutions(query=None, ticket_id=None, from_date=None, to_date=None, limit=6):
    """How cases like these were answered: the last Support replies (and
    internal notes) of the best-matching solved or closed cases."""
    ensure()
    if ticket_id:
        me = read(ticket_id, chars=0)
        if not me:
            return {"error": "ticket #%s isn't among the downloaded 2026 cases" % ticket_id}
        cands = [me["ticket"]]
    else:
        res = search(query, from_date, to_date, "solved,closed", limit=max(1, min(int(limit or 6), 8)))
        if res.get("error"):
            return res
        cands = [m["ticket"] for m in res["best_matches"]]
    out, live = [], 0
    for tid in cands:
        r = store._read("SELECT subject, body, convo, convo_ms FROM cases WHERE ticket_id = %s", [tid])
        if not r:
            continue
        subj, body, convo, convo_ms = r[0]
        if convo_ms is None and live < 3 and not zendesk.configured():
            try:                                           # not read yet: read it now (and keep it)
                convo, turns = conversation(tid)
                _save_convo(tid, convo, turns)
                live += 1
            except zendesk.ZendeskError:
                pass
        out.append({"ticket": tid, "subject": subj, "problem": re.sub(r"\s+", " ", body or "")[:300],
                    "support_replies": _support_turns(convo) or ["(no support reply saved yet)"]})
    return {"cases": out, "note": "the last support replies and notes of each case; say what fixed it, and if several "
                                  "cases share a fix, say so"}


def read(ticket_id, chars=6000):
    ensure()
    try:
        tid = int(str(ticket_id).lstrip("#"))
    except (TypeError, ValueError):
        return None
    cols = ("ticket_id", "created_ms", "updated_ms", "status", "type", "priority", "channel", "subject", "body", "tags",
            "requester_email", "organization", "country", "convo", "convo_turns")
    rows = store._read("SELECT %s FROM cases WHERE ticket_id = %%s" % ", ".join(cols), [tid])
    if not rows:
        return None
    d = dict(zip(cols, rows[0]))
    convo = d["convo"] or ""
    return {"ticket": tid, "created": _day(d["created_ms"]), "updated": _day(d["updated_ms"]) if d["updated_ms"] else None,
            "status": d["status"], "type": d["type"], "priority": d["priority"], "channel": d["channel"],
            "subject": d["subject"], "requester": d["requester_email"], "organization": d["organization"],
            "country": d["country"], "tags": (d["tags"] or "").split(), "first_message": d["body"],
            "conversation": (convo[:chars] + ("…" if len(convo) > chars else "")) if chars else None,
            "replies": d["convo_turns"], "conversation_saved": d["convo_turns"] is not None}


def similar(ticket_id, limit=8):
    """Cases like one ticket: its own key words, searched for (loosely)."""
    me = read(ticket_id, chars=0)
    if not me:
        try:                                         # not kept (yet): read it from Zendesk
            t = zendesk.ticket(int(str(ticket_id).lstrip("#")))
            me = {"ticket": t["id"], "subject": t["subject"], "first_message": scrub(t["description"]), "tags": []}
        except (zendesk.ZendeskError, ValueError, TypeError):
            return {"error": "ticket #%s isn't among the downloaded cases and couldn't be read from Zendesk" % ticket_id}
    words = list(dict.fromkeys(keywords(me["subject"], 6) + keywords(me["first_message"], 10)))[:14]
    res = search(", ".join(words), limit=limit, exclude=me["ticket"])     # each word a phrase: any of them, best first
    if res.get("error"):
        return res
    # Any-of-the-words counts every loosely related case: only the ranking means something here.
    return {"about": {"ticket": me["ticket"], "subject": me["subject"], "key_words": words},
            "how_matched": "cases sharing the most of these key words rank first",
            "most_similar": res["best_matches"]}


def _topic_words(where, args, n=25):
    """The words most used in subjects and first messages (no boilerplate), as {word: cases}."""
    if _pg():
        # ts_stat runs a query given as text: the filters are numbers we put in ourselves.
        inner = "SELECT to_tsvector('english', coalesce(subject,'') || ' ' || left(coalesce(body,''), 400)) FROM cases"
        cond = []
        for k, v in zip(where, args):
            if k.startswith("created_ms") and isinstance(v, int):
                cond.append(k.replace("%s", str(int(v))))
        if cond:
            inner += " WHERE " + " AND ".join(cond)
        rows = store._read("SELECT word, ndoc FROM ts_stat(%s) ORDER BY ndoc DESC LIMIT 200", [inner])
    else:
        rows = store._read("SELECT subject, body FROM cases" + _where_sql(where), args)
        cnt = {}
        for subj, body in rows:
            for x in set(keywords((subj or "") + " " + (body or "")[:400], 60)):
                cnt[x] = cnt.get(x, 0) + 1
        rows = sorted(cnt.items(), key=lambda x: -x[1])[:200]
    return {w: n_ for w, n_ in rows if w not in BOILER and w not in STOP and len(w) > 2 and not w.isdigit()}


def overview(from_date=None, to_date=None):
    """The general picture over a period: totals and breakdowns, the words most
    used in what customers wrote, and the words rising most in the last 30 days."""
    ensure()
    where, args = _filters(from_date, to_date)
    w = _where_sql(where)
    total = store._read("SELECT count(*) FROM cases" + w, args)[0][0]
    res = {"cases": total, "from": from_date or START, "to": to_date or _day(_now())}
    if total:
        res.update(_breakdowns("", w, args))
    words = _topic_words(where, args)
    res["top_words"] = dict(list(words.items())[:25])
    # rising: share of cases using a word, last 30 days vs the 90 before
    now = _now()
    recent_n = store._read("SELECT count(*) FROM cases WHERE created_ms >= %s", [now - 30 * 86400000])[0][0]
    prior_n = store._read("SELECT count(*) FROM cases WHERE created_ms >= %s AND created_ms < %s",
                          [now - 120 * 86400000, now - 30 * 86400000])[0][0]
    if recent_n >= 50 and prior_n >= 50:
        recent = _topic_words(["created_ms >= %s"], [now - 30 * 86400000])
        prior = _topic_words(["created_ms >= %s", "created_ms < %s"], [now - 120 * 86400000, now - 30 * 86400000])
        rising = []
        for x, n_ in recent.items():
            if n_ < 10:
                continue
            a, b = n_ / recent_n, (prior.get(x, 0) + 1) / prior_n
            if a / b >= 1.5:
                rising.append((x, n_, round(a / b, 1)))
        res["rising_last_30_days"] = [{"word": x, "cases": n_, "times_more_common": r}
                                      for x, n_, r in sorted(rising, key=lambda t: -t[2])[:12]]
    res["note"] = ("top_words and rising words are single words, not problems: use case_themes to see the actual "
                   "problems behind them")
    return res
