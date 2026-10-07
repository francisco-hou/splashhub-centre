"""AutoTag: the language of every new Zendesk ticket, read by Spark in the
background -- the job SplashTags does in the agent's browser, done here for
every ticket from the day it was switched on, whether or not anyone opens it.

HELD, NOT WRITTEN: the language tag each ticket would get is only kept here
(the AutoTag page) so the team can check it against what the ticket really is.
Nothing is written to Zendesk yet.

The same rules as SplashTags (Auto Tag Tool Zendesk/assets/main.js):
  - read the subject and the FIRST customer message only (later replies drift
    to English); agents' comments are left out; a chat transcript keeps only the
    visitor's lines; chat boilerplate ("Chat started:", "Name:", "Email:" ...)
    is stripped; "Chat with X" subjects are integration text, not the customer's
  - a skip phrase anywhere in the first message (default "Provision Details")
    means no tag
  - a requester on the always-Japanese list is Japanese whatever the text
  - the same ten languages and tags (tags.LANGUAGES); a real language not on
    that list is Other (language_other); no real customer text gets no tag

Every 2 minutes: a Zendesk search for tickets created since the start day
(the last 3 days of them, to refresh their status and tags), and Spark reads
the new ones, 8 to a call. Spark costs nothing; reads only.
"""
import json, re, sys, threading, time

import store
import tags as tagsets

KEY = "autotag"
EVERY = 120
BATCH = 8
PER_ROUND = 48
LANGS = [(l["label"], l["tag"]) for l in tagsets.LANGUAGES] + [("Other", "language_other")]   # Other: any language not on the list
LABEL_OF_TAG = {t: l for l, t in LANGS}
TAG_OF = dict(LANGS)
COLS = ("ticket_id", "created_ms", "subject", "status", "channel", "requester", "sample", "lang", "tag", "confidence",
        "reason", "method", "state", "zd_tags", "checked_ms", "verdict", "correct_lang", "reviewed_ms", "seen_ms",
        "applied_tag", "applied_ms", "applied_from")
DDL = """CREATE TABLE IF NOT EXISTS autotag (
    ticket_id BIGINT PRIMARY KEY, created_ms BIGINT, subject TEXT, status TEXT, channel TEXT, requester TEXT,
    sample TEXT, lang TEXT, tag TEXT, confidence TEXT, reason TEXT, method TEXT, state TEXT, zd_tags TEXT,
    checked_ms BIGINT, verdict TEXT, correct_lang TEXT, reviewed_ms BIGINT, seen_ms BIGINT,
    applied_tag TEXT, applied_ms BIGINT, applied_from TEXT)"""
CHAT_LINE = re.compile(r"^(chat started:|chat ended:|served by:|ip:|user agent:|country:|city:|url:|chat id:|name:|email:|phone:|notes:|"
                       r"department:|rating:|the chat transcript will be appended)", re.I)
CHAT_TIME = re.compile(r"^\(\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM)?\)\s*", re.I)
KEEP = ("ticket_id", "verdict", "correct_lang", "reviewed_ms", "applied_tag", "applied_ms", "applied_from")   # people's work: never overwritten by a round
_ready = False
_lock = threading.Lock()
STATE = {"last_ms": None, "error": None, "busy": False}
# The page's mass Add tags (for the checking phase; to be removed once AutoTag writes tags by itself)
BULK = {"running": False, "total": 0, "done": 0, "tagged": 0, "skipped": 0, "failed": 0, "error": None, "finished_ms": None}


def _now():
    return int(time.time() * 1000)


def _ms(iso):
    import calendar
    try:
        return int(calendar.timegm(time.strptime((iso or "")[:19], "%Y-%m-%dT%H:%M:%S")) * 1000)
    except ValueError:
        return None


def ensure():
    global _ready
    if _ready:
        return
    store.ensure_schema()
    c = store.connect(True)
    try:
        cur = c.cursor()
        cur.execute(DDL)
        cur.execute("CREATE INDEX IF NOT EXISTS autotag_created ON autotag (created_ms)")
        c.commit()
    finally:
        c.close()
    _ready = True


# ---- settings --------------------------------------------------------------------------------

def _today():
    """Today's date where the team is (Taiwan, UTC+8): where "today" starts."""
    return time.strftime("%Y-%m-%d", time.gmtime(time.time() + 8 * 3600))


