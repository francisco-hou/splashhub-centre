"""Ad filter: Spark (Spluki's AI) reads each new ticket and decides whether it
is unsolicited marketing / spam -- someone selling a service to Splashtop (SEO,
backlinks, website traffic, ads, development...) -- or a real request. The ones
it calls ads are listed on the Ad filter page to be checked (Right / Wrong).

HELD: nothing is changed in Zendesk by itself. A person can open a ticket's
preview and press Silent close (confirmed twice): the silent_close tag, then one
update -- a private note "Silent-Close" (nothing is sent to the customer),
Product = Don't Know, Issue Type = Other (both required to solve) and status
Solved; the ticket is read back to show what stuck. It can be pressed again.

Its own Zendesk search, every 2 minutes: tickets created in the last 3 days
(never before the start day: the day before it was first switched on),
whatever their status; older ads' statuses are refreshed once a day. Each new
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
        "verdict", "reviewed_ms", "status", "channel", "silent_ms", "prev_spam", "rescan_ms", "gone_ms")
DDL = """CREATE TABLE IF NOT EXISTS adfilter (
    ticket_id BIGINT PRIMARY KEY, created_ms BIGINT, subject TEXT, requester TEXT, sample TEXT, spam INTEGER,
    confidence TEXT, why TEXT, checked_ms BIGINT, verdict TEXT, reviewed_ms BIGINT, status TEXT, channel TEXT,
    silent_ms BIGINT, prev_spam INTEGER, rescan_ms BIGINT, gone_ms BIGINT)"""
DONE = ("solved", "closed")
_ready = False
_lock = threading.Lock()
STATE = {"last_ms": None, "error": None, "busy": False}
RESCAN = {"running": False, "total": 0, "done": 0, "failed": 0, "changed": [], "error": None, "finished_ms": None, "why": {}}
JUDGE = {"error": None}           # Spark's last error in _judge, worded (Scan again shows it)


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
        # added after the table first shipped: silent_ms (0.12.7), prev_spam and rescan_ms (Scan again, 0.12.12)
        for col, typ in (("silent_ms", "BIGINT"), ("prev_spam", "INTEGER"), ("rescan_ms", "BIGINT"), ("gone_ms", "BIGINT")):
            if store.backend() == "postgres":
                cur.execute("ALTER TABLE adfilter ADD COLUMN IF NOT EXISTS %s %s" % (col, typ))
            else:
                cur.execute("PRAGMA table_info(adfilter)")
                if col not in [r[1] for r in cur.fetchall()]:
                    cur.execute("ALTER TABLE adfilter ADD COLUMN %s %s" % (col, typ))
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
              "invoice or an existing order, or someone reports a security problem. A chat where someone asks about "
              "Splashtop is never spam; neither is a message with no real text. When unsure, it is not spam.\n\n"
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


GONE = "deleted"                  # the status of a ticket Zendesk no longer has (most likely marked as spam)


def _mark_gone(ids):
    """Tickets Zendesk no longer returns: most likely marked as spam (which deletes
    them). Kept here, out of the open / solved views, in Not in Zendesk."""
    ids = [int(i) for i in ids]
    if not ids:
        return
    c = store.connect(True)
    try:
        cur = c.cursor()
        for tid in ids:
            cur.execute(store._q("UPDATE adfilter SET status = %s, gone_ms = %s WHERE ticket_id = %s AND coalesce(status, '') <> %s"),
                        (GONE, _now(), tid, GONE))
        c.commit()
    finally:
        c.close()


def _check_gone(ids):
    """Ask Zendesk for these tickets (100 to a call); the ones it doesn't return are gone.
    Only on an answer: a failed call marks nothing."""
    import zendesk
    ids = [int(i) for i in ids]
    for i in range(0, len(ids), 100):
        part = ids[i:i + 100]
        got = zendesk.statuses(part)                      # raises when Zendesk doesn't answer
        _mark_gone([tid for tid in part if tid not in got])


def _statuses(found, known):
    """Each ticket's Zendesk status as the search sees it now (it moves between the page's views)."""
    c = store.connect(True)
    try:
        cur = c.cursor()
        for t in found:
            if int(t["id"]) in known:
                cur.execute(store._q("UPDATE adfilter SET status = %s, gone_ms = NULL WHERE ticket_id = %s AND coalesce(status, '') <> %s"),
                            (t.get("status"), int(t["id"]), t.get("status") or ""))     # back in Zendesk (restored): its status again
        c.commit()
    finally:
        c.close()


def _refresh_older():
    """Once a day: the status of ads older than the 3-day search (still open
    ones only), 100 to a Zendesk call -- they move between the page's views."""
    import zendesk
    day = time.strftime("%Y-%m-%d", time.gmtime())
    if store.get_setting("adfilter_status_day", "") == day:
        return
    cutoff = _now() - 3 * 86400000
    ids = [int(r[0]) for r in store._read("SELECT ticket_id FROM adfilter WHERE spam = 1 AND created_ms < %s AND "
                                          "coalesce(status, '') NOT IN ('solved', 'closed', %s)", [cutoff, GONE], fresh=True)]
    for i in range(0, len(ids), 100):
        part = ids[i:i + 100]
        got = zendesk.statuses(part)
        _mark_gone([tid for tid in part if tid not in got])     # not returned: deleted, most likely marked as spam
        if got:
            c = store.connect(True)
            try:
                cur = c.cursor()
                for tid, st in got.items():
                    cur.execute(store._q("UPDATE adfilter SET status = %s WHERE ticket_id = %s"), (st, tid))
                c.commit()
            finally:
                c.close()
    store.set_setting("adfilter_status_day", day, "adfilter")


