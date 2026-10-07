"""Holiday themes: a light seasonal touch on every page, for everyone.

Settings > Look > Theme. "Automatic" follows the calendar below; an admin can
also pick one theme to keep, or turn them off. A theme only tints the top bar
and the menu, adds a thin festive stripe and a greeting, and (if on) a few
decorations drifting behind the boxes -- the text and the data never change
colour, so everything stays as readable as ever.
"""
import datetime, json

import store

KEY = "theme"
# key, label, greeting, emoji -- the CSS in app.css ([data-theme=...]) holds the colours
THEMES = [
    ("new_year", "New Year", "Happy New Year", "🎉"),
    ("lunar_new_year", "Lunar New Year", "Happy Lunar New Year", "🏮"),
    ("valentines", "Valentine's Day", "Happy Valentine's Day", "💝"),
    ("st_patricks", "St. Patrick's Day", "Happy St. Patrick's Day", "☘️"),
    ("sakura", "Cherry blossoms", "Hanami season", "🌸"),
    ("easter", "Easter", "Happy Easter", "🐣"),
    ("july_4", "Independence Day", "Happy 4th of July", "🎆"),
    ("mid_autumn", "Mid-Autumn Festival", "Happy Mid-Autumn Festival", "🥮"),
    ("halloween", "Halloween", "Happy Halloween", "🎃"),
    ("diwali", "Diwali", "Happy Diwali", "🪔"),
    ("thanksgiving", "Thanksgiving", "Happy Thanksgiving", "🦃"),
    ("christmas", "Christmas", "Happy Holidays", "🎄"),
]
INFO = {k: {"key": k, "label": l, "greet": g, "emoji": e} for k, l, g, e in THEMES}

# Moving dates (lunar calendars), a few years ahead
LUNAR_NEW_YEAR = {2026: (2, 17), 2027: (2, 6), 2028: (1, 26), 2029: (2, 13), 2030: (2, 3), 2031: (1, 23)}
MID_AUTUMN = {2026: (9, 25), 2027: (9, 15), 2028: (10, 3), 2029: (9, 22), 2030: (9, 12), 2031: (10, 1)}
DIWALI = {2026: (11, 8), 2027: (10, 29), 2028: (10, 17), 2029: (11, 5), 2030: (10, 26), 2031: (11, 14)}


def _easter(y):
    a, b, c = y % 19, y // 100, y % 100                 # the Gregorian computus
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    n = h + l - 7 * m + 114
    return datetime.date(y, n // 31, n % 31 + 1)


def _windows(y):
    """(key, first day, last day) for year y; the shorter, one-off days come
    first, so they win where two overlap (Diwali inside Halloween week)."""
    D = datetime.date
    out = []

    def around(day, before, after):
        return day - datetime.timedelta(days=before), day + datetime.timedelta(days=after)
    if y in LUNAR_NEW_YEAR:
        out.append(("lunar_new_year",) + around(D(y, *LUNAR_NEW_YEAR[y]), 2, 5))
    if y in MID_AUTUMN:
        out.append(("mid_autumn",) + around(D(y, *MID_AUTUMN[y]), 2, 1))
    if y in DIWALI:
        out.append(("diwali",) + around(D(y, *DIWALI[y]), 2, 1))
    nov1 = D(y, 11, 1)
    tg = nov1 + datetime.timedelta(days=(3 - nov1.weekday()) % 7 + 21)          # 4th Thursday of November
    out += [("valentines", D(y, 2, 12), D(y, 2, 14)), ("st_patricks", D(y, 3, 15), D(y, 3, 17)),
            ("easter",) + around(_easter(y), 3, 1), ("july_4", D(y, 7, 2), D(y, 7, 4)),
            ("thanksgiving",) + around(tg, 3, 1), ("halloween", D(y, 10, 24), D(y, 10, 31)),
            ("sakura", D(y, 3, 25), D(y, 4, 10)), ("christmas", D(y, 12, 15), D(y, 12, 26)),
            ("new_year", D(y, 12, 30), D(y, 12, 31)), ("new_year", D(y, 1, 1), D(y, 1, 3))]
    return out


def on_date(day):
    for k, a, b in _windows(day.year):
        if a <= day <= b:
            return k
    return None


def upcoming(day, n=4):
    """The next themes on the calendar: [{key, label, emoji, from, to}]."""
    seen, out = set(), []
    for k, a, b in sorted(_windows(day.year) + _windows(day.year + 1), key=lambda w: w[1]):
        if b >= day and k not in seen:
            seen.add(k)
            out.append(dict(INFO[k], **{"from": a.isoformat(), "to": b.isoformat()}))
    return out[:n]


def get():
    try:
        s = json.loads(store.get_setting(KEY, "") or "{}")
    except ValueError:
        s = {}
    choice = s.get("choice") if s.get("choice") in INFO or s.get("choice") == "off" else "auto"
    return {"choice": choice, "fx": s.get("fx", True) is not False}


def current(today=None):
    """What every page shows now; also the choices for Settings."""
    today = today or datetime.date.today()
    s = get()
    key = on_date(today) if s["choice"] == "auto" else (None if s["choice"] == "off" else s["choice"])
    return {"choice": s["choice"], "fx": s["fx"], "active": INFO.get(key),
            "themes": [INFO[k] for k, _, _, _ in THEMES], "upcoming": upcoming(today)}


def save(data, by=None):
    s = get()
    if "choice" in data:
        c = str(data.get("choice") or "")
        if c not in INFO and c not in ("auto", "off"):
            raise ValueError("unknown theme")
        s["choice"] = c
    if "fx" in data:
        s["fx"] = bool(data.get("fx"))
    store.set_setting(KEY, json.dumps(s), by)
    return current()
