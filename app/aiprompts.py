"""The AI prompts, editable on the Prompts & Templates page (admins).

Each tool keeps its own default in its own module; what an admin saves here is
kept in settings and used from the next call on -- no new release. Empty means
the default. Every save keeps the text it replaced in a short history, so a
change can be looked at and put back.

Only the instructions are editable. What the tool needs to READ the answer
(the JSON it parses, the languages AutoTag allows, the examples Ad/Spam was
given) is added after the text by the code, and the page shows that part as
fixed. The rule that the AI never discusses individual support agents is
part of that fixed part too: no edit can take it out.

Placeholders such as {languages} are filled in by the tool; one taken out of
the text is added back at the end, so the tool still gets what it needs.
"""
import json, time

import store

MAX_LEN = 20000
KEEP = 15                 # versions kept per prompt


def _defaults():
    """{key: (default text)} -- read from each tool, so a code change to a default shows here."""
    import replylab, adfilter, autotag, customers, askai, sosscan
    return {"reply": replylab.DEFAULT_PROMPT, "adfilter": adfilter.DEFAULT_PROMPT, "autotag": autotag.DEFAULT_PROMPT,
            "customers": customers.SUMMARY_PROMPT, "askai": askai.DEFAULT_PROMPT, "translate": sosscan.TRANSLATE_PROMPT}


# What the page shows for each: its name, where it is used, the model it runs on,
# the placeholders it fills in, and what the code adds after it.
PROMPTS = [
    {"key": "reply", "name": "Reply drafts", "icon": "reply", "engine": "Spark · Claude",
     "where": "Reply Lab and the ticket sidebar's Reply Lab tile",
     "about": "How a reply is written: the tone, when to use a team template word for word, what never to promise.",
     "placeholders": [],
     "fixed": "After this the model gets the ticket's conversation, the closest team templates and the agent's notes. "
              "The first line it writes (TEMPLATE: ...) is how the Centre shows which template was used, so keep that rule in.",
     "test": "reply"},
    {"key": "adfilter", "name": "Ad/Spam Filter", "icon": "filter", "engine": "Spark",
     "where": "Ad/Spam Filter: each new ticket, and Scan again",
     "about": "What counts as an ad or spam, and what never does (customers, quotes, 2FA texts...).",
     "placeholders": [],
     "fixed": "Added after your text: the spam examples from the Ad/Spam Filter's settings, then the JSON answer the filter reads "
              "({\"<ticket id>\": {\"spam\", \"confidence\", \"why\"}})."},
    {"key": "autotag", "name": "AutoTag language", "icon": "tag", "engine": "Spark",
     "where": "AutoTag: each new ticket, and Scan again",
     "about": "How the customer's language is told apart from signatures, quotes and automatic text.",
     "placeholders": [{"name": "{languages}", "about": "the languages AutoTag tags, from its settings"}],
     "fixed": "Added after your text: the JSON answer AutoTag reads ({\"<ticket id>\": {\"lang\", \"confidence\", \"why\"}})."},
    {"key": "customers", "name": "Customer summary", "icon": "users", "engine": "Spark",
     "where": "Customers: the summary at the top of a customer",
     "about": "The 3 to 5 bullets written about one customer from the Centre's records.",
     "placeholders": [],
     "fixed": "After this the model gets the customer's records. Lines starting with \"- \" become the bullets."},
    {"key": "askai", "name": "Ask AI", "icon": "spark", "engine": "Spark",
     "where": "The AI page and the AI chat on other pages",
     "about": "Which lookup to use for which question, how to answer, how to draft replies and quote plans.",
     "placeholders": [{"name": "{today}", "about": "today's date"}],
     "fixed": "Always added after your text: the rule that the AI never discusses individual support agents. "
              "The PriceBook page adds its own line too."},
    {"key": "translate", "name": "Translate (SOS Scans)", "icon": "globe", "engine": "Claude · Spark",
     "where": "SOS Scans: the Translate button on a package's texts",
     "about": "How the package's texts are put into plain English.",
     "placeholders": [],
     "fixed": "Added after your text: the answer format ({\"items\": [{\"key\", \"english\"}]})."},
]
_BY_KEY = {p["key"]: p for p in PROMPTS}


