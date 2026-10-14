"""My Dashboard: the signed-in person's own queue -- the same cards as SplashHub's
Dashboard in Zendesk (Workspace/assets/home.js), built here from Zendesk.

Who "me" is: the e-mail of the Microsoft sign-in (entra.py), matched to the
Zendesk agent with that e-mail. Every query is about that person's own tickets,
except "Tickets in your languages", which -- like SplashHub's -- looks at the
team's round-robin queue for the languages an admin set for them.

  stat tiles    Assigned by RR (new/open), Open, Pending, On hold, Solved this month
  RR            round-robin tickets assigned to me, new or open (newest first, 10)
  open          my open tickets (latest update first, up to 300)
  pins          my pinned tickets where the customer wrote after our last public
                reply (pins live in SplashHub's custom object splashhub_store,
                record pins:<my Zendesk id>, written by the sidebar's pin button)
  languages     the last 7 days of RR tickets whose language tag (language_ja,
                language_zh-cn ... -- from AutoTag / SplashTags) is one of mine, by
                SplashHub's routing list (record config:langroute)

Reads only. One person's dashboard is kept for a minute (Refresh skips that).
Jira cards come later (Centre has no Jira access yet).
"""
import calendar, json, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, urlencode

import zendesk

KEEP = 60
OPEN_MAX = 300
PIN_MAX = 30
LANG_TAGS = {"ja": ("language_ja",), "zh": ("language_zh-cn", "language_zh-tw", "language_zh"),
             "fr": ("language_fr",), "de": ("language_de",), "es": ("language_es",)}
LANG_NAMES = {"ja": "Japanese", "zh": "Chinese", "fr": "French", "de": "German", "es": "Spanish"}

_CACHE, _USERS = {}, {}
_LOCK = threading.Lock()


class DashError(Exception):
    """A message that is safe to show."""


def _ms(iso):
    try:
        return int(calendar.timegm(time.strptime((iso or "")[:19], "%Y-%m-%dT%H:%M:%S")) * 1000)
    except ValueError:
        return None


def agent(email):
    """The Zendesk agent with this e-mail: {id, name, email}."""
    hit = _USERS.get(email)
    if hit and time.time() - hit[0] < 3600:
        return hit[1]
    d = zendesk.get_json("/api/v2/users/search.json?query=" + quote("email:" + email))
    users = [u for u in d.get("users") or [] if (u.get("email") or "").lower() == email and u.get("role") in ("agent", "admin")]
    me = {"id": users[0]["id"], "name": users[0].get("name") or email, "email": email} if users else None
    _USERS[email] = (time.time(), me)
    return me


def _search(query, per_page=100, sort_by="updated_at", pages=1):
    rows, total, url = [], 0, "/api/v2/search.json?" + urlencode({"query": query, "per_page": per_page, "sort_by": sort_by, "sort_order": "desc"})
    for _ in range(pages):
        d = zendesk.get_json(url)
        total = d.get("count") or total
        rows += [r for r in d.get("results") or [] if r.get("result_type", "ticket") == "ticket"]
        nxt = d.get("next_page")
        if not nxt or not nxt.startswith(zendesk.base_url()):
            break
        url = nxt[len(zendesk.base_url()):]
    return rows, total


def _count(query):
    return (zendesk.get_json("/api/v2/search/count.json?query=" + quote(query)) or {}).get("count") or 0


def _row(t):
    return {"id": t.get("id"), "subject": t.get("subject") or "(no subject)", "status": t.get("status"),
            "created": _ms(t.get("created_at")), "updated": _ms(t.get("updated_at"))}


def _record(external_id):
    """A SplashHub shared record (custom object splashhub_store): its payload, or None."""
    d = zendesk.get_json("/api/v2/custom_objects/splashhub_store/records?" + urlencode({"filter[external_ids]": external_id}))
    for r in d.get("custom_object_records") or []:
        if r.get("external_id") == external_id:
            raw = (r.get("custom_object_fields") or {}).get("payload")
            try:
                return json.loads(raw) if isinstance(raw, str) else raw
            except ValueError:
                return None
    return None


