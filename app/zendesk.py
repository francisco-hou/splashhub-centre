"""Read-only Zendesk API client for the SOS package scan.

Reads a ticket, its full comment history and its image attachments. Never
writes: the token's account only needs to read tickets.

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
import base64, json, os, urllib.error, urllib.parse, urllib.request

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
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and urllib.parse.urlparse(newurl).netloc != urllib.parse.urlparse(req.full_url).netloc:
            for h in ("Authorization",):
                new.headers.pop(h, None)
                new.unredirected_hdrs.pop(h, None)
        return new


_OPENER = urllib.request.build_opener(_NoAuthAcrossHosts())


def _open(url, auth=True, accept="application/json", limit=None):
    host = urllib.parse.urlparse(url).netloc
    req = urllib.request.Request(url, headers={"Accept": accept})
    if auth:
        req.add_unredirected_header("Authorization", _auth())
    try:
        with _OPENER.open(req, timeout=TIMEOUT) as r:
            data = r.read(limit + 1 if limit else -1)
            return data, (r.headers.get("Content-Type") or "")
    except urllib.error.HTTPError as e:
        hint = {401: "the API token or its email was refused", 403: "the token's account may not read this ticket",
                404: "not found", 429: "Zendesk rate limit"}.get(e.code, "")
        raise ZendeskError("Zendesk answered HTTP %d for %s%s" % (e.code, host, (" -- " + hint) if hint else ""))
    except Exception as e:     # URLError, timeouts, proxy refusals: never str(e)
        raise ZendeskError("could not reach %s (%s) -- is it in the OUTBOUND_HTTP grant?" % (host, type(e).__name__))


def get_json(path):
    data, _ = _open(base_url() + path)
    try:
        return json.loads(data or b"{}")
    except ValueError:
        raise ZendeskError("Zendesk returned something that is not JSON for " + path.split("?")[0])


def ticket(ticket_id):
    """Ticket + requester + organization, in one call (sideloads)."""
    d = get_json("/api/v2/tickets/%d.json?include=users,organizations" % int(ticket_id))
    t = d.get("ticket") or {}
    users = {u.get("id"): u for u in d.get("users") or []}
    orgs = {o.get("id"): o for o in d.get("organizations") or []}
    req = users.get(t.get("requester_id")) or {}
    org = orgs.get(t.get("organization_id")) or {}
    return {"id": t.get("id"), "subject": t.get("subject") or "", "description": t.get("description") or "",
            "requester_email": req.get("email") or "", "organization": org.get("name") or ""}


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


def search_tickets(query, max_pages=50):
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
