"""Custom SOS package brand scan -- run by SplashHub Centre, stored here only.

The same review as SplashHub's sidebar "Scan Custom SOS PKG" button (scan.js):
the same system prompt, output schema, creator / [Label] extraction and
thumbnail selection, so a verdict means the same thing in both places. The
difference is where it runs and where it goes: started by a Zendesk webhook (or
the "Scan a ticket" box on the SOS Scans page), and stored in the sos_scans
table. NOTHING is written back to Zendesk.

Keep SYSTEM_PROMPT / OUTPUT_SCHEMA in step with scan.js -- change both together.

AI: the CUSTOM_AI grant (AI_BASE_URL, AI_API_KEY, AI_MODELS -- the first model
is used). Zendesk: zendesk.py (read-only).
"""
import base64, hashlib, json, os, queue, re, sys, threading, time, urllib.error, urllib.request

import imagestore
import store
import zendesk

SUPPORTED_IMAGE_TYPES = ("image/png", "image/jpeg", "image/gif", "image/webp")
MAX_IMAGES_PER_SCAN = 8
AI_TIMEOUT = 240
# USD per 1M tokens, as SplashHub's sidebar prices it (sidebar.js MODEL_PRICING_PER_MTOK).
PRICING = {"claude-opus-4-8": (5.00, 25.00), "claude-opus-4-6": (5.00, 25.00), "claude-sonnet-5": (3.00, 15.00)}

FREE_EMAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "yahoo.com", "outlook.com", "hotmail.com", "live.com", "icloud.com", "me.com",
    "aol.com", "protonmail.com", "proton.me", "gmx.com", "mail.com", "zoho.com", "qq.com", "163.com", "126.com"}
CREATOR_TAG_RE = re.compile(r"\[\s*creator\s*\]\s*[:\-]?\s*([\w.+-]+@[\w.-]+\.[A-Za-z]{2,})", re.I)
TICKET_FIELD_RE = re.compile(r"\[([^\]\n]{1,64})\]\s*([^\n]*)")
TEAM_INFO_RE = re.compile(r"Team info\s*\((https?://[^\s)]+)\)", re.I)
WEBSITE_THUMB_RE = re.compile(r"^website_thumbnail(\s*\(\d+\))?\.[a-z0-9]+$", re.I)
THUMB_RE = re.compile(r"^thumbnail(\s*\(\d+\))?\.[a-z0-9]+$", re.I)

# ---- policy: verbatim from scan.js -------------------------------------------------
SYSTEM_PROMPT = """You review customer-submitted branding assets (icons, splash screens, login/UI \
screenshots) for custom builds of Splashtop's white-labeled remote-support ("SOS") client.

HARD RULE — classify every image's Splashtop reference into exactly one bucket:
- "none": no Splashtop reference (fully custom, or an unrelated third-party brand).
- "powered_by_attribution": only a small "Powered by Splashtop"-style credit. Acceptable, not suspicious.
- "unmodified_default": Splashtop's own logo/wordmark/default UI is visible (e.g. "Splashtop SOS" title \
bar, "Connecting to Splashtop servers..." status text) — even alongside a different page/company name \
elsewhere in the same image. This is normal partial customization, not misleading by itself; never \
mark suspicious for this alone. If that default status text looks garbled/low-res, ignore it — don't \
mention the garbling at all.
- "other_reference": Splashtop referenced in misleading TEXT only — an attribution phrased "by \
Splashtop" without "Powered" (e.g. "SOS by Splashtop") or equivalent wording. Fixed policy violation: \
verdict MUST be "suspicious", never downgraded. Logo/wordmark presence alone (no misleading text) does \
NOT qualify — use "unmodified_default" instead.

Only when splashtop_reference is "none", "powered_by_attribution", or "unmodified_default", judge the \
non-Splashtop branding: normal self-branding (a company's own name/logo/identity) vs. signs of \
impersonating a different, unaffiliated brand — reused logo/trademark, mimicked visual identity, \
typosquatting, mismatched branding across assets, or naming that invokes an authority (bank, government, \
well-known tech company) this customer wouldn't legitimately represent.

Use the creator's email domain as corroborating evidence, not a sole determinant: a plausible match \
supports "normal"; a clear mismatch with a well-known unrelated company is a strong "suspicious" signal; \
a generic webmail domain carries no signal either way. Ignore this factor entirely if no domain was \
provided or splashtop_reference is "other_reference".

Separately, set "creator_domain_is_generic_email" (true/false) using your own knowledge of free/consumer \
webmail and disposable-email providers worldwide — not just gmail/outlook/yahoo, but regional ones too \
(qq.com, mail.ru, web.de, naver.com, etc). False for a company's own domain or if none was given.

Don't over-flag: original/generic/stock-style branding with no Splashtop violation is normal. Reserve \
"suspicious" for a concrete, describable reason to suspect brand misuse; use "needs_review" when \
something's off but you're not confident it's impersonation.

SEPARATE CHECK — ticket/package metadata (independent of the image findings above): given any \
"[Label] value" fields extracted from the ticket (Package Name, Subscription, Caption, Instruction \
Text, etc.), produce one "ticket_review" verdict. Flag naming/wording that reads as a social-engineering \
pretext (e.g. "Fraud Investigation", "IRS", "Account Suspended", impersonating a known company's support \
team) or Instruction Text designed to trick someone into sharing a session code — a common tech-support \
scam pattern. Ordinary descriptive names (the requester's own company, "IT Support") are normal. Set \
"not_applicable" if no metadata was provided; otherwise "suspicious" for a concrete pretext, \
"needs_review" if ambiguous, "normal" otherwise."""

