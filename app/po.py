"""PO Requests: every Zendesk ticket that carries a "Provision Details" order --
the purchase / provisioning orders SplashHub's PO tool works on -- from all
years, kept here as a list with each order read out.

The order is read the way SplashHub's po.js parseRaw() does: the "* Key: value"
lines after "Provision Details" are the order (SPID, Order Type, Expected
Provision Date, Provision Email cc List, ...), and each "* Product Name:" after
"Provision Products" is a line item with its Quantity / Additional Quantity /
Provision Start and End Date (maintenance and handling fees left out). The
region follows the PO tool too: a "Japanese Product Name" line is JP, an
On-Prem product is On-Prem, bvinvoice@ in the cc list is EMEA, else US.

Splashtop staff addresses are not kept (the role mailboxes that set the region
are read, then dropped); the customer's are.

Kept per PO ticket: the order (above), the ticket's subject, status, tags and
dates, its first message, and the whole conversation -- every reply and internal
note, marked Customer / Support, agents' names replaced by [agent] (cases.py's
conversation(): the same wall as the Zendesk Tickets data).

Getting them (Settings > Database > PO Requests, admin): a Zendesk search for
"Provision Details" over all years (quick), then each ticket's conversation,
newest first, gently (a few per second); then an hourly search for the ones
created or updated since, whose conversations are read again. Reads only --
nothing is written to Zendesk.
"""
import json, re, sys, threading, time

import store
import zendesk

SYNC_EVERY = 3600
QUERY = 'type:ticket "Provision Details"'
STAFF = re.compile(r"[\w.+'-]+@([\w-]+\.)*splashtop\.(com|eu|co\.jp)\b", re.I)
EMAIL = re.compile(r"[\w.+'-]+@[\w-]+(?:\.[\w-]+)+")
OPEN = ("new", "open", "pending", "hold")

COLS = ("ticket_id", "created_ms", "updated_ms", "status", "subject", "spid", "company", "order_type", "expected",
        "region", "customer_domain", "products_json", "order_json", "saved_ms", "tags", "description")
DDL = """CREATE TABLE IF NOT EXISTS po_requests (
    ticket_id BIGINT PRIMARY KEY, created_ms BIGINT, updated_ms BIGINT, status TEXT, subject TEXT,
    spid TEXT, company TEXT, order_type TEXT, expected TEXT, region TEXT, customer_domain TEXT,
    products_json TEXT, order_json TEXT, saved_ms BIGINT)"""

_ready = False
_lock = threading.Lock()
JOB = {"running": False, "kind": None, "seen": 0, "saved": 0, "error": None, "finished_ms": None, "stop": False}


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
        for col in ("tags", "description", "convo", "convo_ms", "convo_turns"):   # added later: tags, first message, conversation
            if store.backend() == "postgres":
                cur.execute("ALTER TABLE po_requests ADD COLUMN IF NOT EXISTS %s %s" % (col, "BIGINT" if col.startswith("convo_") else "TEXT"))
            else:
                cur.execute("PRAGMA table_info(po_requests)")
                if col not in [r[1] for r in cur.fetchall()]:
                    cur.execute("ALTER TABLE po_requests ADD COLUMN %s %s" % (col, "BIGINT" if col.startswith("convo_") else "TEXT"))
        cur.execute("CREATE INDEX IF NOT EXISTS po_created ON po_requests (created_ms)")
        cur.execute("CREATE INDEX IF NOT EXISTS po_domain ON po_requests (customer_domain)")
        c.commit()
    finally:
        c.close()
    _ready = True


# ---- reading an order (SplashHub po.js parseRaw, in Python) ---------------------------------

def _clean(v):
    v = re.sub(r"<[^>]*>", " ", v or "")
    return re.sub(r"\s+", " ", v).strip(" *-–—")


