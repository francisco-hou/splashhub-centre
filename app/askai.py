"""Ask AI: questions about what SplashHub Centre holds, answered by Spark.

Spark is given a short list of READ-ONLY lookups (TOOLS) over SplashHub
Centre's own data -- SOS requests, SSO requests and the run log -- and asks
for what it needs (OpenAI-style tool calls). The answer comes from those
results only, with ticket numbers to click. Nothing here writes anything,
and nothing reaches Zendesk.

Each step is returned with the answer, so the page can show what was looked
at -- the way to trust (or doubt) a small model's answer.
"""
import json, time

import spark
import store
import sosscan

DAY = 86400000
MAX_STEPS = 5


def _now():
    return int(time.time() * 1000)


def _since(days):
    try:
        days = max(1, min(int(days or 7), 3650))
    except (TypeError, ValueError):
        days = 7
    return _now() - days * DAY, days


def _pkg(r):
    try:
        for f in json.loads(r.get("fields_json") or "[]"):
            if f.get("label", "").lower() in ("package name", "type"):
                r.setdefault("_" + f["label"].lower().replace(" ", "_"), f.get("value"))
    except ValueError:
        pass
    return r


VERDICT = {"normal": "verified", "needs_review": "needs review", "suspicious": "high risk", None: "not reviewed"}


# ---- the lookups ---------------------------------------------------------------------------

def sos_overview(days=7):
    since, days = _since(days)
    rows = [_pkg(r) for r in store.sos_dash_rows(since)]
    by = {}
    for r in rows:
        by[VERDICT.get(r.get("verdict"), "not reviewed")] = by.get(VERDICT.get(r.get("verdict"), "not reviewed"), 0) + 1
    gen = sum(1 for r in rows if (r.get("creator_domain") or "").lower() in sosscan.FREE_EMAIL_DOMAINS)
    trial = sum(1 for r in rows if (r.get("_type") or "").lower() == "trial")
    doms = {}
    for r in rows:
        d = (r.get("creator_domain") or "unknown").lower()
        doms[d] = doms.get(d, 0) + 1
    open_flag = [r for r in rows if r.get("verdict") in ("needs_review", "suspicious") and r.get("ticket_status") not in ("solved", "closed")]
    return {"days": days, "requests": len(rows), "by_verdict": by, "generic_email_creators": gen, "trial_packages": trial,
            "top_creator_domains": sorted(doms.items(), key=lambda x: -x[1])[:8],
            "flagged_with_ticket_still_open": [r["ticket_id"] for r in open_flag][:20],
            "ai_review_cost_usd": round(sum(r.get("cost") or 0 for r in rows), 3)}


def sos_search(text=None, verdict=None, ticket_status=None, creator_domain=None, days=30, limit=10):
    since, days = _since(days)
    rows = [_pkg(r) for r in store.sos_dash_rows(since)]
    t = (text or "").lower().strip()
    v = {"verified": "normal", "needs review": "needs_review", "needs_review": "needs_review", "high risk": "suspicious",
         "suspicious": "suspicious", "normal": "normal", "not reviewed": None}.get((verdict or "").lower().strip(), "any")
    out = []
    for r in reversed(rows):                             # newest first
        if v != "any" and r.get("verdict") != v:
            continue
        if ticket_status and (r.get("ticket_status") or "") != ticket_status.lower().strip():
            continue
        if creator_domain and creator_domain.lower().strip() not in (r.get("creator_domain") or ""):
            continue
        hay = " ".join(str(x or "") for x in (r.get("subject"), r.get("creator_email"), r.get("_package_name"), r["ticket_id"])).lower()
        if t and t not in hay:
            continue
        out.append({"ticket": r["ticket_id"], "date": time.strftime("%Y-%m-%d", time.gmtime(r["requested_ms"] / 1000)),
                    "verdict": VERDICT.get(r.get("verdict"), "not reviewed"), "ticket_status": r.get("ticket_status"),
                    "package": r.get("_package_name"), "type": r.get("_type"), "creator": r.get("creator_email")})
        if len(out) >= max(1, min(int(limit or 10), 25)):
            break
    return {"days": days, "matches": out, "shown": len(out)}


