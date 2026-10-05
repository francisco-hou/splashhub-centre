"""The SOS Scans dashboard: the numbers above the list.

Everything is counted from the sos_scans table -- no extra calls to Zendesk
or the AI. Two optional extras come from Spark (spark.py) when it is
connected: what stands out in a spike, and package names that look like a
well-known brand. Both are cached, so a page refresh does not ask again.

Days are the viewer's days (the page sends its timezone offset).
"""
import hashlib, json, time

import spark
import store
import sosscan

DAY = 86400000
FLAGGED = ("needs_review", "suspicious")
DONE = ("solved", "closed")


def _now():
    return int(time.time() * 1000)


def _type(r):
    try:
        for f in json.loads(r.get("fields_json") or "[]"):
            if f.get("label", "").lower() == "type":
                return (f.get("value") or "").strip().lower() or "unknown"
    except ValueError:
        pass
    return "unknown"


def _team(r):
    """Who made the request: the company domain, or the whole address for a
    generic one (two gmail users are not one team)."""
    d = (r.get("creator_domain") or "").lower()
    if not d:
        return None
    return (r.get("creator_email") or d).lower() if d in sosscan.FREE_EMAIL_DOMAINS else d


def _generic(r):
    return (r.get("creator_domain") or "").lower() in sosscan.FREE_EMAIL_DOMAINS


def _cat(r):
    return {"normal": "verified", "needs_review": "needs_review", "suspicious": "high_risk"}.get(r.get("verdict") or "", "not_reviewed")


def _ratio(n, usual):
    return round(n / usual, 1) if usual else None


def build(tz_offset_min=0, fresh=False):
    now = _now()
    rows = store.sos_dash_rows(now - 60 * DAY)
    # "Open" depends on the Zendesk ticket's status: keep it current for the
    # rows the dashboard calls open (the refresh button reads them now).
    watch = [r for r in rows if r.get("ticket_status") not in DONE and
             (r.get("verdict") in FLAGGED or (not r.get("verdict") and r.get("source") != "import"))][-100:]
    if sosscan.refresh_statuses(watch, force=fresh, wait=fresh):
        rows = store.sos_dash_rows(now - 60 * DAY)
    tz = -int(tz_offset_min) * 60000                     # JS getTimezoneOffset is minutes BEHIND UTC
    day_of = lambda ms: (ms + tz) // DAY
    today = day_of(now)
    in_ = lambda a, b: [r for r in rows if a <= r["requested_ms"] < b]

    # ---- headline numbers
    last24, last7 = in_(now - DAY, now + 1), in_(now - 7 * DAY, now + 1)
    usual_day = len(in_(now - 29 * DAY, now - DAY)) / 28.0
    usual_week = len(in_(now - 35 * DAY, now - 7 * DAY)) / 4.0
    open_flag = [r for r in rows if r.get("verdict") in FLAGGED and r.get("ticket_status") not in DONE]
    nr = [r for r in open_flag if r["verdict"] == "needs_review"]
    hr = [r for r in open_flag if r["verdict"] == "suspicious"]
    month_before = in_(now - 37 * DAY, now - 7 * DAY)
    pct = lambda xs: round(100.0 * sum(1 for r in xs if _generic(r)) / len(xs)) if xs else None
    kpis = {
        "day": {"n": len(last24), "usual": round(usual_day, 1), "ratio": _ratio(len(last24), usual_day)},
        "week": {"n": len(last7), "usual": round(usual_week, 1),
                 "pct": round(100.0 * (len(last7) - usual_week) / usual_week) if usual_week else None},
        "needs_review_open": {"n": len(nr), "oldest_ms": min((r["requested_ms"] for r in nr), default=None)},
        "high_risk_open": {"n": len(hr), "first": hr[0]["ticket_id"] if hr else None},
        "generic": {"pct": pct(last7), "before": pct(month_before)},
    }

    # ---- spikes: a clear jump on the usual, and enough requests to matter
    spikes = {
        "day": {"n": len(last24), "usual": round(usual_day, 1), "ratio": _ratio(len(last24), usual_day),
                "alert": len(last24) >= 5 and len(last24) >= 2 * max(usual_day, 1)},
        "week": {"n": len(last7), "usual": round(usual_week, 1), "ratio": _ratio(len(last7), usual_week),
                 "alert": len(last7) >= 10 and len(last7) >= 1.5 * max(usual_week, 1)},
    }
    alert_rows = last24 if spikes["day"]["alert"] else (last7 if spikes["week"]["alert"] else None)
    spikes["spark"] = _spark_spike(alert_rows, "day" if spikes["day"]["alert"] else "week") if alert_rows else None

    # ---- requests per day (21 days), by verdict, with the usual for that weekday
    days = []
    for d in range(today - 20, today + 1):
        todays = [r for r in rows if day_of(r["requested_ms"]) == d]
        same_wd = [sum(1 for r in rows if day_of(r["requested_ms"]) == d - 7 * k) for k in (1, 2, 3, 4)]
        c = {"verified": 0, "needs_review": 0, "high_risk": 0, "not_reviewed": 0}
        for r in todays:
            c[_cat(r)] += 1
        days.append(dict(c, day_ms=d * DAY - tz, total=len(todays), usual=round(sum(same_wd) / 4.0, 1)))

    # ---- needs attention: flagged, or new and never reviewed; ticket still open; oldest first
    att = [r for r in rows if r.get("ticket_status") not in DONE and
           (r.get("verdict") in FLAGGED or (not r.get("verdict") and r.get("source") != "import"
                                            and r["requested_ms"] >= now - 7 * DAY))]
    att.sort(key=lambda r: r["requested_ms"])
    attention = []
    for r in att[:6]:
        why = "Not reviewed yet"
        if r.get("verdict"):
            full = store.scan_get(r["id"]) or {}
            rs = [x for x in sosscan.review_reasons(full) if x]
            why = rs[0] if rs else {"needs_review": "Needs review", "suspicious": "High risk"}.get(r["verdict"], "")
        attention.append({"id": r["id"], "ticket_id": r["ticket_id"], "verdict": r.get("verdict"), "status": r.get("status"),
                          "source": r.get("source"), "why": why, "requested_ms": r["requested_ms"]})

    # ---- who's asking (7 days): top creator domains, new vs returning teams
    seen_before = {_team(r) for r in rows if r["requested_ms"] < now - 7 * DAY}
    flagged_before = {_team(r) for r in rows if r["requested_ms"] < now - 7 * DAY and r.get("verdict") in FLAGGED}
    doms = {}
    for r in last7:
        d = (r.get("creator_domain") or "unknown").lower()
        doms[d] = doms.get(d, 0) + 1
    teams = {_team(r) for r in last7 if _team(r)}
    who = {"domains": [{"domain": d, "n": n, "generic": d in sosscan.FREE_EMAIL_DOMAINS}
                       for d, n in sorted(doms.items(), key=lambda x: -x[1])[:5]],
           "new": len(teams - seen_before), "returning": len(teams & seen_before),
           "flagged_before": len(teams & flagged_before)}

    # ---- package mix and AI spend (7 days)
    mix = {}
    for r in last7:
        t = _type(r)
        mix[t] = mix.get(t, 0) + 1
    reviewed = [r for r in last7 if (r.get("cost") or 0) > 0]
    spend = {"total": round(sum(r["cost"] for r in reviewed), 4), "reviews": len(reviewed),
             "avg": round(sum(r["cost"] for r in reviewed) / len(reviewed), 4) if reviewed else 0}

    return {"kpis": kpis, "spikes": spikes, "days": days, "attention": attention, "who": who,
            "mix": [{"type": k, "n": v} for k, v in sorted(mix.items(), key=lambda x: -x[1])], "spend": spend,
            "lookalikes": _spark_lookalikes(last7), "spark": spark.available(), "now": now}


