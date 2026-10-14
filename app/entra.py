"""Company sign-in: Microsoft Entra ID over OIDC (authorization code flow with
PKCE, confidential client), standard library only.

OFF until two things are true: the app registration is configured (CLIENT_ID
plus the sealed secret ENTRA_CLIENT_SECRET), and an admin turns it on from the
top bar's menu (setting sso_login) -- which needs a test sign-in that worked
first, so a broken registration can never lock the team out. While off, the
pages behave exactly as before; /auth/login still works, for that test.

What stays outside sign-in (server.py, OPEN_PATHS): /health (Spluki's health
check expects a plain 200), /auth/* (this flow), the two endpoints the Zendesk
sidebar calls from an agent's browser (/api/sidebar/review, /api/sidebar/replylab
-- they carry no cookie and keep their own Zendesk-origin check), the admin
password login (/login, /logout: the way back in if Entra is ever down) and
the static styles, scripts and icon. Anything else without a session: a page
is sent to sign in and comes back to where it was; an API call answers 401
with X-Centre-Signin, which nav.js turns into the same round trip.

Spluki specifics (spluki doc user-activity-for-developers): TLS ends before the
container, so the redirect URI is built from PUBLIC_URL, never the request;
login.microsoftonline.com must be in the OUTBOUND_HTTP grant (discovery, token
and keys all live there); the tenant ID is not a secret and sits here; every
sign-in and sign-out writes an activity line on stdout.

The ID token comes straight from the token endpoint over TLS, and is also
checked in full: RS256 signature against Entra's published keys, issuer,
audience, expiry, nonce. Only @splashtop.com accounts are let in (guests in the
tenant are not). Errors are worded here, never copied from a library: a proxy
refusal quotes the proxy URL, which carries this app's proxy password.
"""
import base64, hashlib, hmac, json, os, secrets, sys, time, urllib.error, urllib.parse, urllib.request

import store

# The app registration. Not secrets: the tenant is public and the client ID is
# sent to every browser. Fill these in (or set the environment variables).
TENANT_ID = os.environ.get("ENTRA_TENANT_ID") or "ee78438f-d19a-4ef6-874b-4a083ee0a508"   # Splashtop's Entra tenant
CLIENT_ID = os.environ.get("ENTRA_CLIENT_ID") or "fdc63ab5-149b-4498-a44f-6e61bff4f17c"   # SplashHub Centre's app registration
PUBLIC_URL = (os.environ.get("CENTRE_PUBLIC_URL") or "https://splashhub-37268f-dev.tperd.splashtop.dev").rstrip("/")
REDIRECT_PATH = "/auth/callback"                 # must match the registration exactly
ALLOWED_DOMAINS = tuple(d.strip().lower() for d in (os.environ.get("ENTRA_ALLOWED_DOMAINS") or "splashtop.com").split(",") if d.strip())

USER_COOKIE, FLOW_COOKIE = "shcuser", "shcflow"
SESSION_HOURS = 12
TIMEOUT = 15
# ENTRA_LOGIN_BASE is for local tests against a fake Entra; never set on Spluki.
LOGIN = (os.environ.get("ENTRA_LOGIN_BASE") or "https://login.microsoftonline.com").rstrip("/")


class SignInError(Exception):
    """A message that is safe to show."""


def _secret():
    return (os.environ.get("ENTRA_CLIENT_SECRET") or "").strip()


def configured():
    return bool(CLIENT_ID and _secret())


def missing():
    return [n for n, v in (("client ID (entra.py CLIENT_ID or ENTRA_CLIENT_ID)", CLIENT_ID),
                           ("ENTRA_CLIENT_SECRET", _secret())) if not v]


def active():
    """Is sign-in required right now? Configured AND switched on by an admin."""
    if not configured():
        return False
    try:
        return store.get_setting("sso_login", "off") == "on"
    except Exception:
        return False


def redirect_uri():
    return PUBLIC_URL + REDIRECT_PATH


# ---- signed cookies (a key kept in the database: a release doesn't sign everyone out) ----

_KEY = None


def _key():
    global _KEY
    if _KEY is None:
        k = store.get_setting("session_key", "")
        if not k:
            k = secrets.token_hex(32)
            store.set_setting("session_key", k, "sign-in")
            k = store.get_setting("session_key", "") or k     # two containers at once: both use the stored one
        _KEY = bytes.fromhex(k)
    return _KEY


