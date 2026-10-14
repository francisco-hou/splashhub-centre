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
    return ({"email": email, "name": user["n"] or email, "oid": user["o"]}, flow.get("x") or "/",
            [_cookie(USER_COOKIE, seal(user), SESSION_HOURS * 3600), _cookie(FLOW_COOKIE, "", 0, "/auth")])


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


# ---- the few pages this flow shows itself ---------------------------------------------

def page(title, body):
    return ("<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            "<title>%s · SplashHub Centre</title><link rel=\"icon\" href=\"/splashtop-icon.png\"><style>"
            ":root{color-scheme:light}body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;"
            "background:#f5f8fb;font:15px/1.5 Poppins,system-ui,sans-serif;color:#14171c}"
            ".c{background:#fff;border:1px solid #dce7f2;border-radius:12px;padding:28px 32px;max-width:420px;margin:16px;"
            "box-shadow:0 10px 30px rgba(15,20,26,.06)}h1{font-size:18px;margin:10px 0 6px}p{color:#3d4650;margin:0 0 14px}"
            "a.b,button{display:inline-block;background:#0071ce;color:#fff;border:0;border-radius:8px;padding:9px 16px;"
            "font:inherit;text-decoration:none;cursor:pointer}small{color:#6b7682}input{width:100%%;box-sizing:border-box;"
            "padding:8px 10px;border:1px solid #dce7f2;border-radius:8px;font:inherit;margin:6px 0}.e{color:#b42318;min-height:1em}"
            "</style></head><body><div class=\"c\"><img src=\"/splashtop-icon.png\" alt=\"\" width=\"32\" height=\"32\">%s</div></body></html>"
            % (title, body))


def _esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def bounce_page():
    """Sent instead of a page while signed out: the address bar's #part never
    reaches the server, so the browser itself sends us to sign in, all of it."""
    return page("Signing in", "<h1>Signing you in…</h1><p>One moment.</p><script>location.replace('/auth/login?next=' + "
                "encodeURIComponent(location.pathname + location.search + location.hash));</script>")


def error_page(msg):
    return page("Sign-in problem",
                "<h1>Couldn&rsquo;t sign you in</h1><p>%s</p><p><a class=\"b\" href=\"/auth/login\">Try again</a></p>"
                "<details><summary><small>Admins: sign in with the admin password</small></summary>"
                "<form id=\"f\"><input type=\"password\" id=\"p\" placeholder=\"Admin password\" autocomplete=\"current-password\">"
                "<div class=\"e\" id=\"e\"></div><button type=\"submit\">Log in</button></form></details>"
                "<script>document.getElementById('f').addEventListener('submit',function(ev){ev.preventDefault();"
                "fetch('/login',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',"
                "body:JSON.stringify({password:document.getElementById('p').value})}).then(function(r){if(r.ok){location.href='/logs';}"
                "else{document.getElementById('e').textContent='That password isn\\u2019t right.';}});});</script>" % _esc(msg))


def signed_out_page():
    return page("Signed out", "<h1>You&rsquo;re signed out of SplashHub Centre</h1>"
                "<p>Your Microsoft account stays signed in for Outlook, Teams and the rest.</p>"
                "<p><a class=\"b\" href=\"/auth/login\">Sign in again</a></p>")