def settings():
    try:
        s = json.loads(store.get_setting(KEY, "") or "{}")
    except ValueError:
        s = {}
    if not s.get("since"):                          # the first time: from today on
        s = dict(s, since=_today(), on=True)
        store.set_setting(KEY, json.dumps(s), "autotag")
    return {"on": s.get("on", True) is not False, "since": s["since"],
            "skip": s.get("skip") if isinstance(s.get("skip"), list) else ["Provision Details"],
            "jp_emails": s.get("jp_emails") if isinstance(s.get("jp_emails"), list) else ["splashtop@och.co.jp"],
            "write": False}             # automatic writing to Zendesk: not yet (verifying); the page's Add tag button does one ticket


def save_settings(data, by=None):
    s = settings()
    if "on" in data:
        s["on"] = bool(data["on"])
    for k in ("skip", "jp_emails"):
        if k in data:
            v = data[k]
            items = v if isinstance(v, list) else re.split(r"[,\n]", str(v or ""))
            s[k] = [x.strip() for x in items if str(x).strip()][:50]
    s["jp_emails"] = [e.lower() for e in s["jp_emails"]]
    store.set_setting(KEY, json.dumps({k: s[k] for k in ("on", "since", "skip", "jp_emails")}), by)
    if s["on"]:
        kick()
    return status()


# ---- what the customer wrote (SplashTags' rules) ---------------------------------------------

def _strip(text):
    return "\n".join(l for l in (text or "").split("\n") if not CHAT_LINE.match(l.strip()))


def _visitor_lines(text):
    lines = text.split("\n")
    agents = {m.group(1).strip() for m in (re.search(r"\*\*\*\s*(.+?)\s+(?:joined|left) the chat", l, re.I) for l in lines) if m}
    kept, keeping = [], False
    for line in lines:
        rest = CHAT_TIME.sub("", line, count=1)
        if rest != line:
            if rest.startswith("***"):
                keeping = False
                continue
            m = re.match(r"^([^:]{1,60}?):\s*([\s\S]*)$", rest)
            keeping = bool(m) and m.group(1).strip() not in agents
            if keeping and m.group(2) and not re.match(r"visitor uploaded:", m.group(2), re.I):
                kept.append(m.group(2))
            continue
        if keeping and line.strip():
            kept.append(line)
    return "\n".join(kept)


def _customer_text(body, role):
    clean = _strip(body)
    if CHAT_TIME.match(clean) or re.search(r"\n\(\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM)?\)\s*", clean, re.I):
        return _visitor_lines(clean)
    if role and role != "end-user":
        return ""
    return clean


def _first_message(t):
    """(the first customer message, the requester's email), from the ticket's
    first comments; the description when they can't be read."""
    import zendesk
    email = (((t.get("via") or {}).get("source") or {}).get("from") or {}).get("address") or ""
    try:
        d = zendesk.get_json("/api/v2/tickets/%d/comments.json?page[size]=10&include=users" % int(t["id"]))
        users = {u.get("id"): u for u in d.get("users") or []}
        req = users.get(t.get("requester_id")) or {}
        email = email or req.get("email") or ""
        for c in d.get("comments") or []:
            role = (users.get(c.get("author_id")) or {}).get("role")
            text = _customer_text(c.get("body") or c.get("plain_body") or "", role)
            if text.strip():
                return text, email.lower()
    except Exception as e:
        sys.stderr.write("[autotag] comments of #%s: %s\n" % (t.get("id"), type(e).__name__))
    return _customer_text(t.get("description") or "", None), email.lower()


# ---- Spark ---------------------------------------------------------------------------------

def _ask_spark(items):
    """{ticket id: (label or "Other", confidence, reason)} for [(id, subject, text)]."""
    import spark
    names = [l for l, _ in LANGS if l != "Other"]
    system = ("You tell which language a support ticket's CUSTOMER wrote in. Allowed answers: %s; Other (a real language "
              "that is not in that list); or None (no real customer text: empty, only a signature, only an automatic "
              "message or attachment names). Judge the customer's own words; ignore English signatures, legal disclaimers, "
              "quoted replies, product names, error messages and automatic text. Chinese: Simplified if it uses simplified "
              "characters (这 们 说 么 发), Traditional if traditional ones (這 們 說 麼 發). Japanese if there is any kana. "
              "confidence is high, medium or low. Answer with JSON only, one entry per ticket: "
              '{"<ticket id>": {"lang": "<answer>", "confidence": "high|medium|low", "why": "<6 words at most>"}}') % ", ".join(names)
    text = "\n\n".join("Ticket %s\nSubject: %s\nCustomer wrote: %s" % (i, s[:160], re.sub(r"\s+", " ", x)[:900]) for i, s, x in items)
    raw = spark.chat(system, text, max_tokens=900)
    got = json.loads(raw[raw.find("{"):raw.rfind("}") + 1] or "{}")
    allowed = dict({n.lower(): n for n in names}, other="Other", none="None")
    out = {}
    for i, _, _ in items:
        a = got.get(str(i)) or {}
        if isinstance(a, str):
            a = {"lang": a}
        lang = allowed.get(str(a.get("lang") or "").strip().lower(), "None")      # an answer off the list: no tag
        conf = str(a.get("confidence") or "").lower()
        out[i] = (lang, conf if conf in ("high", "medium", "low") else "medium", str(a.get("why") or "")[:80])
    return out


