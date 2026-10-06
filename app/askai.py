"""Ask AI: questions about what SplashHub Centre holds, answered by Spark.

Spark is given a short list of READ-ONLY lookups (TOOLS) over SplashHub
Centre's own data -- SOS requests, SSO requests, the 2026 cases (cases.py),
plans and prices, and the run log -- and asks for what it needs (OpenAI-style
tool calls). The answer comes from those results only, with ticket numbers to
click. Nothing here writes anything.

The wall: nothing about a specific SUPPORT AGENT -- who handled what, how
someone performs, one agent's tickets or usage. A question with a Splashtop
address in it, or plainly about agents (_AGENT_Q), is refused before Spark sees
it (AGENT_WALL); no lookup returns anything per agent (the run log only by tool
and model; cases keep no assignee, mark replies "Support" and replace agents'
names); the system prompt tells Spark the rest -- and that customers,
companies and countries are NOT agents, since a small model over-refuses: a
refusal of a question the code let through is retried once (_REFUSAL); and a
Splashtop address that still reaches an answer is blanked (_blank).

Each step is returned with the answer, so the page can show what was looked
at -- the way to trust (or doubt) a small model's answer.
"""
import json, re, time

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
    by_model = store._read("SELECT model, count(*), coalesce(sum(cost),0) FROM runs WHERE ts_ms >= %s AND model IS NOT NULL "
                           "GROUP BY model ORDER BY count(*) DESC LIMIT 8", [since])
    return {"days": days, "runs": agg["runs"], "cost_usd": round(agg["cost"], 2), "agents": agg["agents"],
            "by_tool": [{"tool": t["label"], "runs": t["runs"], "cost_usd": round(t["cost"], 2)} for t in agg["by_tool"] if t["runs"]],
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
                     "last N days: totals, cost, and breakdowns by tool and model (never by agent).",
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


def _cases():
    import cases
    return cases


def case_overview(from_date=None, to_date=None):
    return _cases().overview(from_date, to_date)


def case_search(query=None, from_date=None, to_date=None, status=None, tag=None, requester=None, country=None, limit=10):
    return _cases().search(query, from_date, to_date, status, tag, requester, country, limit)


def case_themes(query=None, from_date=None, to_date=None, status=None, country=None):
    return _cases().themes(query, from_date, to_date, status, country)


def case_solutions(query=None, ticket_id=None, from_date=None, to_date=None):
    return _cases().solutions(query, ticket_id, from_date, to_date)


def case_similar(ticket_id, limit=8):
    return _cases().similar(ticket_id, limit)


def case_read(ticket_id, fresh=False):
    import zendesk
    c = _cases()
    got = None if fresh else c.read(ticket_id)
    if not got:
        try:
            got = c.read_live(ticket_id)          # the latest, straight from Zendesk (read only)
        except zendesk.ZendeskError as e:
            if "HTTP 404" in str(e):
                return {"error": "ticket #%s wasn't found in Zendesk" % ticket_id}
            return {"error": "couldn't read #%s from Zendesk: %s" % (ticket_id, e)}
    return got or {"error": "ticket #%s wasn't found" % ticket_id}


_DATES = {"from_date": {"type": "string", "description": "YYYY-MM-DD, optional"},
          "to_date": {"type": "string", "description": "YYYY-MM-DD inclusive, optional"}}
_QUERY = {"type": "string", "description": "2-5 short alternative phrasings, comma-separated, e.g. "
                                           "'2fa, two-factor, two step verification, authenticator'. A case matches when "
                                           "it has ALL the words of ONE phrase, so keep each phrase to 1-3 words."}
TOOLS["case_search"] = (case_search, "COUNT and FIND support cases (Zendesk tickets since 2026-01-01) about something: "
                        "how many match, per month, by country, region (Americas/EMEA/APAC), language and status, plus "
                        "the best matches with requester, organization and a snippet. Filters: dates, ticket status "
                        "(new/open/pending/hold/solved/closed, comma-separated), Zendesk tag, requester (e-mail, domain "
                        "or organization), country.",
                        dict(_DATES, query=_QUERY, status={"type": "string"}, tag={"type": "string"},
                             requester={"type": "string"}, country={"type": "string"}, limit={"type": "integer"}))
TOOLS["case_themes"] = (case_themes, "WHAT THE PROBLEMS ARE: a random sample of what customers wrote in the matching "
                        "cases (all cases if no query), to read and group into the real problems with their share. Use "
                        "for 'most common issues', 'trending problems', 'what goes wrong with Windows 7'.",
                        dict(_DATES, query=_QUERY, status={"type": "string"}, country={"type": "string"}))
TOOLS["case_solutions"] = (case_solutions, "HOW IT WAS FIXED: the last support replies and internal notes of the "
                           "best-matching solved/closed cases about a topic, or of one ticket. Use for 'how was it fixed', "
                           "'what's the solution', 'how do we usually answer this'.",
                           dict(_DATES, query=_QUERY, ticket_id={"type": "integer"}))
TOOLS["case_overview"] = (case_overview, "Totals for a period: cases per month, status, country, region, language, the "
                          "words most used, and the words rising most in the last 30 days. Single words, not problems: "
                          "follow up with case_themes.", dict(_DATES))
TOOLS["case_similar"] = (case_similar, "Cases most similar to one ticket, by ticket number.",
                         {"ticket_id": {"type": "integer"}, "limit": {"type": "integer"}})
TOOLS["case_read"] = (case_read, "One case in full by ticket number: subject, requester, organization, country, "
                      "tags, status, the first message and the whole conversation (Customer / Support turns). "
                      "fresh=true reads the latest straight from Zendesk -- ALWAYS use it to draft a reply.",
                      {"ticket_id": {"type": "integer"}, "fresh": {"type": "boolean"}})

# The wall, in code. Only about Splashtop's own support staff -- customers,
# companies and countries are fine. A Splashtop address in the question, or a
# question plainly about agents, never reaches Spark; Spark is told the rest.
_AGENT_EMAIL = re.compile(r"[\w.+'-]+@([\w-]+\.)*splashtop\.com\b", re.I)
_AGENT_Q = re.compile(r"\b(support agents?|which agents?|what agents?|each agent|every agent|per agent|by agent|"
                      r"top agents?|best agents?|worst agents?|fastest agents?|slowest agents?|"
                      r"agents?'?s? (performance|workload|stats|statistics|productivity|response times?)|assignees?|"
                      r"assigned to (whom|who)|who (handled|solved|answered|closed|replied to|responded to|worked on|took|"
                      r"was assigned)|(handled|solved|answered|closed) by (whom|who))\b", re.I)
AGENT_WALL = ("I can't answer questions about individual support agents. "
              "Ask about cases, customers, topics, products, plans or trends instead.")


_REFUSAL = re.compile(r"can.?t (answer|help with|discuss) (any )?questions about (specific|individual) (support )?agents", re.I)


def _about_agents(text):
    return bool(_AGENT_EMAIL.search(text or "") or _AGENT_Q.search(text or ""))


def _blank(text):
    return _AGENT_EMAIL.sub("[agent hidden]", text or "")


def _tool_specs():
    return [{"type": "function", "function": {"name": n, "description": d, "parameters": {"type": "object", "properties": p}}}
            for n, (_, d, p) in TOOLS.items()]


SYSTEM = ("You are the assistant inside SplashHub Centre, Splashtop support's internal tool. Answer questions about "
          "what SplashHub Centre holds: Zendesk support cases since 2026, Custom SOS package requests and their AI "
          "brand reviews, SSO method validation requests, Splashtop list prices (the Price Book), and the SplashHub "
          "run log. ALWAYS look things up with the tools before answering, and answer ONLY from their results: never "
          "invent numbers or tickets, and never say something can't be counted or found without trying a lookup "
          "first. Be brief: a sentence or two, then a short list. Write ticket numbers as #12345. Today is %s (UTC).\n\n"
          "CASES -- every ticket since 2026-01-01 with its subject, the customer's first message, the whole "
          "conversation (turns marked Customer / Support), the requester's e-mail and organization, and a country "
          "guess. Pick the lookup by the question:\n"
          "- how many / how often / per month / by country, region or language -> case_search. Give 2-5 short "
          "alternative phrasings in query, comma-separated. Report matching_cases and the breakdown asked for.\n"
          "- the most common or trending problems, overall or within a topic ('windows 7', '2fa') -> case_themes; read "
          "the sample and group it into 3-6 concrete problems customers had, each with a rough share and an example "
          "ticket. For 'trending' also call case_overview and use rising_last_30_days. A tag, a channel or a single "
          "word such as 'chat' is never a problem.\n"
          "- how was it fixed / the solution / how do we answer this -> case_solutions (query for a topic, ticket_id "
          "for one case); say what support did, and which fixes recur, citing tickets.\n"
          "- similar to #123 -> case_similar. One case in detail -> case_read.\n\n"
          "DRAFT A REPLY (\"draft a reply for #123\", \"how should I answer #123\", \"write a response\"): 1) case_read "
          "with fresh=true. 2) case_solutions with a short query for the customer's actual problem (case_similar too if "
          "useful) to see how support fixed it before. 3) Write the reply TO THE CUSTOMER, in the language they wrote "
          "in, answering their LATEST message: thank them, then clear numbered steps taken from the fixes you found; if "
          "something is missing to help (version, OS, logs, screenshots), ask for it. Friendly and short. Sign off as "
          "'Splashtop Support' -- never an agent's name. Never promise refunds, dates or fixes, and never invent "
          "settings, links or steps the cases don't show. Answer as: '**Draft reply**', the reply text, then '**Based "
          "on**' with one line naming the tickets you used. If the ticket is solved or closed, say so first.\n"
          "Countries are a guess (the e-mail's country domain, else the profile time zone): say so when you give them.\n\n"
          "FOLLOW-UPS: when the user pushes back or asks again in other words, your last answer missed. Use a "
          "DIFFERENT lookup (case_themes rather than case_overview, case_solutions for fixes, case_search for counts) "
          "and never repeat an earlier answer.\n\n"
          "SUPPORT AGENTS: SplashHub Centre never discusses individual support agents (Splashtop's own support "
          "staff): who handled, solved or answered which tickets, how someone performs, anyone's workload or "
          "activity. If asked that, say only: '%s' This rule is ONLY about Splashtop support staff. Questions about "
          "customers, requesters, companies, countries, regions, products, topics, counts and trends are NOT about "
          "agents: answer them. Never name a support agent.\n\n"
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


def ask(messages, focus=None, on_event=None):
    """messages: the conversation so far, [{role: user|assistant, content}].
    focus: "prices" when asked from the PriceBook page.
    on_event: told what is happening as it happens, for the page's progress line:
      {"phase": "think", "round": n} before each Spark call,
      {"phase": "step", "tool": name, "args": {...}} before each lookup.
    Returns {answer, steps: [{tool, args, note}]}."""
    tell = on_event or (lambda e: None)
    last = str((messages[-1] if messages else {}).get("content") or "")
    if _about_agents(last):
        return {"answer": AGENT_WALL, "steps": [], "refused": True}
    if not spark.available():
        raise spark.SparkError("Spark isn't connected yet")
    sysmsg = SYSTEM % (time.strftime("%Y-%m-%d"), AGENT_WALL)
    if focus == "prices":
        sysmsg += ("\n\nThe user is on the PriceBook page: questions are most likely about Splashtop plans and "
                   "prices -- use plan_guide and quote.")
    convo = [{"role": "system", "content": sysmsg}]
    for m in messages[-10:]:
        if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str):
            if m["role"] == "assistant" and _REFUSAL.search(m["content"]):
                continue                     # an earlier refusal only teaches a small model to refuse again
            convo.append({"role": m["role"], "content": m["content"][:4000]})
    steps, nudged = [], False
    for n in range(MAX_STEPS):
        tell({"phase": "think", "round": n})
        msg = spark.chat_raw(convo, tools=_tool_specs())
        calls = msg.get("tool_calls") or []
        if not calls:
            answer = spark.clean(msg.get("content") or "")
            if _REFUSAL.search(answer) and not nudged and n < MAX_STEPS - 1:
                # The code already let the question through: it isn't about agents. Once more, with that said.
                nudged = True
                convo.append({"role": "system", "content": "That question is not about support agents (it is about "
                              "cases, customers, countries, products or topics). Answer it, using the tools."})
                continue
            return {"answer": _blank(answer), "steps": steps}
        convo.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
        for c in calls:
            fn = (c.get("function") or {})
            name = fn.get("name")
            try:
                args = json.loads(fn.get("arguments") or "{}") if isinstance(fn.get("arguments"), str) else (fn.get("arguments") or {})
            except ValueError:
                args = {}
            tell({"phase": "step", "tool": name, "args": args})
            if name in TOOLS:
                try:
                    result = TOOLS[name][0](**{k: v for k, v in args.items() if k in TOOLS[name][2]})
                except Exception as e:                    # a bad argument: tell the model, don't crash
                    result = {"error": "lookup failed (%s)" % type(e).__name__}
            else:
                result = {"error": "no such lookup"}
            steps.append({"tool": name, "args": args})
            convo.append({"role": "tool", "tool_call_id": c.get("id") or name, "content": json.dumps(result, default=str)[:24000]})
    # out of steps: ask for an answer with what it has
    tell({"phase": "think", "round": MAX_STEPS})
    msg = spark.chat_raw(convo + [{"role": "user", "content": "Answer now with what you found."}])
    return {"answer": _blank(spark.clean(msg.get("content") or "")), "steps": steps}
