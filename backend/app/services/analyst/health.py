"""Six health checks, each green / amber / red with its thresholds in ONE place (THRESHOLDS) and the evidence behind it.

  pricing          price objections per new lead; proposals accepted per proposal shared
  routes_packages  guest asks that match nothing published; check-in weekends below the coverage target
  communication    contacts who gave a phone number (DM -> lead)
  response_time    median minutes from enquiry to the first human contact
  team_activity    missed calls not returned; outbound calls that connected
  follow_ups       follow-up tasks done on time, of those due in the period

A check whose base is below its minimum is "no_data" (never green by default). Evidence = record ids (calls, conversations,
enquiries, tasks) and up to 3 short quotes from guests, ANONYMISED: first name only, phone numbers and e-mail addresses masked,
cut at 160 characters. Nothing else about a guest leaves this module.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models.conversation import Conversation, Message, MessageDirection
from app.models.guest import Guest

# check -> metric -> (amber_at, red_at, worse_when "above"|"below", min_base)
THRESHOLDS: dict[str, dict[str, tuple]] = {
    "pricing": {"price_objection_share": (0.15, 0.30, "above", 10), "quote_accept_share": (0.20, 0.10, "below", 10)},
    "routes_packages": {"unavailable_share": (0.15, 0.30, "above", 10), "weekends_below_target": (2, 4, "above", 1)},
    "communication": {"dm_to_lead": (0.40, 0.25, "below", 30)},
    "response_time": {"median_first_contact_minutes": (15, 60, "above", 5)},
    "team_activity": {"missed_not_returned": (2, 5, "above", 1), "outbound_connect_share": (0.5, 0.3, "below", 10)},
    "follow_ups": {"on_time_share": (0.8, 0.5, "below", 5)},
}
LABELS = {"pricing": "Pricing", "routes_packages": "Routes and packages", "communication": "Communication",
          "response_time": "Response time", "team_activity": "Team activity", "follow_ups": "Follow-ups"}
_RANK = {"no_data": -1, "green": 0, "amber": 1, "red": 2}
_PHONE = re.compile(r"\+?\d[\d\s().-]{6,}\d")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_PRICE = re.compile(r"\b(price|budget|expensive|cost|discount|rate|cheaper|how much)\b", re.I)


def anonymise(text: str, limit: int = 160) -> str:
    t = _EMAIL.sub("[email]", text or "")
    t = _PHONE.sub("[number]", t)
    t = " ".join(t.split())
    return (t[: limit - 1] + "…") if len(t) > limit else t


def _first(name: Optional[str]) -> str:
    from app.services.guest_names import first_name
    return first_name(name) or "Guest"


def _status(value, amber, red, worse: str, base: int, min_base: int) -> str:
    if value is None or base < min_base:
        return "no_data"
    if worse == "above":
        return "red" if value >= red else "amber" if value >= amber else "green"
    return "red" if value <= red else "amber" if value <= amber else "green"


def _metric(check: str, key: str, value, base: int, explain: str) -> dict:
    amber, red, worse, min_base = THRESHOLDS[check][key]
    return {"metric": key, "value": value, "base": base, "status": _status(value, amber, red, worse, base, min_base),
            "amber_at": amber, "red_at": red, "worse_when": worse, "min_base": min_base, "explain": explain}


def _quotes(db: Session, tenant_id: str, lo: datetime, hi: datetime, *, pattern: Optional[re.Pattern] = None,
            guest_ids: Optional[list[str]] = None, words: Optional[list[str]] = None) -> list[dict]:
    q = (db.query(Message.body, Message.conversation_id, Guest.name)
         .join(Conversation, Conversation.id == Message.conversation_id).join(Guest, Guest.id == Conversation.guest_id)
         .filter(Message.tenant_id == tenant_id, Conversation.tenant_id == tenant_id, Message.direction == MessageDirection.INBOUND,
                 Message.created_at >= lo, Message.created_at <= hi, Message.body.isnot(None))
         .order_by(Message.created_at.desc()))
    if guest_ids is not None:
        q = q.filter(Conversation.guest_id.in_(guest_ids or ["-"]))
    out = []
    for body, cid, name in q.limit(400).all():
        text = body or ""
        if pattern is not None and not pattern.search(text):
            continue
        if words and not any(w.lower() in text.lower() for w in words):
            continue
        out.append({"who": _first(name), "text": anonymise(text), "conversation_id": cid})
        if len(out) >= 3:
            break
    return out


def build(db: Session, tenant_id: str, lo: datetime, hi: datetime, facts: dict) -> list[dict]:
    j, team, demand, pricing = facts["journey"], facts["team"], facts["demand"], facts["pricing"]
    checks = []

    new_leads = j["leads"]["new"]
    objections = pricing["price_objections_leads"] + pricing["price_objections_calls"]
    shared = pricing["quotes_shared"]
    checks.append(("pricing", [
        _metric("pricing", "price_objection_share", round(objections / new_leads, 3) if new_leads else None, new_leads,
                "Price objections (call and lead readings) per new lead."),
        _metric("pricing", "quote_accept_share", round(pricing["quotes_accepted"] / shared, 3) if shared else None, shared,
                "Proposals accepted, of the proposals shared."),
    ], {"calls": pricing["_evidence"]["calls"][:10], "inquiries": pricing["_evidence"]["inquiries"][:10]},
        _quotes(db, tenant_id, lo, hi, pattern=_PRICE)))

    asked = sum(r["count"] for r in demand["routes_asked"])
    unavailable = sum(r["count"] for r in demand["unavailable_asks"])
    cov = demand.get("checkin_coverage") or {}
    checks.append(("routes_packages", [
        _metric("routes_packages", "unavailable_share", round(unavailable / asked, 3) if asked else None, asked,
                "Routes guests asked for that match nothing published."),
        _metric("routes_packages", "weekends_below_target", len(cov.get("below_target") or []) if cov else None,
                cov.get("weekends", 0) if cov else 0, "Full weekends in the next 8 weeks below the valid-enquiry target."),
    ], {"unavailable": [r["label"] for r in demand["unavailable_asks"]]},
        _quotes(db, tenant_id, lo, hi, words=[r["label"].split()[0] for r in demand["unavailable_asks"][:3]])
        if demand["unavailable_asks"] else []))

    tl = j["contacts"]["to_lead"]
    nonlead_ids = [gid for (gid,) in db.query(Guest.id).filter(Guest.tenant_id == tenant_id, Guest.created_at >= lo,
                                                                  Guest.created_at <= hi, Guest.lead_identified_at.is_(None)).limit(50).all()]
    checks.append(("communication", [
        _metric("communication", "dm_to_lead", tl["rate"], tl["n"], "People who wrote in and gave a phone number."),
    ], {"guests_without_number": nonlead_ids[:10]}, _quotes(db, tenant_id, lo, hi, guest_ids=nonlead_ids)))

    wf = j["workflow"]
    checks.append(("response_time", [
        _metric("response_time", "median_first_contact_minutes", wf["median_first_contact_minutes"], wf["contacted"],
                "Median minutes from an enquiry arriving to the first human contact."),
    ], {}, []))

    missed = sum(r["missed_not_returned"] for r in team)
    made = sum(r["outbound_made"] for r in team)
    conn = sum(r["outbound_connected"] for r in team)
    checks.append(("team_activity", [
        _metric("team_activity", "missed_not_returned", missed, 1, "Missed inbound calls nobody returned."),
        _metric("team_activity", "outbound_connect_share", round(conn / made, 3) if made else None, made,
                "Outbound calls where a person spoke to the guest."),
    ], {}, []))

    due = sum(r["followups_due"] for r in team)
    on_time = sum(r["followups_on_time"] for r in team)
    checks.append(("follow_ups", [
        _metric("follow_ups", "on_time_share", round(on_time / due, 3) if due else None, due,
                "Follow-up tasks done within 30 minutes of when they were due."),
    ], {}, []))

    out = []
    for key, metrics, ids, quotes in checks:
        worst = max((m["status"] for m in metrics), key=lambda s: _RANK[s])
        out.append({"key": key, "label": LABELS[key], "status": worst, "metrics": metrics,
                    "evidence": {"ids": ids, "quotes": quotes[:3]}})
    return out
