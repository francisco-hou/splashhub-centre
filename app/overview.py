"""Overview: the whole support picture on one admin page (Admin > Dashboard).

Team-wide numbers, except AI usage: per member as the run log records it (the
Logs page shows the same), with a member filter. Admin only.

  Zendesk now     tickets new / open / pending / on hold, the RR queue, created
                  and solved today, and the RR queue per routed language --
                  Zendesk search counts, read in the background at most every 5
                  minutes; the page shows the last ones and never waits for them
  Tickets         2026 tickets per day for 14 days, this week vs last, top tags
                  and the words rising in what customers write (Zendesk Tickets)
  SOS / SSO / PO  what is waiting and what came in (their own pages' numbers)
  Needs attention one list across them: oldest first, with links
  AI usage        runs and estimated cost this week vs last, by tool (Logs)
  Knowledge Base  articles rated least helpful, outdated translations
  Customers       the most active this month
"""
import json, sys, threading, time

import store

DAY = 86400000
OPEN = ("new", "open", "pending", "hold")
LIVE_EVERY = 300
_live = {"ms": 0, "data": None, "error": None}
_busy = threading.Lock()
_rising = {"ms": 0, "words": []}


def _now():
    return int(time.time() * 1000)


def _rows(sql, args=()):
    try:
        return store._read(sql, list(args), fresh=True)
    except Exception:
        return []


def _one(sql, args=()):
    r = _rows(sql, args)
    return int(r[0][0] or 0) if r else 0


# ---- Zendesk now (search counts, in the background) ------------------------------------------

def _count(q):
    import zendesk
    from urllib.parse import quote
    return int((zendesk.get_json("/api/v2/search/count.json?query=" + quote(q)) or {}).get("count") or 0)


def _read_live():
    import notify, zendesk
    if zendesk.configured():
        raise RuntimeError("SplashHub Centre can't read Zendesk yet")
    today = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 86400))        # Zendesk compares whole days: > yesterday
    d = {k: _count("type:ticket status:" + k) for k in ("new", "open", "pending", "hold")}
    cfg = notify.lang_config()
    d["rr"] = _count(cfg["query"])
    d["created_today"] = _count("type:ticket created>" + today)
    d["solved_today"] = _count("type:ticket solved>" + today)
    langs = []
    for r in cfg["rows"]:
        if r.get("tags"):
            n = sum(_count("%s tags:%s" % (cfg["query"], t)) for t in r["tags"])
            langs.append({"lang": r["lang"], "n": n})
    d["languages"] = sorted([l for l in langs if l["n"]], key=lambda l: -l["n"])
    return d


def live(fresh=False):
    """The last Zendesk counts; refreshed in the background when older than 5 minutes."""
    stale = fresh or time.time() - _live["ms"] / 1000 > LIVE_EVERY

    def run():
        try:
            _live.update(data=_read_live(), error=None, ms=_now())
        except Exception as e:
            _live.update(error=str(e)[:200] if "Zendesk" in str(e) else "could not read Zendesk (%s)" % type(e).__name__, ms=_now())
            sys.stderr.write("[overview] Zendesk counts: %s\n" % _live["error"])
        finally:
            _busy.release()
    if stale and _busy.acquire(blocking=False):
        threading.Thread(target=run, name="overview-live", daemon=True).start()
    return {"data": _live["data"], "ms": _live["ms"] or None, "error": _live["error"], "updating": _busy.locked()}


# ---- from SplashHub Centre's own data -----------------------------------------------------------

