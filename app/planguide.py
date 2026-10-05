"""Plan guide and quote calculator for Ask AI's "which plan / how much" questions.

Everything comes from splashtop.com, read through pricebook.fetch():
  - prices: the price feed (the Price Book's saved link), including the volume
    rows the Price Book page doesn't show -- Pro and Performance are cheaper per
    user from 4 and from 10 licences;
  - the rules: the FAQ on the pricing pages (who a plan is for, how many
    computers, attended vs unattended);
  - plus the team's own notes from Settings (pb:notes), for what the FAQ
    doesn't say.

quote() does the arithmetic in code -- a small model should never add up a
price itself. Prices are list prices; quotes and special terms come from Sales.
"""
import json, re, time

import pricebook
import store

# Market -> the feed's column (the same mapping as pricebook.js's MARKETS).
MARKET_COLS = {"USA": "USD_GLOBAL", "Canada": "Canada", "EU": "EUR_ExcludingFrance", "UK": "GBP", "Brazil": "BRL",
               "Mexico": "MXN", "Japan": "JPY", "Taiwan": "TWD", "China": "CNY", "Switzerland": "CHF",
               "Denmark": "DKK", "Sweden": "SEK", "Norway": "NOK"}

# tiers: (from quantity, feed row, multiplier to a per-unit YEARLY price)
PLANS = {
    "solo": {"name": "Splashtop Remote Access Solo", "unit": "user (max 1)", "max": 1,
             "tiers": [(1, "sbasoloyearly", 1)],
             "for": "One person reaching their OWN computers: 1 user, up to 2 computers. Unattended access. Not for supporting other people's computers."},
    "pro": {"name": "Splashtop Remote Access Pro", "unit": "user",
            "tiers": [(1, "sbaproyearly", 1), (4, "sbapro4to9monthly", 12), (10, "sbaprovlmonthly", 12)],
            "for": "End users reaching their own / company computers. Licensed per named user; each licence covers up to 10 computers, pooled across the account (10 users share 100 computers). Unattended access. Cheaper per user from 4 and from 10 users."},
    "performance": {"name": "Splashtop Remote Access Performance", "unit": "user",
                    "tiers": [(1, "sbaperfyearly", 1), (4, "sbaperf4to9monthly", 12), (10, "sbaperf10+monthly", 12)],
                    "for": "Like Pro (per named user, up to 10 computers per licence) with higher performance features. Cheaper per user from 4 and from 10 users."},
    "sos10": {"name": "Splashtop SOS+10", "unit": "concurrent technician",
              "tiers": [(1, "sos10yearly", 1)],
              "for": "IT / support teams helping OTHER people: per concurrent technician (up to 10 users per licence, one at a time). Attended on-demand support with a 9-digit session code, plus unattended access to up to 10 computers."},
    "sos300": {"name": "Splashtop SOS+300", "unit": "concurrent technician",
               "tiers": [(1, "sosunltdyearly", 1)],
               "for": "Like SOS+10, with unattended access to up to 300 computers/endpoints per licence. Per concurrent technician."},
    "aem": {"name": "Splashtop Autonomous Endpoint Management (billed annually)", "unit": "endpoint",
            "bands": [(100, "aemannualbase", "flat"), (250, "aemannualtier1annual", "each"), (500, "aemannualtier2annual", "each"),
                      (1000, "aemannualtier3annual", "each"), (10 ** 9, "aemannualtier4annual", "each")],
            "for": "Patching, monitoring and automation per endpoint. Up to 100 endpoints is one flat fee; above that the band the count falls in sets the per-endpoint rate."},
    "antivirus": {"name": "Splashtop Antivirus (Bitdefender)", "unit": "endpoint", "min": 5,
                  "bands": [(100, "bitdefenderless100", "month"), (3000, "bitdefendermore101", "month")],
                  "for": "Endpoint antivirus, per endpoint per month (5 minimum); the band the count falls in sets the rate."},
}

_FEED = {"at": 0, "rows": None}