def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s):
    s = s or ""
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def seal(obj):
    body = _b64(json.dumps(obj, separators=(",", ":")).encode())
    return body + "." + _b64(hmac.new(_key(), body.encode(), hashlib.sha256).digest())


def unseal(tok):
    try:
        body, sig = (tok or "").split(".", 1)
        if not hmac.compare_digest(_b64(hmac.new(_key(), body.encode(), hashlib.sha256).digest()), sig):
            return None
        obj = json.loads(_unb64(body))
        return obj if obj.get("exp", 0) > time.time() else None
    except Exception:
        return None


def _cookie(name, value, max_age, path="/"):
    secure = "; Secure" if store.backend() == "postgres" else ""
    # Lax, not Strict: the way back from Microsoft is a cross-site navigation,
    # and a Strict cookie would not come along on it.
    return ("Set-Cookie", "%s=%s; Path=%s; HttpOnly; SameSite=Lax; Max-Age=%d%s" % (name, value, path, max_age, secure))


def user_from(cookie_jar):
    """The signed-in person from the request's cookies: {email, name, oid} or None."""
    m = cookie_jar.get(USER_COOKIE)
    obj = unseal(m.value) if m else None
    return {"email": obj["e"], "name": obj.get("n") or obj["e"], "oid": obj.get("o")} if obj and obj.get("e") else None


def safe_next(nxt):
    """Only a path on this site: never //host, a scheme or a backslash."""
    nxt = (nxt or "/").strip()
    if not nxt.startswith("/") or nxt.startswith("//") or "\\" in nxt or len(nxt) > 600:
        return "/"
    return nxt


# ---- Entra: discovery, keys, the code exchange ----------------------------------------

_DISC = {"at": 0, "doc": None}
_JWKS = {"at": 0, "keys": {}}


def _http(url, data=None):
    req = urllib.request.Request(url, data=data, headers={"Accept": "application/json", "User-Agent": "SplashHubCentre/1.0 (sign-in)"})
    if data is not None:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:                                              # Entra's own error code and description are safe to show
            j = json.loads(e.read() or b"{}")
            why = (j.get("error") or "") + (": " + str(j.get("error_description") or "").split("\r")[0][:160] if j.get("error_description") else "")
        except Exception:
            why = ""
        raise SignInError("Microsoft answered HTTP %d%s" % (e.code, (" (" + why + ")") if why else ""))
    except Exception as e:                                # URLError, timeouts, proxy refusals: never str(e)
        raise SignInError("could not reach %s (%s) -- is login.microsoftonline.com in the OUTBOUND_HTTP grant?"
                          % (urllib.parse.urlparse(url).netloc, type(e).__name__))


def discovery():
    if not _DISC["doc"] or time.time() - _DISC["at"] > 86400:
        _DISC["doc"] = _http("%s/%s/v2.0/.well-known/openid-configuration" % (LOGIN, urllib.parse.quote(TENANT_ID)))
        _DISC["at"] = time.time()
    return _DISC["doc"]


def _jwk(kid):
    if kid not in _JWKS["keys"] or time.time() - _JWKS["at"] > 86400:
        doc = _http(discovery()["jwks_uri"])
        _JWKS["keys"] = {k.get("kid"): k for k in doc.get("keys") or [] if k.get("kty") == "RSA"}
        _JWKS["at"] = time.time()
    k = _JWKS["keys"].get(kid)
    if not k:
        raise SignInError("Microsoft's signing key for this sign-in wasn't found")
    return k


_SHA256_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")


def _rs256_ok(signing_input, sig, jwk):
    """RSASSA-PKCS1-v1_5 with SHA-256, by hand (the standard library has no RSA)."""
    n = int.from_bytes(_unb64(jwk["n"]), "big")
    e = int.from_bytes(_unb64(jwk["e"]), "big")
    k = (n.bit_length() + 7) // 8
    s = int.from_bytes(sig, "big")
    if len(sig) != k or s >= n:
        return False
    em = pow(s, e, n).to_bytes(k, "big")
    t = _SHA256_PREFIX + hashlib.sha256(signing_input).digest()
    want = b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t
    return hmac.compare_digest(em, want)


