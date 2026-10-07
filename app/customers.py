"""Customers: everything SplashHub Centre holds about one customer, on one page.

A customer is an e-mail domain (datamaas.com) -- or, for a generic / free
e-mail (gmail.com ...), one e-mail address, since a free domain is thousands of
unrelated people. Searching by a company name finds the domains it goes by.

From what is already here (nothing new is read from Zendesk):
  Zendesk Tickets (cases.py)  2026 tickets whose requester has that domain / address
  Provisioning requests       tickets whose first message has a "Provision Details" block
                              (as SplashHub's JP PO's page reads them) naming the customer's
                              domain, address or company -- usually raised by Splashtop staff
  SOS Scans (sos_scans)       Custom SOS packages its people created, with verdicts
  SSO Requests                SSO validation requests for that domain
Splashtop's own domain is not a customer (the wall around support agents).
"""
import hashlib, json, re, threading, time

import store
import sosscan

# The Provision Details block, as SplashHub's future.js reads it
PROVISION = re.compile(r"provision\s*details", re.I)
P_PRODUCT = re.compile(r"product\s*name\s*[:\-]\s*(.+)", re.I)
P_QTY = re.compile(r"quantity\s*[:\-]\s*([\d,]+)", re.I)
P_ORDER = re.compile(r"order\s*type\s*[:\-]\s*(.+)", re.I)
P_DATE = re.compile(r"expected\s*provision\s*date\s*[:\-]?\s*(\d{4})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{1,2})", re.I)


def _field(text, rx):
    m = rx.search(text or "")
    return re.sub(r"\s+", " ", re.sub(r"<[^>]*>", " ", m.group(1).split("\n")[0])).strip(" *-\u2013\u2014")[:120] if m else ""


def provision_of(t):
    """What a provisioning ticket orders: product, quantity, order type, expected date."""
    body = t.get("body") or ""
    m = P_DATE.search(body)
    q = P_QTY.search(body)
    return {"product": _field(body, P_PRODUCT), "quantity": int(q.group(1).replace(",", "")) if q else None,
            "order_type": _field(body, P_ORDER),
            "expected": "%s-%02d-%02d" % (m.group(1), int(m.group(2)), int(m.group(3))) if m else ""}

OPEN = ("new", "open", "pending", "hold")
OWN = re.compile(r"(^|\.)splashtop\.com$", re.I)


def _now():
    return int(time.time() * 1000)


def _rows(sql, args):
    try:
        return store._read(sql, args, fresh=True)
    except Exception:                       # a table that doesn't exist yet (e.g. tickets not downloaded)
        return []


def key_of(q):
    """(kind, value) for a search: ('email', a@b.com) for a generic address,
    ('domain', b.com) for an address or a domain, ('name', text) otherwise."""
    q = (q or "").strip().lower().strip("<>\"' ")
    m = re.fullmatch(r"[^@\s]+@([a-z0-9.-]+\.[a-z]{2,})", q)
    if m:
        return ("email", q) if m.group(1) in sosscan.FREE_EMAIL_DOMAINS else ("domain", m.group(1))
    m = re.fullmatch(r"(?:https?://)?(?:www\.)?([a-z0-9-]+(?:\.[a-z0-9-]+)+)/?.*", q)
    if m and " " not in q:
        return ("domain", m.group(1))
    return ("name", q)


