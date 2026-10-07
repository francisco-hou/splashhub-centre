"""Spark: Splashtop's own AI service (spark-llm-service on the DGX Spark hosts).

Small open models behind an OpenAI-compatible API, reached app-to-app inside
Spluki (no OUTBOUND_HTTP grant). Free per call, rate-limited per token.

Settings (environment), filled in on Spluki by an administrator once the
SPLUKI_AI_SPARK grant is declared and its token issued:
  AI_SPARK_BASE_URL   ends in /v1
  AI_SPARK_API_KEY    this app's token (Bearer)
Until both are there, available() is False and callers carry on without it.

Errors are worded here, never copied from the library (see zendesk.py).
"""
import json, os, re, threading, time, urllib.error, urllib.request

TIMEOUT = 60
_MODELS = {"at": 0, "list": []}


class SparkError(Exception):
    """A message that is safe to show."""


def _cfg():
    return (os.environ.get("AI_SPARK_BASE_URL") or "").strip().rstrip("/"), (os.environ.get("AI_SPARK_API_KEY") or "").strip()


def available():
    base, key = _cfg()
    return bool(base and key)


def _call(path, body=None):
    base, key = _cfg()
    if not (base and key):
        raise SparkError("Spark isn't connected yet")
    req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                 method="POST" if body is not None else "GET",
                                 headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        hint = {401: "the Spark token was refused", 403: "this token may not use that model", 429: "Spark rate limit"}.get(e.code, "")
        raise SparkError("Spark answered HTTP %d%s" % (e.code, (" -- " + hint) if hint else ""))
    except Exception as e:
        raise SparkError("could not reach Spark (%s)" % type(e).__name__)


def models():
    """The models this token may use, as Spark lists them (cached an hour)."""
    if not _MODELS["list"] or time.time() - _MODELS["at"] > 3600:
        d = _call("/models")
        _MODELS.update(at=time.time(), list=[m.get("id") for m in d.get("data") or [] if m.get("id")])
    return list(_MODELS["list"])


def model():
    """The model to use: AI_SPARK_MODEL if set; else the one picked in Settings
    (spark_model), if Spark still offers it; else the first it lists."""
    if os.environ.get("AI_SPARK_MODEL"):
        return os.environ["AI_SPARK_MODEL"].strip()
    have = models()
    if not have:
        raise SparkError("Spark lists no model for this token")
    try:
        import store
        picked = store.get_setting("spark_model", "") or ""
    except Exception:
        picked = ""
    return picked if picked in have else have[0]


def clean(text):
    """The answer without a reasoning model's <think> block (Qwen3 on Spark
    may think out loud first; only what follows is the answer)."""
    text = text or ""
    if "</think>" in text:
        text = text.split("</think>")[-1]
    return re.sub(r"<think>.*", "", text, flags=re.S).strip()


def thinking_on():
    """Settings: let the model think before answering (slower). Off by default."""
    try:
        import store
        return store.get_setting("spark_thinking", "off") == "on"
    except Exception:
        return False


def speed_test(m=None):
    """Seconds for a tiny question on a model (Settings' Test speed button)."""
    m = m or model()
    if m not in models():
        raise SparkError("Spark doesn't offer that model")
    body = {"model": m, "max_tokens": 200, "temperature": 0,
            "messages": [{"role": "user", "content": "In one short sentence: what is remote support software?"}]}
    if _NO_THINK["ok"] and not thinking_on():
        body["chat_template_kwargs"] = {"enable_thinking": False}
    t0 = time.time()
    d = _call("/chat/completions", body)
    secs = round(time.time() - t0, 1)
    try:
        answer = clean(d["choices"][0]["message"].get("content"))
    except (KeyError, IndexError, TypeError, AttributeError):
        answer = ""
    return {"model": m, "seconds": secs, "answer": answer[:200]}


# Thinking models (Qwen3) write a long hidden chain of reasoning before every
# answer -- most of the wait, and none of it is used. vLLM, behind Spark,
# turns it off with chat_template_kwargs. A model or server that refuses the
# switch gets one retry without it, and is not sent it again.
_NO_THINK = {"ok": True}
_LAST = threading.local()      # the last call's token counts on this thread (Spark activity reads them)


def chat_raw(messages, tools=None, max_tokens=2000):
    """One Chat Completions call; the reply message as Spark sends it
    (content and, when tools are given, any tool_calls). Timed in the log."""
    m = model()
    body = {"model": m, "max_tokens": max_tokens, "temperature": 0.2, "messages": messages}
    if tools:
        body["tools"] = tools
    t0 = time.time()
    if _NO_THINK["ok"] and not thinking_on():
        try:
            d = _call("/chat/completions", dict(body, chat_template_kwargs={"enable_thinking": False}))
        except SparkError as e:
            if "HTTP 400" not in str(e) and "HTTP 422" not in str(e):
                raise
            _NO_THINK["ok"] = False
            import sys
            sys.stderr.write("[spark] the thinking switch was refused; asking without it from now on\n")
            d = _call("/chat/completions", body)
    else:
        d = _call("/chat/completions", body)
    import sys
    u = d.get("usage") or {}
    _LAST.usage = u
    sys.stderr.write("[spark] %s %.1fs%s%s\n" % (m, time.time() - t0, " +tools" if tools else "",
                                                ", %s tokens out" % u["completion_tokens"] if u.get("completion_tokens") else ""))
    try:
        return d["choices"][0]["message"] or {}
    except (KeyError, IndexError, TypeError):
        raise SparkError("Spark's answer had no message")


def _thoughts(msg, raw):
    """The model's reasoning, when it thought out loud (Settings > Spark: thinking on)."""
    t = msg.get("reasoning_content") or msg.get("reasoning") or ""
    if not t and "<think>" in (raw or ""):
        t = raw.split("<think>", 1)[1].split("</think>", 1)[0]
    return t.strip()


def chat(system, user, max_tokens=2000, log=None):     # room for a model that thinks first
    """One short answer as plain text. log={"area": ..., "tickets": id or [ids]}:
    the call is kept in Spark activity (sparklog.py) -- the question, the text,
    the answer, the reasoning -- and log["id"] is set for sparklog.decide()."""
    t0 = time.time()
    _LAST.usage = {}
    try:
        msg = chat_raw([{"role": "system", "content": system}, {"role": "user", "content": user}], max_tokens=max_tokens)
    except Exception as e:
        if log is not None:
            _keep(log, system, user, "", "", t0, "%s" % e if isinstance(e, SparkError) else type(e).__name__)
        raise
    raw = msg.get("content") or ""
    text = clean(raw)
    if log is not None:
        _keep(log, system, user, text, _thoughts(msg, raw), t0, None if text else "the answer had no text")
    if not text:
        raise SparkError("Spark's answer had no text")
    return text


def _keep(log, system, user, answer, thinking, t0, error):
    try:
        import sparklog
        u = getattr(_LAST, "usage", None) or {}
        log["id"] = sparklog.record(log.get("area") or "other", log.get("tickets"), system, user, answer, thinking,
                                    int((time.time() - t0) * 1000), model(), error,
                                    u.get("prompt_tokens"), u.get("completion_tokens"))
    except Exception:
        log["id"] = None