def verify_id_token(tok, nonce):
    try:
        h64, p64, s64 = tok.split(".")
        head, claims, sig = json.loads(_unb64(h64)), json.loads(_unb64(p64)), _unb64(s64)
    except Exception:
        raise SignInError("Microsoft's answer could not be read")
    if head.get("alg") != "RS256" or not _rs256_ok((h64 + "." + p64).encode(), sig, _jwk(head.get("kid"))):
        raise SignInError("Microsoft's answer did not carry a valid signature")
    now = time.time()
    iss = discovery().get("issuer") or ""
    if "{tenantid}" in iss:
        iss = iss.replace("{tenantid}", str(claims.get("tid") or ""))
    if claims.get("iss") != iss:
        raise SignInError("the sign-in came from another directory")
    aud = claims.get("aud")
    if aud != CLIENT_ID and not (isinstance(aud, list) and CLIENT_ID in aud):
        raise SignInError("the sign-in was for another application")
    if not (claims.get("exp", 0) > now - 120 and claims.get("nbf", 0) < now + 300):
        raise SignInError("the sign-in had expired; please try again")
    if not nonce or not hmac.compare_digest(str(claims.get("nonce") or ""), nonce):
        raise SignInError("the sign-in didn't match this browser; please try again")
    return claims


# ---- the flow -------------------------------------------------------------------------

def start(nxt):
    """(Location, [cookie]) to send the browser to Microsoft."""
    if not configured():
        raise SignInError("company sign-in isn't set up yet (missing: %s)" % ", ".join(missing()))
    d = discovery()
    state, nonce, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    challenge = _b64(hashlib.sha256(verifier.encode()).digest())
    q = urllib.parse.urlencode({"client_id": CLIENT_ID, "response_type": "code", "redirect_uri": redirect_uri(),
                                "response_mode": "query", "scope": "openid profile email", "state": state, "nonce": nonce,
                                "code_challenge": challenge, "code_challenge_method": "S256"})
    flow = seal({"s": state, "n": nonce, "v": verifier, "x": safe_next(nxt), "exp": int(time.time()) + 600})
    return d["authorization_endpoint"] + "?" + q, [_cookie(FLOW_COOKIE, flow, 600, "/auth")]


def finish(params, cookie_jar):
    """The callback: (user, next, [cookies]). Raises SignInError."""
    m = cookie_jar.get(FLOW_COOKIE)
    flow = unseal(m.value) if m else None
    if params.get("error"):
        raise SignInError("Microsoft said: %s" % str(params.get("error_description") or params.get("error"))[:200])
    if not flow or not params.get("state") or not hmac.compare_digest(str(params.get("state")), str(flow.get("s"))):
        raise SignInError("this sign-in started in another tab or took too long; please try again")
    tok = _http(discovery()["token_endpoint"], urllib.parse.urlencode({
        "grant_type": "authorization_code", "code": params.get("code") or "", "redirect_uri": redirect_uri(),
        "client_id": CLIENT_ID, "client_secret": _secret(), "code_verifier": flow["v"], "scope": "openid profile email"}).encode())
    claims = verify_id_token(tok.get("id_token") or "", flow["n"])
    email = str(claims.get("email") or claims.get("preferred_username") or claims.get("upn") or "").strip().lower()
    if "@" not in email or email.rsplit("@", 1)[1] not in ALLOWED_DOMAINS:
        activity(email if "@" in email else None, "sign_in", "failed", error="not a company account")
        raise SignInError("%s isn't a Splashtop company account" % (email or "That account"))
    user = {"e": email, "n": str(claims.get("name") or "")[:120], "o": str(claims.get("oid") or claims.get("sub") or "")[:80],
            "exp": int(time.time()) + SESSION_HOURS * 3600}
    activity(email, "sign_in", "completed")
    try:
        record_sign_in(email, user["n"], user["o"])
    except Exception as e:                       # the People list is a nicety; never block a sign-in on it
        sys.stderr.write("[sign-in] people list not updated: %s\n" % type(e).__name__)
    return ({"email": email, "name": user["n"] or email, "oid": user["o"]}, flow.get("x") or "/",
            [_cookie(USER_COOKIE, seal(user), SESSION_HOURS * 3600), _cookie(FLOW_COOKIE, "", 0, "/auth")])


# ---- people and roles ---------------------------------------------------------------------
# Everyone who has signed in with Microsoft, with a role: member (every team page)
# or admin (also Logs, Settings, managing Downloads, and this list). Roles are read
# on each request (cached a few seconds), so a change applies at once -- no
# signing out. The admin password still works beside them, and is how the first
# admin is made.