def find(q, limit=12):
    """Customers matching a search: [{key, label, orgs, tickets, sos, sso, last_ms}]."""
    kind, val = key_of(q)
    if not val or len(val) < 2:
        return {"matches": []}
    if kind != "name":
        if OWN.search(val.split("@")[-1]):
            return {"matches": [], "note": "That is Splashtop's own domain, not a customer."}
        if kind == "domain" and val in sosscan.FREE_EMAIL_DOMAINS:
            return {"matches": [], "note": "%s is a free e-mail provider: search one address (name@%s) instead." % (val, val)}
        p = profile(kind + ":" + val, brief=True)
        return {"matches": [p] if p["found"] else [], "exact": True}
    # a company name: the domains it goes by, most active first
    like = "%" + val + "%"
    seen = {}
    for dom, org, ms in _rows("SELECT requester_domain, organization, max(created_ms) FROM cases WHERE lower(organization) LIKE %s "
                              "AND requester_domain IS NOT NULL GROUP BY requester_domain, organization", [like]):
        seen.setdefault(dom, [set(), 0])[0].add(org); seen[dom][1] = max(seen[dom][1], ms or 0)
    for dom, org, ms in _rows("SELECT creator_domain, organization, max(requested_ms) FROM sos_scans WHERE lower(organization) LIKE %s "
                              "AND creator_domain IS NOT NULL GROUP BY creator_domain, organization", [like]):
        seen.setdefault(dom, [set(), 0])[0].add(org); seen[dom][1] = max(seen[dom][1], ms or 0)
    for dom, org, ms in _rows("SELECT domain, organization, max(requested_ms) FROM sso_requests WHERE lower(organization) LIKE %s "
                              "AND domain IS NOT NULL GROUP BY domain, organization", [like]):
        seen.setdefault(dom, [set(), 0])[0].add(org); seen[dom][1] = max(seen[dom][1], ms or 0)
    out = []
    for dom, (orgs, ms) in sorted(seen.items(), key=lambda x: -x[1][1])[:limit]:
        if not dom or dom in sosscan.FREE_EMAIL_DOMAINS or OWN.search(dom):
            continue
        p = profile("domain:" + dom, brief=True)
        if p["found"]:
            out.append(p)
    return {"matches": out}


def _where(kind, val, email_col, domain_col):
    return ("%s = %%s" % email_col, val) if kind == "email" else ("%s = %%s" % domain_col, val)