def _tickets(now):
    days = []
    start = (now // DAY) * DAY - 13 * DAY
    per = dict(_rows("SELECT created_ms / %d AS d, count(*) FROM cases WHERE created_ms >= %%s GROUP BY created_ms / %d" % (DAY, DAY), (start,)))
    for i in range(14):
        k = start // DAY + i
        days.append({"day_ms": k * DAY, "n": int(per.get(k, 0) or 0)})
    week = _one("SELECT count(*) FROM cases WHERE created_ms >= %s", (now - 7 * DAY,))
    prev = _one("SELECT count(*) FROM cases WHERE created_ms >= %s AND created_ms < %s", (now - 14 * DAY, now - 7 * DAY))
    tags = {}
    for (t,) in _rows("SELECT tags FROM cases WHERE created_ms >= %s", (now - 7 * DAY,)):
        for g in (t or "").split():
            if g not in ("assigned_by_rr",) and not g.startswith("language_"):
                tags[g] = tags.get(g, 0) + 1
    if now - _rising["ms"] > 600000:                     # a heavier count: kept 10 minutes
        try:
            import cases
            o = cases.overview(time.strftime("%Y-%m-%d", time.gmtime((now - 30 * DAY) / 1000)))
            _rising.update(ms=now, words=[w for w in (o.get("rising_last_30_days") or [])][:8])
        except Exception:
            _rising.update(ms=now, words=[])
    rising = _rising["words"]
    return {"days": days, "week": week, "prev_week": prev, "total_2026": _one("SELECT count(*) FROM cases"),
            "tags": [{"tag": g, "n": n} for g, n in sorted(tags.items(), key=lambda x: -x[1])[:10]], "rising": rising}


def _sos(now):
    flagged = lambda v: _one("SELECT count(*) FROM sos_scans WHERE verdict = %s AND coalesce(ticket_status, '') NOT IN ('solved', 'closed')", (v,))
    return {"day": _one("SELECT count(*) FROM sos_scans WHERE requested_ms >= %s", (now - DAY,)),
            "week": _one("SELECT count(*) FROM sos_scans WHERE requested_ms >= %s", (now - 7 * DAY,)),
            "needs_review": flagged("needs_review"), "high_risk": flagged("suspicious")}


def _sso(now):
    st = dict(_rows("SELECT status, count(*) FROM sso_requests GROUP BY status"))
    return {"waiting": int(st.get("pending", 0) or 0) + int(st.get("not_found", 0) or 0),
            "needs_details": int(st.get("needs_details", 0) or 0), "verified_week": _one(
                "SELECT count(*) FROM sso_requests WHERE verified_ms >= %s", (now - 7 * DAY,)),
            "total": sum(int(v or 0) for v in st.values())}


def _po():
    try:
        import po
        o = po.overview()
        return {k: o[k] for k in ("total", "open", "due_week", "overdue", "last_30d")}
    except Exception:
        return {"total": 0, "open": 0, "due_week": 0, "overdue": 0, "last_30d": 0}


def _attention(now):
    out = []
    for sid, tid, ms, v in _rows("SELECT id, ticket_id, requested_ms, verdict FROM sos_scans WHERE verdict IN ('needs_review', 'suspicious') "
                                 "AND coalesce(ticket_status, '') NOT IN ('solved', 'closed') ORDER BY requested_ms ASC LIMIT 6"):
        out.append({"kind": "SOS", "what": "High risk" if v == "suspicious" else "Needs review", "ticket": tid, "ms": ms,
                    "link": "/scans#%s" % sid, "tone": "red" if v == "suspicious" else "orange"})
    try:
        import po
        for r in po.search(when="overdue", per_page=6)["rows"]:
            out.append({"kind": "PO", "what": "Overdue · %s" % (r.get("company") or r.get("spid") or ""), "ticket": r["ticket_id"],
                        "ms": r.get("created_ms"), "link": "/po#%s" % r["ticket_id"], "tone": "red", "note": "expected %s" % r.get("expected")})
    except Exception:
        pass
    for sid, tid, ms, dom, st in _rows("SELECT id, ticket_id, requested_ms, domain, status FROM sso_requests WHERE status IN ('pending', 'not_found', 'needs_details') "
                                       "AND requested_ms < %s ORDER BY requested_ms ASC LIMIT 6", (now - 3 * DAY,)):
        out.append({"kind": "SSO", "what": ("Needs details" if st == "needs_details" else "Waiting") + (" · %s" % dom if dom else ""),
                    "ticket": tid, "ms": ms, "link": "/sso#%s" % sid, "tone": "orange"})
    out.sort(key=lambda x: x.get("ms") or 0)
    return out[:14]


def _ai(now, agent=None):
    """Runs and cost by tool, this week vs last -- for everyone, or one member
    (the name the run log records); plus each member's runs this week."""
    who, wa = (" AND agent = %s", (agent,)) if agent else ("", ())

    def by_tool(a, b):
        return {t: {"runs": int(n or 0), "cost": float(c or 0)} for t, n, c in _rows(
            "SELECT tool, count(*), sum(cost) FROM runs WHERE ts_ms >= %s AND ts_ms < %s" + who + " GROUP BY tool", (a, b) + wa)}
    people = [{"agent": a, "runs": int(n or 0), "cost": round(float(c or 0), 2)} for a, n, c in _rows(
        "SELECT agent, count(*), sum(cost) FROM runs WHERE ts_ms >= %s AND agent IS NOT NULL AND agent <> '' "
        "GROUP BY agent ORDER BY count(*) DESC", (now - 30 * DAY,))]
    week, prev = by_tool(now - 7 * DAY, now + 1), by_tool(now - 14 * DAY, now - 7 * DAY)
    labels = dict(store.TOOLS)
    tools = [{"tool": labels.get(t, t), "runs": v["runs"], "cost": round(v["cost"], 2), "prev_runs": (prev.get(t) or {}).get("runs", 0)}
             for t, v in sorted(week.items(), key=lambda x: -x[1]["runs"])]
    return {"runs": sum(v["runs"] for v in week.values()), "cost": round(sum(v["cost"] for v in week.values()), 2),
            "prev_runs": sum(v["runs"] for v in prev.values()), "prev_cost": round(sum(v["cost"] for v in prev.values()), 2),
            "tools": tools, "agent": agent, "people": people}


def _kb():
    rows = _rows("SELECT id, title, url, vote_sum, vote_count FROM kb_articles WHERE locale = 'en-us' AND vote_count >= 10 "
                 "AND draft = 0 ORDER BY (1.0 * vote_sum / vote_count) ASC LIMIT 5")
    worst = []
    for i, t, u, s, c in rows:
        up = (int(c) + int(s)) // 2
        worst.append({"id": i, "title": t, "url": u, "helpful": round(100.0 * up / int(c)) if c else None, "votes": int(c)})
    return {"articles": _one("SELECT count(DISTINCT id) FROM kb_articles"),
            "outdated": _one("SELECT count(*) FROM kb_articles WHERE outdated = 1"), "least_helpful": worst}


def _customers():
    try:
        import customers
        return [{"key": c["key"], "label": c["label"], "tickets": c["tickets"], "open": c["open"], "sos": c["sos"], "sso": c["sso"]}
                for c in customers.top(30, 6)["customers"]]
    except Exception:
        return []


def build(fresh=False, agent=None):
    now = _now()
    return {"now": now, "live": live(fresh), "tickets": _tickets(now), "sos": _sos(now), "sso": _sso(now), "po": _po(),
            "attention": _attention(now), "ai": _ai(now, agent), "kb": _kb(), "customers": _customers()}