OUTPUT_SCHEMA = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "overall_summary": {"type": "string", "description": "One short sentence overall summary across all images reviewed."},
            "creator_domain_is_generic_email": {
                "type": "boolean",
                "description": "True if the request creator's email domain is any free/consumer webmail or "
                               "disposable-email provider (worldwide, not just well-known US ones) rather than a company's "
                               "own domain. False if it's a company domain, or no creator domain was provided."},
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "image_index": {"type": "integer", "description": "0-based index matching the order images were provided in."},
                        "splashtop_reference": {
                            "type": "string",
                            "enum": ["none", "powered_by_attribution", "unmodified_default", "other_reference"],
                            "description": '"none": no Splashtop reference. "powered_by_attribution": only a small '
                                           '"Powered by Splashtop"-style credit (acceptable). "unmodified_default": Splashtop\'s own '
                                           'logo/wordmark/default UI visible, even alongside a different brand name/logo (acceptable — '
                                           'partial customization, not misleading by itself). "other_reference": misleading TEXT only, '
                                           'a bare "by Splashtop" attribution — per the hard rule this always forces verdict "suspicious".'},
                        "verdict": {"type": "string", "enum": ["normal", "suspicious", "needs_review"]},
                        "confidence": {"type": "number", "description": "0 to 1 confidence in this verdict."},
                        "detected_brand_references": {
                            "type": "array", "items": {"type": "string"},
                            "description": "Any real company/brand names or trademarks the image appears to reference, empty if none."},
                        "domain_consistency": {
                            "type": "string", "enum": ["consistent", "inconsistent", "unclear", "not_applicable"],
                            "description": "Whether detected brand references are consistent with the request creator's email domain/company. "
                                           '"not_applicable" when splashtop_reference is "other_reference", no creator domain was provided, '
                                           "no brand was detected, or the domain is a generic webmail provider."},
                        "flagged_elements": {
                            "type": "array", "items": {"type": "string"},
                            "description": "Specific concrete things that drove the verdict (empty if verdict is normal)."},
                        "summary": {"type": "string", "description": "One short sentence explaining the verdict."}
                    },
                    "required": ["image_index", "splashtop_reference", "verdict", "confidence", "detected_brand_references",
                                 "domain_consistency", "flagged_elements", "summary"],
                    "additionalProperties": False
                }
            },
            "ticket_review": {
                "type": "object",
                "description": "Verdict on the ticket's own [Label] metadata fields (Package Name, Subscription, "
                               "Caption, Instruction Text, etc.) — independent of the per-image findings above.",
                "properties": {
                    "verdict": {"type": "string", "enum": ["normal", "suspicious", "needs_review", "not_applicable"]},
                    "flagged_fields": {
                        "type": "array", "items": {"type": "string"},
                        "description": "Which metadata field(s) raised concern and why. Empty if verdict is normal or not_applicable."},
                    "summary": {"type": "string", "description": "One short sentence explaining the verdict."}
                },
                "required": ["verdict", "flagged_fields", "summary"],
                "additionalProperties": False
            }
        },
        "required": ["overall_summary", "creator_domain_is_generic_email", "findings", "ticket_review"],
        "additionalProperties": False
    }
}