def parse(raw):
    """{"order": {key: value}, "products": [{Product Name, Quantity, ...}]}"""
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", (raw or "").replace("\r", ""))
    pi = re.search(r"Provision Products", text, re.I)
    order_part = text[:pi.start()] if pi else text
    prod_part = text[pi.start():] if pi else ""
    dm = re.search(r"Provision Details", order_part, re.I)
    if dm:
        order_part = order_part[dm.start():]
    order = {}
    for tok in re.split(r"\s*\*\s+", order_part):
        ci = tok.find(":")
        if ci == -1 or ci > 40:
            continue
        key, val = tok[:ci].strip(), tok[ci + 1:].strip()
        if "notes" not in key.lower():
            val = val.split("\n")[0].strip()
        if key and val:
            order[key] = val[:2000]
    if re.search(r"Japanese Product Name\s*:", text, re.I):
        return {"order": order, "products": _jp_products(prod_part or text)}
    products = []
    for sec in re.split(r"\*\s*Product Name\s*:", prod_part, flags=re.I)[1:]:
        name = sec.split("\n")[0].strip()
        if not name or "maintenance" in name.lower() or "handling fee" in name.lower():
            continue
        p = {"Product Name": _clean(name)[:200]}
        for k in ("Quantity", "Additional Quantity", "Provision Start Date", "Provision End Date"):
            m = re.search(r"\*\s*" + k + r"\s*:\s*(.*)", sec, re.I)
            if m:
                p[k] = _clean(m.group(1))[:60]
        if not any(x["Product Name"] == p["Product Name"] and x.get("Quantity") == p.get("Quantity") for x in products):
            products.append(p)
    if not products and re.search(r"Product Name\s*:", prod_part or text, re.I):
        products = _jp_products(prod_part or text)            # fields without "* " bullets: read by key
    return {"order": order, "products": products}


JP_KEYS = ("Product Name", "Japanese Product Name", "License Key", "Activation Key", "Quantity", "Provision Start Date", "Provision End Date")
JP_KEY_RE = re.compile(r"(" + "|".join(re.escape(k) for k in JP_KEYS) + r")\s*:")


def _jp_products(part):
    """A JP order's products (SplashHub po.js parseRawJP): the lines are read by
    key, a key seen again starts the next product. "Product Name" falls back to
    the Japanese name. License / activation keys are not kept."""
    found = list(JP_KEY_RE.finditer(part or ""))
    items, cur = [], {}
    for i, m in enumerate(found):
        key = m.group(1)
        end = found[i + 1].start() if i + 1 < len(found) else len(part)
        val = re.split(r"\n(?:For any|Thank you|Splashtop Sales)", part[m.end():end], flags=re.I)[0].strip()
        val = val.split("\n")[0].strip().lstrip("*").strip()
        if key in cur or (key == "Product Name" and cur):
            items.append(cur)
            cur = {}
        cur[key] = val
    if cur:
        items.append(cur)
    out = []
    for it in items:
        name = _clean(it.get("Product Name") or it.get("Japanese Product Name") or "")
        if not name or "maintenance" in name.lower() or "handling fee" in name.lower() or "保守" in name:
            continue
        p = {"Product Name": name[:200]}
        if it.get("Japanese Product Name") and it.get("Product Name"):
            p["Japanese Product Name"] = _clean(it["Japanese Product Name"])[:200]
        for k in ("Quantity", "Provision Start Date", "Provision End Date"):
            if it.get(k):
                p[k] = _clean(it[k])[:60]
        if not any(x["Product Name"] == p["Product Name"] and x.get("Quantity") == p.get("Quantity") for x in out):
            out.append(p)
    return out


def order_kind(v):
    """The order type, short: Renewal, Renewal Upgrade, Upsell / Expansion, New
    Business ("Existing Business - " dropped); anything else as written."""
    s = re.sub(r"^\s*existing\s+business\s*[-\u2013\u2014:]\s*", "", _clean(v or ""), flags=re.I).strip()
    low = s.lower()
    if "renewal" in low and "upgrade" in low:
        return "Renewal Upgrade"
    if "renewal" in low:
        return "Renewal"
    if "upsell" in low or "expansion" in low:
        return "Upsell / Expansion"
    if "new business" in low or low == "new":
        return "New Business"
    return s[:1].upper() + s[1:]


