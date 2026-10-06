"""SplashHub Centre -- the Spluki home for SplashHub's run log.

    python app/server.py [port]        local preview (SQLite + sample data)

Routes
  GET  /health                          Spluki health check (no login)
  GET  /                                -> /scans
  GET  /logs                            the Logs page (admin)
  POST /login  {password}               sets the session cookie
  POST /logout
  GET  /api/meta                        tools, agents, models, backend, sample flag
  GET  /api/summary?<filters>&tz=       totals, per-day, per-tool
  GET  /api/runs?<filters>&page=        one page of rows, newest first
  GET  /api/runs.csv?<filters>          the filtered rows as CSV
  <filters> = since, until (epoch ms), tool, agent, model, q

Access. Every page is open to the team except the two under Admin in the left
menu -- Logs and Settings -- which need the one ADMIN_PASSWORD (a sealed Spluki
secret; locally an env var or app/admin_password.txt, gitignored), as SplashHub
shows its Logs page to admins only. Locally with no password set those are open
too, for previewing. On Spluki (PostgreSQL backend) a missing password keeps
them locked instead of opening them.

The table is filled by feed.py: SplashHub posts each run (and, on request, its
Zendesk history) to the platform's SPLUKI_WEBHOOK intake, and a background loop
here takes it. SplashHub keeps writing to Zendesk as well.
"""
import base64, csv, hashlib, hmac, http.server, io, json, os, re, secrets, sys, time
from http import cookies
from urllib.parse import parse_qs, urlparse

APP = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APP)
import store
import feed
import imagestore
import sosdash
import sosscan
import ssocheck
import zendesk

STATIC = os.path.join(APP, "static")
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("PORT", "8795"))
HOST = os.environ.get("HOST", "127.0.0.1")      # the container sets 0.0.0.0
PW_FILE = os.path.join(APP, "admin_password.txt")
COOKIE = "shcadmin"
# What needs the admin session: the Logs page's data and the Settings page's.
# Everything else (SOS Scans, SSO Requests, PriceBook, AI) is open to the team.
ADMIN_GET = {"/api/meta", "/api/summary", "/api/runs", "/api/runs.csv", "/api/settings", "/api/import-past", "/api/cases",
             "/api/kb", "/api/po", "/api/notify", "/api/teams-ask", "/api/overview"}
ADMIN_POST = {"/api/import-past", "/api/import-past/stop", "/api/settings", "/api/ai-review", "/api/spark/test",
              "/api/cases/download", "/api/cases/stop", "/api/cases/update", "/api/kb/sync", "/api/kb/stop", "/api/po/import", "/api/po/update", "/api/po/stop", "/api/notify",
              "/api/notify/test", "/api/notify/run", "/api/notify/languages", "/api/teams-ask", "/api/teams-ask/key"}
# Local preview fills an empty database with sample runs. Never on Spluki.
SAMPLE = store.backend() == "sqlite" and os.environ.get("SAMPLE_DATA", "1") != "0"


# ---- session ------------------------------------------------------------------
_KEY = secrets.token_bytes(32)      # per process: a redeploy logs everyone out


def admin_password():
    pw = os.environ.get("ADMIN_PASSWORD")
    if not pw and os.path.exists(PW_FILE):
        pw = open(PW_FILE, encoding="utf-8").read().strip()
    return pw or None


def login_required():
    return bool(admin_password()) or store.backend() == "postgres"


def make_token(hours=12):
    exp = str(int(time.time()) + hours * 3600).encode()
    return base64.urlsafe_b64encode(exp + b"." + hmac.new(_KEY, exp, hashlib.sha256).digest()).decode()


def check_token(tok):
    try:
        raw = base64.urlsafe_b64decode((tok or "").encode())
        exp, sig = raw.split(b".", 1)
        return hmac.compare_digest(hmac.new(_KEY, exp, hashlib.sha256).digest(), sig) and int(exp) > time.time()
    except Exception:
        return False


# ---- request helpers ------------------------------------------------------------