class ScanError(Exception):
    """A message safe to show and store."""


# ---- reading the ticket (the scan.js helpers, in Python) ---------------------------

def _url_name(url):
    try:
        from urllib.parse import urlparse, parse_qs
        return (parse_qs(urlparse(url).query).get("name") or [""])[0]
    except Exception:
        return ""


def pick_images(comments):
    """website_thumbnail first, then plain thumbnail; the sd_/android_/ios_
    variants are left out, as in the sidebar."""
    seen, primary, fallback = set(), [], []
    for c in comments:
        for a in c.get("attachments") or []:
            if a.get("id") in seen or a.get("content_type") not in SUPPORTED_IMAGE_TYPES:
                continue
            fn, un = a.get("file_name") or "", _url_name(a.get("content_url") or "")
            is_primary = bool(WEBSITE_THUMB_RE.match(fn) or WEBSITE_THUMB_RE.match(un))
            if not is_primary and not (THUMB_RE.match(fn) or THUMB_RE.match(un)):
                continue
            seen.add(a.get("id"))
            (primary if is_primary else fallback).append(
                {"id": a.get("id"), "filename": fn or un, "content_type": a.get("content_type"), "content_url": a.get("content_url")})
    return (primary + fallback)[:MAX_IMAGES_PER_SCAN]


def label_fields(subject, description, comments):
    text = "\n".join(s for s in [subject, description] + [c.get("plain_body") or c.get("body") or "" for c in comments] if s)
    seen, fields = set(), []
    for m in TICKET_FIELD_RE.finditer(text):
        label, value = m.group(1).strip(), m.group(2).strip()
        if not label or label.lower() in seen:
            continue
        seen.add(label.lower())
        fields.append({"label": label, "value": value})
    if "team info" not in seen:
        m = TEAM_INFO_RE.search(text)
        if m:
            fields.append({"label": "Team info", "value": m.group(1)})
    return fields


LINK_LINE_RE = re.compile(r"^\s*([^\[\]\n()]{1,60}?)\s*\((https?://[^\s)]+)\)\s*$", re.M)
# Like TICKET_FIELD_RE, but the value stops at the end of its own line: an empty
# "[Disclaimer]" must not take the next line as its value. (TICKET_FIELD_RE --
# kept identical to scan.js for the AI's input -- does exactly that.)
FIELD_LINE_RE = re.compile(r"\[([^\]\n]{1,64})\][ \t]*([^\n]*)")


def parse_request(text):
    """The request as the page shows it, from the ticket's FIRST message only:
    every "[Label] value" line in order (empty values kept -- an empty
    [Disclaimer] is itself information) and every "Label (https://...)" line as
    a link (Team info, Download Package, Manage)."""
    text = text or ""
    fields, seen = [], set()
    for m in FIELD_LINE_RE.finditer(text):
        label, value = m.group(1).strip(), m.group(2).strip()
        if label and label.lower() not in seen:
            seen.add(label.lower())
            fields.append({"label": label, "value": value})
    links = [{"label": m.group(1).strip(), "url": m.group(2)} for m in LINK_LINE_RE.finditer(text)]
    return {"fields": fields, "links": links}


def all_images(comments, limit=24):
    """Every image on the ticket, in the order it arrived -- the gallery. The AI
    still reviews only pick_images()'s thumbnails, as the sidebar does."""
    seen, out = set(), []
    for c in comments:
        for a in c.get("attachments") or []:
            if a.get("id") in seen or a.get("content_type") not in SUPPORTED_IMAGE_TYPES:
                continue
            seen.add(a.get("id"))
            out.append({"id": a.get("id"), "filename": a.get("file_name") or _url_name(a.get("content_url") or "") or "image",
                        "content_type": a.get("content_type"), "content_url": a.get("content_url"), "size": a.get("size")})
    return out[:limit]


