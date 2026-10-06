"""Knowledge Base: the Zendesk Help Center's articles, kept here so the team can
search them, see each one's stats, and the AI page can point a customer to the
right article.

What is kept per article and language (one row each):
  title, the text (from the article's HTML: headings, lists and paragraphs kept),
  section and category, the Help Center link, labels, draft / agents-only /
  promoted / outdated flags, votes (up and down), created / updated / edited.
  Not kept: the author (a support agent), comments, images.
Plus, from the downloaded Zendesk tickets (cases.py): how many 2026 tickets link
each article -- the ticket text keeps "article <id>" for every Help Center link.

Getting them (Settings > Database > Zendesk Knowledge Base, admin): every
language the Help Center has, 100 articles a call, with their sections and
categories. A whole sync is a few hundred calls; it runs again every 6 hours and
drops articles Zendesk no longer has. Reads only -- nothing is written to Zendesk.
"""
import html as _html, re, sys, threading, time

import store
import zendesk

SYNC_EVERY = 6 * 3600
TEXT_CHARS = 60000
PAGES_MAX = 200               # 100 articles a page, per language

COLS = ("id", "locale", "source_locale", "title", "body", "url", "section_id", "section", "category",
        "labels", "draft", "internal", "promoted", "outdated", "vote_sum", "vote_count",
        "created_ms", "updated_ms", "edited_ms", "saved_ms")

DDL = """CREATE TABLE IF NOT EXISTS kb_articles (
    id BIGINT NOT NULL, locale TEXT NOT NULL, source_locale TEXT,
    title TEXT, body TEXT, url TEXT, section_id BIGINT, section TEXT, category TEXT, labels TEXT,
    draft INTEGER, internal INTEGER, promoted INTEGER, outdated INTEGER,
    vote_sum INTEGER, vote_count INTEGER,
    created_ms BIGINT, updated_ms BIGINT, edited_ms BIGINT, saved_ms BIGINT,
    PRIMARY KEY (id, locale))"""
TSV_PG = """ALTER TABLE kb_articles ADD COLUMN IF NOT EXISTS tsv tsvector GENERATED ALWAYS AS (
        setweight(to_tsvector('simple', coalesce(title, '')), 'A') ||
        setweight(to_tsvector('simple', coalesce(labels, '')), 'B') ||
        setweight(to_tsvector('simple', coalesce(section, '') || ' ' || coalesce(category, '')), 'C') ||
        setweight(to_tsvector('simple', coalesce(body, '')), 'D')) STORED"""

_ready = False
_lock = threading.Lock()
JOB = {"running": False, "saved": 0, "locale": None, "error": None, "finished_ms": None, "stop": False}
ARTICLE_RE = re.compile(r"\barticle (\d{6,})\b")


def _pg():
    return store.backend() == "postgres"


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
        if _pg():
            cur.execute(TSV_PG)
            cur.execute("CREATE INDEX IF NOT EXISTS kb_tsv ON kb_articles USING GIN (tsv)")
        cur.execute("CREATE INDEX IF NOT EXISTS kb_locale ON kb_articles (locale)")
        c.commit()
    finally:
        c.close()
    _ready = True


# ---- the article's HTML as readable text ---------------------------------------------

def text_of(h):
    """Headings, list items and paragraphs on their own lines; links as their words."""
    h = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", h or "")
    h = re.sub(r"(?i)<h([1-6])[^>]*>", lambda m: "\n\n" + "#" * min(int(m.group(1)), 4) + " ", h)
    h = re.sub(r"(?i)</h[1-6]>", "\n", h)
    h = re.sub(r"(?i)<li[^>]*>", "\n- ", h)
    h = re.sub(r"(?i)<br\s*/?>", "\n", h)
    h = re.sub(r"(?i)</(p|div|ul|ol|table|tr|blockquote|pre)>", "\n", h)
    h = re.sub(r"(?i)<(td|th)[^>]*>", " | ", h)
    h = re.sub(r"(?s)<[^>]+>", "", h)
    t = _html.unescape(h).replace("\xa0", " ")
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r" *\n *", "\n", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()[:TEXT_CHARS]


# ---- download -----------------------------------------------------------------------------

def _get(path):
    for attempt in range(5):
        try:
            return zendesk.get_json(path)
        except zendesk.ZendeskError as e:
            if "429" not in str(e) or attempt == 4:
                raise
            time.sleep(30 * (attempt + 1))


def _path(url):
    base = zendesk.base_url()
    return url[len(base):] if url and url.startswith(base) else None


def locales():
    d = _get("/api/v2/help_center/locales.json")
    out = [l for l in (d.get("locales") or []) if isinstance(l, str)]
    default = d.get("default_locale") or "en-us"
    return [default] + [l for l in out if l != default]


