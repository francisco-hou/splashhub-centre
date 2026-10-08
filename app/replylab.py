"""Reply Lab: draft the next reply to a ticket with a chosen model and prompt.

For trying things out before any of it is used for real: put a ticket number
in by hand, pick one to three models (Spark's, and Claude Haiku 5.5 through the
CUSTOM_AI grant SOS Scans uses), adjust the prompt, and press Draft: the
drafts show side by side with how long each took and its tokens. MANUAL and
READ ONLY: nothing runs by itself, nothing is ever written to Zendesk; a draft
is shown to be read and copied.

The team's reply templates (replytemplates.json, from the Notion "Ticket
Templates" page, customers' details taken out) are given to the model as the
format to follow: the closest three by the words the customer used, one picked
by hand, or none.

The prompt in use is kept in settings (replylab_prompt), so it can be tuned
over time; empty means DEFAULT_PROMPT. Spark's drafts are kept in Spark
activity (area reply_lab), like every other Spark call.
"""
import difflib, json, os, re, time

import store

KEY = "replylab_prompt"
MAX_TEXT = 14000                # the conversation given to the model, newest kept when longer
CLAUDE_MODELS = ["claude-haiku-5-5"]     # Claude in Reply Lab, for now: Haiku 5.5 only
DEFAULT_PROMPT = """You are a Splashtop technical support agent writing the next PUBLIC reply on a Zendesk ticket.
Splashtop makes remote access and remote support software (Splashtop Business Access, Remote Support, Enterprise, SOS, On-Prem).

- Reply in the customer's language: the language of their latest message.
- Answer what the customer asked in their latest message; don't repeat what was already said or asked.
- Be accurate. If you're not sure of a product fact, say what you will check or ask for the detail you need (version, OS, logs, screenshots) -- never invent features, prices, dates or policies.
- Internal notes are for you only: use what they say, never quote them or mention them.
- TEAM TEMPLATES COME FIRST. When one of the team templates given fits this ticket, your reply IS that template, word for word (99% the same):
  keep its greeting, every sentence, its steps and their numbering, its links and its closing exactly as written.
  Change ONLY what must change for this ticket: the customer's name, a detail such as their OS, version or computer name, and placeholders like XXX.
  Do not rephrase, shorten, add sentences, add steps or add a signature the template doesn't have.
  Some templates hold two versions one after the other (each starting with "Hello"): use the one version that fits, not both.
  If the customer wrote in another language, translate the template faithfully, sentence by sentence.
- Only when NO template fits, write a short reply in the same style: "Hello,", a line thanking them or saying sorry about the trouble, short paragraphs or numbered steps, a link to the matching Splashtop support article when there is one, "Please let us know how it goes!", then "Regards," and "Splashtop Business Support Team".
- Plain text, no Markdown, no subject line.
- Never promise refunds, discounts, delivery dates or new features.
- The FIRST line of your answer is "TEMPLATE: <the template's title in brackets, exactly as given>" or "TEMPLATE: none"; the reply starts on the next line."""
TEMPLATES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "replytemplates.json")
_TPL = {"list": None}
MIN_SCORE = 1.0                 # below this a template isn't given at all: none beats a wrong one


def _now():
    return int(time.time() * 1000)


# ---- the models --------------------------------------------------------------------------------

def models():
    """[{id, label, provider}] -- id "spark:<model>" or "claude:<model>"."""
    import spark, sosscan
    out, notes = [], []
    if spark.available():
        try:
            out += [{"id": "spark:" + m, "label": m, "provider": "Spark"} for m in spark.models()]
        except Exception as e:
            notes.append("Spark didn't list its models (%s)" % (e if isinstance(e, spark.SparkError) else type(e).__name__))
    else:
        notes.append("Spark isn't connected")
    base, key, _ = sosscan.ai_config()
    if base and key:
        out += [{"id": "claude:" + m, "label": {"claude-haiku-5-5": "Haiku 5.5"}.get(m, m), "provider": "Claude"} for m in CLAUDE_MODELS]
    else:
        notes.append("Claude isn't set up (AI_BASE_URL / AI_API_KEY)")
    return out, notes


# ---- the prompt --------------------------------------------------------------------------------

def prompt():
    return store.get_setting(KEY, "") or DEFAULT_PROMPT