def _field(order, *patterns):
    for k, v in order.items():
        if any(re.search(p, k, re.I) for p in patterns):
            return _clean(v)
    return ""


def _region(raw, order, products):
    if re.search(r"Japanese Product Name\s*:", raw or "", re.I):
        return "JP"
    if any("on-prem" in (p.get("Product Name") or "").lower() for p in products):
        return "On-Prem"
    cc = (order.get("Provision Email cc List") or "").lower()
    if "bvinvoice@splashtop.com" in cc:
        return "EMEA"
    return "US"


def _date(v):
    m = re.search(r"(\d{4})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{1,2})", v or "")
    return "%s-%02d-%02d" % (m.group(1), int(m.group(2)), int(m.group(3))) if m else ""


def row_of(t):
    """A po_requests row from a Zendesk ticket (search result), or None when its
    first message has no Provision Details block."""
    raw = t.get("description") or ""
    if not re.search(r"Provision\s*Details", raw, re.I):
        return None
    p = parse(raw)
    order, products = p["order"], p["products"]
    region = _region(raw, order, products)
    # Splashtop staff addresses out (after the region has read the cc list)
    order = {k: STAFF.sub("[splashtop]", v) for k, v in order.items()}
    spid = _field(order, r"^spid$", r"splashtop id", r"^account( email)?$")
    company = _field(order, r"company", r"organi[sz]ation", r"customer name", r"account name", r"end user")
    cust = [e.lower() for e in EMAIL.findall(" ".join([spid] + list(order.values()))) if not STAFF.search(e)]
    dom = cust[0].split("@")[-1] if cust else None
    return (int(t["id"]), _ms(t.get("created_at")), _ms(t.get("updated_at")), t.get("status"), (t.get("subject") or "")[:300],
            spid[:200] or None, company[:200] or None, order_kind(_field(order, r"order\s*type"))[:120] or None,
            _date(_field(order, r"expected\s*provision\s*date")) or None, region, dom,
            json.dumps(products), json.dumps(order), _now(), " ".join(t.get("tags") or [])[:1000] or None, _text(raw))


def _text(raw):
    """The ticket's first message as a record: Splashtop staff addresses and the
    signature block out (cases.scrub), links as their site."""
    try:
        import cases
        return cases.scrub(STAFF.sub("[splashtop]", raw or ""), 20000) or None
    except Exception:
        return STAFF.sub("[splashtop]", raw or "")[:20000] or None


def _save(rows):
    if not rows:
        return
    ensure()
    c = store.connect(True)
    try:
        cur = c.cursor()
        marks = ", ".join(["%s"] * len(COLS))
        if store.backend() == "postgres":
            sql = "INSERT INTO po_requests (%s) VALUES (%s) ON CONFLICT (ticket_id) DO UPDATE SET %s" % (
                ", ".join(COLS), marks, ", ".join("%s = EXCLUDED.%s" % (k, k) for k in COLS[1:]))
        else:
            sql = "INSERT OR REPLACE INTO po_requests (%s) VALUES (%s)" % (", ".join(COLS), marks)
        for r in rows:
            cur.execute(store._q(sql), r)
        c.commit()
    finally:
        c.close()


# ---- the jobs: all of history once, then hourly ------------------------------------------