def _sync_locale(loc, seen):
    url, pages, saved = "/api/v2/help_center/%s/articles.json?include=sections,categories&per_page=100&sort_by=updated_at" % loc, 0, 0
    sections, categories = {}, {}
    while url and pages < PAGES_MAX and not JOB["stop"]:
        d = _get(url)
        for s in d.get("sections") or []:
            sections[s.get("id")] = s
        for c in d.get("categories") or []:
            categories[c.get("id")] = c.get("name") or ""
        rows, now = [], _now()
        for a in d.get("articles") or []:
            if not a.get("id"):
                continue
            sec = sections.get(a.get("section_id")) or {}
            rows.append((int(a["id"]), loc, a.get("source_locale"), (a.get("title") or "")[:500], text_of(a.get("body")),
                         (a.get("html_url") or "")[:500], a.get("section_id"), (sec.get("name") or "")[:300],
                         (categories.get(sec.get("category_id")) or "")[:300], ", ".join(a.get("label_names") or [])[:1000],
                         int(bool(a.get("draft"))), int(a.get("user_segment_id") is not None), int(bool(a.get("promoted"))),
                         int(bool(a.get("outdated"))), int(a.get("vote_sum") or 0), int(a.get("vote_count") or 0),
                         _ms(a.get("created_at")), _ms(a.get("updated_at")), _ms(a.get("edited_at")), now))
            seen.add((int(a["id"]), loc))
        _save(rows)
        saved += len(rows)
        JOB["saved"] += len(rows)
        url = _path(d.get("next_page"))
        pages += 1
    return saved


def _save(rows):
    if not rows:
        return
    c = store.connect(True)
    try:
        cur = c.cursor()
        marks = ", ".join(["%s"] * len(COLS))
        if _pg():
            sql = "INSERT INTO kb_articles (%s) VALUES (%s) ON CONFLICT (id, locale) DO UPDATE SET %s" % (
                ", ".join(COLS), marks, ", ".join("%s = EXCLUDED.%s" % (k, k) for k in COLS[2:]))
        else:
            sql = "INSERT OR REPLACE INTO kb_articles (%s) VALUES (%s)" % (", ".join(COLS), marks)
        for r in rows:
            cur.execute(store._q(sql), r)
        c.commit()
    finally:
        c.close()


def _drop_missing(seen, done_locales):
    """Articles a whole sync didn't see any more (deleted, archived) go too."""
    have = store._read("SELECT id, locale FROM kb_articles", [], fresh=True)
    gone = [(i, l) for i, l in have if l in done_locales and (int(i), l) not in seen]
    if not gone:
        return 0
    c = store.connect(True)
    try:
        cur = c.cursor()
        for i, l in gone:
            cur.execute(store._q("DELETE FROM kb_articles WHERE id = %s AND locale = %s"), (i, l))
        c.commit()
    finally:
        c.close()
    return len(gone)


def _run():
    try:
        ensure()
        seen, done = set(), set()
        for loc in locales():
            if JOB["stop"]:
                break
            JOB["locale"] = loc
            _sync_locale(loc, seen)
            if not JOB["stop"]:
                done.add(loc)
        dropped = 0 if JOB["stop"] else _drop_missing(seen, done)
        if not JOB["stop"]:
            store.set_setting("kb_synced", str(_now()), "kb")
        _LINKS["at"] = 0
        sys.stderr.write("[kb] sync %s: %d article(s) in %d language(s)%s\n" % (
            "stopped" if JOB["stop"] else "finished", JOB["saved"], len(done), (", %d removed" % dropped) if dropped else ""))
    except zendesk.ZendeskError as e:
        JOB["error"] = str(e)[:300]
        sys.stderr.write("[kb] sync failed: %s\n" % e)
    except Exception as e:
        JOB["error"] = "internal error (%s)" % type(e).__name__
        sys.stderr.write("[kb] sync failed: %s\n" % type(e).__name__)
    finally:
        JOB.update(running=False, locale=None, finished_ms=_now())


def start():
    with _lock:
        if JOB["running"]:
            return False
        if zendesk.configured():
            JOB["error"] = "SplashHub Centre can't read Zendesk yet"
            return False
        JOB.update(running=True, saved=0, locale=None, error=None, finished_ms=None, stop=False)
    threading.Thread(target=_run, name="kb-sync", daemon=True).start()
    return True


def stop():
    JOB["stop"] = True
    return JOB["running"]


def boot():
    """Every 6 hours, once the Knowledge Base has been downloaded the first time."""
    def loop():
        while True:
            time.sleep(SYNC_EVERY)
            try:
                if store.get_setting("kb_synced", "") and not zendesk.configured():
                    start()
            except Exception as e:
                sys.stderr.write("[kb] scheduled sync skipped: %s\n" % type(e).__name__)
    threading.Thread(target=loop, name="kb-loop", daemon=True).start()