ROLES = ("member", "admin")
_ROLE_CACHE = {}
_people_ready = False


def _people_table():
    global _people_ready
    if _people_ready:
        return
    store.ensure_schema()
    big = "BIGINT" if store.backend() == "postgres" else "INTEGER"
    c = store.connect(True)
    try:
        c.cursor().execute("CREATE TABLE IF NOT EXISTS people (email TEXT PRIMARY KEY, name TEXT, oid TEXT, "
                           "role TEXT NOT NULL DEFAULT 'member', first_ms %s, last_ms %s, signins %s NOT NULL DEFAULT 0, "
                           "role_by TEXT, role_ms %s)" % (big, big, big, big))
        c.commit()
    finally:
        c.close()
    _people_ready = True


def record_sign_in(email, name, oid):
    _people_table()
    now = int(time.time() * 1000)
    c = store.connect(True)
    try:
        cur = c.cursor()
        cur.execute(store._q("UPDATE people SET name = %s, oid = %s, last_ms = %s, signins = signins + 1 WHERE email = %s"),
                    [name or None, oid or None, now, email])
        if not cur.rowcount:
            cur.execute(store._q("INSERT INTO people (email, name, oid, role, first_ms, last_ms, signins) VALUES (%s,%s,%s,'member',%s,%s,1)"),
                        [email, name or None, oid or None, now, now])
        c.commit()
    finally:
        c.close()


def role_of(email):
    """'admin', 'member', or None for someone who never signed in here."""
    if not email:
        return None
    hit = _ROLE_CACHE.get(email)
    if hit and time.time() - hit[0] < 10:
        return hit[1]
    _people_table()
    rows = store._read("SELECT role FROM people WHERE email = %s", [email], fresh=True)
    role = rows[0][0] if rows else None
    _ROLE_CACHE[email] = (time.time(), role)
    return role


def set_role(email, role, by):
    if role not in ROLES:
        raise SignInError("Unknown role.")
    _people_table()
    c = store.connect(True)
    try:
        cur = c.cursor()
        cur.execute(store._q("UPDATE people SET role = %s, role_by = %s, role_ms = %s WHERE email = %s"),
                    [role, by, int(time.time() * 1000), (email or "").strip().lower()])
        found = cur.rowcount
        c.commit()
    finally:
        c.close()
    if not found:
        raise SignInError("%s hasn't signed in to SplashHub Centre yet." % email)
    _ROLE_CACHE.pop((email or "").strip().lower(), None)


def people():
    _people_table()
    cols = ("email", "name", "role", "first_ms", "last_ms", "signins", "role_by", "role_ms")
    return [dict(zip(cols, r)) for r in store._read("SELECT %s FROM people ORDER BY role = 'admin' DESC, last_ms DESC" % ", ".join(cols), [])]


def sign_out(user):
    if user:
        activity(user.get("email"), "sign_out", "completed")
    return [_cookie(USER_COOKIE, "", 0)]


def activity(user, feature, stage, error=None, run=None, detail=None):
    """One Spluki activity line on stdout (spluki doc user-activity-for-developers)."""
    line = {"spluki_activity": 1, "ts": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()), "login_type": "sso",
            "feature": feature, "stage": stage}
    if user:
        line["user"] = str(user)[:254]
    if run:
        line["run"] = str(run)[:64]
    if error:
        line["error"] = str(error)[:200]
    if detail:
        line["detail"] = str(detail)[:200]
    sys.stdout.write(json.dumps(line, separators=(",", ":")) + "\n")
    sys.stdout.flush()


# ---- the pages this flow shows itself (design F: brand panel with a fine grid) ----------

_MS = ('<svg width="16" height="16" viewBox="0 0 21 21" aria-hidden="true"><rect x="1" y="1" width="9" height="9" fill="#F25022"/>'
       '<rect x="11" y="1" width="9" height="9" fill="#7FBA00"/><rect x="1" y="11" width="9" height="9" fill="#00A4EF"/>'
       '<rect x="11" y="11" width="9" height="9" fill="#FFB900"/></svg>')
_LOCK_ICON = ('<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
              'stroke-linejoin="round" aria-hidden="true"><rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg>')
_DL_ICON = ('<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
            'stroke-linejoin="round" aria-hidden="true"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/>'
            '<line x1="12" y1="15" x2="12" y2="3"/></svg>')