def _rows():
    """The feed's rows by name, read through the Price Book's saved link (5-min cache in pricebook.fetch)."""
    if _FEED["rows"] and time.time() - _FEED["at"] < 300:
        return _FEED["rows"]
    try:
        cfg = json.loads(store.get_setting("pb:pricebookcfg", "") or "null") or {}
    except ValueError:
        cfg = {}
    url = cfg.get("url") or "https://www.splashtop.com/page-data/sq/d/4007116652.json"
    d = json.loads(pricebook.fetch(url))
    rows = {n.get("name"): n for n in (((d.get("data") or {}).get("allPricesCsv") or {}).get("nodes") or []) if n.get("name")}
    if not rows:
        raise pricebook.PriceError("the saved price feed has no price rows -- scan for the current feed in Settings")
    _FEED.update(at=time.time(), rows=rows)
    return rows


MONEY = re.compile(r"(-?[\d.,]+)")


def _parse(cell):
    """'$1,197.00' / '66.00 €' / 'JPY 11,880' -> (number, prefix, suffix, decimals)."""
    m = MONEY.search(cell or "")
    if not m:
        return None
    raw = m.group(1)
    dec = len(raw.split(".")[1]) if "." in raw else 0
    return float(raw.replace(",", "")), cell[:m.start()], cell[m.end():], dec


def _fmt(n, like):
    _, pre, suf, dec = like
    return "%s%s%s" % (pre, "{:,.{}f}".format(n, max(dec, 2 if n % 1 else dec)), suf)


def _market(market):
    m = (market or "USA").strip().lower()
    for name in MARKET_COLS:
        if m in (name.lower(), {"usd": "usa", "us": "usa", "united states": "usa", "gbp": "uk", "eur": "eu", "europe": "eu",
                                "jpy": "japan", "jp": "japan"}.get(m, "")):
            return name
    for name in MARKET_COLS:
        if name.lower().startswith(m[:3]):
            return name
    return "USA"


def _cell(rows, row, market):
    return _parse((rows.get(row) or {}).get(MARKET_COLS[market]))


# ---- the FAQ ------------------------------------------------------------------------------

FAQ_PAGES = ["https://www.splashtop.com/page-data/pricing/page-data.json",
             "https://www.splashtop.com/page-data/autonomous-endpoint-management/pricing/page-data.json"]


def _rich(raw):
    out = []

    def walk(o):
        if isinstance(o, dict):
            if isinstance(o.get("value"), str):
                out.append(o["value"])
            for v in o.values():
                if isinstance(v, (dict, list)):
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    try:
        walk(json.loads(raw))
    except ValueError:
        pass
    return re.sub(r"\s+", " ", " ".join(out)).strip()


def faq():
    """[{q, a}] from splashtop.com's pricing pages; read at most once a day."""
    try:
        got = json.loads(store.get_setting("pb:faq", "") or "null")
    except ValueError:
        got = None
    if got and time.time() * 1000 - got.get("ms", 0) < 86400000:
        return got["items"]
    items = []

    def walk(o):
        if isinstance(o, dict):
            h, t = o.get("headline"), o.get("text")
            if isinstance(h, str) and h.strip().endswith("?") and isinstance(t, dict) and isinstance(t.get("raw"), str):
                a = _rich(t["raw"])
                if a:
                    items.append({"q": h.strip(), "a": a[:900]})
            for v in o.values():
                if isinstance(v, (dict, list)):
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    for url in FAQ_PAGES:
        try:
            walk(json.loads(pricebook.fetch(url)).get("result"))
        except (pricebook.PriceError, ValueError):
            continue
    if items:
        store.set_setting("pb:faq", json.dumps({"ms": int(time.time() * 1000), "items": items}), "planguide")
    return items or (got or {}).get("items") or []


# ---- the lookups Ask AI uses ----------------------------------------------------------------

