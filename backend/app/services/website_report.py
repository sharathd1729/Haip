"""Website report (phase 2): visits -> enquiries -> bookings by source, and which WhatsApp buttons brought chats.

  visits     site_page_views (the cookie-less beacon: utm_source, else the referring site)
  enquiries  leads in the window with source WEBSITE, or a WhatsApp chat that opened with a website button's code
             (custom_fields.website_ref, website_refs); source = utm_source, else "whatsapp button", else "direct"
  bookings   live stays (not cancelled) on those leads; value only for people who may see booking amounts
A source name is normalised the same way on both sides ("l.instagram.com" and utm "Instagram" -> "instagram").
"""

from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.models.inquiry import Inquiry, InquirySource
from app.models.property import Stay
from app.models.website import Site, SitePageView

MAX_LEADS = 5000

# Chat assistants that link to sites: one source of their own (the ONE list; a referrer host or a utm_source naming
# any of them). Matched on the whole host or a subdomain of it, so "gemini.google.com" never swallows "google.com".
AI_ASSISTANTS = "AI assistants"
AI_HOSTS = ("chatgpt.com", "chat.openai.com", "perplexity.ai", "gemini.google.com", "copilot.microsoft.com", "claude.ai")
AI_UTM = {"chatgpt", "chatgpt.com", "openai", "perplexity", "gemini", "copilot", "claude", "claude.ai"}


def _ai_assistant(s: str) -> bool:
    host = s.split("//")[-1].split("/")[0].split(":")[0]
    return s in AI_UTM or any(host == h or host.endswith("." + h) for h in AI_HOSTS)


def norm(source: str) -> str:
    s = (source or "").strip().lower()
    if _ai_assistant(s):
        return AI_ASSISTANTS
    if "." in s:
        parts = [p for p in s.split(".") if p]
        while len(parts) > 2 and parts[0] in ("www", "l", "m", "lm", "web", "mobile"):
            parts = parts[1:]
        s = parts[0] if parts else s
    return s[:60] or "direct"


def _lead_source(inq: Inquiry) -> str:
    cf = inq.custom_fields or {}
    utm = (cf.get("utm") or {}).get("utm_source")
    if utm:
        return norm(utm)
    return "whatsapp button" if (cf.get("website_ref") or {}).get("code") else "direct"


def build(db: Session, site: Site, *, today, days: int, show_money: bool) -> dict:
    since = datetime.now(UTC) - timedelta(days=days)
    rows: dict = defaultdict(lambda: {"visits": 0, "enquiries": 0, "bookings": 0, "value": 0.0})
    for r in db.query(SitePageView).filter(
        SitePageView.tenant_id == site.tenant_id,
        SitePageView.site_id == site.id,
        SitePageView.day >= (today - timedelta(days=days - 1)).isoformat(),
    ):
        rows[norm(r.source)]["visits"] += r.views
    leads = [
        i
        for i in db.query(Inquiry)
        .filter(
            Inquiry.tenant_id == site.tenant_id,
            Inquiry.created_at >= since,
            Inquiry.source.in_((InquirySource.WEBSITE, InquirySource.WA_DIRECT)),
        )
        .limit(MAX_LEADS)
        if i.source == InquirySource.WEBSITE or ((i.custom_fields or {}).get("website_ref") or {}).get("code")
    ]
    by_id = {i.id: i for i in leads}
    stays = (
        [
            s
            for s in db.query(Stay).filter(Stay.tenant_id == site.tenant_id, Stay.inquiry_id.in_(list(by_id)))
            if s.status != "cancelled"
        ]
        if by_id
        else []
    )
    buttons: dict = defaultdict(lambda: {"enquiries": 0, "bookings": 0})
    for i in leads:
        rows[_lead_source(i)]["enquiries"] += 1
        code = ((i.custom_fields or {}).get("website_ref") or {}).get("code")
        if code:
            buttons[code]["enquiries"] += 1
    for s in stays:
        i = by_id[s.inquiry_id]
        rows[_lead_source(i)]["bookings"] += 1
        rows[_lead_source(i)]["value"] += float(s.total_amount or 0)
        code = ((i.custom_fields or {}).get("website_ref") or {}).get("code")
        if code:
            buttons[code]["bookings"] += 1
    out_rows = []
    for src, d in sorted(rows.items(), key=lambda x: (-x[1]["bookings"], -x[1]["enquiries"], -x[1]["visits"])):
        row = {
            "source": src,
            "visits": d["visits"],
            "enquiries": d["enquiries"],
            "bookings": d["bookings"],
            "enquiry_rate": round(d["enquiries"] / d["visits"], 4) if d["visits"] else None,
        }
        if show_money:
            row["value"] = round(d["value"], 2)
        out_rows.append(row)
    total = {k: sum(r[k] for r in out_rows) for k in ("visits", "enquiries", "bookings")}
    return {
        "days": days,
        "since": since.date().isoformat(),
        "total": total,
        "rows": out_rows,
        "buttons": [{"code": c, **d} for c, d in sorted(buttons.items(), key=lambda x: -x[1]["enquiries"])][:30],
        "money_restricted": not show_money,
    }