def run_once(limit=PER_ROUND):
    import spark, zendesk, autotag
    ensure()
    s = settings()
    if not s["on"]:
        return
    if zendesk.configured():
        raise RuntimeError("SplashHub Centre can't read Zendesk yet")
    # the last 3 days only (it never grows): every new ticket is in it, and recent ones' statuses
    since = max(s["since"], time.strftime("%Y-%m-%d", time.gmtime(time.time() - 3 * 86400)))
    found = [t for t in zendesk.search_tickets("type:ticket created>=%s" % since, max_pages=30)
             if (t.get("created_at") or "")[:10] >= s["since"]]
    _refresh_older()
    ids = [int(t["id"]) for t in found]
    known = set()
    for i in range(0, len(ids), 500):
        part = ids[i:i + 500]
        known |= {int(r[0]) for r in store._read("SELECT ticket_id FROM adfilter WHERE ticket_id IN (%s)" % ",".join(["%s"] * len(part)),
                                                 part, fresh=True)}
    _statuses(found, known)
    # ads from these days that the search no longer returns: still in Zendesk?
    seen = set(ids)
    missing = [int(r[0]) for r in store._read("SELECT ticket_id FROM adfilter WHERE spam = 1 AND created_ms >= %s AND "
                                              "coalesce(status, '') <> %s", [autotag._ms(since + "T00:00:00Z") or 0, GONE], fresh=True)
               if int(r[0]) not in seen]
    if missing:
        _check_gone(missing)
    if store.get_setting("adfilter_chats_v2", "") != "yes":
        c = store.connect(True)
        try:
            c.cursor().execute("DELETE FROM adfilter WHERE spam = 1 AND verdict IS NULL AND silent_ms IS NULL AND "
                               "(coalesce(sample, '') = '' OR lower(coalesce(subject, '')) LIKE 'chat with%' OR "
                               "lower(coalesce(subject, '')) LIKE 'conversation with%' OR lower(coalesce(channel, '')) LIKE '%chat%' OR "
                               "lower(coalesce(channel, '')) LIKE '%messag%')")
            c.commit()
        finally:
            c.close()
        store.set_setting("adfilter_chats_v2", "yes", "adfilter")
        known = set()
        for i in range(0, len(ids), 500):
            part = ids[i:i + 500]
            known |= {int(r[0]) for r in store._read("SELECT ticket_id FROM adfilter WHERE ticket_id IN (%s)" % ",".join(["%s"] * len(part)),
                                                     part, fresh=True)}
    todo = sorted([t for t in found if int(t["id"]) not in known], key=lambda t: t.get("created_at") or "", reverse=True)[:limit]
    if not todo:
        return
    if not spark.available():
        raise RuntimeError("Spark isn't set up")
    skip = [p.lower() for p in autotag.settings()["skip"]]
    for i in range(0, len(todo), BATCH):
        rows, failed = _judge(todo[i:i + BATCH], s, skip)
        if failed:                                   # Spark didn't answer: these wait for the next round
            STATE["error"] = "Spark didn't answer; trying again in 2 minutes"
        _save(list(rows.values()))