def save_prompt(text, by=None):
    text = (text or "").strip()
    if len(text) > 8000:
        raise ValueError("the prompt is too long (8,000 characters at most)")
    store.set_setting(KEY, "" if text == DEFAULT_PROMPT.strip() else text, by)
    return {"prompt": prompt(), "is_default": not store.get_setting(KEY, "")}


# ---- the team's templates ----------------------------------------------------------------------

def templates():
    """[{id, title, tag, language, text}], read once."""
    if _TPL["list"] is None:
        try:
            with open(TEMPLATES_FILE, encoding="utf-8") as f:
                _TPL["list"] = json.load(f)
        except (OSError, ValueError):
            _TPL["list"] = []
    return _TPL["list"]


_STOP = set("the a an and or to of in on for with is are was it this that you your we our i my me be can could would please "
            "thank thanks hello hi regards support splashtop team not no do does have has will just so if as at by from "
            "but there their they them what when how any all also get got its am pm "
            "chat started ended transcript visitor url http https www com appended".split())       # a chat's own words


def _stem(w):
    for suf in ("ations", "ation", "ions", "ion", "ing", "ed", "es", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            return w[:-len(suf)]
    return w


def _words(text):
    """The words that say what it's about: no little words, no numbers, roughly stemmed
    (disconnecting / disconnections -> disconnect)."""
    return {_stem(w) for w in re.findall(r"[a-z0-9][a-z0-9'-]{2,}", (text or "").lower()) if w not in _STOP and not w.isdigit()}


def closest(tk, n=3):
    """The n templates that share the most words with what the customer wrote
    (the title counts three times): a cheap match, no model involved."""
    subject = tk["ticket"].get("subject") or ""
    if re.match(r"^(chat|conversation) with\b", subject.strip(), re.I):      # a chat's subject says nothing about it
        subject = ""
    said = _words(" ".join([subject] + [m.get("text") or "" for m in tk["conversation"] if m["kind"] == "customer"]))
    scored = []
    for t in templates():
        title, body = _words(t["title"] + " " + t["tag"]), _words(t["text"])
        score = 3 * len(said & title) + len(said & body) / (1 + len(body) ** 0.5)
        if score >= MIN_SCORE:                     # a word in the title, or several in the text
            scored.append((score, t))
    scored.sort(key=lambda x: -x[0])
    return [t for _, t in scored[:n]]


def _template_part(tk, template):
    """(text for the model, [titles used]). template: "auto" (the closest three), "none", or a template id."""
    if template == "none":
        return "", []
    if template and template != "auto":
        t = next((x for x in templates() if x["id"] == template), None)
        if not t:
            raise ValueError("unknown template")
        return ("\n\n---\nThe team template to use (it fits this ticket; reply with it word for word, changing only what this ticket needs):\n\n[%s]\n%s" % (t["title"], t["text"]), [t["title"]])
    picks = closest(tk)
    if not picks:
        return "", []
    return ("\n\n---\nThe team's reply templates closest to this ticket. If one fits, reply with it word for word "
            "(changing only what this ticket needs); if none fits, write in their style:\n\n" + "\n\n".join("[%s]\n%s" % (t["title"], t["text"]) for t in picks),
            [t["title"] for t in picks])


def _which(text, given):
    """(reply without the TEMPLATE line, the template used or None, how alike the two are in %).
    The likeness is worked out here (difflib), not taken from the model: for a two-version
    template, against whichever version is closest."""
    m = re.match(r"\s*TEMPLATE:\s*\[?(.*?)\]?\s*(?:\n|$)", text or "", re.I)
    if not m:
        return text, None, None
    reply, name = text[m.end():].strip(), m.group(1).strip()
    t = next((x for x in templates() if x["title"].lower() == name.lower() and x["title"] in given), None)
    if not t:
        return reply, None, None
    norm = lambda s: re.sub(r"\s+", " ", s or "").strip().lower()
    versions = [v for v in re.split(r"\n(?=Hello\b)", t["text"]) if v.strip()] or [t["text"]]
    best = max(difflib.SequenceMatcher(None, norm(v), norm(reply)).ratio() for v in versions + [t["text"]])
    return reply, t["title"], int(round(best * 100))


# ---- the ticket --------------------------------------------------------------------------------

def ticket(ticket_id):
    """The ticket as Zendesk has it now and its whole conversation, oldest first."""
    import zendesk
    if zendesk.configured():
        raise ValueError("SplashHub Centre can't read Zendesk yet")
    t, convo = zendesk.conversation(int(ticket_id))
    if not t.get("id"):
        raise ValueError("Zendesk has no ticket #%s" % ticket_id)
    return {"ticket": {"id": t.get("id"), "subject": t.get("subject") or "", "status": t.get("status") or "",
                       "channel": ((t.get("via") or {}).get("channel") or ""), "created_at": t.get("created_at") or "",
                       "tags": t.get("tags") or []},
            "conversation": convo}


def _transcript(tk, include_notes):
    """The conversation as the model reads it: the subject, then each message, oldest first."""
    LBL = {"customer": "Customer", "agent": "Support agent", "note": "Internal note (agents only)"}
    parts = []
    for m in tk["conversation"]:
        if m["kind"] == "note" and not include_notes:
            continue
        when = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(m["ms"] / 1000)) if m.get("ms") else ""
        parts.append("[%s%s]\n%s" % (LBL.get(m["kind"], m["kind"]), (" · " + when) if when else "", (m.get("text") or "").strip()))
    body = "\n\n".join(parts)
    if len(body) > MAX_TEXT:                                   # the newest part matters most
        body = "[... earlier messages left out ...]\n\n" + body[-MAX_TEXT:]
    return "Ticket #%s\nSubject: %s\nStatus: %s\n\n%s" % (tk["ticket"]["id"], tk["ticket"]["subject"], tk["ticket"]["status"], body)