# ---- the round --------------------------------------------------------------------------------

def _known(ids):
    if not ids:
        return {}
    marks = ",".join(["%s"] * len(ids))
    return {int(r[0]): r[1] for r in store._read("SELECT ticket_id, state FROM autotag WHERE ticket_id IN (%s)" % marks, list(ids), fresh=True)}


def _save(rows):
    c = store.connect(True)
    try:
        cur = c.cursor()
        upd = ", ".join("%s = EXCLUDED.%s" % (k, k) for k in COLS if k not in KEEP)
        sql = store._q("INSERT INTO autotag (%s) VALUES (%s) ON CONFLICT (ticket_id) DO UPDATE SET %s"
                       % (", ".join(COLS), ", ".join(["%s"] * len(COLS)), upd))      # a team member's check is kept
        for r in rows:
            cur.execute(sql, [r.get(k) for k in COLS])
        c.commit()
    finally:
        c.close()


def _refresh(tickets):
    """The latest status and tags of tickets already read (SplashTags or an agent may tag them)."""
    c = store.connect(True)
    try:
        cur = c.cursor()
        for t in tickets:
            cur.execute(store._q("UPDATE autotag SET status = %s, zd_tags = %s, subject = %s, seen_ms = %s WHERE ticket_id = %s"),
                        (t.get("status"), " ".join(t.get("tags") or []), (t.get("subject") or "")[:300], _now(), int(t["id"])))
        c.commit()
    finally:
        c.close()


def run_once(force=False, limit=PER_ROUND):
    import spark, zendesk
    ensure()
    s = settings()
    if not (s["on"] or force):                  # off: only the page's Scan button reads tickets
        return
    if zendesk.configured():
        raise RuntimeError("SplashHub Centre can't read Zendesk yet")
    since = max(s["since"], time.strftime("%Y-%m-%d", time.gmtime(time.time() - 3 * 86400)))
    found = list(zendesk.search_tickets("type:ticket created>=%s" % since, max_pages=20))
    found = [t for t in found if (t.get("created_at") or "")[:10] >= s["since"]]
    known = _known([int(t["id"]) for t in found])
    _refresh([t for t in found if int(t["id"]) in known and known[int(t["id"])] != "waiting"])
    todo = sorted([t for t in found if int(t["id"]) not in known or known[int(t["id"])] == "waiting"], key=lambda t: t.get("created_at") or "")
    if not todo:
        return
    if not spark.available():
        raise RuntimeError("Spark isn't set up")
    skip = [p.lower() for p in s["skip"]]
    for i in range(0, min(len(todo), limit), BATCH):
        batch, rows, ask = todo[i:i + BATCH], {}, []
        for t in batch:
            text, email = _first_message(t)
            subject = t.get("subject") or ""
            if re.match(r"^(chat|conversation) with\b", subject.strip(), re.I):
                subject = ""
            row = {"ticket_id": int(t["id"]), "created_ms": _ms(t.get("created_at")), "subject": (t.get("subject") or "")[:300],
                   "status": t.get("status"), "channel": ((t.get("via") or {}).get("channel") or ""), "requester": email,
                   "sample": re.sub(r"\s+", " ", text).strip()[:1200], "zd_tags": " ".join(t.get("tags") or []),
                   "checked_ms": _now(), "seen_ms": _now()}
            hit = next((p for p in skip if p and (p in text.lower() or p in (t.get("description") or "").lower())), None)
            if hit:
                row.update(lang=None, tag=None, confidence=None, method="skip", state="skipped", reason='skip phrase "%s"' % hit)
            elif email and email in s["jp_emails"]:
                row.update(lang="Japanese", tag=TAG_OF["Japanese"], confidence="high", method="requester", state="held",
                           reason="always-Japanese requester")
            elif not (subject.strip() or text.strip()):
                row.update(lang="None", tag=None, confidence="low", method="spark", state="none", reason="no customer text")
            else:
                ask.append((int(t["id"]), subject, text))
            rows[int(t["id"])] = row
        if ask:
            try:
                got = _ask_spark(ask)
            except Exception as e:                       # Spark down or an odd answer: these wait for the next round
                sys.stderr.write("[autotag] Spark skipped %d ticket(s): %s\n" % (len(ask), type(e).__name__))
                got = {}
                STATE["error"] = "Spark didn't answer (%s); trying again in 2 minutes" % type(e).__name__
            for tid, _, _ in ask:
                if tid in got:
                    lang, conf, why = got[tid]
                    rows[tid].update(lang=lang, tag=TAG_OF.get(lang), confidence=conf, reason=why, method="spark",
                                     state="held" if lang in TAG_OF else "none")
                else:
                    rows[tid].update(state="waiting", method="spark")
        _save(list(rows.values()))