def _judge(batch, s, skip):
    """Read each ticket and decide, with today's rules: ({ticket id: row}, [ids
    Spark didn't answer for]). A chat still going is left out (judged once its
    transcript arrives). Used by the rounds and by Scan again."""
    import autotag
    rows, ask = {}, []
    for t in batch:
        ch = ((t.get("via") or {}).get("channel") or "")
        r = {"ticket_id": int(t["id"]), "created_ms": autotag._ms(t.get("created_at")), "subject": (t.get("subject") or "")[:300],
             "status": t.get("status"), "channel": ch, "requester": "", "sample": "", "spam": 0}
        if autotag._is_call(ch, t.get("subject"), t.get("tags")):          # a phone call: not an ad, not read
            r["why"] = "phone call"
        else:
            text, email, ready = autotag._customer_words(t)
            if not ready:                          # a chat still going: judged once its transcript arrives
                continue
            r.update(requester=email, sample=re.sub(r"\s+", " ", text).strip())
            if any(p and p in (text + " " + (t.get("description") or "")).lower() for p in skip):
                r["why"] = "provisioning request"
            elif len(re.sub(r"\s+", "", text)) < 15:  # no real message: never called spam
                r["why"] = "no customer text"
            else:
                subj = "" if autotag._chat_kind(t) else (t.get("subject") or "")
                ask.append((int(t["id"]), subj, email, text))
        rows[int(t["id"])] = r
    failed = []
    if ask:
        try:
            got = _ask(ask, s["examples"])
        except Exception as e:               # Spark down or an odd answer
            sys.stderr.write("[adfilter] Spark skipped %d ticket(s): %s\n" % (len(ask), type(e).__name__))
            JUDGE["error"] = str(e)[:160] if type(e).__name__ == "SparkError" else \
                "its answer couldn't be read" if isinstance(e, ValueError) else type(e).__name__
            got = {}
        for tid, _, _, _ in ask:
            if tid in got:
                spam, conf, why = got[tid]
                rows[tid].update(spam=1 if spam else 0, confidence=conf, why=why)
            else:
                rows.pop(tid, None)
                failed.append(tid)
    return rows, failed


# ---- Scan again: tickets already read, read and asked again with today's rules ---------------------

def _update(rows):
    c = store.connect(True)
    try:
        cur = c.cursor()
        for r in rows:
            cur.execute(store._q("UPDATE adfilter SET subject = %s, requester = %s, sample = %s, spam = %s, confidence = %s, why = %s, "
                                 "checked_ms = %s, status = %s, channel = %s, prev_spam = %s, rescan_ms = %s WHERE ticket_id = %s"),
                        (r["subject"], r["requester"], (r["sample"] or "")[:1200], r["spam"], r.get("confidence"), r.get("why"),
                         _now(), r["status"], r["channel"], r.get("prev_spam"), r.get("rescan_ms"), r["ticket_id"]))
        c.commit()
    finally:
        c.close()