def _run(kind):
    try:
        ensure()
        since = store.get_setting("po_synced", "")
        q = QUERY
        if kind == "update" and since:
            day = time.strftime("%Y-%m-%d", time.gmtime(int(since) / 1000 - 86400))   # Zendesk compares whole days
            q += " updated>%s" % day
        started = _now()
        batch = []
        for t in zendesk.search_tickets(q, max_pages=5000):
            if JOB["stop"]:
                break
            JOB["seen"] += 1
            r = row_of(t)
            if r:
                batch.append(r)
            if len(batch) >= 100:
                _save(batch); JOB["saved"] += len(batch); batch = []
        _save(batch); JOB["saved"] += len(batch)
        _fill_convos()
        if not JOB["stop"]:
            store.set_setting("po_synced", str(started), "po")
        sys.stderr.write("[po] %s %s: %d ticket(s) read, %d PO request(s) saved\n" % (
            kind, "stopped" if JOB["stop"] else "finished", JOB["seen"], JOB["saved"]))
    except zendesk.ZendeskError as e:
        JOB["error"] = str(e)[:300]
        sys.stderr.write("[po] %s failed: %s\n" % (kind, e))
    except Exception as e:
        JOB["error"] = "internal error (%s)" % type(e).__name__
        sys.stderr.write("[po] %s failed: %s\n" % (kind, type(e).__name__))
    finally:
        JOB.update(running=False, finished_ms=_now())


RATE = 3.0      # conversation reads per second, at most (Zendesk's limit is shared with every other app)


def _fill_convos():
    """Each PO ticket's whole conversation, newest first; a ticket updated since
    its conversation was read is read again."""
    import cases
    JOB["phase"] = "conversations"
    while not JOB["stop"]:
        ids = [r[0] for r in store._read("SELECT ticket_id FROM po_requests WHERE convo_ms IS NULL OR convo_ms < updated_ms "
                                         "ORDER BY created_ms DESC LIMIT 100", [], fresh=True)]
        if not ids:
            break
        for tid in ids:
            if JOB["stop"]:
                break
            began = time.time()
            try:
                text, turns = cases.conversation(tid)
            except zendesk.ZendeskError as e:
                if "HTTP 404" not in str(e) and "HTTP 403" not in str(e):
                    raise
                text, turns = "", 0                       # deleted or not readable: don't ask again
            c = store.connect(True)
            try:
                c.cursor().execute(store._q("UPDATE po_requests SET convo = %s, convo_ms = %s, convo_turns = %s WHERE ticket_id = %s"),
                                   [STAFF.sub("[splashtop]", text or "") or None, _now(), turns, tid])
                c.commit()
            finally:
                c.close()
            JOB["replies"] = JOB.get("replies", 0) + 1
            time.sleep(max(0.0, 1.0 / RATE - (time.time() - began)))
    JOB["phase"] = None


def start(kind="import"):
    with _lock:
        if JOB["running"]:
            return False
        if zendesk.configured():
            JOB["error"] = "SplashHub Centre can't read Zendesk yet"
            return False
        JOB.update(running=True, kind=kind, seen=0, saved=0, replies=0, phase="tickets", error=None, finished_ms=None, stop=False)
    threading.Thread(target=_run, args=(kind,), name="po-" + kind, daemon=True).start()
    return True


def stop():
    JOB["stop"] = True
    return JOB["running"]


def fix_once():
    """Orders saved before these rules: the order type made short, and JP
    orders' products read (from the saved first message, else from Zendesk)."""
    if store.get_setting("po_fix_v2", "") == "yes":
        return
    ensure()
    rows = store._read("SELECT ticket_id, order_type, region, products_json, description FROM po_requests", [], fresh=True)
    fixed = 0
    c = store.connect(True)
    try:
        cur = c.cursor()
        for tid, ot, region, pj, desc in rows:
            upd = {}
            short = order_kind(ot) if ot else ot
            if short != ot:
                upd["order_type"] = short
            if region == "JP" and (pj or "[]") in ("[]", "", "null"):
                prods = parse(desc or "")["products"] if desc else []
                if not prods and not zendesk.configured():
                    try:
                        t = zendesk.get_json("/api/v2/tickets/%d.json" % int(tid)).get("ticket") or {}
                        prods = parse(t.get("description") or "")["products"]
                        time.sleep(0.3)                     # gentle on Zendesk
                    except Exception as e:
                        sys.stderr.write("[po] JP products of #%s: %s\n" % (tid, type(e).__name__))
                if prods:
                    upd["products_json"] = json.dumps(prods)
            if upd:
                cur.execute(store._q("UPDATE po_requests SET %s WHERE ticket_id = %%s" % ", ".join(k + " = %s" for k in upd)),
                            list(upd.values()) + [int(tid)])
                fixed += 1
                if fixed % 200 == 0:
                    c.commit()
        c.commit()
    finally:
        c.close()
    store.set_setting("po_fix_v2", "yes", "po")
    sys.stderr.write("[po] order types and JP products fixed on %d order(s)\n" % fixed)