def creator(t, comments):
    tagged = None
    for s in [t["subject"], t["description"]] + [c.get("plain_body") or c.get("body") or "" for c in comments]:
        m = CREATOR_TAG_RE.search(s or "")
        if m:
            tagged = m.group(1)
            break
    email = tagged or t["requester_email"] or ""
    domain = email.split("@")[-1].lower() if "@" in email else ""
    return {"email": email, "domain": domain, "is_free": domain in FREE_EMAIL_DOMAINS,
            "source": "[Creator] tag found in ticket text" if tagged else ("Zendesk ticket requester" if t["requester_email"] else "none"),
            "requester_email": t["requester_email"], "organization": t["organization"]}


def creator_text(c):
    if not c["email"]:
        return "Request creator email domain: unknown (no [Creator] tag or Zendesk requester email on file)."
    parts = ["Request creator email: %s (source: %s)" % (c["email"], c["source"]),
             "Request creator email domain: " + c["domain"] +
             (" (generic consumer webmail provider — not a company signal)" if c["is_free"] else "")]
    if c["source"].startswith("[Creator]") and c["requester_email"] and c["requester_email"] != c["email"]:
        parts.append("(Note: this differs from the Zendesk ticket requester, %s — likely a shared/system account for "
                     "this ticket source, so the [Creator] tag was used instead.)" % c["requester_email"])
    if c["organization"]:
        parts.append("Zendesk organization on file: " + c["organization"])
    return "\n".join(parts)


def fields_text(fields):
    if not fields:
        return "No structured package/subscription [Label] metadata block was found in this ticket's text."
    return ("Structured package/subscription metadata auto-extracted from the ticket's text:\n" +
            "\n".join("- %s: %s" % (f["label"], f["value"]) for f in fields))


# ---- the review ----------------------------------------------------------------------

def ai_config():
    base = (os.environ.get("AI_BASE_URL") or "").strip().rstrip("/")
    key = (os.environ.get("AI_API_KEY") or "").strip()
    models = [m.strip() for m in (os.environ.get("AI_MODELS") or "").split(",") if m.strip()]
    return base, key, (models[0] if models else "claude-opus-4-8")


def missing_config():
    base, key, _ = ai_config()
    out = zendesk.configured()
    if not base:
        out.append("AI_BASE_URL")
    if not key:
        out.append("AI_API_KEY")
    return out


def call_claude(images, b64s, ctext, ftext):
    base, key, model = ai_config()
    blocks = []
    for i, (img, data) in enumerate(zip(images, b64s)):
        blocks.append({"type": "text", "text": "Image index %d — filename: %s" % (i, img["filename"])})
        blocks.append({"type": "image", "source": {"type": "base64", "media_type": img["content_type"], "data": data}})
    instruction = ("Review the %d image(s) above per your instructions — the Splashtop reference hard rule first, "
                   "then brand impersonation vs. normal self-branding. Return one finding per image, using the "
                   "image_index values given above. Also produce ticket_review for the ticket metadata above." % len(images)
                   if images else
                   "There are no image attachments to review — return an empty findings array. Produce "
                   "ticket_review for the ticket metadata above.")
    body = {"model": model, "max_tokens": 8000, "thinking": {"type": "adaptive"},
            "output_config": {"effort": "high", "format": OUTPUT_SCHEMA}, "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": [{"type": "text", "text": ctext}, {"type": "text", "text": ftext}]
                          + blocks + [{"type": "text", "text": instruction}]}]}
    req = urllib.request.Request(base + "/v1/messages", data=json.dumps(body).encode(), method="POST",
                                 headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=AI_TIMEOUT) as r:
            res = json.loads(r.read())
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = ((json.loads(e.read() or b"{}").get("error") or {}).get("message") or "")[:200]
        except Exception:
            pass
        hint = {401: "the Claude API key was refused", 403: "the Claude API key may not use this model",
                429: "Anthropic rate limit", 529: "Anthropic is overloaded"}.get(e.code, "")
        raise ScanError("Claude answered HTTP %d%s%s" % (e.code, (" -- " + hint) if hint else "", (": " + detail) if detail else ""))
    except Exception as e:     # never str(e): see zendesk.py
        raise ScanError("could not reach the Claude API (%s) -- is the CUSTOM_AI grant approved?" % type(e).__name__)
    if res.get("stop_reason") == "refusal":
        raise ScanError("Claude declined to analyze these images (safety refusal).")
    text = next((b.get("text") for b in res.get("content") or [] if b.get("type") == "text"), None)
    if not text:
        raise ScanError("Claude's answer had no text to read" + (" (cut off at max_tokens)" if res.get("stop_reason") == "max_tokens" else ""))
    try:
        parsed = json.loads(text)
    except ValueError:
        raise ScanError("Claude's answer was not the expected JSON")
    return parsed, res.get("usage") or {}, res.get("model") or model


