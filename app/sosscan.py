"""Custom SOS package brand scan -- run by SplashHub Centre, stored here.

The same review as SplashHub's sidebar "Scan Custom SOS PKG" button (scan.js):
the same system prompt, output schema, creator / [Label] extraction and
thumbnail selection, so a verdict means the same thing in both places. The
difference is where it runs and where it goes: started by a Zendesk webhook (or
the "Scan a ticket" box on the SOS Scans page), and stored in the sos_scans
table. The one write to Zendesk is an internal note with a review, and only
when an agent presses "Add as internal note" (add_note).

Keep SYSTEM_PROMPT / OUTPUT_SCHEMA in step with scan.js -- change both together.

AI: the CUSTOM_AI grant (AI_BASE_URL, AI_API_KEY, AI_MODELS -- the first model
is used). Zendesk: zendesk.py. Images are never stored: the page shows them
from Zendesk, and a review downloads the ones it checks, in memory.
"""
import base64, hashlib, json, os, queue, re, sys, threading, time, urllib.error, urllib.request

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
    return _messages(body, model, "Claude declined to analyze these images (safety refusal).")


def _messages(body, model, refused):
    """POST one Messages API request through CUSTOM_AI; the parsed JSON answer,
    usage and model. Errors are worded here (never str(e) of a network error)."""
    base, key, _ = ai_config()
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
        raise ScanError(refused)
    text = next((b.get("text") for b in res.get("content") or [] if b.get("type") == "text"), None)
    if not text:
        raise ScanError("Claude's answer had no text to read" + (" (cut off at max_tokens)" if res.get("stop_reason") == "max_tokens" else ""))
    try:
        parsed = json.loads(text)
    except ValueError:
        raise ScanError("Claude's answer was not the expected JSON")
    return parsed, res.get("usage") or {}, res.get("model") or model


# ---- the Translate button ------------------------------------------------------------
# English for the words the package shows its end users (name, caption,
# instruction text, disclaimer...), so anyone can read a Japanese or German
# request. Asked once per request and saved; never written to Zendesk.

TRANSLATE_SCHEMA = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {"items": {"type": "array", "items": {
            "type": "object",
            "properties": {"key": {"type": "string"}, "english": {"type": "string"}},
            "required": ["key", "english"], "additionalProperties": False}}},
        "required": ["items"], "additionalProperties": False,
    },
}
TRANSLATE_PROMPT = ("You translate short texts from a remote-support software package into plain English for a "
                    "support team. Keep the meaning and tone; keep product names, numbers and URLs as they are. "
                    "Return one item per input key. If a text is already English, return it unchanged.")
NON_ASCII = re.compile(r"[^\x00-\x7f]")
UNTRANSLATED = {"creator", "date of creation", "technician count", "type", "subscription"}   # facts, not wording


def translate_engine():
    """Settings: "claude" (default) or "spark" for the Translate button."""
    return "spark" if store.get_setting("translate_engine", "claude") == "spark" else "claude"


def _translate_spark(texts):
    """The same job on Spark: free, smaller model. Asked for the same JSON;
    read leniently, since small models sometimes wrap it in prose."""
    import spark
    if not spark.available():
        raise ScanError("Spark isn't connected yet -- pick Claude in Settings, or wait for the next release.")
    try:
        text = spark.chat(TRANSLATE_PROMPT + ' Answer with JSON only: {"items": [{"key": ..., "english": ...}]}.',
                          json.dumps([{"key": k, "text": v} for k, v in texts.items()], ensure_ascii=False), max_tokens=4000)
    except spark.SparkError as e:
        raise ScanError("Spark couldn't translate: %s" % e)
    start, end = text.find("{"), text.rfind("}")
    try:
        parsed = json.loads(text[start:end + 1]) if start >= 0 else {}
    except ValueError:
        raise ScanError("Spark's answer wasn't the expected JSON -- try again, or pick Claude in Settings.")
    return parsed, spark.model()


