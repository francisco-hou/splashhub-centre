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
import json, os, re, time, urllib.error, urllib.request

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


def model():
    """The model to use: AI_SPARK_MODEL if set, else the first the token may use."""
    if os.environ.get("AI_SPARK_MODEL"):
        return os.environ["AI_SPARK_MODEL"].strip()
    if not _MODELS["list"] or time.time() - _MODELS["at"] > 3600:
        d = _call("/models")
        _MODELS.update(at=time.time(), list=[m.get("id") for m in d.get("data") or [] if m.get("id")])
    if not _MODELS["list"]:
        raise SparkError("Spark lists no model for this token")
    return _MODELS["list"][0]


def clean(text):
    """The answer without a reasoning model's <think> block (Qwen3 on Spark
    may think out loud first; only what follows is the answer)."""
    text = text or ""
    if "</think>" in text:
        text = text.split("</think>")[-1]
    return re.sub(r"<think>.*", "", text, flags=re.S).strip()


def chat_raw(messages, tools=None, max_tokens=2000):
    """One Chat Completions call; the reply message as Spark sends it
    (content and, when tools are given, any tool_calls)."""
    body = {"model": model(), "max_tokens": max_tokens, "temperature": 0.2, "messages": messages}
    if tools:
        body["tools"] = tools
    d = _call("/chat/completions", body)
    try:
        return d["choices"][0]["message"] or {}
    except (KeyError, IndexError, TypeError):
        raise SparkError("Spark's answer had no message")


def chat(system, user, max_tokens=2000):     # room for a model that thinks first
    """One short answer as plain text."""
    text = clean(chat_raw([{"role": "system", "content": system}, {"role": "user", "content": user}],
                          max_tokens=max_tokens).get("content"))
    if not text:
        raise SparkError("Spark's answer had no text")
    return text
