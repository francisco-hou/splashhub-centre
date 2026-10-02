"""Sample runs for the local preview -- never used on Spluki.

Shaped like what SplashHub's logSharedRun() records today: the same kinds,
models and topic styles, priced with the same per-model table the sidebar uses
(sidebar.js MODEL_PRICING_PER_MTOK), so totals look like the real thing.
Agent names are invented. Deterministic (seeded), so a reload shows the same log.
"""
import random, time

# USD per 1M tokens -- copied from SplashHub sidebar.js so sample costs match.
PRICING = {
    "claude-opus-4-8": (5.00, 25.00),
    "claude-sonnet-5": (3.00, 15.00),
    "gpt-5.6-terra": (2.00, 12.00),
}

AGENTS = ["Mia Chen", "Lucas Ortega", "Hana Sato", "Daniel Weber", "Priya Nair",
          "Tom Okafor", "Elena Rossi", "Kevin Lin"]
# Not everyone uses everything equally: a weight per agent.
AGENT_W = [14, 11, 9, 9, 8, 6, 5, 3]

SUBJECTS = ["black screen after update", "cannot connect to streamer", "audio not working in session",
            "SSO login loop", "license not applied", "file transfer stuck at 0%", "slow session on Mac",
            "deployment package fails", "two-factor reset", "remote print missing", "multi-monitor switch",
            "session drops every 10 minutes", "invoice copy request", "seat count wrong after renewal"]
LANGS = ["Japanese", "German", "French", "Spanish", "Portuguese (Brazil)", "Chinese (Traditional)", "Italian", "Korean"]
MOCKUPS = ["SRS › Settings › Sound", "SRC › Options › Video", "SOS › Advanced › Proxy", "SRS › Security › Request permission",
           "SRC › Computer list › Wake", "SRS › Status › Log ID"]


def _tid(r):
    return "#" + str(r.randint(44000, 49999))


def _usage(r, model, lo_in, hi_in, lo_out, hi_out):
    i, o = r.randint(lo_in, hi_in), r.randint(lo_out, hi_out)
    pi, po = PRICING.get(model, (0, 0))
    return i, o, round(i / 1e6 * pi + o / 1e6 * po, 6)


# kind -> (weight, builder). Builders return (model, topic, tickets, in, out, cost).
def _jira(r):
    m = "claude-opus-4-8"; i, o, c = _usage(r, m, 5000, 15000, 700, 1800)
    return m, "%s %s" % (_tid(r), r.choice(SUBJECTS)), 1, i, o, c

def _feature(r):
    m = "claude-opus-4-8"; i, o, c = _usage(r, m, 4000, 11000, 500, 1200)
    return m, "%s Request: %s" % (_tid(r), r.choice(["dark mode in Business app", "bulk export of logs", "Linux streamer ARM", "longer session timeout"])), 1, i, o, c

def _scan(r):
    m = "claude-opus-4-8"; i, o, c = _usage(r, m, 3000, 9000, 300, 800)
    return m, "%s custom SOS package" % _tid(r), 1, i, o, c

def _translate(r):
    m = "claude-sonnet-5"
    if r.random() < 0.35:
        i, o, c = _usage(r, m, 600, 2500, 20, 60)
        return m, "detect language", 1, i, o, c
    i, o, c = _usage(r, m, 1500, 6000, 400, 2200)
    return m, r.choice(LANGS), 1, i, o, c

def _spell(r):
    m = "claude-sonnet-5"; i, o, c = _usage(r, m, 900, 3500, 200, 1400)
    n = r.choice([0, 1, 1, 2, 2, 3, 4])
    return m, "%s · %s" % (_tid(r), "no mistakes" if n == 0 else "%d fix%s" % (n, "" if n == 1 else "es")), 1, i, o, c

def _tone(r):
    m = "claude-sonnet-5"; i, o, c = _usage(r, m, 1000, 4000, 300, 1600)
    return m, "%s · rewritten" % _tid(r), 1, i, o, c