def translate(scan_id):
    """English for this request's non-English texts: {key: english}. Saved on
    the row; a second press returns the saved one without calling the AI.
    Claude or Spark, as Settings says (translate_engine)."""
    row = store.scan_get(scan_id, fresh=True)
    if not row:
        raise ScanError("That request is gone.")
    if row.get("translation_json"):
        return json.loads(row["translation_json"])
    engine = translate_engine()
    miss = [m for m in missing_config() if m.startswith("AI_")] if engine == "claude" else []
    if miss:
        raise ScanError("Translation needs the AI set up (missing %s)." % ", ".join(miss))
    req = parse_request(row.get("description") or "")
    # Every piece of wording the package shows (any language -- German or
    # Spanish need no special characters), but not the facts: emails, dates,
    # counts, plan names. English comes back unchanged and isn't shown twice.
    texts = {f["label"].lower(): f["value"] for f in req["fields"]
             if (f.get("value") or "").strip() and f["label"].lower() not in UNTRANSLATED and "@" not in f["value"]}
    if row.get("subject") and NON_ASCII.search(row["subject"]):
        texts["subject"] = row["subject"]
    if not texts:
        out = {}
    elif engine == "spark":
        parsed, model = _translate_spark(texts)
        out = {i["key"]: i["english"] for i in parsed.get("items") or []
               if isinstance(i, dict) and i.get("key") in texts and i.get("english")}
        store.insert_many([{"when": _now(), "agent": "SplashHub Centre", "kind": "translate (SOS request)", "model": "spark:" + model,
                            "topic": "#%d custom SOS package" % int(row["ticket_id"]), "tickets": 1,
                            "input_tokens": 0, "output_tokens": 0, "cost": 0, "source": "centre"}])
    else:
        _, _, model = ai_config()
        body = {"model": model, "max_tokens": 4000, "system": TRANSLATE_PROMPT,
                "output_config": {"effort": "low", "format": TRANSLATE_SCHEMA},
                "messages": [{"role": "user", "content": [{"type": "text", "text": json.dumps(
                    [{"key": k, "text": v} for k, v in texts.items()], ensure_ascii=False)}]}]}
        parsed, usage, model = _messages(body, model, "Claude declined to translate this request.")
        out = {i["key"]: i["english"] for i in parsed.get("items") or [] if i.get("key") in texts and i.get("english")}
        cost = cost_of(usage, model)
        store.insert_many([{"when": _now(), "agent": "SplashHub Centre", "kind": "translate (SOS request)", "model": model,
                            "topic": "#%d custom SOS package" % int(row["ticket_id"]), "tickets": 1,
                            "input_tokens": usage.get("input_tokens", 0), "output_tokens": usage.get("output_tokens", 0),
                            "cost": cost, "source": "centre"}])
    store.scan_update(scan_id, translation_json=json.dumps(out, ensure_ascii=False))
    return out


# ---- "Add as internal note" -------------------------------------------------------------
# After an AI review, an agent can add it to the ticket as an internal note --
# a short summary or the full details. Manual for now (a button press each
# time); nothing is posted without one.

VERDICT_WORDS = {"suspicious": "Suspicious", "needs_review": "Needs review", "normal": "Normal",
                 "not_applicable": "Not applicable"}
REF_WORDS = {"powered_by_attribution": "\u201cPowered by Splashtop\u201d credit",
             "unmodified_default": "Splashtop default UI visible", "other_reference": "Misleading \u201cby Splashtop\u201d text"}


STATUS_WORDS = {"normal": "Verified", "needs_review": "Needs review", "suspicious": "High risk"}
LINK_WORDS = {"manage": "Manage SOS PKG on ACP", "team info": "View team on ACP", "download package": "Download package"}


def _e(s):
    import html
    return html.escape(str(s or ""), quote=True)


def is_generic(row, res):
    """The creator's email is a generic / free one: SplashHub's list, or the AI's own call."""
    return bool(res.get("generic_email") or res.get("creator_domain_is_generic_email") or
                (row.get("creator_domain") or "").lower() in FREE_EMAIL_DOMAINS)


def brand_mismatch(row, res):
    """Images whose branding does not match the creator's email domain (the
    AI's own domain_consistency call): [(image index, [brands], how)]. Empty for a
    generic email -- that has its own rule."""
    if is_generic(row, res):
        return []
    out = []
    for f in res.get("findings") or []:
        brands = [b for b in f.get("detected_brand_references") or [] if b]
        # "inconsistent": the AI sees another company; "unclear": a company name
        # it can't tie to the email's domain -- both are for a person to check.
        if f.get("domain_consistency") == "inconsistent" or (f.get("domain_consistency") == "unclear" and brands):
            out.append((f.get("image_index", 0), brands, f.get("domain_consistency")))
    return out


def effective_verdict(row, res):
    """The verdict as shown. Two team rules make "normal" at least "needs
    review" (also for reviews made before the rules): a generic email, and
    branding that does not match the creator's email domain."""
    v = row.get("verdict") or "normal"
    return "needs_review" if v == "normal" and (is_generic(row, res) or brand_mismatch(row, res)) else v


