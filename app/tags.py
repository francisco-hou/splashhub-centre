"""Tags: how many tickets carry each Zendesk tag -- today, last 7 days, last 30
days, the change on the period before, and an 8-week heatmap -- for the Tags
page. The same sets as SplashHub's Tags page (Languages; Topics, with its
groups), plus "All tags": the most used ones, found by themselves.

Counted from the Zendesk Tickets data (cases.py: every 2026 ticket and its
tags, updated hourly) -- one pass, no Zendesk calls, no limit on how many tags.
A group ("2FA & recovery") counts a ticket once even when it has several of
its tags. SOS package and SSO validation tickets are not in that data.
"""
import time

import store

DAY = 86400000
# From SplashHub's tags.js (LANGS, TOPIC_GROUPS, the Topics items)
LANGUAGES = [{"label": "Japanese", "tag": "language_ja"}, {"label": "Korean", "tag": "language_ko"}, {"label": "Chinese (Simplified)", "tag": "language_zh-cn"}, {"label": "Chinese (Traditional)", "tag": "language_zh-tw"}, {"label": "English", "tag": "language_en"}, {"label": "French", "tag": "language_fr"}, {"label": "German", "tag": "language_de"}, {"label": "Spanish", "tag": "language_es"}, {"label": "Italian", "tag": "language_it"}, {"label": "Portuguese", "tag": "language_pt"}]
GROUPS = [{"label": "2FA & recovery", "tags": ["2fa", "2fa_reset", "security__2_step_authentication", "recovery", "need_recovery_codes"]}, {"label": "Account provisioning (all)", "tags": ["account_provisioning", "account_provisioning_jp"]}]
TOPICS = [{"label": "2FA", "tag": "2fa"}, {"label": "2FA reset", "tag": "2fa_reset"}, {"label": "2段階認証 (JP 2FA)", "tag": "2段階認証"}, {"label": "Access", "tag": "access"}, {"label": "Access Support Performance SOS 300", "tag": "splashtop_access_support___performace_sos_300"}, {"label": "Access Support Pro SOS 10", "tag": "splashtop_access_support__pro__sos_10"}, {"label": "Access Support Pro SOS 300", "tag": "splashtop_access_support__pro__sos_300"}, {"label": "Access Support Trial", "tag": "splashtop_access_support__trial"}, {"label": "Account", "tag": "account"}, {"label": "Account provisioning", "tag": "account_provisioning"}, {"label": "Account provisioning JP", "tag": "account_provisioning_jp"}, {"label": "Adam", "tag": "adam"}, {"label": "App streamer crash", "tag": "app_streamer_crash"}, {"label": "AR marked unhelpful", "tag": "ar_marked_unhelpful"}, {"label": "AR suggest true", "tag": "ar_suggest_true"}, {"label": "Assigned by RR", "tag": "assigned_by_rr"}, {"label": "Authentication", "tag": "authentication"}, {"label": "Autosolved", "tag": "autosolved"}, {"label": "Basic", "tag": "basic"}, {"label": "Business", "tag": "business"}, {"label": "Call", "tag": "call"}, {"label": "Call request", "tag": "call_request"}, {"label": "Can", "tag": "can"}, {"label": "Cancellation form", "tag": "cancellation_form"}, {"label": "Check", "tag": "check"}, {"label": "Closed by merge", "tag": "closed_by_merge"}, {"label": "Code", "tag": "code"}, {"label": "Connection", "tag": "connection"}, {"label": "Connector", "tag": "connector"}, {"label": "Contact", "tag": "contact"}, {"label": "Don't know", "tag": "don_t_know"}, {"label": "Email", "tag": "email"}, {"label": "Enterprise", "tag": "enterprise"}, {"label": "Future ticket pending", "tag": "future_ticket_pending"}, {"label": "GoDaddy cert update 07/30/26", "tag": "07302026_godaddy_cert_update"}, {"label": "Goodbye survey", "tag": "goodbye_survey"}, {"label": "Hangup", "tag": "hangup"}, {"label": "Information", "tag": "information"}, {"label": "Installation", "tag": "installation"}, {"label": "Japan", "tag": "japan"}, {"label": "Jason", "tag": "jason"}, {"label": "Jira escalated", "tag": "jira_escalated"}, {"label": "Language Japan", "tag": "language_japan"}, {"label": "Mac client", "tag": "mac_client"}, {"label": "Mirroring360", "tag": "mirroring360"}, {"label": "No CSAT", "tag": "no_csat"}, {"label": "No survey", "tag": "no_survey"}, {"label": "Not", "tag": "not"}, {"label": "On-prem", "tag": "on-prem"}, {"label": "Other", "tag": "other"}, {"label": "Other client", "tag": "other_client"}, {"label": "Personal", "tag": "personal"}, {"label": "Plus", "tag": "plus"}, {"label": "PO support", "tag": "posupport"}, {"label": "Purchase / refund", "tag": "purchase___refund"}, {"label": "Recovery", "tag": "recovery"}, {"label": "Recovery codes", "tag": "need_recovery_codes"}, {"label": "Refund", "tag": "refund"}, {"label": "Remote access", "tag": "remote_access"}, {"label": "Remote Access SBA", "tag": "remote_access__sba"}, {"label": "Remote Access SBA Perf", "tag": "remote_access__sbaperf"}, {"label": "Remote Access Solo", "tag": "remote_access__solo"}, {"label": "Remote print", "tag": "remote_print"}, {"label": "Remote Support AEM", "tag": "remote_support__aem"}, {"label": "Remote Support MSP", "tag": "remote_support__msp"}, {"label": "Remote Support Premium", "tag": "remote_support__premium"}, {"label": "Request", "tag": "request"}, {"label": "Reset", "tag": "reset"}, {"label": "RMM", "tag": "rmm"}, {"label": "Security 2-step authentication", "tag": "security__2_step_authentication"}, {"label": "Service level 1", "tag": "service_level_1"}, {"label": "Silent close", "tag": "silent_close"}, {"label": "Single sign-on (SSO)", "tag": "single_sign-on__sso_"}, {"label": "SOS computers", "tag": "sos__computers"}, {"label": "SOS package verify", "tag": "sos_package_verify"}, {"label": "Splashtop Access Performance", "tag": "splashtop_access__performance"}, {"label": "Splashtop Access Pro", "tag": "splashtop_access__pro"}, {"label": "Splashtop Access Solo", "tag": "splashtop_access__solo"}, {"label": "Splashtop Access Trial", "tag": "splashtop_access__trial"}, {"label": "Splashtop Business - Support", "tag": "splashtop_business_-_support"}, {"label": "Splashtop Support", "tag": "splashtop_support"}, {"label": "Splashtop Support SOS 300", "tag": "splashtop_support__sos_300"}, {"label": "Splashtop Support Trial", "tag": "splashtop_support__trial"}, {"label": "SSO", "tag": "sso"}, {"label": "Subscription", "tag": "subscription"}, {"label": "Support", "tag": "support"}, {"label": "Support JP", "tag": "support_jp"}, {"label": "System email notification failure", "tag": "system_email_notification_failure"}, {"label": "Usage", "tag": "usage"}, {"label": "Video", "tag": "video"}, {"label": "Voicemail", "tag": "voicemail"}, {"label": "Web widget", "tag": "web_widget"}, {"label": "Website", "tag": "website"}, {"label": "Windows 10", "tag": "windows___win10"}, {"label": "Windows 11", "tag": "windows___win11"}, {"label": "Windows client", "tag": "win_client"}, {"label": "X", "tag": "x"}, {"label": "Zopim chat", "tag": "zopim_chat"}, {"label": "Zopim chat ended", "tag": "zopim_chat_ended"}]
SKIP = {"assigned_by_rr"}


