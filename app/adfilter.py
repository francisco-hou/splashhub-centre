"""Ad filter: Spark (Spluki's AI) reads each new ticket and decides whether it
is unsolicited marketing / spam -- someone selling a service to Splashtop (SEO,
backlinks, website traffic, ads, development...) -- or a real request. The ones
it calls ads are listed on the Ad filter page to be checked (Right / Wrong).

HELD: nothing is changed in Zendesk by itself. A person can open a ticket's
preview and press Silent close (confirmed twice): one Zendesk update adds a
private note "Silent-Close" and the silent_close tag -- nothing is sent to the
customer; Zendesk's own triggers do the rest.

Its own Zendesk search, every 2 minutes: tickets created from the start day
(the day before it was first switched on), whatever their status. Each new
one's subject, sender and the customer's first message (read the way AutoTag
reads it); phone calls and provisioning requests are left out (not ads). 8
tickets to a Spark call, the example ads (Settings > AutoTag > Ad filter) in
the question; each call is kept in Spark activity (area ad_filter). The page
lists only the ones Spark calls ads -- open tasks first (not solved / closed),
each ticket's status refreshed by the search.
"""
import json, re, sys, threading, time

import store

KEY = "adfilter"
EVERY = 120
BATCH = 8
PER_ROUND = 120
EXAMPLES = [
    """Dear Sir/Mam,

Please check the new high-traffic websites.with reasonable prices,

Websites Traffic
https://msn.com/ 17.9M
https://www.benzinga.com/ 877K
https://coinpedia.org/ 377K
https://programminginsider.com/ 10.2K
https://artdaily.com/ 6.34K

If you have any questions, feel free to contact me.

Thanks & Regards!""",
    """Hi

I checked your website and noticed that your on-page SEO is quite good, but your off-page SEO still has room for improvement. With stronger backlinks and authority building, your site can rank much better and attract more organic traffic.

We help businesses improve rankings, increase website authority, and generate more customer inquiries through professional SEO services.

Would you like me to share our SEO packages and a few suggestions for your websites?""",
]
COLS = ("ticket_id", "created_ms", "subject", "requester", "sample", "spam", "confidence", "why", "checked_ms",
        "verdict", "reviewed_ms", "status", "channel", "silent_ms")
DDL = """CREATE TABLE IF NOT EXISTS adfilter (
    ticket_id BIGINT PRIMARY KEY, created_ms BIGINT, subject TEXT, requester TEXT, sample TEXT, spam INTEGER,
    confidence TEXT, why TEXT, checked_ms BIGINT, verdict TEXT, reviewed_ms BIGINT, status TEXT, channel TEXT,
    silent_ms BIGINT)"""
DONE = ("solved", "closed")
_ready = False
_lock = threading.Lock()
STATE = {"last_ms": None, "error": None, "busy": False}


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
        if store.backend() == "postgres":                  # added after the table first shipped (0.12.7)
            cur.execute("ALTER TABLE adfilter ADD COLUMN IF NOT EXISTS silent_ms BIGINT")
        else:
            cur.execute("PRAGMA table_info(adfilter)")
            if "silent_ms" not in [r[1] for r in cur.fetchall()]:
                cur.execute("ALTER TABLE adfilter ADD COLUMN silent_ms BIGINT")
        cur.execute("CREATE INDEX IF NOT EXISTS adfilter_created ON adfilter (created_ms)")
        c.commit()
    finally:
        c.close()
    _ready = True


# ---- settings ----------------------------------------------------------------------------------

def settings():
    try:
        s = json.loads(store.get_setting(KEY, "") or "{}")
    except ValueError:
        s = {}
    if not s.get("since"):                          # the first time: from yesterday on (Taiwan time)
        s = dict(s, since=time.strftime("%Y-%m-%d", time.gmtime(time.time() + 8 * 3600 - 86400)))
        store.set_setting(KEY, json.dumps(s), "adfilter")
    ex = s.get("examples") if isinstance(s.get("examples"), list) else EXAMPLES
    return {"on": s.get("on", True) is not False, "examples": ex, "since": s["since"], "act": False}   # act: silent close -- not yet