def review_reasons(row, res=None):
    """Why a review is not "Verified", most important first -- the Reason on
    the page's card and in the internal note. ["No issues found"] when clean."""
    res = res if res is not None else json.loads(row.get("result_json") or "null") or {}
    verdict = effective_verdict(row, res)
    names = {g.get("reviewed_index"): g.get("filename") for g in json.loads(row.get("gallery_json") or "[]")
             if g.get("reviewed_index") is not None}
    fs = res.get("findings") or []
    tr = res.get("ticket_review") or {}
    fname = lambda f: names.get(f.get("image_index")) or "Image %d" % (f.get("image_index", 0) + 1)
    reasons = []
    if is_generic(row, res):
        reasons.append("Generic email (%s): not accepted unless the customer gives a reason" % (row.get("creator_email") or "creator"))
    mism = brand_mismatch(row, res)
    if mism:
        brands = []
        for _, bs, _how in mism:
            brands += [b for b in bs if b not in brands]
        sure = any(how == "inconsistent" for _, _, how in mism)
        dom = (row.get("creator_domain") or "").lower() or ((row.get("creator_email") or "").split("@")[-1].lower())
        reasons.append("Branding %s the creator’s email: %s show%s %s, but the email is %s" % (
            "doesn’t match" if sure else "may not match", ", ".join(fname({"image_index": i}) for i, _, _h in mism), "" if len(mism) > 1 else "s",
            ", ".join("“%s”" % b for b in brands[:4]) or "another company’s branding",
            ("@" + dom) if dom else "from another domain"))
    if any(f.get("splashtop_reference") == "other_reference" for f in fs):
        reasons.append("Contains a Splashtop name/logo/attribution beyond \u201cPowered by\u201d: not acceptable for a white-label build")
    for f in fs:
        if f.get("verdict") in ("needs_review", "suspicious"):
            why = "; ".join(f.get("flagged_elements") or []) or (f.get("summary") or "").strip()
            reasons.append("%s: %s" % (fname(f), why))
    if tr.get("verdict") in ("needs_review", "suspicious"):
        reasons += ["Package details: " + x for x in (tr.get("flagged_fields") or [])] or \
                   ["Package details: " + (tr.get("summary") or "").strip()]
    if res.get("text_only"):
        reasons.append("Text-only review: %d image(s) could not be downloaded, so the AI did not see them" % res["text_only"])
    if not reasons:
        reasons = ["No issues found"] if verdict == "normal" else [(res.get("overall_summary") or "").strip()]

    return reasons


def note_html(row):
    """The internal note for this request's AI review, as the HTML Zendesk
    shows (bold, dividers, links). Everything from the ticket or the AI is
    escaped; links are only the http(s) ones parse_request found.

    SplashHub AI Review / Status / Reason / Review, with Image details and
    Package details as bullets / Quick links / one divider / package and
    creator / when. One version only (there used to be a shorter "summary")."""
    res = json.loads(row.get("result_json") or "null")
    if not res:
        raise ScanError("This request has no AI review yet.")
    verdict = effective_verdict(row, res)
    when = time.strftime("%b %d, %Y %H:%M UTC", time.gmtime((row.get("reviewed_ms") or row.get("finished_ms") or _now()) / 1000))
    names = {g.get("reviewed_index"): g.get("filename") for g in json.loads(row.get("gallery_json") or "[]")
             if g.get("reviewed_index") is not None}
    fs = res.get("findings") or []
    tr = res.get("ticket_review") or {}
    fname = lambda f: names.get(f.get("image_index")) or "Image %d" % (f.get("image_index", 0) + 1)

    reasons = review_reasons(row, res)

    h = ["<p><strong>SplashHub AI Review</strong></p>",
         "<p><strong>Status:</strong> %s%s</p>" % (_e(STATUS_WORDS.get(verdict, verdict)),
            # the average confidence over the images, as SplashHub's sidebar shows it
            (" (%d%%)" % round(sum(f.get("confidence") or 0 for f in fs) / len(fs) * 100)) if fs else "")]
    if len(reasons) == 1:
        h.append("<p><strong>Reason:</strong> %s</p>" % _e(reasons[0]))
    else:
        h.append("<p><strong>Reason:</strong></p><ul>%s</ul>" % "".join("<li>%s</li>" % _e(r) for r in reasons))
    summary = (res.get("overall_summary") or "").strip()
    h.append("<p><strong>Review</strong></p>")
    if summary:
        h.append("<ul><li>%s</li></ul>" % _e(summary))
    # Review, Image details and Package details: a bold label on its own,
    # and everything under it as bullet points -- the verdict first.
    def section(label, verdict, conf, points):
        first = "Verdict: %s%s" % (VERDICT_WORDS.get(verdict, verdict or "?"), (" (%d%%)" % conf) if conf is not None else "")
        points = [first] + [x.strip() for x in points if x and x.strip()]
        h.append("<p><strong>%s</strong></p><ul>%s</ul>" % (label, "".join("<li>%s</li>" % _e(x) for x in points)))

    if fs:
        sev = {"normal": 0, "needs_review": 1, "suspicious": 2}
        worst = max((f.get("verdict") for f in fs), key=lambda v: sev.get(v, 0))
        confs = [f["confidence"] for f in fs if f.get("confidence") is not None]
        section("Image details", worst, round(sum(confs) / len(confs) * 100) if confs else None,
                [f.get("summary") for f in fs])
    if tr:
        section("Package details", tr.get("verdict"), None,
                [tr.get("summary")] + ["Flagged: " + x for x in (tr.get("flagged_fields") or [])])
    req = parse_request(row.get("description") or "")
    # Quick links, right under the review
    links = [(LINK_WORDS.get(l["label"].lower(), l["label"]), l["url"]) for l in req["links"]
             if re.match(r"https?://", l["url"] or "")]
    order = {"Manage SOS PKG on ACP": 0, "View team on ACP": 1, "Download package": 2}
    links.sort(key=lambda x: order.get(x[0], 9))
    if links:
        h.append("<p><strong>Quick links:</strong> %s</p>" % " \u00b7 ".join(
            '<a href="%s">%s</a>' % (_e(u), _e(t)) for t, u in links))
    # the note's only divider, under the quick links; then who and when
    h.append("<hr>")
    labels = {f["label"].lower(): f["value"] for f in req["fields"]}
    meta = []
    if labels.get("package name"):
        meta.append("Package: " + labels["package name"])
    if row.get("creator_email"):
        meta.append("Creator: " + row["creator_email"])
    if meta:
        h.append("<p><small>%s</small></p>" % _e(" \u00b7 ".join(meta)))
    h.append("<p><small>Reviewed %s \u00b7 %s \u00b7 AI-generated; check before acting on it.</small></p>" % (
        _e(when), _e(row.get("model") or "Claude")))
    return "\n".join(h)