def _round(force=False, limit=PER_ROUND):
    if not _lock.acquire(blocking=False):
        return
    STATE.update(busy=True, error=None)
    try:
        run_once(force, limit)                       # may leave a note in STATE["error"] (Spark didn't answer)
        STATE["last_ms"] = _now()
    except Exception as e:
        STATE.update(last_ms=_now(), error=str(e)[:200] if "Zendesk" in str(e) or "Spark" in str(e) else "a round failed (%s)" % type(e).__name__)
        sys.stderr.write("[autotag] %s\n" % STATE["error"])
    finally:
        STATE["busy"] = False
        _lock.release()


def kick():
    threading.Thread(target=_round, name="autotag-now", daemon=True).start()


def scan_now():
    """The page's Scan new tickets button (for the checking phase): every
    ticket not read yet, at once, whether or not the 2-minute rounds are on."""
    if STATE["busy"]:
        return False
    threading.Thread(target=_round, args=(True, 100000), name="autotag-scan", daemon=True).start()
    return True


def boot():
    def loop():
        time.sleep(20)
        while True:
            _round()
            time.sleep(EVERY)
    threading.Thread(target=loop, name="autotag-loop", daemon=True).start()


# ---- the page ---------------------------------------------------------------------------------

def _zd_lang(zd_tags):
    for g in (zd_tags or "").split():
        if g in LABEL_OF_TAG:
            return LABEL_OF_TAG[g]
    return None


def _match(r):
    zl = _zd_lang(r["zd_tags"])
    if r["state"] != "held" and r["state"] != "none":
        return None
    if not zl:
        return "no_tag"
    want = r["lang"] if r["state"] == "held" else None
    return "same" if want == zl else "differs"


def _row(t):
    r = dict(zip(COLS, t))
    r["zd_lang"] = _zd_lang(r["zd_tags"])
    r["match"] = _match(r)
    r.pop("zd_tags", None)
    return r


def search(q=None, lang=None, state=None, match=None, verdict=None, page=0, per_page=50):
    ensure()
    where, args = [], []
    if q:
        q = q.strip().lstrip("#")
        if q.isdigit():
            where.append("ticket_id = %s")
            args.append(int(q))
        else:
            where.append("(lower(subject) LIKE %s OR lower(requester) LIKE %s OR lower(sample) LIKE %s)")
            args += ["%" + q.lower() + "%"] * 3
    if lang:
        where.append("lang = %s")
        args.append(lang)
    if state:
        where.append("state = %s")
        args.append(state)
    if verdict == "unchecked":
        where.append("verdict IS NULL AND state IN ('held', 'none')")
    elif verdict:
        where.append("verdict = %s")
        args.append(verdict)
    sql_where = (" WHERE " + " AND ".join(where)) if where else ""
    rows = [_row(t) for t in store._read("SELECT %s FROM autotag%s ORDER BY created_ms DESC" % (", ".join(COLS), sql_where), args, fresh=True)]
    if match:
        rows = [r for r in rows if r["match"] == match]
    total = len(rows)
    return {"rows": rows[page * per_page:(page + 1) * per_page], "total": total, "page": page, "per_page": per_page}


