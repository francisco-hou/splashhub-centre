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

Getting them (Settings > Database > PO Requests, admin): a Zendesk search for
"Provision Details" over all years, then an hourly search for the ones created
or updated since. Reads only -- nothing is written to Zendesk.
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
        "region", "customer_domain", "products_json", "order_json", "saved_ms")
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
    return {"order": order, "products": products}


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
            spid[:200] or None, company[:200] or None, _field(order, r"order\s*type")[:120] or None,
            _date(_field(order, r"expected\s*provision\s*date")) or None, region, dom,
            json.dumps(products), json.dumps(order), _now())


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


def start(kind="import"):
    with _lock:
        if JOB["running"]:
            return False
        if zendesk.configured():
            JOB["error"] = "SplashHub Centre can't read Zendesk yet"
            return False
        JOB.update(running=True, kind=kind, seen=0, saved=0, error=None, finished_ms=None, stop=False)
    threading.Thread(target=_run, args=(kind,), name="po-" + kind, daemon=True).start()
    return True


def stop():
    JOB["stop"] = True
    return JOB["running"]


def boot():
    """Hourly, once all of history has been imported."""
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
    n, first, last = store._read("SELECT count(*), min(created_ms), max(created_ms) FROM po_requests", [])[0]
    synced = store.get_setting("po_synced", "")
    return dict(JOB, count=int(n or 0), first_ms=first, last_ms=last, synced_ms=int(synced) if synced else None)


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