RANK = {"suspicious": 3, "needs_review": 2, "normal": 1}


def overall(parsed):
    vs = [f.get("verdict") for f in parsed.get("findings") or []] + [(parsed.get("ticket_review") or {}).get("verdict")]
    vs = [v for v in vs if v in RANK]
    return max(vs, key=RANK.get) if vs else "normal"


def cost_of(usage, model):
    pi, po = PRICING.get(model, PRICING["claude-opus-4-8"])
    return (usage.get("input_tokens", 0) or 0) / 1e6 * pi + (usage.get("output_tokens", 0) or 0) / 1e6 * po


def save_gallery(ticket_id, comments, reviewed):
    """Download every image on the ticket once and keep a copy of each.
    Returns (gallery entries for the page, bytes by attachment id for the
    review). A gallery image that fails is noted and skipped; one the AI must
    review that fails stops the scan, as it always has."""
    rev = {img["id"]: i for i, img in enumerate(reviewed)}
    gallery, data_by_id = [], {}
    for img in all_images(comments):
        entry = {"id": img["id"], "filename": img["filename"], "content_type": img["content_type"],
                 "reviewed_index": rev.get(img["id"])}
        try:
            data, _ = zendesk.download(img["content_url"])
            data_by_id[img["id"]] = data
            entry["bytes"] = len(data)
            try:
                k = imagestore.key_for(ticket_id, img["id"], img["filename"])
                imagestore.store().put(k, data, img["content_type"])
                entry["key"] = k
            except Exception as e:
                entry["error"] = "could not keep a copy (%s)" % type(e).__name__
        except zendesk.ZendeskError as e:
            entry["error"] = str(e)
        gallery.append(entry)
    for img in reviewed:                      # not in the gallery (over its cap) or failed there
        if img["id"] not in data_by_id:
            data_by_id[img["id"]] = zendesk.download(img["content_url"])[0]
    return gallery, data_by_id


def ai_review_on():
    """The team switch on the SOS Scans page. Off until someone turns it on --
    and it applies only to requests that arrive while it is on: nothing held
    earlier, and no imported past request, is ever reviewed after the fact."""
    return store.get_setting("ai_review", "off") == "on"


def _now():
    return int(time.time() * 1000)


