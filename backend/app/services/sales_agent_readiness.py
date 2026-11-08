"""Everything between "guest asks" and "booking paid" for the AI sales agent, as one checklist (Settings > AI > AI sales agent).

Read only: no LLM, no external call. Each row = {key, group, ok, label, detail, fix: {href, label} | None}.
  group "suggest"    needed for the agent to prepare a quote a person sends (sales_agent.mode suggest)
  group "autopilot"  also needed for the agent to send the quote + payment link itself (sales_agent.mode autopilot)
  group "after"      what happens after the guest pays (not needed to quote; shown so nothing is a surprise)
Every row reads the setting the real code path reads (sales_agent_service, quote_send_service.readiness, agent_policy,
learning.limits, wa_booking_pack), so the checklist cannot say "ready" while the agent would still hold back.
docs/architecture/DATA_BRIDGES_AUDIT.md section 4 lists the same steps.
"""

from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.business_record import BusinessRecord
from app.models.integration import Integration
from app.services import agent_policy, ops_pack_catalog, sales_agent_settings
from app.services import business_data_service as bds
from app.services import wa_booking_pack as pack
from app.services.price_policy import price_mode

AI_TAB = "/dashboard/settings"
DATA = "/dashboard/settings/knowledge?tab=structured"
TEMPLATES = "/dashboard/settings/quotes?tab=messages"


def _row(key, group, ok, label, detail, href=None, fix=None) -> dict:
    return {
        "key": key,
        "group": group,
        "ok": bool(ok),
        "label": label,
        "detail": detail,
        "fix": {"href": href, "label": fix} if href and not ok else None,
    }


def _drafts(db: Session, tenant_id: str) -> dict[str, int]:
    rows = (
        db.query(BusinessRecord.kind, func.count(BusinessRecord.id))
        .filter(BusinessRecord.tenant_id == tenant_id, BusinessRecord.status == "draft")
        .group_by(BusinessRecord.kind)
        .all()
    )
    return dict(rows)