def boot():
    """Hourly, once all of history has been imported."""
    def first():
        try:
            fix_once()
        except Exception as e:
            sys.stderr.write("[po] fix skipped: %s\n" % type(e).__name__)
    threading.Thread(target=first, name="po-fix", daemon=True).start()

    def loop():
        while True:
            time.sleep(SYNC_EVERY)
            try:
                if store.get_setting("po_synced", "") and not zendesk.configured():
                    start("update")
            except Exception as e:
                sys.stderr.write("[po] hourly update skipped: %s\n" % type(e).__name__)
    threading.Thread(target=loop, name="po-loop", daemon=True).start()


def status():
    ensure()
    n, first, last, conv = store._read("SELECT count(*), min(created_ms), max(created_ms), "
                                       "sum(CASE WHEN convo_ms IS NOT NULL THEN 1 ELSE 0 END) FROM po_requests", [])[0]
    synced = store.get_setting("po_synced", "")
    return dict(JOB, count=int(n or 0), with_convo=int(conv or 0), first_ms=first, last_ms=last,
                synced_ms=int(synced) if synced else None)


# ---- the PO Requests page -------------------------------------------------------------------

LIST = ("ticket_id", "created_ms", "updated_ms", "status", "subject", "spid", "company", "order_type", "expected",
        "region", "customer_domain", "products_json")


def _card(r):
    d = dict(zip(LIST, r))
    try:
        prods = json.loads(d.pop("products_json") or "[]")
    except ValueError:
        prods = []
    d["products"] = [{"name": p.get("Product Name"), "qty": p.get("Quantity") or p.get("Additional Quantity") or ""} for p in prods][:6]
    return d


def search(q=None, status=None, region=None, when=None, year=None, page=0, per_page=50):
    ensure()
    where, args = [], []
    if status == "open":
        where.append("status IN ('new', 'open', 'pending', 'hold')")
    elif status in ("solved", "closed", "new", "open", "pending", "hold"):
        where.append("status = %s"); args.append(status)
    if region in ("US", "EMEA", "JP", "On-Prem"):
        where.append("region = %s"); args.append(region)
    today = time.strftime("%Y-%m-%d", time.gmtime())
    if when == "upcoming":
        where.append("expected >= %s"); args.append(today)
    elif when == "overdue":
        where.append("expected < %s AND status IN ('new', 'open', 'pending', 'hold')"); args.append(today)
    if year and re.fullmatch(r"\d{4}", str(year)):
        y0 = _ms("%s-01-01T00:00:00" % year); y1 = _ms("%d-01-01T00:00:00" % (int(year) + 1))
        where.append("created_ms >= %s AND created_ms < %s"); args += [y0, y1]
    q = (q or "").strip().lower()
    if q:
        if re.fullmatch(r"#?\d{3,}", q):
            where.append("ticket_id = %s"); args.append(int(q.lstrip("#")))
        else:
            for w in q.split()[:5]:
                where.append("(lower(coalesce(spid,'')) LIKE %s OR lower(coalesce(company,'')) LIKE %s OR lower(coalesce(subject,'')) "
                             "LIKE %s OR lower(coalesce(products_json,'')) LIKE %s OR lower(coalesce(customer_domain,'')) LIKE %s "
                             "OR lower(coalesce(order_type,'')) LIKE %s)")
                args += ["%" + w + "%"] * 6
    w = (" WHERE " + " AND ".join(where)) if where else ""
    total = store._read("SELECT count(*) FROM po_requests" + w, args)[0][0]
    rows = store._read("SELECT " + ", ".join(LIST) + " FROM po_requests" + w +
                       " ORDER BY created_ms DESC LIMIT %d OFFSET %d" % (per_page, page * per_page), args)
    return {"total": int(total or 0), "page": page, "per_page": per_page, "rows": [_card(r) for r in rows]}