def _po(r):
    return "—", "%s Order 000%d %s" % (_tid(r), r.randint(24000, 25999), r.choice(["renewal", "new business", "upsell"])), 1, 0, 0, 0.0

def _sso(r):
    return "—", "%s %s" % (_tid(r), r.choice(["domain challenge sent", "verified, reply inserted"])), 1, 0, 0, 0.0

def _wrap(r):
    m = "claude-opus-4-8"; i, o, c = _usage(r, m, 4000, 16000, 250, 600)
    return m, "%s wrap-up" % _tid(r), 1, i, o, c

def _mockup(r):
    return "—", "%s — %s (sidebar)" % (r.choice(MOCKUPS), r.choice(["copied", "downloaded"])), 1, 0, 0, 0.0

def _transcribe(r):
    mins = r.randint(2, 14)
    return "gpt-4o-transcribe", "%s call recording %d:%02d" % (_tid(r), mins, r.randint(0, 59)), 1, r.randint(1500, 9000), r.randint(400, 3000), round(mins * 0.006 + r.random() * 0.01, 6)

def _transfer(r):
    m = "claude-opus-4-8"; i, o, c = _usage(r, m, 3000, 9000, 250, 700)
    return m, "%s → %s" % (_tid(r), r.choice(["Sales", "CS", "Billing"])), 1, i, o, c

def _overview(r):
    m = "claude-opus-4-8"; i, o, c = _usage(r, m, 60000, 160000, 3000, 7000)
    return m, r.choice(["Last 7 days", "Last 14 days", "Last 30 days"]), r.randint(180, 900), i, o, c

def _deep(r):
    m = "claude-opus-4-8"; i, o, c = _usage(r, m, 30000, 90000, 2000, 5000)
    return m, "Deep dive: " + r.choice(SUBJECTS), r.randint(15, 120), i, o, c


KINDS = [
    ("jira draft", 9, _jira), ("feature request", 3, _feature), ("brand scan", 2, _scan),
    ("translate", 16, _translate), ("spellcheck", 9, _spell), ("customer-ready tone", 6, _tone),
    ("po reply", 8, _po), ("sso challenge", 2, _sso), ("sso reply", 2, _sso), ("wrap up", 10, _wrap),
    ("mockup shot", 5, _mockup), ("transcribe", 2, _transcribe), ("transfer", 2, _transfer),
    ("overview", 1, _overview), ("deep dive", 1, _deep),
]


def generate(days=90, seed=7):
    """~90 days of runs ending now: busier on weekdays, office-hours heavy."""
    r = random.Random(seed)
    now_ms = int(time.time() * 1000)
    day_ms = 86400000
    today0 = now_ms - (now_ms % day_ms)
    kinds = [k for k in KINDS]
    kw = [k[1] for k in KINDS]
    out = []
    for back in range(days, -1, -1):
        d0 = today0 - back * day_ms
        weekday = time.gmtime(d0 / 1000).tm_wday
        base = r.randint(45, 85) if weekday < 5 else r.randint(4, 14)
        # a slow ramp: adoption grew over the quarter
        n = int(base * (0.65 + 0.35 * (days - back) / days))
        for _ in range(n):
            kind, _w, build = r.choices(kinds, weights=kw)[0]
            model, topic, tickets, i, o, c = build(r)
            ts = d0 + int(r.triangular(0, day_ms, day_ms * 0.4))
            if ts > now_ms:
                continue
            out.append({"event_id": "sample-%d-%d" % (ts, r.randint(0, 1 << 30)), "when": ts,
                        "agent": r.choices(AGENTS, weights=AGENT_W)[0], "kind": kind, "model": model,
                        "topic": topic, "tickets": tickets, "input_tokens": i, "output_tokens": o,
                        "cost": c, "source": "sample"})
    return out