def add_note(scan_id):
    """Add the review to the ticket as an internal note; records when."""
    row = store.scan_get(scan_id, fresh=True)
    if not row:
        raise ScanError("That request is gone.")
    if zendesk.configured():
        raise ScanError("SplashHub Centre has no Zendesk login yet.")
    zendesk.add_internal_note(row["ticket_id"], note_html(row), html=True)
    info = {"ms": _now()}
    store.scan_update(scan_id, note_json=json.dumps(info))
    sys.stderr.write("[note] #%s internal note added\n" % row["ticket_id"])
    return info


RANK = {"suspicious": 3, "needs_review": 2, "normal": 1}


def overall(parsed):
    vs = [f.get("verdict") for f in parsed.get("findings") or []] + [(parsed.get("ticket_review") or {}).get("verdict")]
    vs = [v for v in vs if v in RANK]
    return max(vs, key=RANK.get) if vs else "normal"


def cost_of(usage, model):
    pi, po = PRICING.get(model, PRICING["claude-opus-4-8"])
    return (usage.get("input_tokens", 0) or 0) / 1e6 * pi + (usage.get("output_tokens", 0) or 0) / 1e6 * po


def _ms(iso):
    from datetime import datetime
    try:
        return int(datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp() * 1000)
    except (TypeError, ValueError):
        return None


def save_gallery(ticket_id, comments, reviewed, strict=True):
    """List every image on the ticket for the page, as Zendesk's own links:
    no copies are kept, and the images load from Zendesk for anyone signed in
    to it. Only the images an AI review needs (`reviewed`) are downloaded, in
    memory, and never stored. Returns (gallery entries, bytes by attachment id).
    A reviewed image that cannot be downloaded stops the scan when strict (the
    automatic review); the button's review goes ahead without it."""
    rev = {img["id"]: i for i, img in enumerate(reviewed)}
    gallery = [{"id": img["id"], "filename": img["filename"], "content_type": img["content_type"],
                "reviewed_index": rev.get(img["id"]), "url": img.get("content_url")} for img in all_images(comments)]
    data_by_id = {}
    for img in reviewed:
        try:
            data_by_id[img["id"]] = zendesk.download(img["content_url"])[0]
        except zendesk.ZendeskError:
            if strict:
                raise
    return gallery, data_by_id


def auto_note():
    """The Settings page's "Auto add internal note": add every finished AI review?"""
    return store.get_setting("auto_note", "off") == "on"


def _auto_note(scan_id, ticket_id):
    """After a review: add it to the ticket when the setting is on. A failure
    is noted on the request (the page shows it) and never undoes the review."""
    if not auto_note():
        return
    try:
        info = add_note(scan_id)
        info["auto"] = True
        store.scan_update(scan_id, note_json=json.dumps(info))
    except Exception as e:     # never let the note undo the review
        why = str(e)[:300] if isinstance(e, (ScanError, zendesk.ZendeskError)) else "internal error (%s)" % type(e).__name__
        store.scan_update(scan_id, note_json=json.dumps({"error": why, "ms": _now(), "auto": True}))
        sys.stderr.write("[note] #%s automatic internal note failed: %s\n" % (ticket_id, why))


def ai_review_on():
    """The team switch on the SOS Scans page. Off until someone turns it on --
    and it applies only to requests that arrive while it is on: nothing held
    earlier, and no imported past request, is ever reviewed after the fact."""
    return store.get_setting("ai_review", "off") == "on"


def _now():
    return int(time.time() * 1000)


class _NotRun(Exception):
    """A manual review that could not run: the request keeps what it had."""