def _rows(since):
    try:
        return store._read("SELECT created_ms, tags FROM cases WHERE created_ms >= %s", [since], fresh=True)
    except Exception:
        return []


def counts(kind="topics", tz_offset_min=0, select=None, top=40):
    """{"rows": [{label, tags, today, d7, d30, prev7, prev30, weeks[8]}], "weeks": [start ms...], ...}
    kind: languages | topics | all. select: the labels to keep (topics)."""
    now = int(time.time() * 1000)
    tz = -int(tz_offset_min) * 60000
    midnight = ((now + tz) // DAY) * DAY - tz
    week0 = midnight - 7 * 7 * DAY - 6 * DAY             # 8 weeks, the last one ending today
    since = min(now - 60 * DAY, week0)
    data = [(ms, set((t or "").split())) for ms, t in _rows(since)]
    if kind == "languages":
        items = [{"label": l["label"], "tags": [l["tag"]]} for l in LANGUAGES]
    elif kind == "all":
        freq = {}
        for ms, tags in data:
            if ms >= now - 30 * DAY:
                for g in tags:
                    if g not in SKIP:
                        freq[g] = freq.get(g, 0) + 1
        items = [{"label": g, "tags": [g]} for g, _ in sorted(freq.items(), key=lambda x: -x[1])[:top]]
    else:
        items = [{"label": g["label"], "tags": g["tags"], "group": True} for g in GROUPS] +                 [{"label": t["label"], "tags": [t["tag"]]} for t in TOPICS]
        if select:
            keep = set(select)
            items = [i for i in items if i["label"] in keep]
    weeks = [week0 + k * 7 * DAY for k in range(8)]
    out = []
    for it in items:
        want = set(it["tags"])
        r = {"label": it["label"], "tags": it["tags"], "group": bool(it.get("group")), "today": 0, "d7": 0, "d30": 0,
             "prev7": 0, "prev30": 0, "weeks": [0] * 8}
        for ms, tags in data:
            if not (want & tags):
                continue
            if ms >= midnight:
                r["today"] += 1
            if ms >= now - 7 * DAY:
                r["d7"] += 1
            elif ms >= now - 14 * DAY:
                r["prev7"] += 1
            if ms >= now - 30 * DAY:
                r["d30"] += 1
            elif ms >= now - 60 * DAY:
                r["prev30"] += 1
            if ms >= week0:
                r["weeks"][min(7, (ms - week0) // (7 * DAY))] += 1
        out.append(r)
    total = {"today": sum(1 for ms, _ in data if ms >= midnight), "d7": sum(1 for ms, _ in data if ms >= now - 7 * DAY),
             "d30": sum(1 for ms, _ in data if ms >= now - 30 * DAY)}
    return {"kind": kind, "rows": out, "weeks": weeks, "total": total, "ready": bool(data),
            "choices": [g["label"] for g in GROUPS] + [t["label"] for t in TOPICS] if kind == "topics" else None}