def filters(qs):
    def one(k):
        v = (qs.get(k) or [""])[0].strip()
        return v or None
    f = {}
    for k in ("since", "until"):
        v = one(k)
        if v is not None:
            try:
                f[k] = int(v)
            except ValueError:
                pass
    tool = one("tool")
    if tool in store.TOOL_KEYS:
        f["tool"] = tool
    for k in ("agent", "model"):
        v = one(k)
        if v:
            f[k] = v[:120]
    q = one("q")
    if q:
        f["q"] = q[:120]
    return f


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "SplashHubCentre"

    def log_message(self, fmt, *args):      # quiet; errors still print below
        pass

    def _send(self, code, body, ctype, extra=()):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        # Styles, scripts and images are versioned (?v=) in the pages, so the browser
        # may keep them: page to page then reuses them instead of fetching (no flash).
        # Pages and data are never kept.
        static_asset = ctype.split(";")[0] in ("text/css", "text/javascript", "image/png")
        self.send_header("Cache-Control", "public, max-age=604800" if static_asset and code == 200 else "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        for k, v in extra:
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _sidebar_origin(self):
        """The Origin of SplashHub's sidebar in an agent's browser (a Zendesk app
        page), or None. Only such pages may call /api/sidebar/review cross-site;
        Spluki's network fence keeps out anything off the company network."""
        o = (self.headers.get("Origin") or "").strip()
        return o if re.fullmatch(r"https://[a-z0-9-]+\.apps\.zdusercontent\.com|https://[a-z0-9-]+\.zendesk\.com", o) else None

    def _cors(self, origin):
        return [("Access-Control-Allow-Origin", origin), ("Vary", "Origin"),
                ("Access-Control-Allow-Private-Network", "true")] if origin else []

    def do_OPTIONS(self):
        # The browser's pre-flight for the sidebar's call.
        origin = self._sidebar_origin()
        if urlparse(self.path).path != "/api/sidebar/review" or not origin:
            return self._send(404, "", "text/plain")
        return self._send(204, "", "text/plain", self._cors(origin) + [
            ("Access-Control-Allow-Methods", "POST"), ("Access-Control-Allow-Headers", "Content-Type"),
            ("Access-Control-Max-Age", "600")])

    def json(self, obj, code=200, extra=()):
        self._send(code, json.dumps(obj, ensure_ascii=False), "application/json; charset=utf-8", extra)

    def authed(self):
        if not login_required():
            return True
        c = cookies.SimpleCookie(self.headers.get("Cookie") or "")
        return COOKIE in c and check_token(c[COOKIE].value)

    def static(self, name, ctype):
        path = os.path.join(STATIC, name)
        with open(path, "rb") as fh:
            self._send(200, fh.read(), ctype)

    # ---- GET ----
    def do_GET(self):
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        try:
            if u.path == "/health":
                return self._send(200, "ok", "text/plain; charset=utf-8")
            if u.path in ("/", "/index.html"):
                return self._send(302, "", "text/plain; charset=utf-8", [("Location", "/scans")])
            if u.path in ("/logs", "/logs.html"):
                return self.static("index.html", "text/html; charset=utf-8")
            if u.path in ("/tags", "/tags.html"):
                return self.static("tags.html", "text/html; charset=utf-8")
            if u.path in ("/me", "/me.html"):
                return self.static("me.html", "text/html; charset=utf-8")
            if u.path in ("/overview", "/overview.html"):
                return self.static("overview.html", "text/html; charset=utf-8")
            if u.path in ("/scans", "/scans.html"):
                return self.static("scans.html", "text/html; charset=utf-8")
            if u.path in ("/prices", "/prices.html"):
                return self.static("prices.html", "text/html; charset=utf-8")
            if u.path in ("/ask", "/ask.html"):
                return self.static("ask.html", "text/html; charset=utf-8")
            if u.path in ("/settings", "/settings.html"):
                return self.static("settings.html", "text/html; charset=utf-8")
            if u.path in ("/sso", "/sso.html"):
                return self.static("sso.html", "text/html; charset=utf-8")
            if u.path in ("/kb", "/kb.html"):
                return self.static("kb.html", "text/html; charset=utf-8")
            if u.path in ("/po", "/po.html"):
                return self.static("po.html", "text/html; charset=utf-8")
            if u.path in ("/customers", "/customers.html"):
                return self.static("customers.html", "text/html; charset=utf-8")
            if u.path in ("/app.css", "/app.js", "/scans.js", "/sso.js", "/settings.js",
                          "/prices.js", "/prices.css", "/pricebook.js", "/pbsettings.js", "/aichat.js", "/nav.js", "/kb.js", "/customers.js", "/po.js", "/overview.js", "/tags.js", "/splashtop-icon.png"):
                ctype = {"css": "text/css; charset=utf-8", "js": "text/javascript; charset=utf-8",
                         "png": "image/png"}[u.path.rsplit(".", 1)[1]]
                return self.static(u.path.lstrip("/"), ctype)
            if not u.path.startswith("/api/"):
                return self._send(404, "Not found", "text/plain; charset=utf-8")

            if u.path == "/api/session":
                return self.json({"required": login_required(), "authed": self.authed(),
                                  "configured": bool(admin_password())})
            if u.path in ADMIN_GET and not self.authed():
                return self.json({"error": "login required"}, 401)

            if u.path == "/api/meta":
                fac = store.facets()
                return self.json({"tools": [{"key": k, "label": l} for k, l in store.TOOLS],
                                  "agents": fac["agents"], "models": fac["models"],
                                  "first": fac["first"], "last": fac["last"],
                                  "backend": store.backend(), "sample": SAMPLE, "feed": feed.status()})
            if u.path == "/api/summary":
                try:
                    tz = int((qs.get("tz") or ["0"])[0])
                except ValueError:
                    tz = 0
                return self.json(store.summary(filters(qs), max(-840, min(840, tz))))
            if u.path == "/api/runs":
                try:
                    page = int((qs.get("page") or ["0"])[0])
                except ValueError:
                    page = 0
                return self.json(store.runs(filters(qs), page, 25))
            # ---- SOS package scans ----
            if u.path == "/api/scans/dashboard":
                try:
                    tz = int((qs.get("tz") or ["0"])[0])
                except ValueError:
                    tz = 0
                return self.json(sosdash.build(max(-840, min(840, tz)), fresh=(qs.get("fresh") or [""])[0] == "1"))
            if u.path == "/api/scans":
                one = lambda k: ((qs.get(k) or [""])[0]).strip()
                try:
                    page = int(one("page") or 0)
                except ValueError:
                    page = 0
                res = store.scans(one("q")[:80] or None, one("verdict") or None, page, 50)
                # The Ticket status column: the refresh button (fresh=1) reads
                # every status on screen now and shows it; other loads top up
                # old ones in the background.
                fresh = one("fresh") == "1"
                if sosscan.refresh_statuses(res["rows"], force=fresh, wait=fresh):
                    res = store.scans(one("q")[:80] or None, one("verdict") or None, page, 50)
                return self.json(res)
            m = re.match(r"^/api/scans/(\d+)/image/(\d+)$", u.path)
            if m:
                # A stored copy of one of the ticket's images (imagestore.py). Only
                # requests from before copies were dropped have any.
                row = store.scan_get(int(m.group(1)))
                try:
                    gallery = json.loads((row or {}).get("gallery_json") or "[]")
                except ValueError:
                    gallery = []
                g = next((x for x in gallery if str(x.get("id")) == m.group(2) and x.get("key")), None)
                if not g or g.get("content_type") not in sosscan.SUPPORTED_IMAGE_TYPES:
                    return self._send(404, "Not found", "text/plain; charset=utf-8")
                data = imagestore.store().get(g["key"])
                if data is None:
                    return self._send(404, "Not found", "text/plain; charset=utf-8")
                return self._send(200, data, g["content_type"], [("Cache-Control", "private, max-age=86400"),
                                                                  ("Content-Disposition", "inline")])
            m = re.match(r"^/api/scans/(\d+)/note$", u.path)
            if m:
                # The note's preview, exactly as it would be added.
                row = store.scan_get(int(m.group(1)))
                if not row:
                    return self.json({"error": "not found"}, 404)
                try:
                    return self.json({"html": sosscan.note_html(row)})
                except sosscan.ScanError as e:
                    return self.json({"error": str(e)}, 400)
            if u.path.startswith("/api/scans/") and u.path.rsplit("/", 1)[1].isdigit():
                row = store.scan_get(int(u.path.rsplit("/", 1)[1]))
                if not row:
                    return self.json({"error": "not found"}, 404)
                for k in ("images_json", "fields_json", "result_json", "gallery_json", "translation_json", "note_json"):
                    try:
                        row[k[:-5]] = json.loads(row.pop(k) or "null")
                    except ValueError:
                        row[k[:-5]] = None
                # The ticket's first message, organised; the raw text stays for "Show original text".
                row["request"] = sosscan.parse_request(row.get("description") or "")
                # SplashHub's FREE_EMAIL_DOMAINS (the AI's own broader call is in the result)
                row["creator_is_free_email"] = (row.get("creator_domain") or "").lower() in sosscan.FREE_EMAIL_DOMAINS
                if row.get("result"):
                    # the card's Status and Reason -- the same as the internal note's
                    full = store.scan_get(row["id"])
                    row["status_verdict"] = sosscan.effective_verdict(full, row["result"])
                    row["reasons"] = sosscan.review_reasons(full, row["result"])
                    row["generic"] = sosscan.is_generic(full, row["result"])
                    # branding vs the creator's email (team rule): the reason line and which images
                    mm = sosscan.brand_mismatch(full, row["result"])
                    row["mismatch"] = {"text": next((r for r in row["reasons"] if r.startswith("Branding ")), ""),
                                       "images": [i for i, _b, _h in mm]} if mm else None
                row["zendesk_url"] = zendesk.base_url()
                return self.json(row)
            if u.path == "/api/import-past":
                return self.json(sosscan.import_status())
            # ---- PO Requests (po.py): the list is open to the team; the import is admin ----
            if u.path == "/api/overview":
                # Admin > Dashboard: the whole support picture; AI usage per member (?agent=).
                import overview
                return self.json(overview.build(fresh=(qs.get("fresh") or [""])[0] == "1",
                                                agent=((qs.get("agent") or [""])[0])[:120] or None))
            if u.path == "/api/tags":
                # The Tags page: tickets per tag from the Zendesk Tickets data (no Zendesk calls).
                import tags
                one = lambda k: ((qs.get(k) or [""])[0]).strip()
                try:
                    tz = max(-840, min(840, int(one("tz") or 0)))
                except ValueError:
                    tz = 0
                sel = [x for x in one("select").split("|") if x] or None
                return self.json(tags.counts(one("kind") or "topics", tz, sel))
            if u.path == "/api/notify":
                import notify
                return self.json(notify.settings())
            if u.path == "/api/teams-ask":
                import teamsask
                return self.json(dict(teamsask.settings(), flow=teamsask.flow_setup()))
            if u.path == "/api/po":
                import po
                return self.json(po.status())
            if u.path == "/api/po/overview":
                import po
                return self.json(po.overview())
            if u.path == "/api/po/search":
                import po
                one = lambda k: ((qs.get(k) or [""])[0]).strip()
                try:
                    page = max(0, int(one("page") or 0))
                except ValueError:
                    page = 0
                return self.json(po.search(one("q")[:120] or None, one("status") or None, one("region") or None,
                                           one("when") or None, one("year") or None, page))
            m = re.match(r"^/api/po/(\d+)$", u.path)
            if m:
                import po
                r = po.get(int(m.group(1)))
                return self.json(r) if r else self.json({"error": "not found"}, 404)
            # ---- Customers (customers.py): open to the team; reads what is already here ----
            if u.path == "/api/customers/find":
                import customers
                return self.json(customers.find(((qs.get("q") or [""])[0])[:120]))
            if u.path == "/api/customers/profile":
                import customers
                p = customers.profile(((qs.get("key") or [""])[0])[:200])
                return self.json(p) if p.get("found") else self.json(dict(p, error="Nothing about this customer yet."), 404)
            if u.path == "/api/customers/summary":
                # The AI summary box (Spark), written in the background and kept until something new comes in.
                import customers
                return self.json(customers.summary(((qs.get("key") or [""])[0])[:200], fresh=(qs.get("fresh") or [""])[0] == "1"))
            if u.path == "/api/customers/top":
                import customers
                return self.json(customers.top())
            # ---- Knowledge Base (kb.py): the page is open to the team; the sync is admin ----
            if u.path == "/api/kb":
                import kb
                return self.json(kb.status())
            if u.path == "/api/kb/meta":
                import kb
                return self.json(kb.meta((qs.get("locale") or [""])[0] or None))
            if u.path == "/api/kb/search":
                import kb
                one = lambda k: ((qs.get(k) or [""])[0]).strip()
                try:
                    page = max(0, int(one("page") or 0))
                except ValueError:
                    page = 0
                return self.json(kb.search(one("q")[:120] or None, one("locale") or None, one("category") or None,
                                           one("flag") or None, one("sort") or None, page))
            m = re.match(r"^/api/kb/article/(\d+)$", u.path)
            if m:
                import kb
                a = kb.article(int(m.group(1)), (qs.get("locale") or [""])[0] or None)
                return self.json(a) if a else self.json({"error": "not found"}, 404)
            if u.path == "/api/cases":
                # Settings > Zendesk Tickets: what is downloaded, and the job's progress.
                import cases
                st = cases.status()
                if (qs.get("zendesk") or [""])[0] == "1":
                    try:
                        st["zendesk_count"] = cases.zendesk_count()
                    except zendesk.ZendeskError as e:
                        st["zendesk_error"] = str(e)
                return self.json(st)
            # ---- Price Book (pricebook.py) ----
            if u.path == "/api/pricebook/fetch":
                import pricebook
                try:
                    return self._send(200, pricebook.fetch((qs.get("url") or [""])[0]), "application/json; charset=utf-8")
                except pricebook.PriceError as e:
                    return self.json({"error": str(e)}, 502)
            if u.path == "/api/pricebook/store":
                import pricebook
                return self.json(pricebook.records())
            # ---- SSO method validation requests ----
            if u.path == "/api/sso":
                one = lambda k: ((qs.get(k) or [""])[0]).strip()
                try:
                    page = int(one("page") or 0)
                except ValueError:
                    page = 0
                return self.json(store.sso_list(one("q")[:80] or None, one("status") or None, page, 50))
            m = re.match(r"^/api/sso/(\d+)/note$", u.path)
            if m:
                row = store.sso_get(int(m.group(1)))
                if not row:
                    return self.json({"error": "not found"}, 404)
                try:
                    return self.json({"text": ssocheck.note_text(row)})
                except sosscan.ScanError as e:
                    return self.json({"error": str(e)}, 400)
            m = re.match(r"^/api/sso/(\d+)$", u.path)
            if m:
                row = store.sso_get(int(m.group(1)))
                if not row:
                    return self.json({"error": "not found"}, 404)
                for k in ("last_result_json", "history_json", "note_json"):
                    try:
                        row[k[:-5]] = json.loads(row.pop(k) or "null")
                    except ValueError:
                        row[k[:-5]] = None
                row["fields"] = sosscan.parse_request(row.get("description") or "")["fields"]
                row["parse"] = ssocheck.parse(row.get("description") or "")["note"]
                row["zendesk_url"] = zendesk.base_url()
                return self.json(row)
            if u.path == "/api/sso-import":
                return self.json(ssocheck.import_status())
            if u.path == "/api/sso-check-all":
                return self.json(ssocheck.check_all_status())
            if u.path == "/api/settings":
                import spark
                sp = {"spark": spark.available()}
                if sp["spark"]:
                    try:
                        sp.update(spark_models=spark.models(), spark_model=spark.model(),
                                  spark_thinking="on" if spark.thinking_on() else "off")
                    except spark.SparkError as e:
                        sp["spark_error"] = str(e)
                return self.json(dict(sp, ai_review="on" if sosscan.ai_review_on() else "off",
                                      auto_note="on" if sosscan.auto_note() else "off",
                                      translate_engine=sosscan.translate_engine()))
            if u.path == "/api/scan-setup":
                missing = sosscan.missing_config()
                if not (os.environ.get("ZENDESK_WEBHOOK_SECRET") or "").strip():
                    missing.append("ZENDESK_WEBHOOK_SECRET")
                return self.json({"missing": missing, "zendesk_url": zendesk.base_url(),
                                  "model": sosscan.ai_config()[2], "can_scan": not sosscan.missing_config(),
                                  "ai_review": "on" if sosscan.ai_review_on() else "off"})
            if u.path == "/api/runs.csv":
                rows = store.all_runs(filters(qs))
                buf = io.StringIO()
                w = csv.writer(buf)
                w.writerow(["when_utc", "agent", "type", "tool", "model", "topic", "tickets",
                            "input_tokens", "output_tokens", "est_cost_usd"])
                for r in rows:
                    w.writerow([time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(r["ts_ms"] / 1000)),
                                r["agent"] or "", r["kind"], dict(store.TOOLS).get(r["tool"], r["tool"]),
                                r["model"] or "", r["topic"] or "", r["tickets"], r["input_tokens"],
                                r["output_tokens"], "%.6f" % (r["cost"] or 0)])
                return self._send(200, buf.getvalue(), "text/csv; charset=utf-8",
                                  [("Content-Disposition", "attachment; filename=splashhub-logs.csv")])
            return self.json({"error": "not found"}, 404)
        except Exception as e:                   # never echo internals to the page
            sys.stderr.write("GET %s failed: %r\n" % (u.path, e))
            return self.json({"error": "server error"}, 500)

    do_HEAD = do_GET

    # ---- POST ----
    def do_POST(self):
        u = urlparse(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        # 64 KB is plenty for every form here; the Price Book's cached prices are the one bigger save.
        raw = self.rfile.read(min(n, (2 * 1024 * 1024) if u.path == "/api/pricebook/store" else 64 * 1024)) if n else b""
        if u.path == "/api/sidebar/review":
            # SplashHub's sidebar: the review made here for a ticket, or one
            # started now -- never a second AI call. It calls from the agent's
            # browser (a Zendesk app page; Zendesk's own servers can't reach
            # an app behind Spluki's company-network fence). Or with the run-log
            # feed's key (RUNLOG_SECRET), for a caller inside the network.
            import feed
            origin = self._sidebar_origin()
            key, given = feed._secret(), (self.headers.get("X-SplashHub-Key") or "").strip()
            keyed = bool(key and given and hmac.compare_digest(given.encode("utf-8"), key.encode("utf-8")))
            if not (origin or keyed):
                return self.json({"error": "not allowed"}, 403)
            cors = self._cors(origin)
            try:
                data = json.loads(raw or b"{}")
                tid = int(str(data.get("ticket_id") or "").strip().lstrip("#"))
            except (ValueError, TypeError):
                return self.json({"error": "Give a ticket number."}, 400, cors)
            if tid <= 0:
                return self.json({"error": "Give a ticket number."}, 400, cors)
            try:
                out = sosscan.sidebar_review(tid, start=data.get("start", True) is not False, again=bool(data.get("again")),
                                             by=data.get("by"), press=bool(data.get("press")))
            except Exception as e:
                sys.stderr.write("[sidebar] #%s lookup failed: %s\n" % (tid, type(e).__name__))
                return self.json({"state": "error", "error": "SplashHub Centre could not look this up (%s)" % type(e).__name__}, 500, cors)
            if data.get("press") or out.get("state") != "pending":
                sys.stderr.write("[sidebar] #%s %s%s\n" % (tid, out.get("state"), " (Review again)" if data.get("again") else ""))
            return self.json(out, 200, cors)
        if u.path == "/login":
            try:
                given = (json.loads(raw or b"{}").get("password") or "")
            except ValueError:
                given = ""
            pw = admin_password()
            if pw and hmac.compare_digest(given.encode("utf-8"), pw.encode("utf-8")):
                return self.json({"ok": True}, 200, [("Set-Cookie", "%s=%s; Path=/; HttpOnly; SameSite=Strict; Max-Age=43200%s"
                                                      % (COOKIE, make_token(), "; Secure" if store.backend() == "postgres" else ""))])
            time.sleep(0.6)                      # blunt brute force a little
            return self.json({"ok": False, "error": "Wrong password." if pw else
                              "No ADMIN_PASSWORD is set for this app yet."}, 401)
        if u.path == "/logout":
            return self.json({"ok": True}, 200, [("Set-Cookie", "%s=; Path=/; Max-Age=0" % COOKIE)])
        if u.path in ADMIN_POST and not self.authed():
            return self.json({"error": "login required"}, 401)
        if u.path == "/api/import-past/stop":
            return self.json({"ok": sosscan.stop_job("import")})
        if u.path == "/api/import-past":
            # "Import past SOS requests": runs in the background on the server.
            started = sosscan.start_import()
            return self.json(dict(sosscan.import_status(), started=started))
        if u.path == "/api/notify/test":
            # Settings > Notifications > Send test message (admin).
            import notify
            err = notify.test()
            return self.json({"error": err}, 400) if err else self.json({"ok": True, "settings": notify.settings()})
        if u.path in ("/api/teams-ask", "/api/teams-ask/key"):
            # Settings > Notifications > Ask from Teams: on/off, the trigger word, a new key (shown once).
            import teamsask
            if u.path.endswith("/key"):
                return self.json(dict(teamsask.settings(), key=teamsask.new_key(), flow=teamsask.flow_setup()))
            try:
                data = json.loads(raw or b"{}")
                st = teamsask.save(data.get("on") if "on" in data else None, data.get("word"))
            except (ValueError, TypeError) as e:
                return self.json({"error": str(e) or "bad request"}, 400)
            return self.json(dict(st, flow=teamsask.flow_setup()))
        if u.path == "/api/notify/run":
            # Settings > Notifications > Run now: this alert, now, from real data (admin).
            import notify, zendesk
            try:
                out = notify.run_now(str((json.loads(raw or b"{}") or {}).get("kind") or ""))
            except ValueError as e:
                return self.json({"error": str(e)}, 400)
            except zendesk.ZendeskError as e:
                return self.json({"error": "Zendesk: %s" % e}, 400)
            return self.json(dict(out, settings=notify.settings()))
        if u.path == "/api/notify/languages":
            # Settings > Notifications > Language routing: languages, their tags and who to @mention (admin).
            import notify
            try:
                notify.set_lang_config(json.loads(raw or b"{}") or {})
            except ValueError as e:
                return self.json({"error": str(e) or "bad request"}, 400)
            return self.json(notify.settings())
        if u.path == "/api/notify":
            import notify
            try:
                data = json.loads(raw or b"{}")
                notify.set_kind(str(data.get("kind") or ""), bool(data.get("on")))
            except (ValueError, TypeError) as e:
                return self.json({"error": "bad request"}, 400)
            return self.json(notify.settings())
        if u.path in ("/api/po/import", "/api/po/update", "/api/po/stop"):
            # Settings > Database > PO Requests (reads Zendesk only).
            import po
            what = u.path.rsplit("/", 1)[1]
            if what == "stop":
                return self.json({"ok": po.stop()})
            started = po.start(what)
            return self.json(dict(po.status(), started=started))
        if u.path in ("/api/kb/sync", "/api/kb/stop"):
            # Settings > Database > Zendesk Knowledge Base (reads Zendesk only).
            import kb
            if u.path.endswith("/stop"):
                return self.json({"ok": kb.stop()})
            started = kb.start()
            return self.json(dict(kb.status(), started=started))
        if u.path in ("/api/cases/download", "/api/cases/update", "/api/cases/stop"):
            # Settings > Cases: download 2026's tickets, update them, or stop (reads Zendesk only).
            import cases
            what = u.path.rsplit("/", 1)[1]
            if what == "stop":
                return self.json({"ok": cases.stop()})
            return self.json(dict(cases.status(), started=cases.start(what)))
        if u.path == "/api/settings":
            # Settings page: "Auto add internal note" (on/off).
            try:
                data = json.loads(raw or b"{}")
            except ValueError:
                return self.json({"error": "bad request"}, 400)
            if "spark_model" in data or "spark_thinking" in data:
                import spark
                try:
                    if "spark_model" in data:
                        if data["spark_model"] not in spark.models():
                            return self.json({"error": "Spark doesn't offer that model"}, 400)
                        store.set_setting("spark_model", data["spark_model"], "Centre admin")
                    if "spark_thinking" in data:
                        store.set_setting("spark_thinking", "on" if data["spark_thinking"] else "off", "Centre admin")
                except spark.SparkError as e:
                    return self.json({"error": str(e)}, 400)
                return self.json({"ok": True, "spark_model": spark.model(), "spark_thinking": "on" if spark.thinking_on() else "off"})
            if data.get("translate_engine") in ("claude", "spark"):
                store.set_setting("translate_engine", data["translate_engine"], "Centre admin")
            if "auto_note" in data:
                store.set_setting("auto_note", "on" if data["auto_note"] else "off", "Centre admin")
                sys.stderr.write("[note] automatic internal notes switched %s\n" % ("on" if data["auto_note"] else "off"))
            return self.json({"ok": True, "auto_note": "on" if sosscan.auto_note() else "off",
                              "translate_engine": sosscan.translate_engine()})
        if u.path == "/api/ai-review":
            # The AI review switch. Applies only to requests that arrive from now
            # on; anything already listed keeps the decision it arrived with.
            try:
                on = bool(json.loads(raw or b"{}").get("on"))
            except ValueError:
                return self.json({"error": "bad request"}, 400)
            store.set_setting("ai_review", "on" if on else "off", "Centre admin")
            sys.stderr.write("[scan] AI review switched %s\n" % ("on" if on else "off"))
            return self.json({"ok": True, "ai_review": "on" if on else "off"})
        if u.path.startswith("/api/sso"):
            return self.sso_post(u, raw)
        if u.path == "/api/pricebook/store":
            import pricebook
            try:
                d = json.loads(raw or b"{}")
                pricebook.save(str(d.get("id") or ""), d.get("payload"))
                return self.json({"ok": True})
            except (ValueError, pricebook.PriceError) as e:
                return self.json({"error": str(e) if isinstance(e, pricebook.PriceError) else "bad request"}, 400)
        if u.path == "/api/spark/test":
            # Settings' "Test speed": one tiny question, timed.
            import spark
            try:
                return self.json(spark.speed_test((json.loads(raw or b"{}").get("model") or None)))
            except ValueError:
                return self.json({"error": "bad request"}, 400)
            except spark.SparkError as e:
                return self.json({"error": str(e)}, 400)
        if u.path == "/api/ask":
            # Ask AI: a question about SplashHub Centre's own data, answered by
            # Spark with read-only lookups (askai.py).
            import askai, spark
            try:
                body = json.loads(raw or b"{}")
                msgs = (body.get("messages") or [])[-10:]
                focus = body.get("focus") if body.get("focus") in ("prices",) else None
            except ValueError:
                return self.json({"error": "bad request"}, 400)
            if not msgs or not isinstance(msgs[-1], dict) or not str(msgs[-1].get("content") or "").strip():
                return self.json({"error": "Ask a question."}, 400)
            def log_run():
                store.insert_many([{"when": int(time.time() * 1000), "agent": "SplashHub Centre", "kind": "ask (Centre AI)" if not focus else "ask (PriceBook AI)",
                                    "model": "spark:" + spark.model(), "topic": str(msgs[-1].get("content"))[:120], "tickets": 0,
                                    "input_tokens": 0, "output_tokens": 0, "cost": 0, "source": "centre"}])
            t0 = time.time()
            if body.get("stream"):
                # One JSON line per event as it happens (what Spark is doing,
                # each lookup), then the answer, so the page shows progress.
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
                self.send_header("Cache-Control", "no-cache, no-transform")
                self.send_header("X-Accel-Buffering", "no")
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True

                def emit(obj):
                    try:
                        self.wfile.write((json.dumps(obj, ensure_ascii=False, default=str) + "\n").encode("utf-8"))
                        self.wfile.flush()
                    except OSError:
                        pass                      # the page went away; finish quietly
                try:
                    out = askai.ask(msgs, focus, on_event=lambda e: emit(dict(e, ms=int((time.time() - t0) * 1000))))
                except spark.SparkError as e:
                    return emit({"error": str(e)})
                except Exception as e:
                    sys.stderr.write("[ask] failed: %s\n" % type(e).__name__)
                    return emit({"error": "the answer could not be put together (%s)" % type(e).__name__})
                emit(dict(out, done=True, ms=int((time.time() - t0) * 1000)))
                return log_run()
            try:
                out = askai.ask(msgs, focus)
            except spark.SparkError as e:
                return self.json({"error": str(e)}, 400)
            log_run()
            return self.json(dict(out, ms=int((time.time() - t0) * 1000)))
        m = re.match(r"^/api/scans/(\d+)/note$", u.path)
        if m:
            # "Add as internal note": the one thing SplashHub Centre writes to
            # Zendesk, and only on this button press.
            try:
                return self.json({"ok": True, "note": sosscan.add_note(int(m.group(1)))})
            except ValueError:
                return self.json({"error": "bad request"}, 400)
            except (sosscan.ScanError, zendesk.ZendeskError) as e:
                return self.json({"error": str(e)}, 400)
        m = re.match(r"^/api/scans/(\d+)/translate$", u.path)
        if m:
            # The pop-up's Translate button: English for the package's own
            # words, saved on the request. Takes a few seconds.
            try:
                return self.json({"ok": True, "translation": sosscan.translate(int(m.group(1)))})
            except sosscan.ScanError as e:
                return self.json({"error": str(e)}, 400)
        m = re.match(r"^/api/scans/(\d+)/review$", u.path)
        if m:
            # The side panel's "AI review" button: this one request, now,
            # whether or not the switch is on.
            err = sosscan.review_now(int(m.group(1)))
            return self.json({"error": err}, 400) if err else self.json({"ok": True})
        if u.path == "/api/scans":
            # "Scan a ticket now" on the SOS Scans page; force re-runs a ticket
            # whose images were already reviewed.
            try:
                data = json.loads(raw or b"{}")
                tid = int(str(data.get("ticket_id") or "").strip().lstrip("#"))
            except (ValueError, TypeError):
                return self.json({"error": "Give a ticket number."}, 400)
            if tid <= 0:
                return self.json({"error": "Give a ticket number."}, 400)
            sid = sosscan.request(tid, "manual", "Centre admin", force=bool(data.get("force")))
            return self.json({"ok": True, "id": sid})
        return self.json({"error": "not found"}, 404)


def _sso_post(self, u, raw):
    """The SSO Requests page's actions (open to the team)."""
    try:
        data = json.loads(raw or b"{}")
    except ValueError:
        return self.json({"error": "bad request"}, 400)
    try:
        if u.path == "/api/sso":                        # "Add a ticket"
            try:
                tid = int(str(data.get("ticket_id") or "").strip().lstrip("#"))
            except ValueError:
                return self.json({"error": "Give a ticket number."}, 400)
            return self.json({"ok": True, "id": ssocheck.request(tid, "manual")})
        if u.path == "/api/sso-import":
            return self.json(dict(ssocheck.import_status(), started=ssocheck.start_import()))
        if u.path == "/api/sso-import/stop":
            return self.json({"ok": ssocheck.stop("import")})
        if u.path == "/api/sso-check-all":
            return self.json(dict(ssocheck.check_all_status(), started=ssocheck.start_check_all()))
        if u.path == "/api/sso-check-all/stop":
            return self.json({"ok": ssocheck.stop("check")})
        m = re.match(r"^/api/sso/(\d+)/(check|details|note)$", u.path)
        if m:
            sid, what = int(m.group(1)), m.group(2)
            if what == "check":
                return self.json({"ok": True, "result": ssocheck.check(sid)})
            if what == "details":
                ssocheck.set_details(sid, data.get("domain"), data.get("txt_name"), data.get("txt_value"))
                return self.json({"ok": True})
            return self.json({"ok": True, "note": ssocheck.add_note(sid)})
    except (sosscan.ScanError, zendesk.ZendeskError) as e:
        return self.json({"error": str(e)}, 400)
    return self.json({"error": "not found"}, 404)


Handler.sso_post = _sso_post


def _spark_hello():
    """One line in the log at start-up: is Spark reachable, and with which model."""
    import spark, threading

    def run():
        if not spark.available():
            sys.stderr.write("[spark] not connected (no AI_SPARK_BASE_URL / AI_SPARK_API_KEY)\n")
            return
        try:
            sys.stderr.write("[spark] connected; using %s; offers: %s\n" % (spark.model(), ", ".join(spark.models())))
        except spark.SparkError as e:
            sys.stderr.write("[spark] configured but not answering: %s\n" % e)
    threading.Thread(target=run, daemon=True).start()


def main():
    store.ensure_schema()
    if SAMPLE and store.count() == 0:
        import sample
        n = store.insert_many(sample.generate())
        print("seeded %d sample runs into %s" % (n, store.SQLITE_FILE))
    feed.start()
    sosscan.requeue_unfinished()      # scans a previous container left half-done
    sosscan.start_rules_fix()         # earlier reviews under today's team rules (in the background)
    sosscan.start_retries()           # and waiting ones, every 10 minutes
    sosscan.resume_import()           # an import a restart interrupted carries on
    ssocheck.resume_import()
    import cases
    cases.boot()                      # a download a restart interrupted carries on; hourly updates
    import kb
    kb.boot()                         # the Knowledge Base again every 6 hours, once downloaded
    import po
    po.boot()                         # new and changed PO requests every hour, once imported
    import notify
    notify.boot()                     # Teams: spike and overdue-PO checks (only what's switched on)
    _spark_hello()
    srv = http.server.ThreadingHTTPServer((HOST, PORT), Handler)
    print("SplashHub Centre on http://%s:%d  (backend: %s%s)" % (HOST, PORT, store.backend(), ", sample data" if SAMPLE else ""))
    srv.serve_forever()


if __name__ == "__main__":
    main()