def sos_request(ticket_id):
    try:
        tid = int(str(ticket_id).lstrip("#"))
    except (TypeError, ValueError):
        return {"error": "not a ticket number"}
    ids = [r[0] for r in store._read("SELECT id FROM sos_scans WHERE ticket_id = %s ORDER BY id DESC LIMIT 1", [tid])]
    if not ids:
        return {"error": "SplashHub Centre has no SOS request for ticket #%d" % tid}
    row = store.scan_get(ids[0]) or {}
    res = json.loads(row.get("result_json") or "null") or {}
    fields = {f["label"]: f["value"] for f in sosscan.parse_request(row.get("description") or "")["fields"] if f.get("value")}
    return {"ticket": tid, "verdict": VERDICT.get(sosscan.effective_verdict(row, res) if res else None, "not reviewed"),
            "reasons": sosscan.review_reasons(row, res) if res else [], "review_summary": res.get("overall_summary"),
            "ticket_status": row.get("ticket_status"), "creator": row.get("creator_email"), "fields": fields,
            "internal_note_added": bool(json.loads(row.get("note_json") or "null"))}


def sso_lookup(text=None, status=None, limit=10):
    st = {"verified": "verified", "not found": "not_found", "not_found": "not_found", "waiting": "waiting", "pending": "pending",
          "needs details": "needs_details", "error": "error"}.get((status or "").lower().strip())
    res = store.sso_list((text or "").strip() or None, st, 0, max(1, min(int(limit or 10), 25)))
    return {"total": res["total"], "counts": res["counts"],
            "requests": [{"ticket": r["ticket_id"], "domain": r.get("domain"), "status": r.get("status"),
                          "requester": r.get("requester_email"),
                          "last_checked": time.strftime("%Y-%m-%d %H:%M", time.gmtime(r["last_checked_ms"] / 1000)) if r.get("last_checked_ms") else None}
                         for r in res["rows"]]}


def runs_summary(days=7):
    since, days = _since(days)
    agg = store.summary({"since": since})
    by_agent = store._read("SELECT agent, count(*), coalesce(sum(cost),0) FROM runs WHERE ts_ms >= %s AND agent IS NOT NULL "
                           "GROUP BY agent ORDER BY count(*) DESC LIMIT 10", [since])
    by_model = store._read("SELECT model, count(*), coalesce(sum(cost),0) FROM runs WHERE ts_ms >= %s AND model IS NOT NULL "
                           "GROUP BY model ORDER BY count(*) DESC LIMIT 8", [since])
    return {"days": days, "runs": agg["runs"], "cost_usd": round(agg["cost"], 2), "agents": agg["agents"],
            "by_tool": [{"tool": t["label"], "runs": t["runs"], "cost_usd": round(t["cost"], 2)} for t in agg["by_tool"] if t["runs"]],
            "by_agent": [{"agent": a, "runs": n, "cost_usd": round(float(c), 2)} for a, n, c in by_agent],
            "by_model": [{"model": m, "runs": n, "cost_usd": round(float(c), 2)} for m, n, c in by_model]}


# The Price Book (pricebook.py): the list prices the Price Book page last read
# from splashtop.com. Plan keys and market columns are pricebook.js's own.
PLANS = {"solo": "Remote Access Solo (per year)", "pro": "Remote Access Pro (per user per year)",
         "performance": "Remote Access Performance (per user per year)",
         "sos10": "SOS+10 (per concurrent user per year)", "sos300": "SOS+300 (per concurrent user per year)",
         "aemMonthly": "AEM, billed monthly (per endpoint per month, 101-250 band)",
         "aemYearly": "AEM, billed yearly (per endpoint per year, 101-250 band)",
         "bitdefender": "Antivirus by Bitdefender (per endpoint per month, 5-100 band)"}
PROMO_MARKETS = {"solo": ("Zone4", "CHF", "SEK", "NOK", "DKK", "BRL")}
MARKETS = {"Zone1": "USA", "Canada": "Canada", "Zone4": "EU", "GBP": "UK", "BRL": "Brazil", "MXN": "Mexico",
           "JPY": "Japan", "TWD": "Taiwan", "Zone5": "China", "CHF": "Switzerland", "DKK": "Denmark",
           "SEK": "Sweden", "NOK": "Norway"}