def run_scan(scan_id, ticket_id, force=False, manual=False, was=None):
    """One request, start to finish. Every outcome is written to its row.

    1. The ticket's details and images: read from Zendesk when SplashHub Centre
       may (images listed as Zendesk links); otherwise what the trigger sent stays.
    2. The AI review -- only if the switch was on when the request came in, or
       someone pressed the panel's "AI review" button (manual). A manual review
       that cannot run leaves the request as it was, with a note why; images it
       cannot download are left out and the review says so (text_only).
    """
    row = store.scan_get(scan_id, fresh=True) or {}
    store.scan_update(scan_id, status="running")
    try:
        # Decided when the request arrived (request() stamps it), never now.
        review = manual or (row.get("ai_review") == "on" and row.get("source") != "import")
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
                              description=(t["description"] or "")[:20000],
                              ticket_status=t.get("status") or None, ticket_status_ms=_now())
                # Image bytes are only REQUIRED when the AI will review them;
                # otherwise a failed copy must not hold up the details.
                gallery, data_by_id = save_gallery(ticket_id, cs, images if review else [], strict=not manual)
                if manual:
                    got = [i for i in images if i["id"] in data_by_id]
                    left_out = len(images) - len(got)
                    images = got
                    idx = {i["id"]: n for n, i in enumerate(images)}
                    for g in gallery:
                        g["reviewed_index"] = idx.get(g["id"])
                store.scan_update(scan_id, gallery_json=json.dumps(gallery), **common)
                fetched = True
            except zendesk.ZendeskError as e:
                zd_note = str(e)
        else:
            zd_note = "SplashHub Centre has no Zendesk login yet"

        if manual and not fetched:
            raise _NotRun("it needs Zendesk access (%s)" % zd_note)
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
        if manual and fields == [] and not images:
            raise _NotRun("there are no images or package details on this ticket to review")
        if fields == [] and not images and fetched:
            store.scan_update(scan_id, status="skipped", finished_ms=_now(),
                              error="No thumbnail images or [Label] package fields on this ticket.")
            return
        miss = missing_config()
        if manual and miss:
            raise _NotRun("setup is missing " + ", ".join(miss))
        if miss or not fetched:
            store.scan_update(scan_id, status="waiting",
                              error="The AI review is waiting for " + ("setup (missing " + ", ".join(miss) + ")" if miss else
                                                                       "Zendesk access (%s)" % zd_note) + "." + shown_from)
            return
        key = hashlib.sha256(",".join(str(i["id"]) for i in images).encode()).hexdigest()[:24]
        if not force and not manual:
            prev = store.scan_done_for(ticket_id, key)
            if prev:
                store.scan_update(scan_id, status="skipped", finished_ms=_now(), attach_key=key,
                                  error="Already reviewed with these same images (scan #%d)." % prev)
                return
        b64s = [base64.b64encode(data_by_id[img["id"]]).decode() for img in images]
        parsed, usage, model = call_claude(images, b64s, creator_text(who), fields_text(fields))
        cost = cost_of(usage, model)
        verdict = overall(parsed)
        # Team rule: a package from a generic / free email is not accepted
        # unless the customer gives a reason -- so it is never "normal".
        if (who or {}).get("is_free") or parsed.get("creator_domain_is_generic_email"):
            parsed["generic_email"] = (who or {}).get("email") or True
            if verdict == "normal":
                verdict = "needs_review"
        # Team rule: branding that does not match the creator's email domain
        # is checked by a person -- at least "needs review".
        if verdict == "normal" and brand_mismatch({"creator_domain": (who or {}).get("domain")}, parsed):
            verdict = "needs_review"
        if manual and left_out:
            parsed["text_only"] = left_out     # images the review could not see
        store.scan_update(scan_id, status="done", verdict=verdict, finished_ms=_now(), attach_key=key,
                          result_json=json.dumps(parsed), model=model, input_tokens=usage.get("input_tokens", 0) or 0,
                          output_tokens=usage.get("output_tokens", 0) or 0, cost=cost, error=None, reviewed_ms=_now())
        _auto_note(scan_id, ticket_id)
        # Its cost on the Logs page, next to the sidebar's own scans -- under
        # the agent who pressed Scan in SplashHub's sidebar, when that started it.
        who = _reviewer(scan_id)
        store.insert_many([{"when": _now(), "agent": who or "SplashHub Centre",
                            "kind": "brand scan (sidebar)" if who else ("brand scan (manual)" if manual else "brand scan (auto)"),
                            "model": model, "topic": "#%d custom SOS package · %s" % (int(ticket_id), verdict),
                            "tickets": 1, "input_tokens": usage.get("input_tokens", 0), "output_tokens": usage.get("output_tokens", 0),
                            "cost": cost, "source": "centre"}])
    except _NotRun as e:
        _restore(scan_id, row, was, "The AI review didn't run: %s." % e)
    except (ScanError, zendesk.ZendeskError) as e:
        if manual:
            _restore(scan_id, row, was, "The AI review didn't finish: %s" % str(e)[:400])
        else:
            store.scan_update(scan_id, status="error", finished_ms=_now(), error=str(e)[:500])
    except Exception as e:    # a bug: say what kind, never the text
        sys.stderr.write("[scan] #%s failed: %s\n" % (ticket_id, type(e).__name__))
        why = "internal error (%s) -- see the app log" % type(e).__name__
        if manual:
            _restore(scan_id, row, was, "The AI review didn't finish: " + why)
        else:
            store.scan_update(scan_id, status="error", finished_ms=_now(), error=why)


