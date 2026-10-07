"""Zendesk API client for the SOS package scan.

Reads a ticket, its full comment history and its image attachments. Writes
one thing only: an internal note with an AI review, when an agent presses
"Add as internal note" on the SOS Scans page (add_internal_note). The
token's account must be an agent who can comment on these tickets.

Settings (environment):
  ZENDESK_SUBDOMAIN   default "splashtopbusiness"
  ZENDESK_EMAIL       the account the API token belongs to
  ZENDESK_API_TOKEN   sealed secret
Outbound goes through the platform's egress proxy (urllib honours HTTPS_PROXY),
which only lets through the hosts the OUTBOUND_HTTP grant names:
<subdomain>.zendesk.com and <subdomain>.zdusercontent.com (attachment downloads).

Errors are worded here, never copied from the library: a proxy refusal quotes
the proxy URL -- which carries this app's proxy password -- in its exception
text, and these messages end up on a web page.
"""
import base64, json, os, re, urllib.error, urllib.parse, urllib.request

MAX_IMAGE_BYTES = 5 * 1024 * 1024
TIMEOUT = 30


class ZendeskError(Exception):
    """A message that is safe to show and store."""


def subdomain():
    return (os.environ.get("ZENDESK_SUBDOMAIN") or "splashtopbusiness").strip()


def base_url():
    # ZENDESK_BASE_URL is for local tests against a fake Zendesk; never set on Spluki.
    return (os.environ.get("ZENDESK_BASE_URL") or "").rstrip("/") or "https://%s.zendesk.com" % subdomain()


def configured():
    """Names of the settings still missing (empty when ready)."""
    return [n for n in ("ZENDESK_EMAIL", "ZENDESK_API_TOKEN") if not (os.environ.get(n) or "").strip()]


def _auth():
    raw = "%s/token:%s" % (os.environ.get("ZENDESK_EMAIL", "").strip(), os.environ.get("ZENDESK_API_TOKEN", "").strip())
    return "Basic " + base64.b64encode(raw.encode()).decode()