def save_settings(data, by=None):
    s = settings()
    if "on" in data:
        s["on"] = bool(data["on"])
    if "examples" in data:
        v = data["examples"]
        parts = v if isinstance(v, list) else re.split(r"\n\s*-{3,}\s*\n", str(v or ""))
        s["examples"] = [p.strip()[:2000] for p in parts if p.strip()][:12]
    store.set_setting(KEY, json.dumps({"on": s["on"], "examples": s["examples"], "since": s["since"]}), by)
    if s["on"]:
        kick()
    return status()


# ---- Spark ------------------------------------------------------------------------------------

def _ask(items, examples):
    """{ticket id: (spam?, confidence, why)} for [(id, subject, sender, text)]."""
    import spark, sparklog
    ex = "\n\n".join("Example %d:\n%s" % (i + 1, e[:900]) for i, e in enumerate(examples[:8]))
    system = ("You sort the tickets arriving at Splashtop's support desk (Splashtop makes remote access and remote support "
              "software). For each, decide if it is UNSOLICITED MARKETING / SPAM: someone selling a service TO Splashtop -- SEO, "
              "backlinks, guest posts, website traffic or ad space, web or app development, design, lead generation, data "
              "lists, outsourcing, crypto -- a cold sales pitch, or a newsletter. It is NOT spam when a customer or a prospect "
              "asks for help with Splashtop, asks to buy it or for a quote, a reseller or partner writes, it is about an "
              "invoice or an existing order, or someone reports a security problem. When unsure, it is not spam.\n\n"
              "Examples of spam this desk has received:\n" + ex + "\n\n"
              'Answer with JSON only, one entry per ticket: {"<ticket id>": {"spam": true or false, "confidence": '
              '"high|medium|low", "why": "<at most 8 words>"}}')
    text = "\n\n".join("Ticket %s\nFrom: %s\nSubject: %s\nMessage: %s" % (i, f or "?", (s or "")[:160], re.sub(r"\s+", " ", x or "")[:900])
                       for i, s, f, x in items)
    lg = {"area": "ad_filter", "tickets": [i for i, _, _, _ in items]}
    raw = spark.chat(system, text, max_tokens=700, log=lg)
    got = json.loads(raw[raw.find("{"):raw.rfind("}") + 1] or "{}")
    out = {}
    for i, _, _, _ in items:
        a = got.get(str(i)) or {}
        if not isinstance(a, dict):
            a = {"spam": a}
        spam = a.get("spam") in (True, "true", "yes")
        conf = str(a.get("confidence") or "").lower()
        out[i] = (spam, conf if conf in ("high", "medium", "low") else "medium", str(a.get("why") or "")[:100])
    sparklog.decide(lg.get("id"), "; ".join("#%s %s" % (i, "ad / spam (listed)" if v[0] else "not an ad") for i, v in out.items()),
                    changed=any(v[0] for v in out.values()))
    return out


# ---- the round ----------------------------------------------------------------------------------