def status():
    ensure()
    n, langs, arts = store._read("SELECT count(*), count(DISTINCT locale), count(DISTINCT id) FROM kb_articles", [])[0]
    synced = store.get_setting("kb_synced", "")
    return dict(JOB, rows=int(n or 0), languages=int(langs or 0), articles=int(arts or 0),
                synced_ms=int(synced) if synced else None)


# ---- tickets that link an article (from the downloaded Zendesk tickets) ----------------

_LINKS = {"at": 0, "map": {}}


def links():
    """{article id: [(ticket id, created ms), ...]} -- tickets whose text links the
    article. Read from the tickets table at most every 10 minutes."""
    if _LINKS["map"] and time.time() - _LINKS["at"] < 600:
        return _LINKS["map"]
    out = {}
    try:
        if _pg():
            rows = store._read("SELECT ticket_id, created_ms, m[1] FROM cases, "
                               "regexp_matches(coalesce(body, '') || ' ' || coalesce(convo, ''), 'article ([0-9]{6,})', 'g') AS m",
                               [], fresh=True)
            for tid, cms, aid in rows:
                out.setdefault(int(aid), {})[int(tid)] = cms
        else:
            for tid, cms, body, convo in store._read("SELECT ticket_id, created_ms, body, convo FROM cases "
                                                     "WHERE body LIKE '%article %' OR convo LIKE '%article %'", [], fresh=True):
                for aid in set(ARTICLE_RE.findall((body or "") + " " + (convo or ""))):
                    out.setdefault(int(aid), {})[int(tid)] = cms
    except Exception:                            # no tickets downloaded yet
        out = {}
    _LINKS.update(at=time.time(), map={a: sorted(t.items(), key=lambda x: -(x[1] or 0)) for a, t in out.items()})
    return _LINKS["map"]


# ---- the Knowledge Base page ---------------------------------------------------------------

LIST_COLS = ("id", "locale", "title", "url", "section", "category", "labels", "draft", "internal", "promoted",
             "outdated", "vote_sum", "vote_count", "created_ms", "updated_ms")
SORTS = {"updated": "updated_ms DESC", "oldest": "updated_ms ASC", "votes": "vote_sum DESC, vote_count DESC",
         "unhelpful": "(vote_count - vote_sum) DESC", "title": "title ASC"}


def _votes(r):
    up = (int(r.get("vote_count") or 0) + int(r.get("vote_sum") or 0)) // 2
    down = int(r.get("vote_count") or 0) - up
    return up, down


def _card(r, lk):
    up, down = _votes(r)
    t = lk.get(int(r["id"])) or []
    return dict({k: r[k] for k in LIST_COLS}, up=up, down=down,
                helpful=round(100.0 * up / (up + down)) if up + down else None, linked=len(t))


def meta(locale=None):
    """Languages, categories and the headline numbers for the page."""
    ensure()
    langs = [dict(locale=l, n=n) for l, n in store._read(
        "SELECT locale, count(*) FROM kb_articles GROUP BY locale ORDER BY count(*) DESC", [])]
    loc = locale or (langs[0]["locale"] if langs else "en-us")
    cats = [dict(name=c, n=n) for c, n in store._read(
        "SELECT category, count(*) FROM kb_articles WHERE locale = %s GROUP BY category ORDER BY category", [loc])]
    month = _now() - 30 * 86400000
    total, recent, drafts, internal, votes = store._read(
        "SELECT count(*), sum(CASE WHEN updated_ms >= %s THEN 1 ELSE 0 END), sum(draft), sum(internal), "
        "sum(vote_count) FROM kb_articles WHERE locale = %s", [month, loc])[0]
    lk = links()
    ids = {int(r[0]) for r in store._read("SELECT id FROM kb_articles WHERE locale = %s", [loc])}
    linked = {a: t for a, t in lk.items() if a in ids}
    synced = store.get_setting("kb_synced", "")
    return {"locale": loc, "languages": langs, "categories": cats,
            "kpis": {"articles": int(total or 0), "updated_30d": int(recent or 0), "drafts": int(drafts or 0),
                     "agents_only": int(internal or 0), "votes": int(votes or 0),
                     # translations in any language that Zendesk marks outdated, and the articles they belong to
                     "outdated": int(store._read("SELECT count(*) FROM kb_articles WHERE outdated = 1", [])[0][0] or 0),
                     "outdated_articles": int(store._read("SELECT count(DISTINCT id) FROM kb_articles WHERE outdated = 1", [])[0][0] or 0),
                     "linked_articles": len(linked), "ticket_links": sum(len(t) for t in linked.values())},
            "synced_ms": int(synced) if synced else None, "tickets_ready": bool(lk) or _has_cases()}