def run_scan(scan_id, ticket_id, force=False):
    """One request, start to finish. Every outcome is written to its row.

    1. The ticket's details and images: read from Zendesk when SplashHub Centre
       may (copies of every image kept); otherwise what the trigger sent stays.
    2. The AI review -- only if the switch was on when the request came in.
    """
    row = store.scan_get(scan_id, fresh=True) or {}
    store.scan_update(scan_id, status="running")
    try:
        # Decided when the request arrived (request() stamps it), never now.
        review = row.get("ai_review") == "on" and row.get("source") != "import"
        fetched, zd_note = False, ""
        images, data_by_id, who, fields = [], {}, None, []
        if not zendesk.configured():
            try:
                t = zendesk.ticket(ticket_id)
                cs = zendesk.comments(ticket_id)
                images = pick_images(cs)
                fields = label_fields(t["subject"], t["description"], cs)
                who = creator(t, cs)
                common = dict(subject=t["subject"][:300], creator_email=who["email"] or None,
                              creator_domain=who["domain"] or None, creator_source=who["source"],
                              organization=who["organization"] or None, fields_json=json.dumps(fields),
                              images_json=json.dumps([{k: i[k] for k in ("id", "filename", "content_type", "content_url")} for i in images]),
                              description=(t["description"] or "")[:20000])
                gallery, data_by_id = save_gallery(ticket_id, cs, images)
                store.scan_update(scan_id, gallery_json=json.dumps(gallery), **common)
                fetched = True
            except zendesk.ZendeskError as e:
                zd_note = str(e)
        else:
            zd_note = "SplashHub Centre has no Zendesk login yet"

        has_details = fetched or bool(row.get("description") or row.get("gallery_json"))
        if not has_details:
            # Nothing to show yet: keep it, and try again at the next start-up.
            store.scan_update(scan_id, status="waiting",
                              error="Waiting for Zendesk access (%s). Tried again every 10 minutes." % zd_note)
            return
        shown_from = "" if fetched else " The details and images below are what Zendesk's trigger sent."

        if not review:
            store.scan_update(scan_id, status="held", finished_ms=_now(),
                              error=("Past request -- listed for reference, never reviewed by AI." if row.get("source") == "import"
                                     else "AI review is off -- details and images only.") + shown_from)
            return
        if fields == [] and not images and fetched:
            store.scan_update(scan_id, status="skipped", finished_ms=_now(),
                              error="No thumbnail images or [Label] package fields on this ticket.")
            return
        miss = missing_config()
        if miss or not fetched:
            store.scan_update(scan_id, status="waiting",
                              error="The AI review is waiting for " + ("setup (missing " + ", ".join(miss) + ")" if miss else
                                                                       "Zendesk access (%s)" % zd_note) + "." + shown_from)
            return
        key = hashlib.sha256(",".join(str(i["id"]) for i in images).encode()).hexdigest()[:24]
        if not force:
            prev = store.scan_done_for(ticket_id, key)
            if prev:
                store.scan_update(scan_id, status="skipped", finished_ms=_now(), attach_key=key,
                                  error="Already reviewed with these same images (scan #%d)." % prev)
                return
        b64s = [base64.b64encode(data_by_id[img["id"]]).decode() for img in images]
        parsed, usage, model = call_claude(images, b64s, creator_text(who), fields_text(fields))
        cost = cost_of(usage, model)
        verdict = overall(parsed)
        store.scan_update(scan_id, status="done", verdict=verdict, finished_ms=_now(), attach_key=key,
                          result_json=json.dumps(parsed), model=model, input_tokens=usage.get("input_tokens", 0) or 0,
                          output_tokens=usage.get("output_tokens", 0) or 0, cost=cost, error=None)
        # Its cost on the Logs page, next to the sidebar's own scans.
        store.insert_many([{"when": _now(), "agent": "SplashHub Centre", "kind": "brand scan (auto)",
                            "model": model, "topic": "#%d custom SOS package · %s" % (int(ticket_id), verdict),
                            "tickets": 1, "input_tokens": usage.get("input_tokens", 0), "output_tokens": usage.get("output_tokens", 0),
                            "cost": cost, "source": "centre"}])
    except (ScanError, zendesk.ZendeskError) as e:
        store.scan_update(scan_id, status="error", finished_ms=_now(), error=str(e)[:500])
    except Exception as e:    # a bug: say what kind, never the text
        sys.stderr.write("[scan] #%s failed: %s\n" % (ticket_id, type(e).__name__))
        store.scan_update(scan_id, status="error", finished_ms=_now(),
                          error="internal error (%s) -- see the app log" % type(e).__name__)


# ---- the queue: one scan at a time, off the webhook loop ------------------------------
_Q = queue.Queue()
_started = False
_lock = threading.Lock()


def _worker():
    while True:
        scan_id, ticket_id, force = _Q.get()
        sys.stderr.write("[scan] #%s started (scan %s)\n" % (ticket_id, scan_id))
        run_scan(scan_id, ticket_id, force)
        row = store.scan_get(scan_id, fresh=True) or {}
        why = (" -- " + (row.get("error") or "")[:300]) if row.get("status") in ("waiting", "error") else ""
        sys.stderr.write("[scan] #%s %s%s%s\n" % (ticket_id, row.get("status"),
                                                 (" " + row["verdict"]) if row.get("verdict") else "", why))