def _restore(scan_id, row, was, note):
    """Put a request back the way it was before its manual review was asked
    for: same status, same verdict and earlier review (if any), plus a note."""
    store.scan_update(scan_id, status=was if was not in (None, "queued", "running") else "held",
                      verdict=row.get("verdict"), error=note)


# ---- the queue: one scan at a time, off the webhook loop ------------------------------
_Q = queue.Queue()
_started = False
_lock = threading.Lock()


def _worker():
    while True:
        item = _Q.get()
        scan_id, ticket_id, force = item[:3]
        manual, was = (item[3], item[4]) if len(item) > 4 else (False, None)   # request() puts three
        sys.stderr.write("[scan] #%s started (scan %s%s)\n" % (ticket_id, scan_id, ", AI review button" if manual else ""))
        run_scan(scan_id, ticket_id, force, manual, was)
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


def request(ticket_id, source, requested_by=None, force=False, pushed=None, review=None):
    """Queue a scan; returns the new row's id. `pushed`: what the trigger sent
    about the ticket (pushed_details), shown until the full scan replaces it.
    review=True: give it an AI review whatever the switch says (the sidebar)."""
    global _started
    with _lock:
        if not _started:
            threading.Thread(target=_worker, name="sos-scan", daemon=True).start()
            _started = True
    scan_id = store.scan_create(ticket_id, source, requested_by)
    store.scan_update(scan_id, ai_review="on" if (source != "import" and (review or ai_review_on())) else "off")
    if pushed:
        _apply_pushed(scan_id, pushed)
    _Q.put((scan_id, int(ticket_id), force))
    return scan_id


def review_now(scan_id):
    """The panel's "AI review" button: review this one request now, whatever
    the switch says and whenever it arrived. Returns an error message, or None."""
    row = store.scan_get(scan_id, fresh=True)
    if not row:
        return "That request is gone."
    if row.get("status") in ("queued", "running"):
        return "This request is already being processed."
    miss = missing_config()
    if miss:
        return "AI review isn't set up yet (missing %s)." % ", ".join(miss)
    # The status it had goes back if the review cannot run (_restore); the
    # verdict and any earlier review stay on the row until a new one replaces them.
    store.scan_update(scan_id, ai_review="manual", status="queued", error=None)
    sys.stderr.write("[scan] #%s AI review requested from the panel\n" % row["ticket_id"])
    request_existing(scan_id, row["ticket_id"], manual=True, was=row.get("status"))
    return None


# ---- the list's Ticket status column ------------------------------------------------------
# Zendesk's own status for each listed ticket, read in ONE Zendesk call for
# the rows on screen (show_many, up to 100 at a time).
#   - The refresh button (wait=True, force=True): every row on screen, right
#     away; the page shows the result of that same click.
#   - Other loads (the check every minute, paging, filters): rows older than
#     STATUS_MAX_AGE, in the background; the next load shows them.
#   - Closed tickets are never read again: that status is final.

STATUS_MAX_AGE = 2 * 60 * 1000
_status_busy = threading.Lock()


def refresh_statuses(rows, force=False, wait=False):
    """True when statuses were read now (wait=True), so the caller re-reads."""
    # Closed is final in Zendesk (a follow-up is a new ticket): never read again.
    # Solved is still read -- a customer reply reopens it.
    stale = [r for r in rows if r.get("ticket_status") != "closed" and
             (force or not r.get("ticket_status_ms") or _now() - r["ticket_status_ms"] > STATUS_MAX_AGE)]
    if not stale or zendesk.configured() or not _status_busy.acquire(blocking=wait, timeout=5 if wait else -1):
        return False

    def run():
        try:
            got = zendesk.statuses([r["ticket_id"] for r in stale])
            # a ticket Zendesk no longer returns (deleted / archived) keeps its last status
            store.scan_set_statuses({r["id"]: got.get(int(r["ticket_id"])) for r in stale}, _now())
        except zendesk.ZendeskError as e:
            sys.stderr.write("[status] could not refresh ticket statuses: %s\n" % e)
        except Exception as e:
            sys.stderr.write("[status] refresh failed: %s\n" % type(e).__name__)
        finally:
            _status_busy.release()
    t = threading.Thread(target=run, name="ticket-status", daemon=True)
    t.start()
    if wait:                      # the refresh button: wait a little, never long
        t.join(10)
        return not t.is_alive()
    return False


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
        full = store.scan_get(r["id"], fresh=True) or {}
        store.scan_update(r["id"], status="queued")
        # an "AI review" button press the restart interrupted carries on as one
        request_existing(r["id"], r["ticket_id"], manual=full.get("ai_review") == "manual" and r["status"] in ("queued", "running"))


def request_existing(scan_id, ticket_id, manual=False, was=None):
    global _started
    with _lock:
        if not _started:
            threading.Thread(target=_worker, name="sos-scan", daemon=True).start()
            _started = True
    _Q.put((scan_id, int(ticket_id), manual, manual, was))