def _rescan(ids):
    """Read these tickets from Zendesk again and ask Spark again (nothing is
    written to Zendesk). The old call is kept in prev_spam; the team's checks
    and silent closes stay as they are."""
    import spark, zendesk, autotag
    if zendesk.configured():
        raise ValueError("SplashHub Centre can't read Zendesk yet")
    if not spark.available():
        raise ValueError("Spark isn't set up")
    s = settings()
    skip = [p.lower() for p in autotag.settings()["skip"]]
    marks = ",".join(["%s"] * len(ids))
    old = {int(r[0]): int(r[1] or 0) for r in store._read("SELECT ticket_id, spam FROM adfilter WHERE ticket_id IN (%s)" % marks,
                                                          list(ids), fresh=True)}
    tickets = [t for t in zendesk.tickets_many(ids) if int(t["id"]) in old]
    w = RESCAN["why"]
    w["missing"] = len(ids) - len(tickets)
    RESCAN["failed"] += w["missing"]
    if w["missing"]:
        back = {int(t["id"]) for t in tickets}
        _mark_gone([tid for tid in ids if tid in old and tid not in back])
    for i in range(0, len(tickets), BATCH):
        part = tickets[i:i + BATCH]
        JUDGE["error"] = None
        rows, failed = _judge(part, s, skip)
        if failed:                                          # Spark didn't answer (often its rate limit): once more
            time.sleep(4)
            JUDGE["error"] = None
            again, failed = _judge([t for t in part if int(t["id"]) in failed], s, skip)
            rows.update(again)
        if failed:
            w["spark"] = w.get("spark", 0) + len(failed)
            w["spark_error"] = JUDGE["error"]
        w["chat"] = w.get("chat", 0) + len(part) - len(rows) - len(failed)    # left out: a chat still going
        for tid, r in rows.items():
            r.update(prev_spam=old[tid], rescan_ms=_now())
            if r["spam"] != old[tid]:
                RESCAN["changed"].append({"ticket_id": tid, "was": "ad / spam" if old[tid] else "not an ad",
                                          "now": "ad / spam" if r["spam"] else "not an ad", "why": r.get("why") or ""})
        _update(list(rows.values()))
        RESCAN["failed"] += len(part) - len(rows)          # no answer, or a chat still going
        RESCAN["done"] += len(part)


def rescan(ids):
    """The page's Scan again: one ticket (the preview) is answered at once; a
    page of them runs in the background (RESCAN, in status())."""
    ensure()
    ids = list(dict.fromkeys(int(i) for i in ids))[:200]
    if not ids:
        raise ValueError("choose some tickets")
    if RESCAN["running"]:
        raise ValueError("Spark is already reading tickets again")
    RESCAN.update(running=True, total=len(ids), done=0, failed=0, changed=[], error=None, finished_ms=None, why={})

    def run():
        try:
            _rescan(ids)
        except Exception as e:
            RESCAN["error"] = str(e)[:200] if isinstance(e, ValueError) or "Zendesk" in str(e) else type(e).__name__
            sys.stderr.write("[adfilter] scan again: %s\n" % RESCAN["error"])
        finally:
            RESCAN.update(running=False, finished_ms=_now(), why_text=_why_text(RESCAN["why"]))
    if len(ids) == 1:
        run()
        if RESCAN["error"]:
            raise ValueError(RESCAN["error"])
        if RESCAN["failed"]:
            raise ValueError("the old call stays: " + (RESCAN["why_text"] or "no answer"))
        return {"row": _get(ids[0]), "rescan": dict(RESCAN)}
    threading.Thread(target=run, name="adfilter-rescan", daemon=True).start()
    return {"rescan": dict(RESCAN)}