def _skey(key):
    return "replylab_prompt" if key == "reply" else "prompt:" + key     # Reply Lab's was saved before this page


def _hkey(key):
    return "prompt_hist:" + key


def _check(key):
    if key not in _BY_KEY:
        raise ValueError("unknown prompt")


def text(key, default=None):
    """The prompt in use: the saved one, else the default. Never raises: a tool always gets a prompt."""
    try:
        saved = store.get_setting(_skey(key), "") or ""
    except Exception:
        saved = ""
    if saved.strip():
        return saved
    return default if default is not None else _defaults().get(key, "")


def fill(t, values):
    """Put in the placeholders; one taken out of the text is added at the end, so the tool still gets it."""
    for name, value in values.items():
        ph = "{" + name + "}"
        t = t.replace(ph, value) if ph in t else t + "\n\n%s: %s" % (name.capitalize(), value)
    return t


def _history(key):
    try:
        h = json.loads(store.get_setting(_hkey(key), "") or "[]")
        return h if isinstance(h, list) else []
    except ValueError:
        return []


def _meta(key):
    """(updated_ms, updated_by) of the saved prompt, from the settings row."""
    try:
        c = store.connect()
        try:
            cur = c.cursor()
            cur.execute(store._q("SELECT updated_ms, updated_by FROM settings WHERE key = %s"), [_skey(key)])
            row = cur.fetchone()
            return (row[0], row[1]) if row else (None, None)
        finally:
            c.close()
    except Exception:
        return None, None


def save(key, new_text, by=None, note=""):
    """Save a prompt (the default's own text, or empty, means back to the default).
    The text it replaces goes into the history first."""
    _check(key)
    new_text = (new_text or "").replace("\r\n", "\n").strip()
    if len(new_text) > MAX_LEN:
        raise ValueError("the prompt is too long (%s characters at most)" % format(MAX_LEN, ","))
    default = _defaults()[key]
    if new_text == default.strip():
        new_text = ""
    old = store.get_setting(_skey(key), "") or ""
    if old.strip() == new_text:
        return one(key)
    ms, who = _meta(key)
    h = _history(key)
    h.insert(0, {"text": old, "ms": ms or int(time.time() * 1000), "by": who or "", "note": "",
                 "default": not old.strip(), "replaced_ms": int(time.time() * 1000), "replaced_by": by or "",
                 "replaced_note": (note or "")[:200]})
    store.set_setting(_hkey(key), json.dumps(h[:KEEP], ensure_ascii=False), by)
    store.set_setting(_skey(key), new_text, by)
    return one(key)


def one(key):
    _check(key)
    p, default = _BY_KEY[key], _defaults()[key]
    saved = (store.get_setting(_skey(key), "") or "").strip()
    ms, by = _meta(key)
    hist = [{"i": i, "text": v.get("text") or default, "default": bool(v.get("default")), "ms": v.get("ms"), "by": v.get("by") or "",
             "replaced_ms": v.get("replaced_ms"), "replaced_by": v.get("replaced_by") or "", "note": v.get("replaced_note") or ""}
            for i, v in enumerate(_history(key))]
    return dict(p, text=saved or default, default=default, is_default=not saved,
                updated_ms=ms if saved else None, updated_by=(by or "") if saved else "", history=hist)


def overview():
    import replylab
    out = {"prompts": [one(p["key"]) for p in PROMPTS], "sidebar_model": replylab.sidebar_model(),
           "sidebar_default": replylab.SIDEBAR_MODEL, "spark_models": []}
    try:
        import spark
        if spark.available():
            out["spark_models"] = spark.models()
    except Exception:
        pass
    return out
