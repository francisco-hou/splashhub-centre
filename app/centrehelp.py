"""SplashHub Centre's own user guide, for the AI page: "what does Needs review
mean?", "how do I add an internal note?", "what does the AI review switch do?",
"how does the sidebar get its review?".

Keep it in step with the app: when a page, a rule or a setting changes, change
its section here too. The AI answers ONLY from this text for questions about
how SplashHub Centre works.
"""

GUIDE = {
    "overview": """SplashHub Centre is the Splashtop support team's web app on Spluki, next to SplashHub (the Zendesk
sidebar app). Pages in the left menu: SOS Scans, SSO Requests, PO Requests, Customers, PriceBook, Knowledge Base, AI -- and, for an admin, Logs and Settings
(under an "Admin" heading). Top right: "Splashtop Support" with the role under it -- Member for everybody, Admin once the
admin password is entered (its menu: Admin login / Log out; SSO sign-in with real names comes later). The left menu
collapses to icons with the button next to the logo. SplashHub Centre only READS Zendesk, with one exception: adding an
internal note (see "internal notes"). It is reachable only inside the company network.""",

    "sos scans": """SOS Scans: Custom SOS package requests -- Zendesk tickets "New SOS package created by ..." -- reviewed
for brand misuse. A Zendesk trigger sends each new one to SplashHub Centre. Two views: Dashboard and View Scans.
Dashboard: last 24 h and last 7 days (vs. usual), Needs review open, High risk open, share of generic e-mails (7 days);
requests per day for 21 days by verdict with the usual for that weekday; Needs attention (flagged or not reviewed,
ticket still open, oldest first); Spike alert (last 24 h / 7 days vs. usual, and Spark's note on what the burst has in
common); Who's asking (creator domains, new vs. returning teams); Package mix (trial / paid); Lookalike names (Spark:
package names imitating a known brand); AI spend for 7 days. Spark's notes fill in a few seconds after the page.
View Scans: the list, with filters by verdict and search; the Ticket status column is the Zendesk ticket's status
(closed tickets are never read again; the refresh button reads the open ones now, and it checks every minute).
Click a request for its pop-up: package details (created, creator, ticket link, type -- "trial" in red --
subscription, technicians), what end users see (caption, instruction text...), the images (shown straight from
Zendesk, small in one row, click to enlarge -- sign in to Zendesk in the same browser if they don't load), Translate to
English, buttons View team on ACP / Manage SOS PKG on ACP / Download package, the AI review card, Add as internal note,
and "Scan in SplashHub" (who pressed Scan in the sidebar, and when).""",

    "verdicts": """Verdicts: Verified (green) = no issue found; Needs review (orange) = a person should look; High risk
(red) = a concrete reason to suspect brand misuse. Team rules on top of the AI's own call:
- A generic / free e-mail (gmail, outlook, qq.com ...) is never Verified -- at least Needs review: not accepted unless
  the customer gives a reason (support asks them for one).
- Branding that doesn't match the creator's e-mail domain (e.g. the images say "Vaultorio", the e-mail is
  @datamaas.com) is at least Needs review; the card says which image shows which brand. Platform names from the
  download links (Windows, Mac, Android, iOS, Linux, Chrome OS) and Splashtop itself never count.
- A Splashtop name/logo/attribution beyond "Powered by Splashtop" (e.g. "SOS by Splashtop") is High risk. A small
  "Powered by Splashtop" is fine; Splashtop's own default title bar left in place is normal partial customisation.
- Package details (name, caption, instruction text) that read like a scam pretext ("Fraud Investigation", "IRS",
  "Account suspended") are flagged too.
Reviews made before a rule existed are re-checked when the app starts.""",

    "ai review": """The AI review (Claude, the same prompt and format as SplashHub's sidebar scan) reads the package's
images and details. Settings > Reviews & notes > AI review: when ON, new requests are reviewed as they arrive; when
OFF they are only listed. Any request can be reviewed by hand with Run AI review / Re-review in its pop-up (no
confirmation). Images are never stored: they show from Zendesk, and are downloaded in memory only for the review. Each
review's cost shows on the card and on Logs. One ticket gets one AI review: SplashHub's sidebar shows the review
SplashHub Centre made instead of running its own.""",

    "internal notes": """Internal notes: the ONE thing SplashHub Centre writes to Zendesk. "Add as internal note" in a
request's pop-up posts the review to that ticket as an internal note (agents only; the customer isn't notified).
Settings > Reviews & notes > Auto add internal note does it after every AI review. The note: SplashHub AI Review,
Status (Verified / Needs review / High risk, with confidence), Reason, Review, Image details, Package details, Quick
links (Manage SOS PKG on ACP, View team on ACP, Download package), then the package and creator.""",

    "sidebar": """SplashHub's sidebar (in Zendesk) and SplashHub Centre: pressing Scan on an SOS package ticket shows
SplashHub Centre's review in the sidebar's usual format ("Review from SplashHub Centre"), so the AI runs once per ticket.
Not reviewed yet: SplashHub Centre reviews it then ("SplashHub Centre is reviewing..."). "Review again" runs a fresh one.
The sidebar calls from the agent's browser, so it needs the company network (VPN); otherwise, after a few seconds, the
sidebar reviews the ticket itself as before. Every press is recorded: in the request's pop-up ("Scan in SplashHub") and
on Logs under the agent's name -- "brand scan (sidebar)" when it ran a review, "brand scan (from Centre)" at $0 when it
showed an existing one. SplashHub's Settings > AI Provider shows SOS scan as "N/A - SplashHub Centre". SplashHub also
sends a copy of every run it logs to SplashHub Centre (Logs).""",

    "sso requests": """SSO Requests: Zendesk tickets "Here comes a new request to validate SSO method". SplashHub Centre
reads the domain and the TXT record the customer must add, and Check DNS looks the TXT record up (Check all waiting does
every waiting one). Statuses: Needs details, Not checked, Waiting, Not found yet, Verified, Check failed. Add a ticket by
number; Import past SSO requests brings in old ones. A result can be added to the ticket as an internal note. Checks
are by hand for now.""",

    "pricebook": """PriceBook: Splashtop list prices per market (USA, Canada, EU, UK, Brazil, Mexico, Japan, Taiwan,
China, Switzerland, Denmark, Sweden, Norway) for Remote Access (Solo, Pro, Performance), Remote Support (SOS+10,
SOS+300), Autonomous Endpoint Management (tiers) and Antivirus, read from splashtop.com -- the same PriceBook as
SplashHub's. It has a calculator and an AI side panel for plans and quotes. Admins set where the prices come from in
Settings > Price feed (scan for the current feed, or paste a link).""",

    "ai page": """The AI page: questions answered by Spark (Splashtop's own AI, free) from SplashHub Centre's data only:
support cases since 2026 (counts, trends, common problems, how they were fixed, similar cases, one case in full), SOS
and SSO requests, plans and prices (with quotes -- 4 or more licences can get a volume price), the run log, and how
SplashHub Centre works. "Draft a reply for #123" reads that ticket fresh from Zendesk, looks at how similar cases were
fixed, and writes a reply to the customer; Copy draft copies just the reply. Each answer shows what it looked up and
how long it took. It never answers questions about individual support agents. Nothing asked there changes anything or
reaches Zendesk.""",

    "zendesk tickets": """Zendesk Tickets (the AI's support-ticket data, once called Cases): every Zendesk ticket created
since 1 January 2026 (not the SOS package or SSO validation tickets), with subject, tags, status, requester,
organization, a country guess, the first message and the whole conversation (Customer / Support turns; agents' names
removed; Help Center article links kept as article numbers). Settings > Database > Zendesk Tickets (admin) downloads
them: ticket details first (fast), then each conversation (a few hours for a year); an hourly update keeps them current.
A ticket not downloaded yet is read live from Zendesk when the AI needs it.""",

    "po requests": """PO Requests (left menu): every Zendesk ticket with a "Provision Details" order -- purchase /
provisioning orders -- from all years. Each is read the way SplashHub's PO tool reads it: SPID, company, order type,
expected provision date, region (US, EMEA, JP, On-Prem), and the products with their quantities and start / end dates.
Top: open orders, due in the next 7 days, overdue (expected date passed, ticket still open), the last 30 days. Filter by
status (open / solved / closed), region, upcoming or overdue, and year; search an SPID, company, product or ticket
number. Click one for the whole order. Settings > Database > PO Requests (admin) imports them all once, then new and
changed ones come in every hour. The Customers page shows a customer's PO requests too.""",

    "customers": """Customers (left menu): everything SplashHub Centre has about one customer, on one page. Search an
e-mail domain (datamaas.com), an e-mail address, or a company name. A customer is a domain -- or, for a free e-mail
provider (gmail.com, outlook.com...), one address. The page shows: the organizations and country seen, first and last
contact, quick links (ACP from their SOS requests, Zendesk search for the domain); 2026 tickets (how many, how many still
open, per month, top tags and topics, the latest ones); their Custom SOS packages with verdicts; their SSO requests;
and the people who wrote in. With no search, it lists the most active customers of the last 30 days. Splashtop's own
domain is not a customer. Nothing new is read from Zendesk: it shows what is already downloaded (Zendesk Tickets in
Settings > Database).""",

    "knowledge base": """Knowledge Base (left menu): Splashtop's Zendesk Help Center articles, in every language. Search by
words, a title or an article number; filter by language, category, and Promoted / Outdated translation / Agents only /
Drafts; sort by most linked in tickets, most helpful votes, most "not helpful" votes, recently or least recently
updated. Top: articles, updated in the last 30 days, articles linked in 2026 tickets, outdated translations. Click an
article for its stats -- helpful % (yes / no votes), how many 2026 tickets link it (by month, and the latest tickets),
updated and created dates, its languages (source, outdated ones marked), labels -- and its text, with Open in the Help
Center. Zendesk doesn't give page views. Settings > Database > Zendesk Knowledge Base (admin) downloads the articles; it
syncs again every 6 hours. The AI page searches it too and links articles in reply drafts.""",

    "logs": """Logs (admin): every SplashHub run across the team -- who ran it, when, which tool, model, tokens and
estimated cost -- from the SplashHub sidebar and from SplashHub Centre (brand scans, AI page questions at $0). Filters:
period (7 / 30 / 90 days, all time), agent, model, tool, search; charts of runs per day and by tool; 25 runs a page;
Export CSV.""",

    "settings": """Settings (admin; team-wide):
- Reviews & notes: AI review (review new SOS requests on arrival), Auto add internal note.
- Translation: Translate with Claude (best, a cent or two) or Spark (free); a translation is made once and kept.
- Import: Past requests -- import every past SOS package ticket (no AI review); it carries on after a restart.
- Database > Zendesk Tickets: download 2026's tickets for the AI, and their progress.
- Database > Zendesk Knowledge Base: download / sync the Help Center articles (every 6 hours once downloaded).
- Spark: the model, Test speed, and "Let the model think first" (slower; off by default).
- Price feed: where the PriceBook reads its prices.""",

    "admin": """Admin: Logs and Settings need the admin password (ADMIN_PASSWORD, set on Spluki). Log in from the top
right menu > Admin login; Logs and Settings then appear in the left menu under AI. Log out from the same menu. Everything
else is open to the team.""",
}


def guide(topic=None):
    """The whole guide (it is short), the sections that match the topic first."""
    words = [w for w in str(topic or "").lower().replace("-", " ").split() if len(w) > 3]
    first = [k for k in GUIDE if any(w in k for w in words)]
    return {"sections": {k: GUIDE[k] for k in first + [k for k in GUIDE if k not in first]}}
