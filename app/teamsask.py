"""Ask from Teams: questions typed in a Teams chat, answered there by Spark.

Teams can't reach SplashHub Centre (it sits behind Spluki's company-network
fence), so a Power Automate flow on the chat -- "When a new chat message is
added" -> HTTP POST -- sends each message to Spluki's public webhook intake,
which SplashHub Centre already polls (feed.py). The message carries the header
X-Centre-Key: a key made in Settings > Notifications (only its hash is kept).

A message is a question when it starts with the trigger word (default
"centre": "centre how many Japanese tickets are waiting?"). Everything else in
the chat -- and the cards the workflow itself posts -- is ignored. The answer
comes from askai (the AI page: the same lookups, the same wall around support
agents) and goes back to the chat through the Teams workflow link
(TEAMS_WEBHOOK_URL), @mentioning whoever asked. A short follow-up from the same
person within 15 minutes keeps the conversation. Nothing asked here changes
anything; every question is a line on the Logs page.

The body may be the flow's whole trigger output (a Teams chatMessage: body.content,
from.user.displayName / id, id) or a small object {text, from_name, from_id, message_id}.
"""
import hashlib, hmac, html, json, re, secrets, sys, threading, time

import store

HEADER = "x-centre-key"
MAX_PER_HOUR = 30
FOLLOW_UP_MS = 15 * 60000
_lock = threading.Lock()
_recent = []                      # times of answered questions (rate limit)
_convos = {}                      # asker id -> {"ms": last, "messages": [...]}


def _now():
    return int(time.time() * 1000)


def settings():
    return {"on": store.get_setting("teams_ask_on", "off") == "on",
            "word": store.get_setting("teams_ask_word", "centre") or "centre",
            "has_key": bool(store.get_setting("teams_ask_key", ""))}


def save(on=None, word=None):
    if on is not None:
        store.set_setting("teams_ask_on", "on" if on else "off", "teams")
    if word is not None:
        w = re.sub(r"[^\w-]", "", str(word)).lower()[:20]
        if not w:
            raise ValueError("the trigger word can't be empty")
        store.set_setting("teams_ask_word", w, "teams")
    return settings()


def new_key():
    """A fresh key, shown once (only its hash is kept); the old one stops working."""
    key = "ctr_" + secrets.token_urlsafe(24)
    store.set_setting("teams_ask_key", hashlib.sha256(key.encode()).hexdigest(), "teams")
    return key


def key_ok(given):
    want = store.get_setting("teams_ask_key", "")
    got = hashlib.sha256((given or "").strip().encode()).hexdigest()
    return bool(want) and hmac.compare_digest(want, got)


# ---- one message from the intake ------------------------------------------------------------

def _text_of(content):
    t = re.sub(r"(?is)<at[^>]*>.*?</at>", " ", content or "")       # an @mention of the workflow, if any
    t = re.sub(r"(?i)<br\s*/?>|</p>|</div>", "\n", t)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    return re.sub(r"[ \t ]+", " ", t).strip()


def parse(data):
    """(question text, asker name, asker id, message id) from either body shape."""
    if isinstance(data, dict) and isinstance(data.get("body"), dict):           # a Teams chatMessage
        frm = (data.get("from") or {}).get("user") or {}
        return (_text_of(data["body"].get("content")), frm.get("displayName") or "", frm.get("id") or "",
                str(data.get("id") or ""), bool((data.get("from") or {}).get("application")))
    d = data if isinstance(data, dict) else {}
    return (_text_of(str(d.get("text") or "")), str(d.get("from_name") or ""), str(d.get("from_id") or ""),
            str(d.get("message_id") or ""), False)


def handle(headers_key, data):
    """From feed.py: returns (1, "") when taken, (-1, why) when refused."""
    if not key_ok(headers_key):
        return -1, "X-Centre-Key does not match the key made in Settings"
    st = settings()
    if not st["on"]:
        return -1, "Ask from Teams is switched off"
    text, name, uid, mid, from_app = parse(data)
    if from_app or not text:
        return 1, ""                                  # the workflow's own cards, or an empty message
    m = re.match(r"^\s*[@/]?%s\b[\s,:]*(.*)$" % re.escape(st["word"]), text, re.I | re.S)
    if not m:
        return 1, ""                                  # ordinary chat, not for us
    q = m.group(1).strip()
    if mid and not _first(mid):
        return 1, ""                                  # the same message twice
    threading.Thread(target=_answer, args=(q, name, uid, st), name="teams-ask", daemon=True).start()
    return 1, ""