def profile(key, brief=False):
    """Everything about one customer. key: 'domain:x.com' or 'email:a@gmail.com'."""
    kind, _, val = (key or "").partition(":")
    val = val.strip().lower()
    if kind not in ("domain", "email") or not val or OWN.search(val.split("@")[-1]):
        return {"key": key, "found": False}
    dom = val.split("@")[-1]
    now = _now()

    # ---- Zendesk tickets (2026)
    w, a = _where(kind, val, "lower(requester_email)", "requester_domain")
    t_cols = ("ticket_id", "created_ms", "updated_ms", "status", "subject", "tags", "organization", "country", "requester_email", "body")
    tickets = [dict(zip(t_cols, r)) for r in _rows(
        "SELECT " + ", ".join(t_cols) + " FROM cases WHERE " + w + " ORDER BY created_ms DESC LIMIT 400", [a])]

    # ---- provisioning requests: a Provision Details block that names this customer
    # (raised by Splashtop staff, so seldom with the customer as the requester)
    names = {val} if kind == "email" else {"@" + val, val}
    for o in {t["organization"] for t in tickets if t["organization"]}:
        if len(o) >= 4:
            names.add(o.lower())
    cond = " OR ".join(["lower(body) LIKE %s"] * len(names))
    prov_rows = [dict(zip(t_cols, r)) for r in _rows(
        "SELECT " + ", ".join(t_cols) + " FROM cases WHERE lower(body) LIKE %s AND (" + cond + ") ORDER BY created_ms DESC LIMIT 100",
        ["%provision%detail%"] + ["%" + n + "%" for n in sorted(names)])]
    prov_rows += [t for t in tickets if PROVISION.search(t["body"] or "")]
    seen_p, provisioning = set(), []
    for t in sorted(prov_rows, key=lambda t: -(t["created_ms"] or 0)):
        if t["ticket_id"] in seen_p or not PROVISION.search(t["body"] or ""):
            continue
        seen_p.add(t["ticket_id"])
        provisioning.append(dict({k: t[k] for k in ("ticket_id", "created_ms", "status", "subject")}, **provision_of(t)))
    # ...and the PO Requests list (po.py: every PO, all years, read like SplashHub's PO tool)
    try:
        import po
        for r in po.for_customer(dom if kind == "domain" else None, val if kind == "email" else None,
                                 [o for o in names if not o.startswith("@") and "." not in o]):
            if r["ticket_id"] in seen_p:
                continue
            seen_p.add(r["ticket_id"])
            first = (r["products"] or [{}])[0]
            provisioning.append({"ticket_id": r["ticket_id"], "created_ms": r["created_ms"], "status": r["status"],
                                 "subject": r["subject"], "product": first.get("name") or "",
                                 "quantity": int(re.sub(r"[^0-9]", "", str(first.get("qty") or "")) or 0) or None,
                                 "order_type": r["order_type"] or "", "expected": r["expected"] or "",
                                 "more": max(0, len(r["products"]) - 1)})
        provisioning.sort(key=lambda x: -(x["created_ms"] or 0))
    except Exception:
        pass
    tickets = [t for t in tickets if t["ticket_id"] not in seen_p]      # the box below has them

    # ---- SOS packages
    w, a = _where(kind, val, "lower(creator_email)", "creator_domain")
    s_cols = ("id", "ticket_id", "requested_ms", "status", "verdict", "creator_email", "organization", "fields_json",
              "ticket_status", "description", "source")
    sos = [dict(zip(s_cols, r)) for r in _rows(
        "SELECT " + ", ".join(s_cols) + " FROM sos_scans WHERE " + w + " ORDER BY requested_ms DESC LIMIT 200", [a])]

    # ---- SSO requests
    if kind == "email":
        sso_rows = _rows("SELECT id, ticket_id, requested_ms, domain, status, verified_ms, requester_email, organization "
                         "FROM sso_requests WHERE lower(requester_email) = %s ORDER BY requested_ms DESC LIMIT 100", [val])
    else:
        sso_rows = _rows("SELECT id, ticket_id, requested_ms, domain, status, verified_ms, requester_email, organization "
                         "FROM sso_requests WHERE domain = %s OR lower(requester_email) LIKE %s ORDER BY requested_ms DESC LIMIT 100",
                         [val, "%@" + val])
    sso = [dict(zip(("id", "ticket_id", "requested_ms", "domain", "status", "verified_ms", "requester_email", "organization"), r))
           for r in sso_rows]

    found = bool(tickets or sos or sso or provisioning)
    times = ([t["created_ms"] for t in tickets if t["created_ms"]] + [p["created_ms"] for p in provisioning if p["created_ms"]] +
             [s["requested_ms"] for s in sos] + [s["requested_ms"] for s in sso])
    orgs = {}
    for o in [t["organization"] for t in tickets] + [s["organization"] for s in sos] + [s["organization"] for s in sso]:
        if o:
            orgs[o] = orgs.get(o, 0) + 1
    base = {"key": "%s:%s" % (kind, val), "kind": kind, "label": val, "domain": dom, "found": found,
            "generic": dom in sosscan.FREE_EMAIL_DOMAINS,
            "orgs": [o for o, _ in sorted(orgs.items(), key=lambda x: -x[1])][:5],
            "tickets": len(tickets), "open": sum(1 for t in tickets if (t["status"] or "") in OPEN),
            "sos": len(sos), "flagged": sum(1 for s in sos if s["verdict"] in ("needs_review", "suspicious")),
            "sso": len(sso), "provisioning": len(provisioning),
            "first_ms": min(times) if times else None, "last_ms": max(times) if times else None}
    if brief or not found:
        return base

    # people: the addresses seen, most active first
    people = {}
    for e in [t["requester_email"] for t in tickets] + [s["creator_email"] for s in sos] + [s["requester_email"] for s in sso]:
        if e and not OWN.search(e.split("@")[-1]):
            people[e.lower()] = people.get(e.lower(), 0) + 1
    countries = {}
    for t in tickets:
        if t["country"]:
            countries[t["country"]] = countries.get(t["country"], 0) + 1
    per_month = {}
    for t in tickets:
        if t["created_ms"]:
            k = time.strftime("%Y-%m", time.gmtime(t["created_ms"] / 1000))
            per_month[k] = per_month.get(k, 0) + 1
    tags = {}
    for t in tickets:
        for g in (t["tags"] or "").split():
            tags[g] = tags.get(g, 0) + 1
    try:
        import cases
        own = {dom, dom.split(".")[0]} | {o.lower() for o in orgs}
        topics = [w for w in cases.keywords(" ".join(t["subject"] or "" for t in tickets), 14)
                  if w not in own and dom not in w][:10]
    except Exception:
        topics = []

    def pkg(s):
        f = {}
        try:
            for x in json.loads(s["fields_json"] or "[]"):
                f[(x.get("label") or "").lower()] = x.get("value")
        except ValueError:
            pass
        return {"id": s["id"], "ticket": s["ticket_id"], "requested_ms": s["requested_ms"], "verdict": s["verdict"],
                "status": s["status"], "ticket_status": s["ticket_status"], "creator": s["creator_email"],
                "name": f.get("package name") or "", "type": f.get("type") or "", "subscription": f.get("subscription") or "",
                "technicians": f.get("technician count") or ""}

    # ACP links from the newest SOS request that has them (Team info / Manage on ACP ...)
    links = []
    for s in sos:
        try:
            links = sosscan.parse_request(s["description"] or "").get("links") or []
        except Exception:
            links = []
        if links:
            break

    return dict(base,
                people=[{"email": e, "n": n} for e, n in sorted(people.items(), key=lambda x: -x[1])][:12],
                countries=[c for c, _ in sorted(countries.items(), key=lambda x: -x[1])][:3],
                per_month=[{"month": k, "n": per_month[k]} for k in sorted(per_month)],
                tags=[{"tag": g, "n": n} for g, n in sorted(tags.items(), key=lambda x: (-x[1], x[0]))[:12]],
                topics=topics,
                recent_tickets=[{k: t[k] for k in ("ticket_id", "created_ms", "status", "subject", "requester_email")} for t in tickets[:15]],
                packages=[pkg(s) for s in sos[:15]],
                provisioning_requests=provisioning[:15],
                sso_requests=sso[:10],
                links=links[:6],
                recent_30d=sum(1 for x in times if x and x >= now - 30 * 86400000))


