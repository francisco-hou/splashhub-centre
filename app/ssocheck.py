"""SSO method validation requests -- the SSO Requests page.

A customer asks to validate an SSO method; the ticket ("Here comes a new
request to validate SSO method ...") gives the domain and the DNS TXT record
they must add to prove they own it. SplashHub Centre lists these requests,
reads the domain and the TXT value out of the ticket, and -- when an agent
presses Check DNS (one request, or every request still waiting) -- looks the
record up and says whether it is there yet. An agent can then add the result
to the ticket as an internal note. Everything is manual for now.

How requests are found -- the way the team really handles them (SplashHub's
SSO tool, Workspace/assets/sso.js): the customer asks in their own words; the
agent creates the records in the sidebar and sends them in a reply -- a TXT
record on splashtop-sso-challenge.<domain> (or -MM-DD-YYYY. / -YYYYMMDD.<domain>)
with a 32-character value -- and SplashHub's Insert Reply tags the ticket
single_sign-on__sso_ (+ enterprise). So every 15 minutes a Zendesk search finds
tickets with that tag, or with "splashtop-sso-challenge" in them, or with the old
form's subject; each one's whole conversation is read the way sso.js reads it
(HOST / Value blocks, hosts paired with the value after them), every domain on
the ticket kept. "Import past SSO requests" does the same for all of 2026, and
the webhook (feed.py: kind=sso or the form's subject) still works.

Checks: every hour, each request with its records and an open ticket is looked
up by itself (all of its records); Check DNS on the page does it at once. A
request is verified when every record carries its value. Reads only -- adding
the result to the ticket stays the page's button.

DNS: a small TXT lookup of our own (dns_txt), asking the resolver the
container already uses -- no extra dependency, no extra network grant.
"""
import json, os, random, re, socket, struct, sys, threading, time

import store
import zendesk
import sosscan          # the [Label] parser and the ScanError type, shared

SSO_SUBJECT = "Here comes a new request to validate SSO method"


def _now():
    return int(time.time() * 1000)


# ---- reading the request ------------------------------------------------------------------
# The ticket's first message. "[Label] value" lines when the form writes them
# (as SOS packages do); otherwise the domain and the TXT value are found in
# the text. Whatever is found can be corrected by hand on the page.

DOMAIN_RE = re.compile(r"\b((?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24})\b", re.I)
# a verification token: name=value, e.g. "splashtop-domain-verification=3f9c..."
TOKEN_RE = re.compile(r"\b([a-z0-9][a-z0-9._-]{2,63}=[A-Za-z0-9+/_.:-]{6,})")
OUR_HOSTS = ("splashtop.com", "splashtop.eu", "zendesk.com", "zdusercontent.com", "my-mail.splashtop.com")


def _ours(d):
    d = d.lower()
    return any(d == h or d.endswith("." + h) for h in OUR_HOSTS)


SSO_TAG = "single_sign-on__sso_"
# Host formats: splashtop-sso-challenge.<domain> | -05-13-2026.<domain> | -20260520.<domain>
HOST_RE = re.compile(r"(?:https?://)?(splashtop-sso-challenge(?:\.[a-z0-9][a-z0-9._-]*|-(?:\d{2}-\d{2}-\d{4}|\d{8})\.[a-z0-9][a-z0-9._-]*))", re.I)
VALUE_RE = re.compile(r"Value\s*:?\s*[\"']?([a-z0-9]{32})\b", re.I)
BARE_RE = re.compile(r"^([a-z0-9]{32})$", re.I)


def _host(raw):
    h = re.sub(r"^https?://", "", str(raw or ""), flags=re.I).replace("\u00a0", " ").strip().lower()
    return re.sub(r"[.,;:!?)>\]/]+$", "", h)


def _is_host(h):
    return bool(re.match(r"^splashtop-sso-challenge(?:\.|-(?:\d{2}-\d{2}-\d{4}|\d{8})\.)", h or "", re.I))


def base_domain(host):
    """The customer's domain from a challenge host (all three formats)."""
    m = re.match(r"^splashtop-sso-challenge(?:-\d{2}-\d{2}-\d{4}|-\d{8})?\.(.+)$", host or "", re.I)
    return m.group(1) if m else host


def _pick(fragment):
    m = HOST_RE.search(str(fragment or "").replace("\u00a0", " "))
    return _host(m.group(1)) if m else None