def _first(mid):
    with _lock:
        try:
            seen = json.loads(store.get_setting("teams_ask_seen", "") or "[]")
        except ValueError:
            seen = []
        if mid in seen:
            return False
        store.set_setting("teams_ask_seen", json.dumps((seen + [mid])[-500:]), "teams")
        return True


def _reply(lines, name, uid, title, footer=None, link=None):
    import notify
    mention = [(name, uid)] if name and uid else []
    first = ("<at>%s</at> " % name) if mention else ""
    body = [first + lines[0]] + lines[1:] if lines else [first]
    msg = notify.card(title, body, link, "Open the AI page", tone="default", mentions=mention)
    if footer:
        msg["attachments"][0]["content"]["body"].insert(-1, {"type": "TextBlock", "text": footer, "isSubtle": True,
                                                              "size": "Small", "wrap": True})
    return notify.post(msg, "teams answer")


def _answer(q, name, uid, st):
    import notify, askai, spark
    who = name or "Someone"
    if not q:
        _reply(['Ask me about SplashHub Centre\'s data, e.g. "%s how many Japanese tickets are waiting?", '
                '"%s tell me about datamaas.com", "%s which POs are overdue?" or "%s draft a reply for #866538".' % ((st["word"],) * 4)],
               name, uid, "SplashHub Centre")
        return
    now = _now()
    with _lock:
        _recent[:] = [t for t in _recent if t > now - 3600000]
        if len(_recent) >= MAX_PER_HOUR:
            busy = True
        else:
            busy = False
            _recent.append(now)
    if busy:
        _reply(["I've answered %d questions this hour; ask again in a little while." % MAX_PER_HOUR], name, uid, "SplashHub Centre")
        return
    key = uid or name or "anon"
    conv = _convos.get(key)
    msgs = conv["messages"] if conv and now - conv["ms"] < FOLLOW_UP_MS else []
    msgs = (msgs + [{"role": "user", "content": q[:2000]}])[-8:]
    t0 = time.time()
    try:
        out = askai.ask(msgs)
    except spark.SparkError as e:
        _reply(["I couldn't answer just now: %s" % e], name, uid, "SplashHub Centre")
        return
    except Exception as e:
        sys.stderr.write("[teams] answer failed: %s\n" % type(e).__name__)
        _reply(["I couldn't answer just now (%s)." % type(e).__name__], name, uid, "SplashHub Centre")
        return
    secs = time.time() - t0
    answer = (out.get("answer") or "No answer.").strip()
    _convos[key] = {"ms": _now(), "messages": msgs + [{"role": "assistant", "content": answer}]}
    steps = [s.get("tool") for s in out.get("steps") or []]
    paras = [p.strip() for p in re.split(r"\n\s*\n", answer) if p.strip()][:20]
    _reply(paras, name, uid, "\U0001F4AC " + (q if len(q) <= 80 else q[:77] + "…"),
           footer="Spark · %.1f s%s · nothing was changed" % (secs, (" · looked at: " + ", ".join(dict.fromkeys(steps))) if steps else ""),
           link=notify.CENTRE + "/ask")
    try:
        store.insert_many([{"when": _now(), "agent": who, "kind": "ask (Teams)", "model": "spark:" + spark.model(),
                            "topic": q[:120], "tickets": 0, "input_tokens": 0, "output_tokens": 0, "cost": 0, "source": "centre"}])
    except Exception:
        pass


def flow_setup():
    """What to put in the Power Automate HTTP step (Settings shows it)."""
    import os
    return {"url": (os.environ.get("SPLUKI_WEBHOOK_PUBLIC_URL") or "").strip(), "header": "X-Centre-Key",
            "body": "@{triggerBody()}"}