def _save(rows):
    c = store.connect(True)
    try:
        cur = c.cursor()
        for r in rows:
            cur.execute(store._q("INSERT INTO adfilter (ticket_id, created_ms, subject, requester, sample, spam, confidence, why, "
                                 "checked_ms, status, channel) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                                 "ON CONFLICT (ticket_id) DO NOTHING"),
                        (r["ticket_id"], r["created_ms"], r["subject"], r["requester"], (r["sample"] or "")[:1200], r["spam"],
                         r.get("confidence"), r.get("why"), _now(), r["status"], r["channel"]))
        c.commit()
    finally:
        c.close()


def _statuses(found, known):
    """Each ticket's Zendesk status as the search sees it now (it moves between the page's views)."""
    c = store.connect(True)
    try:
        cur = c.cursor()
        for t in found:
            if int(t["id"]) in known:
                cur.execute(store._q("UPDATE adfilter SET status = %s WHERE ticket_id = %s AND coalesce(status, '') <> %s"),
                            (t.get("status"), int(t["id"]), t.get("status") or ""))
        c.commit()
    finally:
        c.close()


def run_once(limit=PER_ROUND):
    import spark, zendesk, autotag
    ensure()
    s = settings()
    if not s["on"]:
        return
    if zendesk.configured():
        raise RuntimeError("SplashHub Centre can't read Zendesk yet")
    found = [t for t in zendesk.search_tickets("type:ticket created>=%s" % s["since"], max_pages=30)
             if (t.get("created_at") or "")[:10] >= s["since"]]
    ids = [int(t["id"]) for t in found]
    known = set()
    for i in range(0, len(ids), 500):
        part = ids[i:i + 500]
        known |= {int(r[0]) for r in store._read("SELECT ticket_id FROM adfilter WHERE ticket_id IN (%s)" % ",".join(["%s"] * len(part)),
                                                 part, fresh=True)}
    _statuses(found, known)
    todo = sorted([t for t in found if int(t["id"]) not in known], key=lambda t: t.get("created_at") or "", reverse=True)[:limit]
    if not todo:
        return
    if not spark.available():
        raise RuntimeError("Spark isn't set up")
    skip = [p.lower() for p in autotag.settings()["skip"]]
    for i in range(0, len(todo), BATCH):
        rows, ask = {}, []
        for t in todo[i:i + BATCH]:
            ch = ((t.get("via") or {}).get("channel") or "")
            r = {"ticket_id": int(t["id"]), "created_ms": autotag._ms(t.get("created_at")), "subject": (t.get("subject") or "")[:300],
                 "status": t.get("status"), "channel": ch, "requester": "", "sample": "", "spam": 0}
            if autotag._is_call(ch, t.get("subject"), t.get("tags")):          # a phone call: not an ad, not read
                r["why"] = "phone call"
            else:
                text, email = autotag._first_message(t)
                r.update(requester=email, sample=re.sub(r"\s+", " ", text).strip())
                if any(p and p in (text + " " + (t.get("description") or "")).lower() for p in skip):
                    r["why"] = "provisioning request"
                else:
                    ask.append((int(t["id"]), t.get("subject") or "", email, text))
            rows[int(t["id"])] = r
        if ask:
            try:
                got = _ask(ask, s["examples"])
            except Exception as e:               # Spark down or an odd answer: these wait for the next round
                STATE["error"] = "Spark didn't answer (%s); trying again in 2 minutes" % type(e).__name__
                sys.stderr.write("[adfilter] Spark skipped %d ticket(s): %s\n" % (len(ask), type(e).__name__))
                for tid, _, _, _ in ask:
                    rows.pop(tid, None)
                got = {}
            for tid, (spam, conf, why) in got.items():
                rows[tid].update(spam=1 if spam else 0, confidence=conf, why=why)
        _save(list(rows.values()))


def _round():
    if not _lock.acquire(blocking=False):
        return
    STATE.update(busy=True, error=None)
    try:
        run_once()
        STATE["last_ms"] = _now()
    except Exception as e:
        STATE.update(last_ms=_now(), error=str(e)[:200] if "Spark" in str(e) or "Zendesk" in str(e) else "a round failed (%s)" % type(e).__name__)
        sys.stderr.write("[adfilter] %s\n" % STATE["error"])
    finally:
        STATE["busy"] = False
        _lock.release()


def kick():
    threading.Thread(target=_round, name="adfilter-now", daemon=True).start()


def boot():
    def loop():
        time.sleep(60)
        while True:
            _round()
            time.sleep(EVERY)
    threading.Thread(target=loop, name="adfilter-loop", daemon=True).start()


# ---- the page: only the ads ----------------------------------------------------------------------

def search(view="open", q=None, page=0, per_page=50):
    """view: open (the default -- not solved / closed), done (solved / closed),
    wrong (the ones the team marked wrong). Only tickets Spark called ads."""
    ensure()
    where, args = ["spam = 1"], []
    if view == "done":
        where.append("status IN ('solved', 'closed')")
    elif view == "wrong":
        where.append("verdict = 'wrong'")
    else:
        where.append("coalesce(status, '') NOT IN ('solved', 'closed')")
    if q:
        q = q.strip().lstrip("#")
        if q.isdigit():
            where.append("ticket_id = %s")
            args.append(int(q))
        else:
            where.append("(lower(subject) LIKE %s OR lower(requester) LIKE %s OR lower(sample) LIKE %s)")
            args += ["%" + q.lower() + "%"] * 3
    w = " WHERE " + " AND ".join(where)
    total = store._read("SELECT count(*) FROM adfilter" + w, args, fresh=True)[0][0]
    rows = [dict(zip(COLS, r)) for r in store._read("SELECT %s FROM adfilter%s ORDER BY created_ms DESC LIMIT %d OFFSET %d"
                                                   % (", ".join(COLS), w, per_page, page * per_page), args, fresh=True)]
    return {"rows": rows, "total": total, "page": page, "per_page": per_page}


def status():
    ensure()
    s = settings()
    n, ads, open_ads, right, wrong, silent = store._read(
        "SELECT count(*), sum(spam), sum(CASE WHEN spam = 1 AND coalesce(status, '') NOT IN ('solved', 'closed') THEN 1 ELSE 0 END), "
        "sum(CASE WHEN verdict = 'right' THEN 1 ELSE 0 END), sum(CASE WHEN verdict = 'wrong' THEN 1 ELSE 0 END), "
        "sum(CASE WHEN silent_ms IS NOT NULL THEN 1 ELSE 0 END) FROM adfilter", [], fresh=True)[0]
    return dict(s, checked=int(n or 0), ads=int(ads or 0), open_ads=int(open_ads or 0), done_ads=int(ads or 0) - int(open_ads or 0),
                right=int(right or 0), wrong=int(wrong or 0), silent=int(silent or 0),
                last_ms=STATE["last_ms"], error=STATE["error"], busy=STATE["busy"])


def set_verdict(ticket_id, verdict):
    """Is Spark right about this one? (right / wrong / "" to undo)"""
    ensure()
    if verdict not in ("right", "wrong", ""):
        raise ValueError("verdict is right, wrong or empty")
    c = store.connect(True)
    try:
        c.cursor().execute(store._q("UPDATE adfilter SET verdict = %s, reviewed_ms = %s WHERE ticket_id = %s"),
                           (verdict or None, _now() if verdict else None, int(ticket_id)))
        c.commit()
    finally:
        c.close()
    r = store._read("SELECT %s FROM adfilter WHERE ticket_id = %%s" % ", ".join(COLS), [int(ticket_id)], fresh=True)
    return dict(zip(COLS, r[0])) if r else None


# ---- the preview, and Silent close ------------------------------------------------------------------

def _get(tid):
    r = store._read("SELECT %s FROM adfilter WHERE ticket_id = %%s" % ", ".join(COLS), [int(tid)], fresh=True)
    return dict(zip(COLS, r[0])) if r else None


def preview(ticket_id):
    """What the page's preview shows: the row, and the ticket as Zendesk has it
    now (its whole first message, status, tags)."""
    import zendesk
    ensure()
    row = _get(ticket_id)
    if not row:
        raise ValueError("the Ad/Spam Filter hasn't read this ticket")
    try:
        t = (zendesk.get_json("/api/v2/tickets/%d.json" % int(ticket_id)).get("ticket") or {})
        row.update(description=(t.get("description") or "")[:12000], tags=t.get("tags") or [], status=t.get("status") or row["status"],
                   live=True)
    except Exception as e:                       # Zendesk out of reach: what was kept
        row.update(description=row.get("sample") or "", tags=[], live=False, live_error=str(e)[:200])
    return row


def silent_close(ticket_id):
    """Silent close (a person, twice confirmed): a private note "Silent-Close"
    and the silent_close tag on the Zendesk ticket, in one update. Marked here
    (silent_ms) and counted as Spark being right."""
    import zendesk
    ensure()
    tid = int(ticket_id)
    row = _get(tid)
    if not row:
        raise ValueError("the Ad/Spam Filter hasn't read this ticket")
    if row.get("silent_ms"):
        raise ValueError("this ticket was silently closed already")
    t = zendesk.silent_close(tid)
    c = store.connect(True)
    try:
        c.cursor().execute(store._q("UPDATE adfilter SET silent_ms = %s, status = coalesce(%s, status), verdict = coalesce(verdict, 'right'), "
                                    "reviewed_ms = coalesce(reviewed_ms, %s) WHERE ticket_id = %s"),
                           (_now(), t.get("status"), _now(), tid))
        c.commit()
    finally:
        c.close()
    sys.stderr.write("[adfilter] #%d silently closed (private note + silent_close tag)\n" % tid)
    return _get(tid)