def prices(product=None, market=None):
    import pricebook
    book = pricebook.book()
    if not book or not book.get("prices"):
        return {"error": "the Price Book has no prices yet (open the Price Book page once to load them)"}
    want_p = (product or "").lower().replace(" ", "").replace("+", "")
    want_m = (market or "").lower().strip()
    out = []
    for key, label in PLANS.items():
        if want_p and want_p not in (key.lower() + label.lower().replace(" ", "").replace("+", "")):
            continue
        row = book["prices"].get(key) or {}
        cells = {MARKETS[c]: v for c, v in row.items() if c in MARKETS and (not want_m or want_m in MARKETS[c].lower())}
        # pricebook.js shows Solo's first-year promo only in these markets (SOLO_PROMO_MARKETS)
        promo = {MARKETS[c]: v for c, v in ((book.get("promos") or {}).get(key) or {}).items()
                 if c in PROMO_MARKETS.get(key, ()) and (not want_m or want_m in MARKETS[c].lower())}
        if cells:
            out.append(dict({"plan": label, "list_price": cells}, **({"first_year_promo": promo} if promo else {})))
    when = book.get("when")
    return {"prices": out, "as_of": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(when / 1000)) if when else None,
            "note": "Annual list prices from splashtop.com unless the plan says monthly. AEM and Antivirus have more bands; see the Price Book page."}


TOOLS = {
    "sos_overview": (sos_overview, "Counts of Custom SOS package requests over the last N days: by verdict, generic-email "
                     "creators, trials, top creator domains, flagged requests whose ticket is still open, AI review cost.",
                     {"days": {"type": "integer", "description": "how many days back (default 7)"}}),
    "sos_search": (sos_search, "Find SOS package requests. Filter by text (package name, creator, subject), verdict "
                   "(verified / needs review / high risk / not reviewed), Zendesk ticket status (new, open, pending, hold, "
                   "solved, closed), creator domain, and days back.",
                   {"text": {"type": "string"}, "verdict": {"type": "string"}, "ticket_status": {"type": "string"},
                    "creator_domain": {"type": "string"}, "days": {"type": "integer"}, "limit": {"type": "integer"}}),
    "sos_request": (sos_request, "Everything SplashHub Centre knows about one SOS request, by Zendesk ticket number: "
                    "verdict, reasons, review summary, package fields, ticket status.",
                    {"ticket_id": {"type": "integer"}}),
    "sso_lookup": (sso_lookup, "SSO method validation requests: counts by status, and requests matching a text (ticket, "
                   "domain, requester) or a status (verified / not found / waiting / needs details).",
                   {"text": {"type": "string"}, "status": {"type": "string"}, "limit": {"type": "integer"}}),
    "prices": (prices, "Splashtop list prices from the Price Book, per plan and market (USA, Canada, EU, UK, Brazil, "
               "Mexico, Japan, Taiwan, China, Switzerland, Denmark, Sweden, Norway). Plans: Solo, Pro, Performance, "
               "SOS+10, SOS+300, AEM monthly/yearly, Antivirus. Leave a filter empty to get all.",
               {"product": {"type": "string"}, "market": {"type": "string"}}),
    "runs_summary": (runs_summary, "The SplashHub run log (every AI and tool run by agents in the Zendesk app) over the "
                     "last N days: totals, cost, and breakdowns by tool, agent and model.",
                     {"days": {"type": "integer"}}),
}


def plan_guide(market="USA"):
    import planguide, pricebook
    try:
        return planguide.guide(market)
    except pricebook.PriceError as e:
        return {"error": str(e)}


def quote(items=None, market="USA"):
    import planguide, pricebook
    try:
        return planguide.quote(items or [], market)
    except pricebook.PriceError as e:
        return {"error": str(e)}


TOOLS["plan_guide"] = (plan_guide, "Every Splashtop plan with who it is for, its limits (users, computers, attended / "
                       "unattended), its yearly list price per unit in a market INCLUDING volume steps (Pro and "
                       "Performance are cheaper from 4 and from 10 licences), splashtop.com's pricing FAQ, and the team's "
                       "own notes. Call this first for any 'which plan' or 'how much would it cost' question.",
                       {"market": {"type": "string", "description": "USA, Canada, EU, UK, Brazil, Mexico, Japan, Taiwan, "
                                   "China, Switzerland, Denmark, Sweden or Norway (default USA)"}})