def top(days=30, limit=12):
    """The most active customer domains lately (tickets + SOS + SSO), for the empty page."""
    since = _now() - int(days) * 86400000
    act = {}
    for dom, n in _rows("SELECT requester_domain, count(*) FROM cases WHERE created_ms >= %s AND requester_domain IS NOT NULL "
                        "GROUP BY requester_domain", [since]):
        act[dom] = act.get(dom, 0) + n
    for dom, n in _rows("SELECT creator_domain, count(*) FROM sos_scans WHERE requested_ms >= %s AND creator_domain IS NOT NULL "
                        "GROUP BY creator_domain", [since]):
        act[dom] = act.get(dom, 0) + n
    for dom, n in _rows("SELECT domain, count(*) FROM sso_requests WHERE requested_ms >= %s AND domain IS NOT NULL "
                        "GROUP BY domain", [since]):
        act[dom] = act.get(dom, 0) + n
    doms = [d for d, _ in sorted(act.items(), key=lambda x: -x[1])
            if d and d not in sosscan.FREE_EMAIL_DOMAINS and not OWN.search(d)][:limit]
    return {"days": days, "customers": [profile("domain:" + d, brief=True) for d in doms]}


# ---- the AI summary box (Spark), saved per customer until something new comes in ----------

_busy = set()
_busy_lock = threading.Lock()