# ---- Spark extras (cached in settings; None when Spark is not connected) ---------------

def _cached(key, rows, make, max_age_ms=30 * 60000):
    sig = hashlib.sha256(",".join(str(r["id"]) for r in rows).encode()).hexdigest()[:16]
    try:
        got = json.loads(store.get_setting(key, "") or "null")
    except ValueError:
        got = None
    if got and got.get("sig") == sig and _now() - got.get("ms", 0) < max_age_ms:
        return got["value"]
    value = make()
    store.set_setting(key, json.dumps({"sig": sig, "ms": _now(), "value": value}), "spark")
    return value


def _brief(r):
    name = ""
    try:
        name = next((f.get("value") for f in json.loads(r.get("fields_json") or "[]") if f.get("label", "").lower() == "package name"), "")
    except ValueError:
        pass
    return "- package %r | creator domain %s | type %s | verdict %s | %s UTC" % (
        name or r.get("subject") or "?", r.get("creator_domain") or "?", _type(r), r.get("verdict") or "not reviewed",
        time.strftime("%a %H:%M", time.gmtime(r["requested_ms"] / 1000)))


def _spark_spike(rows, window):
    if not spark.available():
        return {"off": True}
    try:
        text = _cached("spark_spike_" + window, rows, lambda: spark.chat(
            "You look at a burst of Custom SOS package requests (white-labelled remote-support builds) and say, in at most "
            "3 short bullet points, what they have in common: shared creator domains, generic email providers, trial vs "
            "paid, repeated or similar package names, time of day. Facts from the list only; no advice. Start each bullet with '- '.",
            "%d requests in the last %s:\n%s" % (len(rows), "24 hours" if window == "day" else "7 days",
                                                  "\n".join(_brief(r) for r in rows[:60]))))
        return {"points": [l.strip()[2:].strip() for l in text.splitlines() if l.strip().startswith("- ")][:3] or [text.strip()]}
    except spark.SparkError as e:
        return {"error": str(e)}


def _spark_lookalikes(rows):
    if not spark.available():
        return {"off": True}
    if not rows:
        return {"items": []}
    try:
        text = _cached("spark_lookalikes", rows, lambda: spark.chat(
            "From this list of package names, pick the ones that imitate or misspell a well-known brand or institution "
            "(banks, payment services, big tech, governments) that the creator domain does not belong to. Answer one "
            "per line as: name | brand it imitates. Answer NONE if there are none.",
            "\n".join(_brief(r) for r in rows[:120]), max_tokens=300), max_age_ms=60 * 60000)
        items = []
        for line in text.splitlines():
            if "|" in line:
                name, brand = [x.strip(" -*\"'") for x in line.split("|", 1)]
                if name:
                    items.append({"name": name, "brand": brand})
        return {"items": items[:5]}
    except spark.SparkError as e:
        return {"error": str(e)}