def status():
    ensure()
    s = settings()
    now = _now()
    rows = store._read("SELECT lang, state, zd_tags, verdict, created_ms FROM autotag", [], fresh=True)
    by_lang, held, none, skipped, waiting, same, differs, no_tag, right, wrong, today = {}, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
    for lang, state, zd, verdict, cms in rows:
        if cms and cms >= now - 86400000:
            today += 1
        if state == "held":
            held += 1
            by_lang[lang] = by_lang.get(lang, 0) + 1
        elif state == "none":
            none += 1
        elif state == "skipped":
            skipped += 1
        elif state == "waiting":
            waiting += 1
        if state in ("held", "none"):
            m = _match({"zd_tags": zd, "state": state, "lang": lang})
            same += m == "same"
            differs += m == "differs"
            no_tag += m == "no_tag"
        right += verdict == "right"
        wrong += verdict == "wrong"
    return dict(s, total=len(rows), last_24h=today, held=held, none=none, skipped=skipped, waiting=waiting,
                same=same, differs=differs, no_tag=no_tag, right=right, wrong=wrong,
                languages=sorted(({"lang": k, "n": v} for k, v in by_lang.items()), key=lambda x: -x["n"]),
                choices=[l for l, _ in LANGS], last_ms=STATE["last_ms"], error=STATE["error"], busy=STATE["busy"], bulk=dict(BULK))


def set_verdict(ticket_id, verdict, correct_lang=None):
    ensure()
    if verdict not in ("right", "wrong", ""):
        raise ValueError("verdict is right, wrong or empty")
    if correct_lang and correct_lang not in TAG_OF and correct_lang != "None":
        raise ValueError("unknown language")
    c = store.connect(True)
    try:
        cur = c.cursor()
        cur.execute(store._q("UPDATE autotag SET verdict = %s, correct_lang = %s, reviewed_ms = %s WHERE ticket_id = %s"),
                    (verdict or None, (correct_lang or None) if verdict == "wrong" else None, _now() if verdict else None, int(ticket_id)))
        c.commit()
    finally:
        c.close()
    r = search(q=str(ticket_id))["rows"]
    return r[0] if r else None


def apply_tag(ticket_id, lang):
    """The page's Add tag / Change tag: put this language's tag on the Zendesk
    ticket and take off any other language tag (the ten and language_other) -- tags only (no
    status change, nothing to submit). One ticket, when a person presses it."""
    import zendesk
    ensure()
    if lang not in TAG_OF:
        raise ValueError("unknown language")
    tid = int(ticket_id)
    rows = store._read("SELECT zd_tags FROM autotag WHERE ticket_id = %s", [tid], fresh=True)
    if not rows:
        raise ValueError("AutoTag hasn't read this ticket")
    now_tags = (zendesk.get_json("/api/v2/tickets/%d.json" % tid).get("ticket") or {}).get("tags") or []   # as they are right now
    tag = TAG_OF[lang]
    old = [g for g in now_tags if g in LABEL_OF_TAG and g != tag]
    after = zendesk.change_tags(tid, add=[] if tag in now_tags else [tag], remove=old)
    if after is None:
        after = now_tags
    c = store.connect(True)
    try:
        cur = c.cursor()
        cur.execute(store._q("UPDATE autotag SET zd_tags = %s, applied_tag = %s, applied_ms = %s, applied_from = %s WHERE ticket_id = %s"),
                    (" ".join(after), tag, _now(), " ".join(old) or None, tid))
        c.commit()
    finally:
        c.close()
    return search(q=str(tid))["rows"][0]


def _target(r):
    """The language a ticket's tag should be: the team's correction, else Spark's (None: nothing to add)."""
    lang = r["correct_lang"] if r["verdict"] == "wrong" and r["correct_lang"] else (r["lang"] if r["state"] == "held" else None)
    return lang if lang in TAG_OF and lang != r["zd_lang"] else None


def apply_many(ids):
    """The page's mass Add tags (for the checking phase): each chosen ticket's
    tag, one after another in the background (tags only, as apply_tag)."""
    ensure()
    ids = [int(i) for i in ids][:500]
    if BULK["running"]:
        raise ValueError("tags are already being added")
    if not ids:
        raise ValueError("choose some tickets")
    BULK.update(running=True, total=len(ids), done=0, tagged=0, skipped=0, failed=0, error=None, finished_ms=None)

    def run():
        try:
            for tid in ids:
                rows = search(q=str(tid))["rows"]
                lang = _target(rows[0]) if rows else None
                if not lang:
                    BULK["skipped"] += 1
                else:
                    try:
                        apply_tag(tid, lang)
                        BULK["tagged"] += 1
                    except Exception as e:
                        BULK["failed"] += 1
                        BULK["error"] = str(e)[:200] if "Zendesk" in str(e) else type(e).__name__
                        sys.stderr.write("[autotag] tag #%d: %s\n" % (tid, BULK["error"]))
                    time.sleep(0.25)                  # gentle on Zendesk
                BULK["done"] += 1
        finally:
            BULK.update(running=False, finished_ms=_now())
    threading.Thread(target=run, name="autotag-bulk", daemon=True).start()
    return dict(BULK)