def _has_cases():
    try:
        return bool(store._read("SELECT 1 FROM cases LIMIT 1", []))
    except Exception:
        return False


def search(q=None, locale=None, category=None, flag=None, sort=None, page=0, per_page=50):
    ensure()
    loc = locale or "en-us"
    where, args = ["locale = %s"], [loc]
    if category:
        where.append("category = %s"); args.append(category)
    if flag in ("draft", "internal", "promoted"):
        where.append("%s = 1" % flag)
    elif flag == "outdated":                  # an article with any outdated translation
        where.append("id IN (SELECT id FROM kb_articles WHERE outdated = 1)")
    q = (q or "").strip()
    rank = None
    if q:
        if re.fullmatch(r"#?\d{6,}", q):
            where.append("id = %s"); args.append(int(q.lstrip("#")))
        elif _pg():
            where.append("tsv @@ websearch_to_tsquery('simple', %s)"); args.append(q)
            rank = "ts_rank(tsv, websearch_to_tsquery('simple', %s))"
        else:
            for w in q.lower().split()[:6]:
                where.append("(lower(title) LIKE %s OR lower(body) LIKE %s OR lower(labels) LIKE %s)")
                args += ["%" + w + "%"] * 3
    lk = links()
    base = "SELECT " + ", ".join(LIST_COLS) + " FROM kb_articles WHERE " + " AND ".join(where)
    if sort == "linked":
        rows = [dict(zip(LIST_COLS, r)) for r in store._read(base, args)]
        rows.sort(key=lambda r: -len(lk.get(int(r["id"])) or []))
        total = len(rows)
        rows = rows[page * per_page:(page + 1) * per_page]
    else:
        order = SORTS.get(sort) or ("%s DESC" % rank if rank else SORTS["updated"])
        oargs = [q] if (rank and not SORTS.get(sort)) else []
        total = store._read("SELECT count(*) FROM kb_articles WHERE " + " AND ".join(where), args)[0][0]
        rows = [dict(zip(LIST_COLS, r)) for r in store._read(
            base + " ORDER BY " + order + " LIMIT %d OFFSET %d" % (per_page, page * per_page), args + oargs)]
    return {"total": int(total or 0), "page": page, "per_page": per_page, "rows": [_card(r, lk) for r in rows]}


def article(aid, locale=None):
    ensure()
    rows = store._read("SELECT " + ", ".join(COLS) + " FROM kb_articles WHERE id = %s", [int(aid)])
    if not rows:
        return None
    byloc = {r[1]: dict(zip(COLS, r)) for r in rows}
    a = byloc.get(locale) or byloc.get("en-us") or next(iter(byloc.values()))
    lk = links()
    t = lk.get(int(aid)) or []
    out = dict(_card(a, lk), body=a["body"], source_locale=a["source_locale"], edited_ms=a["edited_ms"],
               section_id=a["section_id"],
               languages=[{"locale": l, "outdated": bool(r["outdated"]), "title": r["title"], "url": r["url"],
                           "updated_ms": r["updated_ms"]} for l, r in sorted(byloc.items())],
               tickets=[{"ticket": tid, "created_ms": cms} for tid, cms in t[:25]])
    # When it was linked: per month, 2026
    per = {}
    for _, cms in t:
        if cms:
            k = time.strftime("%Y-%m", time.gmtime(cms / 1000))
            per[k] = per.get(k, 0) + 1
    out["linked_by_month"] = [{"month": k, "n": per[k]} for k in sorted(per)]
    return out


# ---- the AI page ---------------------------------------------------------------------------

def ai_search(query, locale=None, limit=6):
    """Best-matching articles for the AI: title, link, section, a short excerpt."""
    res = search(query, locale or "en-us", sort=None, per_page=max(1, min(int(limit or 6), 10)))
    out = []
    for r in res["rows"]:
        if r["draft"]:
            continue
        body = (store._read("SELECT body FROM kb_articles WHERE id = %s AND locale = %s", [r["id"], r["locale"]]) or [[""]])[0][0] or ""
        out.append({"article": r["id"], "title": r["title"], "url": r["url"], "section": r["section"], "category": r["category"],
                    "agents_only": bool(r["internal"]), "excerpt": re.sub(r"\s+", " ", body)[:600],
                    "votes_up": r["up"], "votes_down": r["down"], "linked_in_tickets": r["linked"]})
    return {"articles": out, "matching": res["total"],
            "note": "link only articles listed here; agents_only articles are for support staff, never send them to a customer"}