IMAGE_EXT = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp"}


def _zendesk_link(url):
    """Only links to Zendesk's own attachment hosts are kept for the gallery."""
    from urllib.parse import urlparse
    try:
        u = urlparse(url)
    except ValueError:
        return False
    return u.scheme == "https" and (u.netloc.endswith(".zendesk.com") or u.netloc.endswith(".zdusercontent.com"))


def pushed_details(data):
    """What the Zendesk trigger sent about the ticket, so the request card and
    the images show even before SplashHub Centre may call Zendesk itself.
    Empty when the trigger sends only the ticket id."""
    desc = str(data.get("description") or "")
    if not desc and not data.get("attachments"):
        return None
    gallery = []
    for i, part in enumerate(str(data.get("attachments") or "").split(";;")):
        part = part.strip()
        if not part:
            continue
        name, _, url = part.rpartition("|") if "|" in part else ("", "", part)
        url, name = url.strip(), (name.strip() or _url_name(url.strip()) or "image")
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if ext not in IMAGE_EXT or not _zendesk_link(url):
            continue
        gallery.append({"id": i + 1, "filename": name[:200], "content_type": IMAGE_EXT[ext], "url": url, "reviewed_index": None})
    return {"subject": str(data.get("subject") or "")[:300], "requester": str(data.get("requester") or "")[:200],
            "description": desc[:20000], "gallery": gallery[:24]}


def _apply_pushed(scan_id, p):
    t = {"subject": p["subject"], "description": p["description"], "requester_email": p["requester"], "organization": ""}
    who = creator(t, [])
    store.scan_update(scan_id, subject=p["subject"] or None, description=p["description"] or None,
                      creator_email=who["email"] or None, creator_domain=who["domain"] or None, creator_source=who["source"],
                      fields_json=json.dumps(label_fields(p["subject"], p["description"], [])),
                      gallery_json=json.dumps(p["gallery"]))


def request(ticket_id, source, requested_by=None, force=False, pushed=None):
    """Queue a scan; returns the new row's id. `pushed`: what the trigger sent
    about the ticket (pushed_details), shown until the full scan replaces it."""
    global _started
    with _lock:
        if not _started:
            threading.Thread(target=_worker, name="sos-scan", daemon=True).start()
            _started = True
    scan_id = store.scan_create(ticket_id, source, requested_by)
    store.scan_update(scan_id, ai_review="on" if (source != "import" and ai_review_on()) else "off")
    if pushed:
        _apply_pushed(scan_id, pushed)
    _Q.put((scan_id, int(ticket_id), force))
    return scan_id


RETRY_EVERY = 600     # seconds between retries of requests still waiting


def _retry_waiting():
    """Requests waiting on Zendesk or setup are tried again every few minutes,
    so fixing a credential or a grant takes effect without a restart."""
    while True:
        time.sleep(RETRY_EVERY)
        try:
            rows = store.scans(verdict="waiting", per_page=200)["rows"]
            for r in rows:
                store.scan_update(r["id"], status="queued")
                request_existing(r["id"], r["ticket_id"])
            if rows:
                sys.stderr.write("[scan] retrying %d waiting request(s)\n" % len(rows))
        except Exception as e:
            sys.stderr.write("[scan] retry pass failed: %s\n" % type(e).__name__)


def start_retries():
    threading.Thread(target=_retry_waiting, name="sos-retry", daemon=True).start()


def requeue_unfinished():
    """After a restart: rows left queued/running by the previous container."""
    rows = []
    for st in ("queued", "running", "waiting"):
        rows += store.scans(verdict=st, per_page=200)["rows"]
    for r in rows:
        store.scan_update(r["id"], status="queued")
        request_existing(r["id"], r["ticket_id"])


def request_existing(scan_id, ticket_id):
    global _started
    with _lock:
        if not _started:
            threading.Thread(target=_worker, name="sos-scan", daemon=True).start()
            _started = True
    _Q.put((scan_id, int(ticket_id), False))