TOOLS["quote"] = (quote, "Price a combination of plans: line items with the right volume step and a yearly total. "
                  "ALWAYS use this for totals -- never add prices up yourself. Plans: solo, pro, performance, sos10, "
                  "sos300, aem, antivirus.",
                  {"items": {"type": "array", "items": {"type": "object", "properties": {
                      "plan": {"type": "string"}, "quantity": {"type": "integer"}}}},
                   "market": {"type": "string"}})


def _tool_specs():
    return [{"type": "function", "function": {"name": n, "description": d, "parameters": {"type": "object", "properties": p}}}
            for n, (_, d, p) in TOOLS.items()]


SYSTEM = ("You are the assistant inside SplashHub Centre, Splashtop support's internal tool. Answer questions about "
          "what SplashHub Centre holds: Custom SOS package requests and their AI brand reviews, SSO method validation "
          "requests and their DNS checks, Splashtop list prices (the Price Book), and the SplashHub run log. Use the tools to look things up; answer ONLY from "
          "their results and never invent numbers or tickets. If the tools can't answer, say so plainly. Be brief: a "
          "sentence or two, then a short list if useful. Write ticket numbers as #12345. Today is %s (UTC).\n\n"
          "PLAN QUESTIONS (\"what's the best plan for 3 techs, 200 users and 10 devices\", attended vs unattended...): "
          "call plan_guide, decide what fits from its 'for' lines and the FAQ, then call quote for EACH option. Answer as:\n"
          "**Assumptions** - how you read the need (technicians = concurrent technician licences for supporting OTHER "
          "people; users reaching their OWN computers = Remote Access user licences; attended = on-demand with a "
          "session code; unattended = installed agent; computers/devices/endpoints counts).\n"
          "**Option 1 - <name>** then each quote line as '- <plan>: <quantity> x <each> = <line total>' (say when a "
          "volume price applies), then '**Total: <total> per year**', and one line on why it fits.\n"
          "**Option 2 - <name>** the same, when a second combination also fits (e.g. a bigger plan with room to grow, "
          "or attended-only vs with unattended computers). Leave it out if only one option makes sense.\n"
          "End with: 'List prices from splashtop.com; Sales can confirm a formal quote.' If the need is unclear, say "
          "which assumption you made rather than asking.")


def ask(messages, focus=None):
    """messages: the conversation so far, [{role: user|assistant, content}].
    focus: "prices" when asked from the PriceBook page.
    Returns {answer, steps: [{tool, args, note}]}."""
    if not spark.available():
        raise spark.SparkError("Spark isn't connected yet")
    sysmsg = SYSTEM % time.strftime("%Y-%m-%d")
    if focus == "prices":
        sysmsg += ("\n\nThe user is on the PriceBook page: questions are most likely about Splashtop plans and "
                   "prices -- use plan_guide and quote.")
    convo = [{"role": "system", "content": sysmsg}]
    for m in messages[-10:]:
        if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str):
            convo.append({"role": m["role"], "content": m["content"][:4000]})
    steps = []
    for _ in range(MAX_STEPS):
        msg = spark.chat_raw(convo, tools=_tool_specs())
        calls = msg.get("tool_calls") or []
        if not calls:
            return {"answer": spark.clean(msg.get("content") or ""), "steps": steps}
        convo.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
        for c in calls:
            fn = (c.get("function") or {})
            name = fn.get("name")
            try:
                args = json.loads(fn.get("arguments") or "{}") if isinstance(fn.get("arguments"), str) else (fn.get("arguments") or {})
            except ValueError:
                args = {}
            if name in TOOLS:
                try:
                    result = TOOLS[name][0](**{k: v for k, v in args.items() if k in TOOLS[name][2]})
                except Exception as e:                    # a bad argument: tell the model, don't crash
                    result = {"error": "lookup failed (%s)" % type(e).__name__}
            else:
                result = {"error": "no such lookup"}
            steps.append({"tool": name, "args": args})
            convo.append({"role": "tool", "tool_call_id": c.get("id") or name, "content": json.dumps(result, default=str)[:12000]})
    # out of steps: ask for an answer with what it has
    msg = spark.chat_raw(convo + [{"role": "user", "content": "Answer now with what you found."}])
    return {"answer": spark.clean(msg.get("content") or ""), "steps": steps}