def guide(market="USA"):
    """Every plan: who it is for, its limits, and its yearly price per unit in
    this market -- volume steps included -- plus the FAQ and the team's notes."""
    market = _market(market)
    rows = _rows()
    plans = []
    for key, p in PLANS.items():
        item = {"plan": key, "name": p["name"], "per": p["unit"], "for": p["for"]}
        if "tiers" in p:
            steps = []
            for i, (q, row, mult) in enumerate(p["tiers"]):
                c = _cell(rows, row, market)
                if not c:
                    continue
                upto = p["tiers"][i + 1][0] - 1 if i + 1 < len(p["tiers"]) else None
                steps.append({"licences": "%d%s" % (q, ("-%d" % upto) if upto else "+") if p.get("max") != 1 else "1",
                              "per_year_each": _fmt(c[0] * mult, c)})
            item["price"] = steps
        else:
            bands, lo = [], p.get("min", 1)
            for upto, row, kind in p["bands"]:
                c = _cell(rows, row, market)
                if c:
                    bands.append({"endpoints": "%d-%s" % (lo, upto if upto < 10 ** 8 else "more"),
                                  "price": _fmt(c[0], c) + {"flat": " flat per year", "each": " per endpoint per year",
                                                             "month": " per endpoint per month"}[kind]})
                lo = upto + 1
            item["price"] = bands
        plans.append(item)
    return {"market": market, "plans": plans, "faq": faq()[:20],
            "team_notes": store.get_setting("pb:notes", "") or "",
            "note": "List prices from splashtop.com. Volume steps apply to Pro and Performance (4+ and 10+ users). Quotes, discounts beyond these and special terms come from Sales."}


def quote(items, market="USA"):
    """Line items and a yearly total for [{plan, quantity}] -- the arithmetic
    done here, never by the model."""
    market = _market(market)
    rows = _rows()
    lines, total, like = [], 0.0, None
    for it in (items or [])[:8]:
        key = str((it or {}).get("plan") or "").lower().replace(" ", "").replace("+", "").replace("splashtop", "")
        key = {"sos10": "sos10", "sos300": "sos300", "sosunlimited": "sos300", "remoteaccesspro": "pro", "remoteaccessperformance": "performance",
               "perf": "performance", "bitdefender": "antivirus", "av": "antivirus"}.get(key, key)
        p = PLANS.get(key)
        try:
            qty = int(float((it or {}).get("quantity") or 0))
        except (TypeError, ValueError):
            qty = 0
        if not p or qty <= 0:
            lines.append({"plan": (it or {}).get("plan"), "error": "unknown plan or quantity"})
            continue
        if p.get("max") and qty > p["max"]:
            lines.append({"plan": p["name"], "error": "%s is for %d user only" % (p["name"], p["max"])})
            continue
        if "tiers" in p:
            q0, row, mult = [t for t in p["tiers"] if qty >= t[0]][-1]
            c = _cell(rows, row, market)
            if not c:
                lines.append({"plan": p["name"], "error": "no price in this market"}); continue
            each = c[0] * mult
            amt = each * qty
            step = "%d+ price" % q0 if q0 > 1 else "standard price"
            lines.append({"plan": p["name"], "quantity": qty, "per": p["unit"], "each_per_year": _fmt(each, c),
                          "price_step": step, "line_total_per_year": _fmt(amt, c)})
        else:
            n = max(qty, p.get("min", 1))
            band = next(b for b in p["bands"] if n <= b[0])
            c = _cell(rows, band[1], market)
            if not c:
                lines.append({"plan": p["name"], "error": "no price in this market"}); continue
            amt = c[0] if band[2] == "flat" else c[0] * n * (12 if band[2] == "month" else 1)
            how = {"flat": "flat fee up to 100 endpoints", "each": "%s per endpoint per year" % _fmt(c[0], c),
                   "month": "%s per endpoint per month x 12" % _fmt(c[0], c)}[band[2]]
            lines.append({"plan": p["name"], "quantity": n, "per": p["unit"], "rate": how, "line_total_per_year": _fmt(amt, c)})
        total += amt
        like = c
    return {"market": market, "lines": lines, "total_per_year": _fmt(total, like) if like else None,
            "note": "List prices, billed annually. Taxes not included. Confirm with Sales for a formal quote."}