# ---- past requests: imported from Zendesk by SplashHub Centre itself -------------------
# The "Import past SOS requests" button on the SOS Scans page. Finds every
# ticket whose subject starts "New SOS package created by ...", keeps copies of
# the images, and lists each as a past request at its own creation date. Never
# reviewed by AI. Tickets already listed are skipped, so the button can be
# pressed again to pick up anything new.
#
# Matched by SUBJECT ONLY. The package system files these from
# be-admin@my-mail.splashtop.com, but agents often change the requester to the
# real customer afterwards, so a requester filter would miss older tickets.
# (The Zendesk trigger can keep its requester condition: it is checked at
# creation, before anyone has changed it.)

SOS_SUBJECT = "New SOS package created by"

IMPORT = {"running": False, "found": 0, "done": 0, "added": 0, "skipped": 0, "error": None,
          "started_ms": None, "finished_ms": None}
_import_lock = threading.Lock()


def import_status():
    return dict(IMPORT)


def _import_one(t):
    tid = int(t["id"])
    cs = zendesk.comments(tid)
    gallery, _ = save_gallery(tid, cs, [])
    try:
        from datetime import datetime
        created = int(datetime.fromisoformat(str(t.get("created_at")).replace("Z", "+00:00")).timestamp() * 1000)
    except (TypeError, ValueError):
        created = _now()
    desc = (t.get("description") or "")[:20000]
    # Creator from the [Creator] line only: the requester is either the system
    # account (not a person) or whoever an agent changed it to later.
    who = creator({"subject": t.get("subject") or "", "description": desc, "requester_email": "",
                   "organization": ""}, cs)
    sid = store.scan_create(tid, "import", "Past request import")
    store.scan_update(sid, requested_ms=created, finished_ms=created, status="held", ai_review="off",
                      subject=(t.get("subject") or "")[:300], description=desc or None,
                      creator_email=who["email"] or None, creator_domain=who["domain"] or None, creator_source=who["source"],
                      fields_json=json.dumps(label_fields(t.get("subject") or "", desc, cs)), gallery_json=json.dumps(gallery),
                      error="Past request -- listed for reference, never reviewed by AI.")


def _run_import():
    try:
        if zendesk.configured():
            raise ScanError("SplashHub Centre has no Zendesk login yet (missing " + ", ".join(zendesk.configured()) + ")")
        found = []
        for t in zendesk.search_tickets('type:ticket subject:"%s"' % SOS_SUBJECT):
            if str(t.get("subject") or "").startswith(SOS_SUBJECT):   # search matches words; keep true subjects
                found.append(t)
                IMPORT["found"] = len(found)
        have = store.scan_ticket_ids([t["id"] for t in found])
        for t in found:
            if int(t["id"]) in have:
                IMPORT["skipped"] += 1
            else:
                try:
                    _import_one(t)
                    IMPORT["added"] += 1
                except zendesk.ZendeskError as e:
                    sys.stderr.write("[import] #%s: %s\n" % (t.get("id"), e))
                    IMPORT["skipped"] += 1
            IMPORT["done"] += 1
    except (ScanError, zendesk.ZendeskError) as e:
        IMPORT["error"] = str(e)[:400]
    except Exception as e:
        IMPORT["error"] = "internal error (%s) -- see the app log" % type(e).__name__
        sys.stderr.write("[import] failed: %s\n" % type(e).__name__)
    finally:
        IMPORT["running"] = False
        IMPORT["finished_ms"] = _now()
        sys.stderr.write("[import] finished: %d found, %d added, %d skipped%s\n" % (
            IMPORT["found"], IMPORT["added"], IMPORT["skipped"], (" -- " + IMPORT["error"]) if IMPORT["error"] else ""))


def start_import():
    """Start the import in the background; False if one is already running."""
    with _import_lock:
        if IMPORT["running"]:
            return False
        IMPORT.update(running=True, found=0, done=0, added=0, skipped=0, error=None, started_ms=_now(), finished_ms=None)
    threading.Thread(target=_run_import, name="sos-import", daemon=True).start()
    return True