_CSS = """
*{box-sizing:border-box}html,body{height:100%}
body{margin:0;font:14px/1.55 Poppins,system-ui,-apple-system,Segoe UI,sans-serif;color:#1D242C;background:#fff}
.wrap{display:grid;grid-template-columns:minmax(0,52fr) minmax(0,48fr);min-height:100vh}
.brand{position:relative;overflow:hidden;background:#0071CE;color:#fff;padding:40px 48px;display:flex;flex-direction:column}
.grid{position:absolute;inset:0;background-image:linear-gradient(rgba(255,255,255,.07) 1px,transparent 1px),
 linear-gradient(90deg,rgba(255,255,255,.07) 1px,transparent 1px);background-size:32px 32px}
.sweep{position:absolute;top:0;bottom:0;left:0;width:35%;background:linear-gradient(90deg,transparent,rgba(255,255,255,.09),transparent);
 animation:sweep 7s ease-in-out infinite}
@keyframes sweep{0%{transform:translateX(-120%)}60%,100%{transform:translateX(320%)}}
.logo{position:relative;height:30px;width:auto;align-self:flex-start}
.pitch{position:relative;margin-top:auto;max-width:440px;animation:up .7s ease both}
.pitch h1{font-size:30px;line-height:1.2;font-weight:600;margin:0 0 10px;letter-spacing:-.01em}
.pitch p{margin:0;font-size:15px;opacity:.88}
.tags{position:relative;display:flex;flex-wrap:wrap;gap:8px;margin-top:22px}
.tags span{font-size:12px;padding:5px 11px;border:1px solid rgba(255,255,255,.35);border-radius:999px;opacity:0;animation:up .6s ease forwards}
.side{display:flex;flex-direction:column;padding:40px 56px}
.form{margin:auto 0;width:100%;max-width:360px;animation:up .6s ease .15s both}
.form h2{font-size:24px;font-weight:600;margin:0 0 6px;letter-spacing:-.01em}
.form .lead{color:#5b6672;margin:0 0 26px}
.ms{display:flex;align-items:center;justify-content:center;gap:12px;width:100%;padding:12px 16px;border:1px solid #c9d3de;border-radius:8px;
 background:#fff;color:#1D242C;font:500 14px Poppins,system-ui,sans-serif;text-decoration:none;cursor:pointer;transition:border-color .2s,box-shadow .2s,background .2s}
.ms:hover{border-color:#0071CE;box-shadow:0 0 0 3px rgba(0,113,206,.12)}
.ms:focus-visible{outline:none;border-color:#0071CE;box-shadow:0 0 0 3px rgba(0,113,206,.25)}
.ms.busy{pointer-events:none;background:#f5f8fb}
.spin{width:16px;height:16px;border:2px solid #c9d3de;border-top-color:#0071CE;border-radius:50%;animation:spin .8s linear infinite;display:none}
.ms.busy .spin{display:block}.ms.busy svg{display:none}
@keyframes spin{to{transform:rotate(360deg)}}
.secure{display:flex;align-items:center;gap:7px;color:#6b7682;font-size:12.5px;margin-top:14px}
.alt{margin-top:28px;padding-top:20px;border-top:1px solid #eef2f6;font-size:13px;color:#5b6672}
.alt a{color:#0071CE;text-decoration:none;font-weight:500;display:inline-flex;align-items:center;gap:6px}
.alt a:hover{text-decoration:underline}
.err{background:#fef3f2;border:1px solid #fecdca;color:#b42318;border-radius:8px;padding:10px 12px;font-size:13px;margin:0 0 20px}
details{margin-top:18px;font-size:13px;color:#5b6672}summary{cursor:pointer}
details input{width:100%;padding:9px 11px;border:1px solid #c9d3de;border-radius:8px;font:inherit;margin:10px 0 8px}
details button{background:#0071CE;color:#fff;border:0;border-radius:8px;padding:9px 16px;font:500 13px Poppins,system-ui,sans-serif;cursor:pointer}
.pwerr{color:#b42318;min-height:1.2em;font-size:12.5px}
.foot{display:flex;justify-content:space-between;font-size:12px;color:#8a96a3}
@keyframes up{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}
@media (max-width:820px){.wrap{grid-template-columns:1fr}.brand{padding:24px;min-height:auto}.pitch{margin-top:36px}
 .pitch h1{font-size:24px}.side{padding:32px 24px}.form{margin:0 auto}}
@media (prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;transition:none!important}.tags span{opacity:1}}
"""