def _pins(me):
    """My pinned tickets the customer is waiting on, longest wait first (SplashHub's
    awaitingInfo: newest first, customer comments add up, our public reply ends it,
    our internal notes don't count)."""
    payload = _record("pins:%s" % me["id"]) or {}
    ids = [int(p["id"]) for p in (payload.get("pins") or []) if str(p.get("id", "")).isdigit()][:PIN_MAX]
    if not ids:
        return {"pinned": 0, "waiting": []}
    tickets = (zendesk.get_json("/api/v2/tickets/show_many.json?ids=" + ",".join(map(str, ids))) or {}).get("tickets") or []
    live = [t for t in tickets if t.get("status") not in ("solved", "closed")]
    out = []

    def one(t):
        cs = (zendesk.get_json("/api/v2/tickets/%d/comments.json?sort_order=desc&per_page=30" % t["id"]) or {}).get("comments") or []
        n, since = 0, None
        for c in cs:
            if c.get("author_id") == t.get("requester_id"):
                n += 1
                since = c.get("created_at") or since
                continue
            if c.get("public", True):
                break
        return dict(_row(t), waiting=n, since=_ms(since)) if n else None
    with ThreadPoolExecutor(6) as ex:
        out = [r for r in ex.map(one, live) if r]
    out.sort(key=lambda r: r["since"] or 0)
    return {"pinned": len(live), "waiting": out}


def _languages(me):
    cfg = _record("config:langroute") or {}
    mine = next((p for p in cfg.get("people") or [] if (p.get("email") or "").strip().lower() == me["email"]), None)
    langs = [c for c in (mine or {}).get("langs") or [] if c in LANG_TAGS]
    if not langs:
        return None
    since = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 7 * 86400))
    rows, _ = _search("type:ticket status<pending tags:assigned_by_rr -tags:survey created>=" + since,
                      per_page=100, sort_by="created_at", pages=2)
    want = {tag: code for code in langs for tag in LANG_TAGS[code]}
    hits = []
    for t in rows:
        code = next((want[tag] for tag in t.get("tags") or [] if tag in want), None)
        if code:
            hits.append(dict(_row(t), lang=code, assigned=bool(t.get("assignee_id")), mine=t.get("assignee_id") == me["id"]))
    return {"langs": [LANG_NAMES[c] for c in langs], "scanned": len(rows), "tickets": hits}


def build(email, fresh=False):
    email = (email or "").strip().lower()
    with _LOCK:
        hit = _CACHE.get(email)
        if hit and not fresh and time.time() - hit[0] < KEEP:
            return hit[1]
    me = agent(email)
    if not me:
        raise DashError("There's no Zendesk agent with the e-mail %s." % email)
    a = "assignee:%s" % me["id"]
    rrq = "type:ticket status<pending tags:assigned_by_rr -tags:survey " + a
    month = time.strftime("%Y-%m-01", time.gmtime())
    tasks = {
        "rr": lambda: _search(rrq, per_page=10, sort_by="created_at"),
        "open": lambda: _search("type:ticket %s status:open" % a, per_page=100, pages=OPEN_MAX // 100),
        "pending": lambda: _count("type:ticket %s status:pending" % a),
        "hold": lambda: _count("type:ticket %s status:hold" % a),
        "solved": lambda: _count("type:ticket %s status>=solved solved>=%s" % (a, month)),
        "pins": lambda: _pins(me),
        "langs": lambda: _languages(me),
    }
    got, errors = {}, {}
    with ThreadPoolExecutor(len(tasks)) as ex:
        futs = {k: ex.submit(f) for k, f in tasks.items()}
        for k, f in futs.items():
            try:
                got[k] = f.result()
            except zendesk.ZendeskError as e:
                errors[k] = str(e)[:200]
                sys.stderr.write("[me] %s: %s\n" % (k, e))
            except Exception as e:
                errors[k] = "couldn't load (%s)" % type(e).__name__
                sys.stderr.write("[me] %s failed: %s\n" % (k, type(e).__name__))
    rr, rr_total = got.get("rr", ([], 0))
    opened, open_total = got.get("open", ([], 0))
    queries = {"rr": rrq, "open": "type:ticket %s status:open" % a, "pending": "type:ticket %s status:pending" % a,
               "hold": "type:ticket %s status:hold" % a, "solved": "type:ticket %s status>=solved solved>=%s" % (a, month)}
    out = {"me": me, "zendesk": zendesk.base_url(), "ms": int(time.time() * 1000), "errors": errors,
           "stats": {"rr": rr_total, "open": open_total, "pending": got.get("pending"), "hold": got.get("hold"),
                     "solved": got.get("solved"), "month": time.strftime("%B", time.gmtime())},
           "queries": queries, "rr": [_row(t) for t in rr], "open": [_row(t) for t in opened],
           "pins": got.get("pins"), "langs": got.get("langs")}
    with _LOCK:
        _CACHE[email] = (time.time(), out)
        if len(_CACHE) > 200:
            _CACHE.clear()
    return out
