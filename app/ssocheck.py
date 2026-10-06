"""SSO method validation requests -- the SSO Requests page.

A customer asks to validate an SSO method; the ticket ("Here comes a new
request to validate SSO method ...") gives the domain and the DNS TXT record
they must add to prove they own it. SplashHub Centre lists these requests,
reads the domain and the TXT value out of the ticket, and -- when an agent
presses Check DNS (one request, or every request still waiting) -- looks the
record up and says whether it is there yet. An agent can then add the result
to the ticket as an internal note. Everything is manual for now.

Arrive by the same Zendesk trigger + webhook as SOS packages (feed.py routes
by subject, or by kind=sso in the trigger's body), or by "Import past SSO
requests", which searches Zendesk by subject.

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


def check(sso_id, by="Centre admin"):
    """Look the TXT record up now; record and return the result."""
    row = store.sso_get(sso_id, fresh=True)
    if not row:
        raise sosscan.ScanError("That request is gone.")
    name, want = (row.get("txt_name") or row.get("domain") or "").strip(), (row.get("txt_value") or "").strip()
    if not name:
        raise sosscan.ScanError("Add the domain first.")
    res = {"ms": _now(), "name": name, "expected": want, "by": by}
    try:
        recs = dns_txt(name)
        res["exists"] = recs is not None
        res["records"] = recs or []
        res["found"] = bool(want) and any(_norm(want) == _norm(r) or _norm(want) in _norm(r) for r in recs or [])
        status = "verified" if res["found"] else ("not_found" if want else "needs_details")
    except DnsError as e:
        res["error"] = str(e)
        status = "error"
    hist = json.loads(row.get("history_json") or "[]")
    hist = ([{k: res.get(k) for k in ("ms", "found", "error", "by")}] + hist)[:20]
    upd = dict(status=status, last_checked_ms=res["ms"], last_result_json=json.dumps(res), history_json=json.dumps(hist),
               checks=(row.get("checks") or 0) + 1)
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


def _fetch(sso_id, ticket_id):
    """Read the ticket from Zendesk when the trigger did not send its text."""
    try:
        t = zendesk.ticket(ticket_id)
        _fill(sso_id, t["subject"], t["description"], t["requester_email"], t["organization"])
    except zendesk.ZendeskError as e:
        store.sso_update(sso_id, status="needs_details", parse_note="Could not read the ticket yet: %s" % e)


def request(ticket_id, source, data=None):
    """A request from the Zendesk trigger (or 'Add a ticket'). One row per
    ticket: a second trigger for the same ticket refreshes it."""
    data = data or {}
    sid = store.sso_upsert(int(ticket_id), source, _now())
    if data.get("description"):
        _fill(sid, data.get("subject"), data.get("description"), data.get("requester"))
    elif not zendesk.configured():
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
                    _fill(sid, t.get("subject"), t.get("description"))
                    IMPORT["added"] += 1
                IMPORT["done"] += 1

        for t in zendesk.search_tickets('type:ticket subject:"%s"' % SSO_SUBJECT):
            if IMPORT.get("stop"):
                break
            if is_sso(t.get("subject")):
                IMPORT["found"] += 1
                batch.append(t)
            if len(batch) >= 100:
                add(batch); batch = []
        if batch and not IMPORT.get("stop"):
            add(batch)
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