def _brief(p):
    """The profile in a few lines for Spark: no addresses beyond what it needs."""
    lines = ["Customer: %s%s. Organizations: %s. Country (guess): %s. First contact %s, last %s." % (
        p["label"], " (one address on a free e-mail provider)" if p["generic"] else "", ", ".join(p["orgs"]) or "unknown",
        ", ".join(p.get("countries") or []) or "unknown",
        time.strftime("%Y-%m-%d", time.gmtime(p["first_ms"] / 1000)) if p["first_ms"] else "?",
        time.strftime("%Y-%m-%d", time.gmtime(p["last_ms"] / 1000)) if p["last_ms"] else "?")]
    lines.append("Tickets in 2026: %d (%d still open). Top tags: %s. Topic words: %s." % (
        p["tickets"], p["open"], ", ".join(t["tag"] for t in p.get("tags", [])[:8]) or "none", ", ".join(p.get("topics") or []) or "none"))
    for t in p.get("recent_tickets", [])[:12]:
        lines.append("- ticket #%s %s [%s]: %s" % (t["ticket_id"], time.strftime("%Y-%m-%d", time.gmtime((t["created_ms"] or 0) / 1000)),
                                                   t["status"], (t["subject"] or "")[:120]))
    for r in p.get("provisioning_requests", [])[:8]:
        lines.append("- provisioning #%s [%s]: %s x%s, %s, expected %s" % (r["ticket_id"], r["status"], r["product"] or "?",
                                                                         r["quantity"] or "?", r["order_type"] or "?", r["expected"] or "?"))
    for k in p.get("packages", [])[:8]:
        lines.append("- Custom SOS package %r (%s) on %s: %s" % (k["name"], k["type"] or "?",
                                                               time.strftime("%Y-%m-%d", time.gmtime(k["requested_ms"] / 1000)),
                                                               {"normal": "verified", "needs_review": "needs review",
                                                                "suspicious": "high risk"}.get(k["verdict"], "not reviewed")))
    for r in p.get("sso_requests", [])[:5]:
        lines.append("- SSO validation for %s: %s" % (r["domain"] or "?", r["status"]))
    return "\n".join(lines)


SUMMARY_PROMPT = ("You write a short briefing for Splashtop support about ONE customer, from SplashHub Centre's records "
                  "below. 3 to 5 bullets, each starting with '- ': who they are (company, country, which products if "
                  "known), what they contact support about most, what is still open or pending (open tickets, upcoming "
                  "provisioning, SSO not verified), and anything to watch (SOS packages that need review or are high risk, "
                  "many recent tickets). Facts from the records only, short, no advice, no guesses, never a support "
                  "agent's name. Mention ticket numbers as #12345.")


def summary(key, fresh=False):
    """{"points": [...], "ms": when written} -- or {"pending": True} while Spark writes it
    (in the background; the page asks again), or {"off": True} / {"error": "..."}."""
    import spark
    if not spark.available():
        return {"off": True}
    p = profile(key)
    if not p.get("found"):
        return {"error": "nothing about this customer yet"}
    sig = hashlib.sha256(("%s|%s|%s|%s|%s|%s" % (p["key"], p["tickets"], p["open"], p["sos"], p["sso"], p["last_ms"])).encode()).hexdigest()[:16]
    skey = "cust_sum:" + hashlib.sha256(p["key"].encode()).hexdigest()[:20]
    try:
        got = json.loads(store.get_setting(skey, "") or "null")
    except ValueError:
        got = None
    if got and got.get("sig") == sig and not fresh:
        return got["value"]

    def run():
        try:
            text = spark.chat(SUMMARY_PROMPT, _brief(p), max_tokens=500, log={"area": "customers"})
            pts = [l.strip()[2:].strip() for l in text.splitlines() if l.strip().startswith("- ")][:5] or [text.strip()]
            value = {"points": pts, "ms": _now()}
        except spark.SparkError as e:
            value = {"error": str(e)}
        except Exception as e:
            value = {"error": "the summary could not be written (%s)" % type(e).__name__}
        try:
            store.set_setting(skey, json.dumps({"sig": sig, "value": value}), "customers")
        finally:
            with _busy_lock:
                _busy.discard(skey)
    with _busy_lock:
        start = skey not in _busy
        _busy.add(skey)
    if start:
        threading.Thread(target=run, name="cust-summary", daemon=True).start()
    return {"pending": True, "old": got["value"] if got and not fresh else None}


def ai_profile(query):
    """For the AI page: one customer's summary (or the matches to choose from)."""
    f = find(query, limit=5)
    if not f.get("matches"):
        return {"error": f.get("note") or "no customer found for %r" % query}
    if len(f["matches"]) > 1 and not f.get("exact"):
        return {"matches": f["matches"], "note": "several customers match; say which one"}
    p = profile(f["matches"][0]["key"])
    for k in ("recent_tickets", "packages", "sso_requests"):
        p[k] = p.get(k, [])[:8]
    return p