def overview():
    ensure()
    today = time.strftime("%Y-%m-%d", time.gmtime())
    week = time.strftime("%Y-%m-%d", time.gmtime(time.time() + 7 * 86400))
    one = lambda sql, a=(): int(store._read(sql, list(a))[0][0] or 0)
    years = [{"year": y, "n": int(n)} for y, n in store._read(
        "SELECT %s AS y, count(*) FROM po_requests WHERE created_ms IS NOT NULL GROUP BY y ORDER BY y DESC" % (
            "to_char(to_timestamp(created_ms / 1000), 'YYYY')" if store.backend() == "postgres"
            else "strftime('%Y', created_ms / 1000, 'unixepoch')"), [])]
    regions = [{"region": r, "n": int(n)} for r, n in store._read(
        "SELECT region, count(*) FROM po_requests GROUP BY region ORDER BY count(*) DESC", [])]
    return {"total": one("SELECT count(*) FROM po_requests"),
            "open": one("SELECT count(*) FROM po_requests WHERE status IN ('new', 'open', 'pending', 'hold')"),
            "due_week": one("SELECT count(*) FROM po_requests WHERE expected >= %s AND expected <= %s AND status IN "
                            "('new', 'open', 'pending', 'hold')", (today, week)),
            "overdue": one("SELECT count(*) FROM po_requests WHERE expected < %s AND status IN ('new', 'open', 'pending', 'hold')", (today,)),
            "last_30d": one("SELECT count(*) FROM po_requests WHERE created_ms >= %s", (_now() - 30 * 86400000,)),
            "years": years, "regions": regions,
            "synced_ms": int(store.get_setting("po_synced", "") or 0) or None}


def get(ticket_id):
    ensure()
    rows = store._read("SELECT " + ", ".join(COLS) + " FROM po_requests WHERE ticket_id = %s", [int(ticket_id)])
    if not rows:
        return None
    d = dict(zip(COLS, rows[0]))
    cv = store._read("SELECT convo, convo_ms, convo_turns FROM po_requests WHERE ticket_id = %s", [int(ticket_id)])
    d["convo"], d["convo_ms"], d["convo_turns"] = cv[0] if cv else (None, None, None)
    for k in ("products_json", "order_json"):
        try:
            d[k[:-5]] = json.loads(d.pop(k) or ("[]" if k == "products_json" else "{}"))
        except ValueError:
            d[k[:-5]] = [] if k == "products_json" else {}
    return d


def for_customer(domain=None, email=None, names=()):
    """The PO requests that name a customer -- for the Customers page."""
    ensure()
    cond, args = [], []
    if email:
        cond.append("lower(coalesce(spid,'')) = %s OR lower(coalesce(order_json,'')) LIKE %s"); args += [email, "%" + email + "%"]
    if domain:
        cond.append("customer_domain = %s OR lower(coalesce(order_json,'')) LIKE %s"); args += [domain, "%@" + domain + "%"]
    for n in names:
        if n and len(n) >= 4:
            cond.append("lower(coalesce(company,'')) LIKE %s"); args.append("%" + n.lower() + "%")
    if not cond:
        return []
    rows = store._read("SELECT " + ", ".join(LIST) + " FROM po_requests WHERE " + " OR ".join("(%s)" % c for c in cond) +
                       " ORDER BY created_ms DESC LIMIT 100", args)
    return [_card(r) for r in rows]