# ---- a draft -----------------------------------------------------------------------------------

def draft(ticket_id, model_id, prompt_text=None, notes=None, include_notes=True, template="auto"):
    """One draft: {model, provider, text, ms, tokens_in, tokens_out, templates}. Nothing goes to Zendesk."""
    provider, _, name = str(model_id or "").partition(":")
    have, _ = models()
    if not any(m["id"] == model_id for m in have):
        raise ValueError("that model isn't available")
    tk = ticket(ticket_id)
    system = (prompt_text or "").strip() or prompt()
    tpl_text, used = _template_part(tk, template or "auto")
    user = _transcript(tk, include_notes) + tpl_text + "\n\n---\nWrite the next reply to the customer."
    if (notes or "").strip():
        user += "\n\nThe agent's notes for this reply (follow them):\n" + notes.strip()[:2000]
    t0 = time.time()
    if provider == "spark":
        import spark
        text = spark.chat(system, user, max_tokens=1800, log={"area": "reply_lab", "tickets": [int(ticket_id)]}, use_model=name)
        u = getattr(spark._LAST, "usage", None) or {}
        tin, tout = u.get("prompt_tokens"), u.get("completion_tokens")
    else:
        import sosscan
        # Haiku 5.5 thinks first (adaptive, effort medium by default): room for that and the reply
        res = sosscan.messages_raw({"model": name, "max_tokens": 8000, "system": system,
                                    "messages": [{"role": "user", "content": user}]})
        if res.get("stop_reason") == "refusal":
            raise ValueError("Claude declined to draft this one")
        text = "".join(b.get("text") or "" for b in res.get("content") or [] if b.get("type") == "text").strip()
        if not text:
            raise ValueError("Claude's answer had no text" + (" (cut off at max_tokens)" if res.get("stop_reason") == "max_tokens" else ""))
        u = res.get("usage") or {}
        tin, tout = u.get("input_tokens"), u.get("output_tokens")
    text, tused, alike = _which(text, used)
    return {"model": name, "provider": "Spark" if provider == "spark" else "Claude", "model_id": model_id, "text": text,
            "ms": int((time.time() - t0) * 1000), "tokens_in": tin, "tokens_out": tout, "ticket_id": int(ticket_id), "templates": used,
            "template_used": tused, "similarity": alike}


def info():
    have, notes = models()
    return {"models": have, "notes": notes, "prompt": prompt(), "default_prompt": DEFAULT_PROMPT,
            "templates": [{"id": t["id"], "title": t["title"], "tag": t["tag"], "language": t["language"], "text": t["text"]} for t in templates()],
            "is_default": not store.get_setting(KEY, "")}