def _esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def page(title, side):
    """Design F: the blue brand panel (white Splashtop logo, fine grid, one slow
    light sweep) and the sign-in side. Self-contained but for the logo and font."""
    tags = "".join('<span style="animation-delay:%.2fs">%s</span>' % (0.35 + i * 0.08, t)
                   for i, t in enumerate(("SOS Scans", "SSO Requests", "Cases and AI", "PriceBook", "Reply Lab")))
    return ("<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            "<title>%s · SplashHub Centre</title><link rel=\"icon\" href=\"/splashtop-icon.png\">"
            "<link rel=\"preconnect\" href=\"https://fonts.googleapis.com\"><link rel=\"preconnect\" href=\"https://fonts.gstatic.com\" crossorigin>"
            "<link href=\"https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600&display=swap\" rel=\"stylesheet\">"
            "<style>%s</style></head><body><div class=\"wrap\">"
            "<section class=\"brand\"><div class=\"grid\"></div><div class=\"sweep\"></div>"
            "<img class=\"logo\" src=\"/splashtop-logo-white.png\" alt=\"Splashtop\" width=\"148\" height=\"30\">"
            "<div class=\"pitch\"><h1>SplashHub Centre</h1><p>SOS reviews, SSO checks, cases and pricing for the support team, in one place.</p></div>"
            "<div class=\"tags\">%s</div></section>"
            "<main class=\"side\"><div class=\"form\">%s</div>"
            "<div class=\"foot\"><span>&copy; Splashtop Inc.</span><span>Internal use only</span></div></main>"
            "</div></body></html>" % (_esc(title), _CSS, tags, side))


def _ms_button(label="Continue with Microsoft"):
    # The address bar's #part never reaches the server, so the link is finished
    # in the browser: sign in, then come back to exactly this page.
    return ("<a class=\"ms\" id=\"ms\" href=\"/auth/login\">%s<span class=\"spin\"></span><span id=\"msl\">%s</span></a>"
            "<div class=\"secure\">%sSecured by Microsoft Entra ID</div>"
            "<script>(function(){var a=document.getElementById('ms'),p=location.pathname;"
            "if(p.indexOf('/auth/')!==0){a.href='/auth/login?next='+encodeURIComponent(p+location.search+location.hash);}"
            "a.addEventListener('click',function(){a.classList.add('busy');document.getElementById('msl').textContent='Opening Microsoft sign-in\\u2026';});"
            "window.addEventListener('pageshow',function(){a.classList.remove('busy');document.getElementById('msl').textContent=%s;});})();</script>"
            % (_MS, label, _LOCK_ICON, json.dumps(label)))


def _downloads_link():
    return "<div class=\"alt\">Looking for the team&rsquo;s extensions? <a href=\"/downloads\">%sDownloads</a></div>" % _DL_ICON


def bounce_page():
    """What a signed-out visitor sees instead of a page: the sign-in landing."""
    return page("Sign in", "<h2>Welcome back</h2><p class=\"lead\">Sign in with your Splashtop work account to continue.</p>"
                + _ms_button() + _downloads_link())


def error_page(msg):
    return page("Sign-in problem",
                "<h2>Couldn&rsquo;t sign you in</h2><div class=\"err\">%s</div>" % _esc(msg)
                + _ms_button("Try again with Microsoft")
                + "<details><summary>Admins: sign in with the admin password</summary>"
                  "<form id=\"f\"><input type=\"password\" id=\"p\" placeholder=\"Admin password\" autocomplete=\"current-password\" aria-label=\"Admin password\">"
                  "<div class=\"pwerr\" id=\"e\" aria-live=\"polite\"></div><button type=\"submit\">Log in</button></form></details>"
                  "<script>document.getElementById('f').addEventListener('submit',function(ev){ev.preventDefault();"
                  "fetch('/login',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',"
                  "body:JSON.stringify({password:document.getElementById('p').value})}).then(function(r){if(r.ok){location.href='/logs';}"
                  "else{document.getElementById('e').textContent='That password isn\\u2019t right.';}});});</script>"
                + _downloads_link())


def signed_out_page():
    return page("Signed out", "<h2>You&rsquo;re signed out</h2><p class=\"lead\">Your Microsoft account stays signed in for Outlook, "
                "Teams and the rest.</p>" + _ms_button("Sign in again") + _downloads_link())