def _why_text(w):
    """Why tickets kept their old answer, in words (Scan again)."""
    parts = []
    if w.get("missing"):
        parts.append("%d not found in Zendesk -- likely marked as spam (moved to Not in Zendesk)" % w["missing"])
    if w.get("chat"):
        parts.append("%d chat%s still going (judged once the transcript is in)" % (w["chat"], "" if w["chat"] == 1 else "s"))
    if w.get("spark"):
        parts.append("%d without an answer from Spark%s" % (w["spark"], (" -- " + w["spark_error"]) if w.get("spark_error") else ""))
    return "; ".join(parts)


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
    wrong (the ones the team marked wrong). Only tickets Spark called ads,
    except a search by ticket number."""
    ensure()
    where, args = ["spam = 1"], []
    if view == "done":
        where.append("status IN ('solved', 'closed')")
    elif view == "wrong":                     # every one marked wrong, also once Spark (scanned again) agrees it's real
        where = ["verdict = 'wrong'"]
    elif view == "gone":                      # no longer in Zendesk: most likely marked as spam
        where.append("status = '%s'" % GONE)
    else:
        where.append("coalesce(status, '') NOT IN ('solved', 'closed', '%s')" % GONE)
    if q:
        q = q.strip().lstrip("#")
        if q.isdigit():                       # a ticket number: that ticket, whatever the view or Spark's call
            where, args = ["ticket_id = %s"], [int(q)]
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
    n, ads, open_ads, right, wrong, silent, gone = store._read(
        "SELECT count(*), sum(spam), sum(CASE WHEN spam = 1 AND coalesce(status, '') NOT IN ('solved', 'closed', '%s') THEN 1 ELSE 0 END), "
        "sum(CASE WHEN verdict = 'right' THEN 1 ELSE 0 END), sum(CASE WHEN verdict = 'wrong' THEN 1 ELSE 0 END), "
        "sum(CASE WHEN silent_ms IS NOT NULL THEN 1 ELSE 0 END), sum(CASE WHEN spam = 1 AND status = '%s' THEN 1 ELSE 0 END) "
        "FROM adfilter" % (GONE, GONE), [], fresh=True)[0]
    return dict(s, checked=int(n or 0), ads=int(ads or 0), open_ads=int(open_ads or 0), gone_ads=int(gone or 0),
                done_ads=int(ads or 0) - int(open_ads or 0) - int(gone or 0),
                right=int(right or 0), wrong=int(wrong or 0), silent=int(silent or 0),
                last_ms=STATE["last_ms"], error=STATE["error"], busy=STATE["busy"], rescan=dict(RESCAN))


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
    now -- status, tags, and the whole conversation (every reply and internal
    note, oldest first, each marked customer / agent / internal note)."""
    import zendesk
    ensure()
    row = _get(ticket_id)
    if not row:
        raise ValueError("the Ad/Spam Filter hasn't read this ticket")
    try:
        t, convo = zendesk.conversation(int(ticket_id))
        row.update(description=(t.get("description") or "")[:12000], tags=t.get("tags") or [], status=t.get("status") or row["status"],
                   conversation=convo, live=True)
    except Exception as e:                       # Zendesk out of reach: what was kept
        if "HTTP 404" in str(e):                 # Zendesk has no such ticket now: most likely marked as spam
            _mark_gone([ticket_id])
            row = _get(ticket_id)
        row.update(description=row.get("sample") or "", tags=[], conversation=[], live=False, live_error=str(e)[:200])
    return row



def silent_close(ticket_id):
    """Silent close (a person, twice confirmed): zendesk.silent_close -- the tag,
    then the private note, the required fields and Solved -- and what stuck.
    Marked here (silent_ms) and counted as Spark being right. Can be pressed
    again (a retry) for now."""
    import zendesk
    ensure()
    tid = int(ticket_id)
    row = _get(tid)
    if not row:
        raise ValueError("the Ad/Spam Filter hasn't read this ticket")
    res = zendesk.silent_close(tid)
    t = res["ticket"]
    c = store.connect(True)
    try:
        c.cursor().execute(store._q("UPDATE adfilter SET silent_ms = %s, status = coalesce(%s, status), verdict = coalesce(verdict, 'right'), "
                                    "reviewed_ms = coalesce(reviewed_ms, %s) WHERE ticket_id = %s"),
                           (_now(), t.get("status"), _now(), tid))
        c.commit()
    finally:
        c.close()
    sys.stderr.write("[adfilter] #%d silent close: tag %s, status %s, %s\n" % (
        tid, "ok" if res["tag"] else "MISSING", res["status"], ", ".join("%s %s" % (k, "ok" if v else "NOT SET") for k, v in res["fields"].items())))
    out = _get(tid)
    out["check"] = {"tag": res["tag"], "status": res["status"], "fields": res["fields"]}
    return out