class _NoAuthAcrossHosts(urllib.request.HTTPRedirectHandler):
    """Follow redirects, but never carry the Zendesk credential to another host
    (attachment downloads redirect from zendesk.com to zdusercontent.com)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        LAST["redirect_host"] = urllib.parse.urlparse(newurl).netloc   # named if that hop fails
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and urllib.parse.urlparse(newurl).netloc != urllib.parse.urlparse(req.full_url).netloc:
            for h in ("Authorization",):
                new.headers.pop(h, None)
                new.unredirected_hdrs.pop(h, None)
        return new


_OPENER = urllib.request.build_opener(_NoAuthAcrossHosts())


UA = "SplashHubCentre/1.0 (Splashtop support tooling)"
LAST = {}      # the last response's status / final URL / type, for describing a surprise


def _open(url, auth=True, accept="application/json", limit=None, method="GET", body=None):
    host = urllib.parse.urlparse(url).netloc
    LAST.pop("redirect_host", None)
    headers = {"Accept": accept, "User-Agent": UA}
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    if auth:
        req.add_unredirected_header("Authorization", _auth())
    try:
        with _OPENER.open(req, timeout=TIMEOUT) as r:
            # read() with no argument for the whole body. NOT read(-1): on a
            # chunked reply (Zendesk's) that returns the raw stream, chunk-size
            # lines and all, so valid JSON arrives corrupted.
            data = r.read(limit + 1) if limit else r.read()
            LAST.update(status=r.status, final=r.geturl(), ctype=r.headers.get("Content-Type") or "",
                        redirected=r.geturl() != url)
            return data, (r.headers.get("Content-Type") or "")
    except urllib.error.HTTPError as e:
        hint = {401: "the API token or its email was refused",
                403: "the token's account may not %s this ticket" % ("read" if method == "GET" else "comment on"),
                404: "not found", 422: "Zendesk did not accept the update", 429: "Zendesk rate limit"}.get(e.code, "")
        raise ZendeskError("Zendesk answered HTTP %d for %s%s" % (e.code, host, (" -- " + hint) if hint else ""))
    except Exception as e:     # URLError, timeouts, proxy refusals: never str(e)
        # Name the host that was actually refused: attachment downloads are
        # redirected (to pNN.zdusercontent.com), and it is that hop that fails.
        where = LAST.get("redirect_host") or host
        raise ZendeskError("could not reach %s%s (%s) -- is it in the OUTBOUND_HTTP grant?" % (
            where, (" (redirected from %s)" % host) if where != host else "", type(e).__name__))


def describe_page(data):
    """What a non-JSON answer was, safely: status, type, where it ended up,
    its <title> and first words -- never headers, cookies or the login."""
    import re
    text = (data or b"")[:20000].decode("utf-8", "replace")
    m = re.search(r"<title[^>]*>(.*?)</title>", text, re.S | re.I)
    title = re.sub(r"\s+", " ", m.group(1)).strip()[:80] if m else ""
    first = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()[:100]
    final = urllib.parse.urlparse(LAST.get("final") or "")
    return "HTTP %s, %s, %d bytes%s%s%s" % (
        LAST.get("status"), (LAST.get("ctype") or "no type").split(";")[0], len(data or b""),
        (", redirected to " + final.netloc + final.path) if LAST.get("redirected") else "",
        (", page title \"%s\"" % title) if title else "", (", starts \"%s\"" % first) if first and not title else "")


def get_json(path):
    data, _ = _open(base_url() + path)
    try:
        return json.loads(data or b"{}")
    except ValueError:
        what = describe_page(data)
        import sys
        sys.stderr.write("[zendesk] not JSON for %s: %s\n" % (path.split("?")[0], what))
        raise ZendeskError("Zendesk returned a web page instead of data for %s (%s)" % (path.split("?")[0], what))


def ticket(ticket_id):
    """Ticket + requester + organization, in one call (sideloads)."""
    d = get_json("/api/v2/tickets/%d.json?include=users,organizations" % int(ticket_id))
    t = d.get("ticket") or {}
    users = {u.get("id"): u for u in d.get("users") or []}
    orgs = {o.get("id"): o for o in d.get("organizations") or []}
    req = users.get(t.get("requester_id")) or {}
    org = orgs.get(t.get("organization_id")) or {}
    return {"id": t.get("id"), "subject": t.get("subject") or "", "description": t.get("description") or "",
            "requester_email": req.get("email") or "", "organization": org.get("name") or "",
            "status": t.get("status") or ""}


def statuses(ticket_ids):
    """{ticket id: status} for up to 100 tickets in one call (show_many)."""
    ids = [str(int(i)) for i in ticket_ids][:100]
    if not ids:
        return {}
    d = get_json("/api/v2/tickets/show_many.json?ids=" + ",".join(ids))
    return {int(t["id"]): t.get("status") or "" for t in d.get("tickets") or [] if t.get("id")}


def comments(ticket_id, max_pages=20):
    """The complete history (the sidebar learned the hard way that a partial one
    misses attachments on long tickets)."""
    out, url = [], "/api/v2/tickets/%d/comments.json?page[size]=100" % int(ticket_id)
    while url and max_pages > 0:
        d = get_json(url)
        out.extend(d.get("comments") or [])
        nxt = (d.get("links") or {}).get("next") if (d.get("meta") or {}).get("has_more") else None
        url = nxt[len(base_url()):] if nxt and nxt.startswith(base_url()) else None
        max_pages -= 1
    return out


def search_tickets(query, max_pages=2000):
    """Every ticket a search query matches. The export endpoint pages with a
    cursor and has no 1,000-result ceiling, unlike /search.json."""
    from urllib.parse import quote
    url = "/api/v2/search/export.json?filter[type]=ticket&page[size]=100&query=" + quote(query)
    while url and max_pages > 0:
        d = get_json(url)
        for t in d.get("results") or []:
            yield t
        nxt = (d.get("links") or {}).get("next") if (d.get("meta") or {}).get("has_more") else None
        url = nxt[len(base_url()):] if nxt and nxt.startswith(base_url()) else None
        max_pages -= 1


def add_internal_note(ticket_id, text, html=False):
    """Add `text` to the ticket as an internal note (public: false) -- seen by
    agents only, never sent to the requester. Nothing else on the ticket
    changes. html=True sends it as html_body (bold, dividers, links)."""
    body = json.dumps({"ticket": {"comment": {"html_body" if html else "body": text, "public": False}}}).encode("utf-8")
    data, _ = _open(base_url() + "/api/v2/tickets/%d.json" % int(ticket_id), method="PUT", body=body)
    try:
        return json.loads(data or b"{}")
    except ValueError:
        return {}


def change_tags(ticket_id, add=(), remove=()):
    """Add and/or remove tags on a ticket -- the tags endpoint, so nothing else
    changes: no status change, no comment, nothing for an agent to submit.
    Returns the ticket's tags afterwards."""
    tags = None
    if remove:
        data, _ = _open(base_url() + "/api/v2/tickets/%d/tags.json" % int(ticket_id), method="DELETE",
                        body=json.dumps({"tags": list(remove)}).encode("utf-8"))
        tags = (json.loads(data or b"{}") or {}).get("tags")
    if add:
        data, _ = _open(base_url() + "/api/v2/tickets/%d/tags.json" % int(ticket_id), method="PUT",
                        body=json.dumps({"tags": list(add)}).encode("utf-8"))
        tags = (json.loads(data or b"{}") or {}).get("tags")
    return tags