# ---- past requests: imported from Zendesk by SplashHub Centre itself -------------------
# The "Import past SOS requests" button on the SOS Scans page. Finds every
# ticket whose subject starts "New SOS package created by ...", lists its
# images as Zendesk links, and each as a past request at its own creation date. Never
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
    created = _ms(t.get("created_at")) or _now()
    gallery, _ = save_gallery(tid, cs, [])
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
                      error="Past request -- listed for reference, never reviewed by AI.",
                      ticket_status=t.get("status") or None, ticket_status_ms=_now())


def _run_import():
    try:
        if zendesk.configured():
            raise ScanError("SplashHub Centre has no Zendesk login yet (missing " + ", ".join(zendesk.configured()) + ")")
        # Each page of results is added before the next is fetched, so the
        # list fills from the first minute and a restart loses nothing done.
        batch = []

        def add(batch):
            have = store.scan_ticket_ids([t["id"] for t in batch])
            for t in batch:
                if IMPORT.get("stop"):
                    return
                if int(t["id"]) in have:
                    IMPORT["skipped"] += 1
                else:
                    try:
                        _import_one(t)
                        IMPORT["added"] += 1
                    except zendesk.ZendeskError as e:
                        sys.stderr.write("[import] #%s: %s\n" % (t.get("id"), e))
                        IMPORT["failed"] = IMPORT.get("failed", 0) + 1
                IMPORT["done"] += 1
                if IMPORT["done"] % 500 == 0:
                    sys.stderr.write("[import] %d checked, %d added\n" % (IMPORT["done"], IMPORT["added"]))

        for t in zendesk.search_tickets('type:ticket subject:"%s"' % SOS_SUBJECT):
            if IMPORT.get("stop"):
                break
            if str(t.get("subject") or "").startswith(SOS_SUBJECT):   # search matches words; keep true subjects
                IMPORT["found"] += 1
                batch.append(t)
            if len(batch) >= 100:
                add(batch); batch = []
        if batch and not IMPORT.get("stop"):
            add(batch)
    except (ScanError, zendesk.ZendeskError) as e:
        IMPORT["error"] = str(e)[:400]
    except Exception as e:
        IMPORT["error"] = "internal error (%s) -- see the app log" % type(e).__name__
        sys.stderr.write("[import] failed: %s\n" % type(e).__name__)
    finally:
        IMPORT["stopped"] = bool(IMPORT.get("stop"))
        IMPORT["running"] = False
        IMPORT["finished_ms"] = _now()
        try:     # finished, stopped or failed: nothing to resume (a killed container never gets here)
            store.set_setting("import_running", "", "import")
        except Exception:
            pass
        sys.stderr.write("[import] finished: %d found, %d added, %d skipped%s\n" % (
            IMPORT["found"], IMPORT["added"], IMPORT["skipped"], (" -- " + IMPORT["error"]) if IMPORT["error"] else ""))


def start_import(resumed=False):
    """Start the import in the background; False if one is already running."""
    with _import_lock:
        if IMPORT["running"]:
            return False
        IMPORT.update(running=True, stop=False, stopped=False, found=0, done=0, added=0, skipped=0, failed=0, error=None,
                      started_ms=_now(), finished_ms=None, resumed=resumed)
    # Remembered in the database: a restart (a new release, a grant change)
    # ends the thread, and the next container picks the import up again.
    store.set_setting("import_running", "yes", "import")
    threading.Thread(target=_run_import, name="sos-import", daemon=True).start()
    return True


def resume_import():
    """At start-up: carry on an import the previous container was running.
    Tickets already listed are skipped, so it picks up where it was."""
    try:
        if store.get_setting("import_running", "") == "yes":
            sys.stderr.write("[import] carrying on after a restart\n")
            start_import(resumed=True)
    except Exception as e:
        sys.stderr.write("[import] could not resume: %s\n" % type(e).__name__)


def stop_job(which="import"):
    """Ask a running import to stop after the ticket it is on. Everything
    already listed stays; pressing the button again carries on."""
    if IMPORT["running"]:
        IMPORT["stop"] = True
        return True
    return False


def apply_rules_to_past():
    """Reviews saved "normal" before a team rule existed (generic email,
    branding vs email) are stored as "needs review", so the list's filter and
    the dashboard count them right. Cheap; runs at start."""
    fixed = 0
    for row in store.scans_normal_reviewed():
        try:
            res = json.loads(row.get("result_json") or "null") or {}
        except ValueError:
            continue
        if effective_verdict(row, res) != "normal":
            store.scan_update(row["id"], verdict="needs_review")
            fixed += 1
    if fixed:
        sys.stderr.write("[scan] %d earlier review(s) now need review under the team rules\n" % fixed)


def start_rules_fix():
    def run():
        try:
            apply_rules_to_past()
        except Exception as e:
            sys.stderr.write("[scan] team-rule pass failed: %s\n" % type(e).__name__)
    threading.Thread(target=run, name="team-rules", daemon=True).start()


# ---- SplashHub's sidebar: show the review made here instead of a second AI call ----