def _plain(raw):
    """A comment's HTML / markdown as lines of text (sso.js ticketContentToPlain)."""
    import html as _html
    t = _html.unescape(str(raw or ""))
    t = re.sub(r"\[([^\]]*)\]\(([^)]+)\)", lambda m: _pick(m.group(1)) or _pick(m.group(2)) or m.group(1).strip() or m.group(2).strip(), t)
    t = re.sub(r"<a\b[^>]*href\s*=\s*[\"']([^\"']+)[\"'][^>]*>([\s\S]*?)</a>",
               lambda m: _pick(m.group(1)) or _pick(re.sub(r"<[^>]+>", " ", m.group(2))) or re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(2))).strip() or m.group(1).strip(),
               t, flags=re.I)
    t = re.sub(r"<br\s*/?>|</p>|</div>|</li>", "\n", t, flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t).replace("**", "").replace("\u00a0", " ")
    t = re.sub(r"[ \t]+\n", "\n", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def _value_after(lines, i, text, host):
    m = VALUE_RE.search(lines[i])
    if m:
        return m.group(1).lower()
    for line in lines[i + 1:i + 7]:
        m = VALUE_RE.search(line) or BARE_RE.match(line.strip())
        if m:
            return m.group(1).lower()
    at = text.lower().find(host.lower())
    if at >= 0:
        m = VALUE_RE.search(text[at:at + 800])
        if m:
            return m.group(1).lower()
    return ""


def records_in(texts):
    """[{host, domain, value}] -- every challenge record in these comments
    (sso.js parseChallengeRecordsFromTicket: HOST/Value blocks, then every
    host paired with the value after it; a host seen twice keeps a value)."""
    import html as _html
    out = {}
    for raw in texts:
        raw = str(raw or "")
        if "splashtop-sso-challenge" not in raw.lower():
            continue
        for text in {raw, _html.unescape(raw), _plain(raw)}:
            lines = text.split("\n")
            for i, line in enumerate(lines):
                hm = re.search(r"HOST\s*:?\s*(.+)", line, re.I)
                cands = [_pick(hm.group(1))] if hm else []
                cands += [_host(m.group(1)) for m in HOST_RE.finditer(line)]
                for h in cands:
                    if not h or not _is_host(h):
                        continue
                    v = _value_after(lines, i, text, h)
                    r = out.setdefault(h, {"host": h, "domain": base_domain(h), "value": ""})
                    if v and not r["value"]:
                        r["value"] = v
    return list(out.values())


def parse(text):
    """{domain, txt_name, txt_value, fields, note}: what the ticket says. Empty
    strings where it could not tell -- the page asks for them then."""
    text = text or ""
    fields = sosscan.parse_request(text)["fields"]
    lab = {f["label"].lower(): (f["value"] or "").strip() for f in fields}
    domain = value = name = ""
    for k, v in lab.items():
        if not domain and "domain" in k and DOMAIN_RE.search(v):
            domain = DOMAIN_RE.search(v).group(1)
        if not value and re.search(r"txt|verif|token|record value|^value$", k) and v:
            value = v.strip().strip('"')
        if not name and re.search(r"host|record name|^name$", k) and v:
            name = v.strip()
    lines = text.splitlines()
    if not value:
        for ln in lines:                         # "TXT ... value" on one line
            if re.search(r"\btxt\b", ln, re.I):
                m = TOKEN_RE.search(ln) or re.search(r'"([^"]{8,})"', ln)
                if m:
                    value = m.group(1)
                    break
    if not value:
        m = TOKEN_RE.search(text)
        if m:
            value = m.group(1)
    if not domain:
        for ln in lines:                         # a line that talks about the domain
            if re.search(r"domain", ln, re.I):
                for m in DOMAIN_RE.finditer(ln):
                    if not _ours(m.group(1)) and "@" not in ln[max(0, m.start() - 1):m.start()]:
                        domain = m.group(1)
                        break
            if domain:
                break
    if domain and name and not name.lower().rstrip(".").endswith(domain.lower()):
        name = name.rstrip(".") + "." + domain          # "_splashtop" -> "_splashtop.example.com"
    note = "" if domain and value else ("Could not find the %s in the ticket -- add %s below." % (
        " and ".join(x for x, ok in (("domain", domain), ("TXT value", value)) if not ok),
        "it" if bool(domain) != bool(value) else "them"))
    return {"domain": domain.lower(), "txt_name": (name or domain).lower(), "txt_value": value,
            "fields": fields, "note": note}


# ---- DNS: TXT records ---------------------------------------------------------------------

def _resolvers():
    """The resolver this container already uses (/etc/resolv.conf); public
    ones only when there is none (a laptop, for local testing)."""
    out = []
    try:
        for ln in open("/etc/resolv.conf", encoding="utf-8"):
            p = ln.split()
            if len(p) >= 2 and p[0] == "nameserver":
                out.append(p[1])
    except OSError:
        pass
    env = (os.environ.get("DNS_RESOLVERS") or "").replace(",", " ").split()
    return env or out or ["1.1.1.1", "8.8.8.8"]


def _query(name):
    qid = random.randint(0, 0xFFFF)
    q = b"".join(bytes([len(p)]) + p.encode("idna") for p in name.rstrip(".").split(".")) + b"\0"
    return qid, struct.pack(">HHHHHH", qid, 0x0100, 1, 0, 0, 0) + q + struct.pack(">HH", 16, 1)   # TXT, IN


def _skip_name(msg, i):
    while True:
        n = msg[i]
        if n == 0:
            return i + 1
        if n & 0xC0 == 0xC0:
            return i + 2
        i += n + 1


def _parse_txt(msg, qid):
    rid, flags, qd, an = struct.unpack(">HHHH", msg[:8])
    if rid != qid:
        raise DnsError("a mismatched answer")
    rcode = flags & 0xF
    if rcode == 3:
        return None                                   # NXDOMAIN: the name does not exist
    if rcode:
        raise DnsError("the DNS server answered with error %d" % rcode)
    i = 12
    for _ in range(qd):
        i = _skip_name(msg, i) + 4
    out = []
    for _ in range(an):
        i = _skip_name(msg, i)
        typ, _cls, _ttl, ln = struct.unpack(">HHIH", msg[i:i + 10])
        i += 10
        if typ == 16:
            j, parts = i, []
            while j < i + ln:
                n = msg[j]
                parts.append(msg[j + 1:j + 1 + n].decode("utf-8", "replace"))
                j += n + 1
            out.append("".join(parts))
        i += ln
    return out


class DnsError(Exception):
    pass


def dns_txt(name, timeout=4.0):
    """The TXT records on `name` (a list, maybe empty), or None if the name
    does not exist. Raises DnsError when no resolver answers."""
    last = "no DNS server answered"
    for server in _resolvers():
        qid, q = _query(name)
        try:
            with socket.socket(socket.AF_INET6 if ":" in server else socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.settimeout(timeout)
                s.sendto(q, (server, 53))
                msg = s.recv(4096)
            if struct.unpack(">H", msg[2:4])[0] & 0x0200:          # truncated: ask again over TCP
                with socket.create_connection((server, 53), timeout=timeout) as t:
                    t.sendall(struct.pack(">H", len(q)) + q)
                    ln = struct.unpack(">H", t.recv(2))[0]
                    msg = b""
                    while len(msg) < ln:
                        chunk = t.recv(ln - len(msg))
                        if not chunk:
                            break
                        msg += chunk
            return _parse_txt(msg, qid)
        except DnsError as e:
            last = str(e)
        except (OSError, struct.error, IndexError):
            last = "the DNS server did not answer"
    raise DnsError(last)


# ---- one check ----------------------------------------------------------------------------

def _norm(v):
    return re.sub(r"\s+", "", (v or "").strip().strip('"')).lower()


def _look(name, want):
    """One record: {host, value, exists, records, found} or {host, value, error}."""
    out = {"host": name, "value": want}
    try:
        recs = dns_txt(name)
        out["exists"] = recs is not None
        out["records"] = recs or []
        out["found"] = bool(want) and any(_norm(want) == _norm(r) or _norm(want) in _norm(r) for r in recs or [])
    except DnsError as e:
        out["error"] = str(e)
    return out


def check(sso_id, by="Centre admin"):
    """Look the TXT record(s) up now; record and return the result. A ticket
    with several challenge records is verified when every one carries its value."""
    row = store.sso_get(sso_id, fresh=True)
    if not row:
        raise sosscan.ScanError("That request is gone.")
    name, want = (row.get("txt_name") or row.get("domain") or "").strip(), (row.get("txt_value") or "").strip()
    if not name:
        raise sosscan.ScanError("Add the domain first.")
    try:
        recs_saved = json.loads(row.get("records_json") or "[]") or []
    except ValueError:
        recs_saved = []
    extra = [r for r in recs_saved if r.get("host") and r["host"] != name]
    first = _look(name, want)
    res = dict(first, ms=_now(), name=name, expected=want, by=by)
    res.pop("host", None); res.pop("value", None)
    if extra:
        alls = [dict(first, domain=row.get("domain"))] + [dict(_look(r["host"], r.get("value") or ""), domain=r.get("domain")) for r in extra]
        res["all"] = [{k: a.get(k) for k in ("host", "domain", "value", "exists", "found", "error")} for a in alls]
        with_value = [a for a in alls if a.get("value")]
        res["found"] = bool(with_value) and all(a.get("found") for a in with_value)
        if all(a.get("error") for a in alls):
            res["error"] = alls[0]["error"]
        else:
            res.pop("error", None)
        for r in recs_saved:                                  # each record's own last result, for the page
            hit = next((a for a in alls if a["host"] == r.get("host")), None)
            if hit:
                r.update(found=hit.get("found"), exists=hit.get("exists"), error=hit.get("error"), checked_ms=res["ms"])
    if res.get("error"):
        status = "error"
    else:
        status = "verified" if res.get("found") else ("not_found" if want else "needs_details")
    if row.get("status") == "enabled":                    # the SSO method is on: a DNS check doesn't undo that
        status = "enabled"
    hist = json.loads(row.get("history_json") or "[]")
    hist = ([{k: res.get(k) for k in ("ms", "found", "error", "by")}] + hist)[:20]
    upd = dict(status=status, last_checked_ms=res["ms"], last_result_json=json.dumps(res), history_json=json.dumps(hist),
               checks=(row.get("checks") or 0) + 1)
    if extra:
        upd["records_json"] = json.dumps(recs_saved)
    newly = res.get("found") and not row.get("verified_ms")
    if newly:
        upd["verified_ms"] = res["ms"]
    store.sso_update(sso_id, **upd)
    if newly:                                             # Teams, when that's switched on (notify.py)
        try:
            import notify
            notify.sso_verified(sso_id, row["ticket_id"], row.get("domain") or name)
        except Exception as e:
            sys.stderr.write("[notify] sso card skipped: %s\n" % type(e).__name__)
    sys.stderr.write("[sso] #%s %s: %s\n" % (row["ticket_id"], name, status))
    return res


CHECK_ALL = {"running": False, "found": 0, "done": 0, "verified": 0, "error": None, "started_ms": None, "finished_ms": None}
_lock = threading.Lock()


def check_all_status():
    return dict(CHECK_ALL)


def _run_check_all():
    try:
        todo = store.sso_waiting_ids()
        CHECK_ALL["found"] = len(todo)
        for sid in todo:
            if CHECK_ALL.get("stop"):
                break
            try:
                if check(sid, "Check all").get("found"):
                    CHECK_ALL["verified"] += 1
            except sosscan.ScanError:
                pass
            CHECK_ALL["done"] += 1
            time.sleep(0.2)                       # gentle on the resolver
    except Exception as e:
        CHECK_ALL["error"] = "internal error (%s) -- see the app log" % type(e).__name__
        sys.stderr.write("[sso] check all failed: %s\n" % type(e).__name__)
    finally:
        CHECK_ALL["running"] = False
        CHECK_ALL["finished_ms"] = _now()


def start_check_all():
    """'Check all waiting': every request with a domain that is not verified yet."""
    with _lock:
        if CHECK_ALL["running"]:
            return False
        CHECK_ALL.update(running=True, stop=False, found=0, done=0, verified=0, error=None, started_ms=_now(), finished_ms=None)
    threading.Thread(target=_run_check_all, name="sso-check-all", daemon=True).start()
    return True


# ---- arriving: the trigger, and the import -------------------------------------------------

def is_sso(subject):
    return str(subject or "").strip().startswith(SSO_SUBJECT)


def _fill(sso_id, subject, description, requester="", organization=""):
    p = parse(description)
    store.sso_update(sso_id, subject=(subject or "")[:300] or None, description=(description or "")[:20000] or None,
                     requester_email=requester or None, organization=organization or None,
                     domain=p["domain"] or None, txt_name=p["txt_name"] or None, txt_value=p["txt_value"] or None,
                     status="pending" if p["domain"] and p["txt_value"] else "needs_details")


def read_ticket(sso_id, ticket_id, t=None):
    """The whole ticket: its first message, requester, status, and every
    splashtop-sso-challenge record anywhere in the conversation. The first
    record fills the request's domain / TXT host / value (the page's fields);
    all of them are kept in records_json."""
    d = zendesk.get_json("/api/v2/tickets/%d.json?include=users,organizations" % int(ticket_id))
    t = d.get("ticket") or t or {}
    users = {u.get("id"): u for u in d.get("users") or []}
    orgs = {o.get("id"): o for o in d.get("organizations") or []}
    comments = zendesk.comments(int(ticket_id), max_pages=5)
    texts = [x for c in comments for x in (c.get("html_body"), c.get("body"), c.get("plain_body")) if x] + [t.get("description") or ""]
    recs = records_in(texts)
    row = store.sso_get(sso_id, fresh=True) or {}
    stage_upd, says_done = _stage(t, comments, recs, row)
    rel_upd = _relevance(t, comments, recs, row)
    upd = dict(subject=(t.get("subject") or "")[:300] or None, description=(t.get("description") or "")[:20000] or None,
               requester_email=(users.get(t.get("requester_id")) or {}).get("email") or row.get("requester_email"),
               organization=(orgs.get(t.get("organization_id")) or {}).get("name") or row.get("organization"),
               ticket_status=t.get("status"), ticket_updated=t.get("updated_at"))
    if recs:
        try:
            old = {r.get("host"): r for r in json.loads(row.get("records_json") or "[]") or []}
        except ValueError:
            old = {}
        for r in recs:                                      # keep each record's last check
            r.update({k: v for k, v in (old.get(r["host"]) or {}).items() if k in ("found", "exists", "error", "checked_ms")})
        main = next((r for r in recs if r["value"]), recs[0])
        upd.update(records_json=json.dumps(recs), domain=main["domain"], txt_name=main["host"], txt_value=main["value"] or None,
                   parse_note="%d challenge record%s in the ticket (%s)" % (len(recs), "" if len(recs) == 1 else "s",
                                                                          ", ".join(r["domain"] for r in recs)))
        if not row.get("status") or row.get("status") == "needs_details":
            upd["status"] = "pending" if main["value"] else "needs_details"
    elif not row.get("txt_value"):
        p = parse(t.get("description") or "")              # the old form's request, if that's what it is
        if p["domain"] and p["txt_value"]:
            upd.update(domain=p["domain"], txt_name=p["txt_name"] or p["domain"], txt_value=p["txt_value"], status="pending")
        else:
            upd.update(status="needs_details", parse_note="No splashtop-sso-challenge record in the ticket yet -- "
                       "the records go out in the agent's reply (SplashHub's SSO tool).")
    upd.update(stage_upd)
    upd.update(rel_upd)
    if (rel_upd.get("relevance") or row.get("relevance")) == "not_sso":
        says_done = False                               # not an SSO request: no DNS look-ups
    if (stage_upd.get("stage") or row.get("stage")) == "enabled":
        upd["status"] = "enabled"                       # the agent's verified & enabled reply: done
    store.sso_update(sso_id, **upd)
    if says_done and (not row.get("last_checked_ms") or _now() - row["last_checked_ms"] > 300000) and (upd.get("txt_value") or row.get("txt_value")):
        try:                                               # the customer says it's added: look now, not in an hour
            check(sso_id, "Customer says it's added")
        except Exception as e:
            sys.stderr.write("[sso] check after the customer's reply: %s\n" % type(e).__name__)
    return recs


# ---- where it stands: plain rules for the facts, Spark only for the customer's latest reply -----------

def _relevance(t, comments, recs, row):
    """Is this really an SSO request? A challenge record or the old form's
    subject: yes, by rule. Only the tag (it lands on tickets that merely mention
    SSO): Spark reads the subject and the first messages, once. A person's
    choice on the page is never overridden -- except by a record turning up."""
    if recs or is_sso(t.get("subject")):
        if row.get("relevance") == "sso" and row.get("relevance_by") in ("rule", "person"):
            return {}
        return dict(relevance="sso", relevance_by="rule",
                    relevance_note="DNS challenge records in the ticket" if recs else "The SSO validation form")
    if row.get("relevance_by") == "person" or (row.get("relevance") and row.get("relevance_by") == "spark"):
        return {}                                        # decided already
    try:
        import spark
        if not spark.available():
            return {}                                    # stays on the list; asked when Spark is there
        req = t.get("requester_id")
        first = " ".join(_text(c) for c in comments[:3])[:1800]
        system = ("A support ticket was picked up as a possible SSO (single sign-on) request because of its tag. Decide if it "
                  "really is a request to set up SSO for the customer's team -- enabling an SSO method (Azure AD / Entra, "
                  "Okta, Google...), verifying their domain with a DNS TXT record -- or the follow-up of one. Answer with JSON "
                  'only: {"sso": true or false, "why": "<at most 10 words>"}. false: anything else, e.g. one user who cannot '
                  "sign in, billing, a licence, or a different problem that only mentions SSO.")
        raw = spark.chat(system, "Subject: %s\n\n%s" % ((t.get("subject") or "")[:200], first), max_tokens=150)
        got = json.loads(raw[raw.find("{"):raw.rfind("}") + 1] or "{}")
    except Exception as e:
        sys.stderr.write("[sso] Spark relevance skipped: %s\n" % type(e).__name__)
        return {}
    yes = got.get("sso") in (True, "true", "yes")
    return dict(relevance="sso" if yes else "not_sso", relevance_by="spark", relevance_note=str(got.get("why") or "")[:120] or None)


def set_relevance(sso_id, is_sso_request):
    """The page's buttons: Not an SSO request / It is an SSO request -- kept over Spark's reading."""
    row = store.sso_get(sso_id, fresh=True)
    if not row:
        raise sosscan.ScanError("That request is gone.")
    store.sso_update(sso_id, relevance="sso" if is_sso_request else "not_sso", relevance_by="person",
                     relevance_note="Marked on the SSO page")
    return store.sso_get(sso_id, fresh=True)


STAGES = ("enabled", "no_records", "sent", "says_done", "stuck", "waiting", "replied")
# SplashHub's "verified & enabled" reply: "We have verified the DNS record(s) and enabled the SSO method."
VERIFIED_RE = re.compile(r"verified the dns\b")
ENABLED_RE = re.compile(r"enabled the sso method|sso method (?:has been|is now) enabled")


def _text(c):
    return _plain(c.get("html_body") or c.get("body") or c.get("plain_body") or "")


def _ask_stage(reply):
    """Spark reads the customer's latest reply: (stage, short note)."""
    import spark
    system = ("A support ticket about verifying a domain for single sign-on (SSO). The agent sent DNS TXT records for the "
              "customer to add. Read the CUSTOMER's latest reply and answer with JSON only: "
              '{"stage": "says_done|stuck|waiting|replied", "note": "<at most 10 words>"}. '
              "says_done: they say the record is added, or ask us to check / verify now. stuck: a problem, an error, or a "
              "question about adding it. waiting: they need time, or someone else (their IT, DNS provider, manager) is doing it. "
              "replied: anything else. Ignore signatures and quoted earlier messages.")
    raw = spark.chat(system, reply[:1500], max_tokens=200)
    got = json.loads(raw[raw.find("{"):raw.rfind("}") + 1] or "{}")
    st = str(got.get("stage") or "").strip().lower()
    return (st if st in ("says_done", "stuck", "waiting", "replied") else "replied"), str(got.get("note") or "")[:120]


def _stage(t, comments, recs, row):
    """({stage, stage_note, stage_ms, stage_for}, says_done now?) -- the
    verified-and-enabled reply and the records are spotted by rule; only a
    customer reply after the records goes to Spark, once per reply."""
    req = t.get("requester_id")
    pub = [c for c in comments if c.get("public", True)]
    agent_text = " ".join(_text(c).lower() for c in pub if c.get("author_id") != req)
    if VERIFIED_RE.search(agent_text) and ENABLED_RE.search(agent_text):
        return dict(stage="enabled", stage_note="The agent sent the verified & enabled reply", stage_ms=_now(), stage_for=None), False
    if not recs:
        return dict(stage="no_records", stage_note="The agent hasn't sent the DNS records yet", stage_ms=_now(), stage_for=None), False
    sent = next((i for i, c in enumerate(pub) if "splashtop-sso-challenge" in (str(c.get("html_body") or "") + str(c.get("body") or "")).lower()), None)
    last = pub[-1] if pub else None
    if last is None or sent is None or len(pub) - 1 <= sent or last.get("author_id") != req:
        return dict(stage="sent", stage_note="Waiting for the customer to add the DNS record", stage_ms=_now(), stage_for=None), False
    key = str(last.get("id") or len(pub))
    if row.get("stage_for") == key and row.get("stage"):     # this reply was read already
        return {}, False
    try:
        import spark
        if not spark.available():
            raise RuntimeError("Spark isn't set up")
        st, note = _ask_stage(_text(last))
    except Exception as e:                                  # no Spark: say so plainly; asked again on the next update
        sys.stderr.write("[sso] Spark stage skipped: %s\n" % type(e).__name__)
        return dict(stage="replied", stage_note="The customer replied", stage_ms=_now(), stage_for=None), False
    return dict(stage=st, stage_note=note or None, stage_ms=_now(), stage_for=key), st == "says_done"


def _fetch(sso_id, ticket_id):
    """Read the ticket from Zendesk (the trigger sends only its start)."""
    try:
        read_ticket(sso_id, ticket_id)
    except zendesk.ZendeskError as e:
        store.sso_update(sso_id, parse_note="Could not read the ticket yet: %s" % e)


def request(ticket_id, source, data=None):
    """A request from the Zendesk trigger (or 'Add a ticket'). One row per
    ticket: a second trigger for the same ticket refreshes it."""
    data = data or {}
    sid = store.sso_upsert(int(ticket_id), source, _now())
    if data.get("description"):
        _fill(sid, data.get("subject"), data.get("description"), data.get("requester"))
    if not zendesk.configured():                          # then the whole conversation (the records are in replies)
        threading.Thread(target=_fetch, args=(sid, int(ticket_id)), daemon=True).start()
    return sid


def set_details(sso_id, domain=None, txt_name=None, txt_value=None):
    """The page's corrections, when the ticket did not say it plainly."""
    upd = {}
    if domain is not None:
        d = domain.strip().lower().rstrip(".")
        if d and not DOMAIN_RE.fullmatch(d):
            raise sosscan.ScanError("That doesn't look like a domain.")
        upd["domain"] = d or None
    if txt_name is not None:
        upd["txt_name"] = txt_name.strip().lower().rstrip(".") or None
    if txt_value is not None:
        upd["txt_value"] = txt_value.strip().strip('"') or None
    row = store.sso_get(sso_id, fresh=True) or {}
    row.update(upd)
    if not row.get("txt_name") and row.get("domain"):
        upd["txt_name"] = row["domain"]
    upd["status"] = "pending" if (row.get("domain") and row.get("txt_value") and row.get("status") in (None, "needs_details", "pending")) \
        else (row.get("status") if row.get("domain") and row.get("txt_value") else "needs_details")
    store.sso_update(sso_id, **upd)


IMPORT = {"running": False, "found": 0, "done": 0, "added": 0, "skipped": 0, "error": None, "started_ms": None, "finished_ms": None}


def import_status():
    return dict(IMPORT)


def _run_import():
    try:
        if zendesk.configured():
            raise sosscan.ScanError("SplashHub Centre has no Zendesk login yet (missing " + ", ".join(zendesk.configured()) + ")")
        batch = []

        def add(batch):
            have = store.sso_ticket_ids([t["id"] for t in batch])
            for t in batch:
                if IMPORT.get("stop"):
                    return
                if int(t["id"]) in have:
                    IMPORT["skipped"] += 1
                else:
                    created = sosscan._ms(t.get("created_at")) or _now()
                    sid = store.sso_upsert(int(t["id"]), "import", created)
                    try:
                        read_ticket(sid, int(t["id"]), t)
                    except zendesk.ZendeskError:
                        _fill(sid, t.get("subject"), t.get("description"))
                    time.sleep(0.3)                        # gentle on Zendesk
                    IMPORT["added"] += 1
                IMPORT["done"] += 1

        seen = set()
        for t in find_tickets("created>=2026-01-01"):
            if IMPORT.get("stop"):
                break
            if int(t["id"]) in seen:
                continue
            seen.add(int(t["id"]))
            IMPORT["found"] += 1
            batch.append(t)
            if len(batch) >= 100:
                add(batch); batch = []
        if batch and not IMPORT.get("stop"):
            add(batch)
        store.set_setting("sso_found_2026_v3", "yes", "import")
    except (sosscan.ScanError, zendesk.ZendeskError) as e:
        IMPORT["error"] = str(e)[:400]
    except Exception as e:
        IMPORT["error"] = "internal error (%s) -- see the app log" % type(e).__name__
        sys.stderr.write("[sso import] failed: %s\n" % type(e).__name__)
    finally:
        IMPORT["stopped"] = bool(IMPORT.get("stop"))
        IMPORT["running"] = False
        IMPORT["finished_ms"] = _now()
        try:
            store.set_setting("sso_import_running", "", "import")
        except Exception:
            pass
        sys.stderr.write("[sso import] finished: %d found, %d added, %d skipped%s\n" % (
            IMPORT["found"], IMPORT["added"], IMPORT["skipped"], (" -- " + IMPORT["error"]) if IMPORT["error"] else ""))


def start_import(resumed=False):
    with _lock:
        if IMPORT["running"]:
            return False
        IMPORT.update(running=True, stop=False, stopped=False, found=0, done=0, added=0, skipped=0, error=None,
                      started_ms=_now(), finished_ms=None, resumed=resumed)
    store.set_setting("sso_import_running", "yes", "import")
    threading.Thread(target=_run_import, name="sso-import", daemon=True).start()
    return True


def resume_import():
    try:
        if store.get_setting("sso_import_running", "") == "yes":
            sys.stderr.write("[sso import] carrying on after a restart\n")
            start_import(resumed=True)
    except Exception as e:
        sys.stderr.write("[sso import] could not resume: %s\n" % type(e).__name__)


def stop(which):
    job = IMPORT if which == "import" else CHECK_ALL
    if job["running"]:
        job["stop"] = True
        return True
    return False


# ---- the internal note -----------------------------------------------------------------------

def note_text(row):
    res = json.loads(row.get("last_result_json") or "null")
    if not res:
        raise sosscan.ScanError("Check DNS first -- the note reports the last check.")
    when = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(res["ms"] / 1000))
    if res.get("error"):
        head = "could not check (%s)" % res["error"]
    elif res.get("found"):
        head = "VERIFIED -- the TXT record is in place"
    elif not res.get("exists"):
        head = "NOT FOUND -- %s does not exist in DNS" % res["name"]
    else:
        head = "NOT FOUND YET -- the expected TXT record is not on %s" % res["name"]
    if res.get("all") and not res.get("error"):
        lines = ["SplashHub Centre — SSO domain check: " + ("VERIFIED -- every TXT record is in place" if res.get("found")
                                                             else "NOT ALL FOUND YET"), ""]
        for a in res["all"]:
            mark = "OK" if a.get("found") else ("lookup failed" if a.get("error") else ("missing" if a.get("value") else "no value in the ticket"))
            lines.append("%s -- %s (TXT on %s)" % (a.get("domain") or "?", mark, a.get("host")))
        lines += ["", "Checked %s (DNS lookup by SplashHub Centre)." % when]
        return "\n".join(lines)
    lines = ["SplashHub Centre — SSO domain check: " + head, "",
             "Domain: %s" % (row.get("domain") or "?"),
             "TXT record on: %s" % res["name"],
             "Expected value: %s" % (res.get("expected") or "(not given)")]
    if not res.get("error") and not res.get("found"):
        recs = res.get("records") or []
        lines.append("TXT records found: %s" % ("; ".join(recs[:6]) + (" ..." if len(recs) > 6 else "") if recs else "none"))
    lines += ["", "Checked %s (DNS lookup by SplashHub Centre)." % when]
    return "\n".join(lines)


def add_note(sso_id):
    row = store.sso_get(sso_id, fresh=True)
    if not row:
        raise sosscan.ScanError("That request is gone.")
    if zendesk.configured():
        raise sosscan.ScanError("SplashHub Centre has no Zendesk login yet.")
    zendesk.add_internal_note(row["ticket_id"], note_text(row))
    info = {"ms": _now(), "status": row.get("status")}
    store.sso_update(sso_id, note_json=json.dumps(info))
    sys.stderr.write("[sso] #%s internal note added\n" % row["ticket_id"])
    return info


# ---- by itself: finding new requests, re-reading updated ones, checking DNS ---------------------------

FIND_EVERY = 900            # the Zendesk search
CHECK_EVERY_MS = 3600000    # each waiting request's DNS, at most hourly


def find_tickets(cond):
    """SSO tickets matching cond (e.g. "updated>=2026-10-05"): SplashHub's SSO
    tag, a challenge record anywhere in the ticket, or the old form's subject."""
    for q in ('type:ticket tags:%s %s' % (SSO_TAG, cond), 'type:ticket "splashtop-sso-challenge" %s' % cond,
              'type:ticket subject:"%s" %s' % (SSO_SUBJECT, cond)):
        for t in zendesk.search_tickets(q, max_pages=50):
            yield t


def _known():
    """{ticket: (request id, updated_at when read -- None when it has no stage yet, so it is read again)}"""
    return {int(r[0]): (r[1], r[2] if r[3] and r[4] else None)
            for r in store._read("SELECT ticket_id, id, ticket_updated, stage, relevance FROM sso_requests", [], fresh=True)}


def _enabled_status():
    """Requests whose stage is enabled carry the Enabled status (once, for the ones read before it existed)."""
    c = store.connect(True)
    try:
        c.cursor().execute("UPDATE sso_requests SET status = 'enabled' WHERE stage = 'enabled' AND status <> 'enabled'")
        c.commit()
    finally:
        c.close()


def sync():
    """New SSO tickets, and the ones updated since their conversation was read
    (a reply with the records, a status change). The first time: all of 2026."""
    _enabled_status()
    if zendesk.configured():
        return
    first = store.get_setting("sso_found_2026_v3", "") != "yes"
    cond = "created>=2026-01-01" if first else "updated>=" + time.strftime("%Y-%m-%d", time.gmtime(time.time() - 2 * 86400))
    known, seen, added = _known(), set(), 0
    for t in find_tickets(cond):
        tid = int(t["id"])
        if tid in seen:
            continue
        seen.add(tid)
        have = known.get(tid)
        if have and have[1] == t.get("updated_at"):
            continue
        sid = have[0] if have else store.sso_upsert(tid, "search", sosscan._ms(t.get("created_at")) or _now())
        try:
            read_ticket(sid, tid, t)
        except zendesk.ZendeskError as e:
            sys.stderr.write("[sso] reading #%d: %s\n" % (tid, e))
        added += not have
        time.sleep(0.3)
    if first:
        store.set_setting("sso_found_2026_v3", "yes", "sso")
    if seen:
        sys.stderr.write("[sso] search: %d SSO ticket(s) looked at, %d new\n" % (len(seen), added))


def auto_check():
    """Each request that has its records and an open ticket, not verified, not
    looked up in the last hour: checked now (all of its records)."""
    cutoff = _now() - CHECK_EVERY_MS
    rows = store._read("SELECT id FROM sso_requests WHERE txt_value IS NOT NULL AND status IN ('pending', 'not_found', 'error') "
                       "AND coalesce(ticket_status, '') NOT IN ('solved', 'closed') AND coalesce(relevance, '') <> 'not_sso' "
                       "AND (last_checked_ms IS NULL OR last_checked_ms < %s) ORDER BY requested_ms DESC", [cutoff], fresh=True)
    for (sid,) in rows:
        try:
            check(sid, "Automatic")
        except Exception as e:
            sys.stderr.write("[sso] automatic check %s: %s\n" % (sid, type(e).__name__))
        time.sleep(0.2)


def boot():
    def loop():
        time.sleep(45)
        while True:
            for f in (sync, auto_check):
                try:
                    f()
                except Exception as e:
                    sys.stderr.write("[sso] %s skipped: %s\n" % (f.__name__, type(e).__name__))
            time.sleep(FIND_EVERY)
    threading.Thread(target=loop, name="sso-loop", daemon=True).start()