def conversation(ticket_id, max_pages=3):
    """(ticket, [messages]) -- the ticket as Zendesk has it now, and every reply
    and internal note, oldest first: {kind: customer | agent | note, who, ms, text}."""
    import calendar, time as _t
    tid = int(ticket_id)
    t = (get_json("/api/v2/tickets/%d.json?include=users" % tid).get("ticket") or {})
    out, users, url, pages = [], {}, "/api/v2/tickets/%d/comments.json?page[size]=100&include=users" % tid, 0
    while url and pages < max_pages:
        d = get_json(url)
        pages += 1
        users.update({u.get("id"): u for u in d.get("users") or []})
        for c in d.get("comments") or []:
            u = users.get(c.get("author_id")) or {}
            kind = "note" if c.get("public") is False else (
                "customer" if c.get("author_id") == t.get("requester_id") or u.get("role") == "end-user" else "agent")
            try:
                ms = int(calendar.timegm(_t.strptime((c.get("created_at") or "")[:19], "%Y-%m-%dT%H:%M:%S")) * 1000)
            except ValueError:
                ms = None
            out.append({"kind": kind, "who": u.get("name") or u.get("email") or "", "ms": ms,
                        "text": (c.get("plain_body") or c.get("body") or "")[:8000]})
        nxt = (d.get("links") or {}).get("next") if (d.get("meta") or {}).get("has_more") else None
        url = nxt[len(base_url()):] if nxt and nxt.startswith(base_url()) else None
    t["_requester"] = (users.get(t.get("requester_id")) or {}).get("email") or ""
    return t, out


_FIELD_OPTS = {}


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def field_option(title, option):
    """(ticket field id, option value) for a field's title and one of its
    options' names -- e.g. ("Product", "Don't Know") -- found in the account's
    ticket fields (a nested option matches on its last part). Kept once found."""
    key = (_norm(title), _norm(option))
    if key in _FIELD_OPTS:
        return _FIELD_OPTS[key]
    url = "/api/v2/ticket_fields.json?page[size]=100"
    pages = 0
    while url and pages < 20:
        d = get_json(url)
        pages += 1
        for f in d.get("ticket_fields") or []:
            if key[0] not in (_norm(f.get("title")), _norm(f.get("raw_title")), _norm(f.get("title_in_portal"))):
                continue
            for o in f.get("custom_field_options") or []:
                if key[1] in (_norm((o.get("name") or "").split("::")[-1]), _norm((o.get("raw_name") or "").split("::")[-1])):
                    _FIELD_OPTS[key] = (int(f["id"]), o.get("value"))
                    return _FIELD_OPTS[key]
        nxt = (d.get("links") or {}).get("next") if (d.get("meta") or {}).get("has_more") else d.get("next_page")
        url = nxt[len(base_url()):] if nxt and nxt.startswith(base_url()) else None
    raise ZendeskError('could not find the ticket field "%s" with the option "%s"' % (title, option))


def silent_close(ticket_id, note="Silent-Close", tag="silent_close", fields=(("Product", "Don't Know"), ("Issue Type", "Other"))):
    """The Ad/Spam Filter's Silent close. 1) the silent_close tag, through the
    tags endpoint (a single-ticket update ignores additional_tags); 2) one update:
    a private note (public: false, never sent to the requester), the required
    fields (Product = Don't Know, Issue Type = Other) and status Solved. Then the
    ticket is read back: {"tag", "status", "fields": {title: ok}, "ticket"} --
    what actually stuck."""
    tid = int(ticket_id)
    want = [(t, o) + field_option(t, o) for t, o in fields]          # before any change: a missing field stops here
    change_tags(tid, add=[tag])
    body = {"ticket": {"comment": {"body": note, "public": False}, "status": "solved",
                       "custom_fields": [{"id": fid, "value": val} for _, _, fid, val in want]}}
    _open(base_url() + "/api/v2/tickets/%d.json" % tid, method="PUT", body=json.dumps(body).encode("utf-8"))
    t = (get_json("/api/v2/tickets/%d.json" % tid).get("ticket") or {})
    if tag not in (t.get("tags") or []):                              # a second try, then say what is there
        change_tags(tid, add=[tag])
        t = (get_json("/api/v2/tickets/%d.json" % tid).get("ticket") or {})
    have = {int(c.get("id")): c.get("value") for c in t.get("custom_fields") or [] if c.get("id") is not None}
    return {"tag": tag in (t.get("tags") or []), "status": t.get("status"),
            "fields": {"%s = %s" % (title, opt): have.get(fid) == val for title, opt, fid, val in want}, "ticket": t}


def download(url):
    """An attachment's bytes. Tried first without credentials, the way the
    sidebar's browser fetch does (content_url is a signed link); with them only
    if Zendesk's secure downloads demand it -- and then only on zendesk.com."""
    host = urllib.parse.urlparse(url).netloc
    test_host = urllib.parse.urlparse(base_url()).netloc if os.environ.get("ZENDESK_BASE_URL") else None
    if not (host.endswith(".zendesk.com") or host.endswith(".zdusercontent.com") or host == test_host):
        raise ZendeskError("attachment is not on a Zendesk host (%s)" % host)
    try:
        data, ctype = _open(url, auth=False, accept="*/*", limit=MAX_IMAGE_BYTES)
    except ZendeskError as e:
        if ("HTTP 401" not in str(e) and "HTTP 403" not in str(e)) or not (host.endswith(".zendesk.com") or host == test_host):
            raise
        data, ctype = _open(url, auth=True, accept="*/*", limit=MAX_IMAGE_BYTES)
    if len(data) > MAX_IMAGE_BYTES:
        raise ZendeskError("attachment larger than 5 MB -- skipped")
    return data, ctype