def checklist(db: Session, tenant) -> dict:
    tid = tenant.id
    mode = sales_agent_settings.mode(tenant)
    prices = price_mode(tenant)
    packages = bds.list_effective(db, tid, "package")
    retail = [r for r in packages if getattr(bds.parse(r), "audience", "retail") != "b2b"]
    drafts = _drafts(db, tid)
    pay = bds.get_effective(db, tid, "payment_policy", bds.SINGLETON_KEY)
    auto = [r.key for r in packages if bds.parse(r).auto_bookable]
    auto += [r.key for r in bds.list_effective(db, tid, "destination") if bds.parse(r).auto_bookable]
    rzp = (
        db.query(Integration.id)
        .filter(
            Integration.tenant_id == tid,
            Integration.kind == "razorpay",
            Integration.status == "active",
            Integration.credentials_kms_blob.isnot(None),
        )
        .first()
        is not None
    )
    templates = pack.statuses(db, tid)
    base = (settings.API_BASE_URL or "").strip()
    modes = agent_policy.get(tenant, prices)
    cfg = tenant.brand_config if isinstance(tenant.brand_config, dict) else {}
    learning_caps = "learning" in cfg  # learning.limits.cap applies only once these settings exist
    link_ok = modes.get("send_payment_link") == "autonomous"
    wa_mode = (getattr(tenant, "wa_ai_mode_default", None) or "shadow").lower()
    ops_pack = ops_pack_catalog.pack_for_business_type(getattr(tenant, "business_type", None))
    from app.services import balance_reminder_service  # local: it imports the booking + payment services

    reminders = balance_reminder_service.state(db, tenant)["on"]
    waiting = sum(drafts.get(k, 0) for k in ("package", "destination", "itinerary"))

    rows = [
        _row(
            "agent_on",
            "suggest",
            mode != "off",
            "Sales agent switched on",
            f"Now: {mode}." + (" The AI answers as before and never prepares a quote." if mode == "off" else ""),
            "#sales-agent",
            "Choose Suggest or Autopilot below",
        ),
        _row(
            "prices",
            "suggest",
            prices == "grounded",
            "AI may quote published prices",
            "Now: team shares prices. The agent checks the calendar but every price question goes to a person."
            if prices == "handoff"
            else "Only figures your published plans give for the guest's dates, party and route.",
            "#sales-agent",
            "Choose 'AI quotes published prices' below",
        ),
        _row(
            "packages",
            "suggest",
            bool(retail),
            "Plans published",
            f"{len(retail)} published plan(s) the AI can quote"
            + (f"; {waiting} draft(s) not used until published" if waiting else "")
            + ".",
            DATA,
            "Publish plans in Structured Business Data",
        ),
        _row(
            "payment_terms",
            "suggest",
            pay is not None,
            "Payment terms published",
            "The advance comes from them; without them every quote is held ('no advance')."
            if pay is None
            else f"{bds.parse(pay).advance_percent}% advance.",
            DATA,
            "Publish Payment terms in Structured Business Data",
        ),
        _row(
            "razorpay",
            "suggest",
            rzp,
            "Razorpay connected",
            "Each quote option gets its own payment link." if rzp else "No payment link can be made.",
            "/dashboard/settings/payments",
            "Connect Razorpay",
        ),
        _row(
            "quote_template",
            "suggest",
            templates.get(pack.QUOTE_PAYMENT) == "approved",
            "Quote message approved by Meta",
            f"{pack.QUOTE_PAYMENT}: {templates.get(pack.QUOTE_PAYMENT) or 'not created'}. Outside the guest's 24-hour window the quote "
            "can only go as this template.",
            TEMPLATES,
            "Create or submit the quote template",
        ),
        _row(
            "wa_autonomous",
            "autopilot",
            wa_mode == "autonomous",
            "WhatsApp replies sent by the AI",
            f"Now: {wa_mode}. Autopilot sends a quote only when the reply itself was sent by the AI.",
            "#whatsapp-ai-mode",
            "Set WhatsApp AI mode to Autonomous",
        ),
        _row(
            "link_policy",
            "autopilot",
            link_ok,
            "AI may send payment links",
            "Autonomous."
            if link_ok
            else (
                "Payment links always wait for a person's tap while the learning loop is set up: its 'holds and payments' area can go "
                "no higher than Suggest (learning/limits.py). Changing 'Send a payment link' below does not lift it."
                if learning_caps
                else f"Now: {modes.get('send_payment_link', 'consult').replace('_', ' ')}."
            ),
            None if learning_caps else "#agent-policy",
            "Set 'Send a payment link' to Autonomous",
        ),
        _row(
            "auto_bookable",
            "autopilot",
            bool(auto),
            "Overnight plans marked auto-bookable",
            f"Auto-bookable: {', '.join(sorted(auto))}."
            if auto
            else "None. Overnight quotes wait for a person to confirm the stay (same-day plans can still go).",
            DATA,
            "Tick 'auto-bookable' on a plan or route",
        ),
        _row(
            "webhook",
            "after",
            base.startswith("https://"),
            "Razorpay can reach HAIP",
            "Payments arrive within seconds."
            if base.startswith("https://")
            else "No public https address is set on the server, so paid links are found by the 10-minute check instead.",
            None,
        ),
        _row(
            "confirmation_template",
            "after",
            templates.get(pack.BOOKING_CONFIRMED) == "approved",
            "Booking confirmation approved by Meta",
            f"{pack.BOOKING_CONFIRMED}: {templates.get(pack.BOOKING_CONFIRMED) or 'not created'}. Without it the guest gets no "
            "confirmation with the invoice.",
            "/dashboard/settings/invoices",
            "Create or submit the booking templates",
        ),
        _row(
            "ops_file",
            "after",
            ops_pack is not None,
            "Trip file made for the team",
            "A trip file is made as soon as the booking is paid."
            if ops_pack
            else "Your business type has no operations pack, so no trip file is made.",
            None,
        ),
        _row(
            "balance_reminders",
            "after",
            reminders,
            "Balance reminders",
            "The guest is reminded once per instalment."
            if reminders
            else "Off: nobody is reminded of the balance automatically. "
            "It turns on by itself once Razorpay is connected and the reminder template is approved, unless you switched it off.",
            "/dashboard/settings/invoices",
            "Turn on balance reminders",
        ),
    ]
    ready = {g: all(r["ok"] for r in rows if r["group"] == g) for g in ("suggest", "autopilot")}
    return {
        "mode": mode,
        "suggest_ready": ready["suggest"],
        "autopilot_ready": ready["suggest"] and ready["autopilot"],
        "rows": rows,
    }