def _who(by):
    """The agent's name as the sidebar sent it: one plain line, short."""
    by = re.sub(r"[\x00-\x1f\x7f]+", " ", str(by or "")).strip()
    return by[:80]


def _press(scan_id, by, action):
    """Who pressed Scan in SplashHub's sidebar for this request, and what it
    did: "viewed" (showed this review), "started" (asked for the review) or
    "again" (Review again). The newest 30, oldest first."""
    if not scan_id:
        return
    row = store.scan_get(scan_id, fresh=True) or {}
    try:
        hist = json.loads(row.get("sidebar_json") or "[]")
    except ValueError:
        hist = []
    hist.append({"by": _who(by) or "Someone", "ms": _now(), "action": action})
    store.scan_update(scan_id, sidebar_json=json.dumps(hist[-30:]))


def _reviewer(scan_id):
    """The agent who started this request's review from SplashHub's sidebar
    (their name), or None: a request the sidebar created carries the name in
    requested_by; one it asked to review has a "started"/"again" press from the
    last half hour."""
    row = store.scan_get(scan_id, fresh=True) or {}
    rb = row.get("requested_by") or ""
    if row.get("source") == "sidebar" and " \u00b7 SplashHub sidebar" in rb:
        return rb.split(" \u00b7 SplashHub sidebar")[0] or None
    try:
        hist = json.loads(row.get("sidebar_json") or "[]")
    except ValueError:
        hist = []
    for p in reversed(hist):
        if p.get("action") in ("started", "again") and _now() - int(p.get("ms") or 0) < 30 * 60000:
            return p.get("by") or None
    return None


def sidebar_review(ticket_id, start=True, again=False, by=None, press=False):
    """What SplashHub's sidebar shows for a ticket, so one ticket gets one AI
    review: the latest one made here, as the AI returned it (the sidebar draws
    it in its own format). Nothing yet: with start, ask for one and say
    "pending"; the sidebar asks again a few seconds later.

    {"state": "done", "result": {...}, "images": [file names, in the order the
     AI saw them], "verdict", "reviewed_ms", "model", "scan_id"}
    {"state": "pending"} / {"state": "none"} / {"state": "error", "error": "..."}

    by: the agent who pressed Scan (their Zendesk name); press: True on the
    first ask of a press (not on the checks that follow), so each press is
    written down once, on the request it showed or started."""
    rows = store.scans_for_ticket(ticket_id)
    busy = next((r for r in rows if r.get("status") in ("queued", "running")), None)
    if busy:
        if press:
            _press(busy["id"], by, "again" if again else "viewed")
        return {"state": "pending"}
    done = next((r for r in rows if r.get("status") == "done" and r.get("result_json")), None)
    if done and not again:
        full = store.scan_get(done["id"], fresh=True) or done
        if press:
            _press(done["id"], by, "viewed")
            try:
                res0 = json.loads(full.get("result_json") or "null") or {}
            except ValueError:
                res0 = {}
            store.insert_many([{"when": _now(), "agent": _who(by) or "SplashHub sidebar", "kind": "brand scan (from Centre)",
                                "model": full.get("model") or "", "tickets": 1, "input_tokens": 0, "output_tokens": 0, "cost": 0,
                                "topic": "#%d custom SOS package \u00b7 %s \u00b7 shown from SplashHub Centre, no new AI call" % (
                                    int(ticket_id), effective_verdict(full, res0)),
                                "source": "centre"}])
        try:
            res = json.loads(full.get("result_json") or "null") or {}
        except ValueError:
            res = {}
        gal = [g for g in json.loads(full.get("gallery_json") or "[]") if g.get("reviewed_index") is not None]
        gal.sort(key=lambda g: g["reviewed_index"])
        return {"state": "done", "result": res, "images": [g.get("filename") or "" for g in gal],
                "verdict": effective_verdict(full, res), "reviewed_ms": full.get("reviewed_ms") or full.get("finished_ms"),
                "model": full.get("model"), "scan_id": full["id"]}
    if not start:
        return {"state": "none"}
    miss = missing_config()
    if miss:
        return {"state": "error", "error": "SplashHub Centre's AI review isn't set up (missing %s)" % ", ".join(miss)}
    # Can't be read right now (Zendesk access, setup): say why -- Centre retries
    # those by itself every few minutes, so asking again would only repeat it.
    if rows and not again and rows[0].get("status") in ("waiting", "error"):
        return {"state": "error", "error": (rows[0].get("error") or "SplashHub Centre couldn't read this ticket yet.").strip()}
    # Listed here already (e.g. while the switch was off): review that request.
    # Otherwise list the ticket and review it.
    if rows and not again:
        if press:
            _press(rows[0]["id"], by, "started")
        err = review_now(rows[0]["id"])
        return {"state": "error", "error": err} if err else {"state": "pending"}
    who = _who(by)
    sid = request(int(ticket_id), "sidebar", (who + " \u00b7 SplashHub sidebar") if who else "SplashHub sidebar",
                  force=bool(again), review=True)
    if press:
        _press(sid, by, "again" if again else "started")
    return {"state": "pending"}
