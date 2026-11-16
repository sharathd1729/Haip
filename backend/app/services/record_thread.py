"""A booking's thread across modules (workspace redesign Phase 4): Enquiry → Chats → Quote → Booking → Money → Guest form
→ Ops file → Review, plus the other records tied to the same guest. Reads only; every step links to its own page, which
checks its own permissions. Amounts only with money=True (bookings.read), never 0 in their place.

state per step: done | due | waiting | none (none = that module has nothing for this booking; the step still shows so the
gap is visible).
"""

from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.call import Call
from app.models.conversation import Conversation
from app.models.inquiry import Inquiry
from app.models.inquiry_360 import InquiryQuote
from app.models.ops_files import OpsFile
from app.models.ops_fleet import OpsAutoMessage, OpsGuestForm
from app.models.pipeline_stage import PipelineStage
from app.models.property import Stay
from app.models.task import Task
from app.services import booking_service

SOURCES = {"META_IG": "Instagram", "META_FB": "Facebook", "CLICK_TO_WA": "WhatsApp ad", "WA_DIRECT": "WhatsApp",
           "PHONE": "Phone", "WEBSITE": "Website", "GOOGLE": "Google", "REFERRAL": "Referral", "WALK_IN": "Walk-in",
           "EMAIL": "Email", "TRAVEL_AGENT": "Travel agent", "organic_call": "Call"}
FILE_STATES = {"accepted": "Accepted", "preparing": "Preparing", "ready": "Ready", "staying": "Guest is in", "checked_out": "Guest has left", "on_trip": "On the road",
               "on_road": "On the road", "settling": "Settling up", "closed": "Closed", "cancelled": "Cancelled"}


def _day(dt) -> str | None:
    return dt.date().isoformat() if hasattr(dt, "date") and dt else (str(dt)[:10] if dt else None)


def for_booking(db: Session, tenant_id: str, stay: Stay, *, money: bool) -> dict:
    amt = (lambda v: round(float(v or 0), 2)) if money else (lambda v: None)
    gid = stay.guest_id
    steps: list[dict] = []

    inq = db.query(Inquiry).filter(Inquiry.id == stay.inquiry_id, Inquiry.tenant_id == tenant_id).first() if stay.inquiry_id else None
    if inq:
        stage = db.query(PipelineStage.label).filter(PipelineStage.id == inq.stage_id, PipelineStage.tenant_id == tenant_id).scalar()
        src = getattr(inq.source, "value", inq.source)
        steps.append({"key": "enquiry", "label": "Enquiry" + (f" · {SOURCES.get(src, str(src).replace('_', ' ').title())}" if src else ""),
                      "value": " · ".join(x for x in (_day(inq.created_at), stage) if x), "state": "done",
                      "href": f"/dashboard/leads/{inq.id}"})
    else:
        steps.append({"key": "enquiry", "label": "Enquiry", "value": "Not linked", "state": "none", "href": None})

    convs = db.query(Conversation).filter(Conversation.tenant_id == tenant_id, Conversation.guest_id == gid).all()
    calls = db.query(func.count(Call.id)).filter(Call.tenant_id == tenant_id, Call.guest_id == gid).scalar() or 0
    channels = sorted({getattr(c.channel, "value", str(c.channel)).replace("_", " ").title() for c in convs})
    latest = max(convs, key=lambda c: c.last_message_at or "", default=None)
    chat_bits = [", ".join(channels)] if channels else []
    if calls:
        chat_bits.append(f"{calls} call{'s' if calls != 1 else ''}")
    steps.append({"key": "chats", "label": "Chats", "value": " · ".join(chat_bits) or "None yet",
                  "state": "done" if chat_bits else "none",
                  "href": f"/dashboard/inbox?conversation={latest.id}" if latest else None})

    quote = (db.query(InquiryQuote).filter(InquiryQuote.tenant_id == tenant_id, InquiryQuote.inquiry_id == inq.id)
             .order_by(InquiryQuote.created_at.desc()).first()) if inq else None
    if quote:
        shared = {"sent": "sent", "copied": "copied"}.get(quote.shared_via or "", "saved")
        value = f"₹{amt(quote.amount):,.0f} · {shared}" if money else shared.capitalize()
        steps.append({"key": "quote", "label": "Quote", "value": value, "state": "done", "href": f"/dashboard/leads/{inq.id}"})
    else:
        steps.append({"key": "quote", "label": "Quote", "value": "None", "state": "none", "href": None})

    steps.append({"key": "booking", "label": "Booking", "value": "You are here", "state": "current",
                  "href": f"/dashboard/bookings/{stay.id}"})

    fin = booking_service.financials_for(db, tenant_id, [stay])[stay.id]
    due = booking_service.next_due(booking_service.schedules_for(db, tenant_id, {stay.id: fin}).get(stay.id, []))
    owing = fin["total"] > 0 and fin["outstanding"] > 0.005
    if stay.status == "cancelled":
        money_step = {"value": "Cancelled", "state": "none"}
    elif owing:
        late = bool(due and due["overdue"])
        money_step = {"value": (f"₹{fin['outstanding']:,.0f} " if money else "Balance ") + ("overdue" if late else "due"),
                      "state": "due" if late else "waiting"}
    else:
        money_step = {"value": "Paid in full" if fin["total"] > 0 else "No amount yet", "state": "done" if fin["total"] > 0 else "none"}

    f = db.query(OpsFile).filter(OpsFile.tenant_id == tenant_id, OpsFile.stay_id == stay.id).first()
    steps.append({"key": "money", "label": "Money", **money_step,
                  "href": f"/dashboard/ops/files/{f.id}#money" if f else f"/dashboard/bookings/{stay.id}#payments"})

    form = db.query(OpsGuestForm).filter(OpsGuestForm.tenant_id == tenant_id, OpsGuestForm.stay_id == stay.id).first()
    steps.append({"key": "form", "label": "Guest form",
                  "value": "Filled" if form and form.submitted_at else ("Sent, not filled" if form else "Not sent"),
                  "state": "done" if form and form.submitted_at else ("waiting" if form else "none"),
                  "href": f"/dashboard/ops/files/{f.id}#guests" if f else None})
    steps.append({"key": "ops", "label": "Ops file", "value": FILE_STATES.get(f.state, f.state.replace("_", " ").title()) if f else "Not opened",
                  "state": ("done" if f.state == "closed" else "waiting") if f else "none",
                  "href": f"/dashboard/ops/files/{f.id}" if f else None})

    review = (db.query(OpsAutoMessage).filter(OpsAutoMessage.tenant_id == tenant_id, OpsAutoMessage.file_id == f.id,
                                              OpsAutoMessage.kind == "review_request").first()) if f else None
    if review and (review.response or "").isdigit():
        r = {"value": f"{review.response} of 5", "state": "done"}
    elif review:
        r = {"value": "Asked, no answer", "state": "waiting"}
    else:
        r = {"value": f"After {stay.check_out.day} {stay.check_out.strftime('%b')}" if stay.status != "cancelled" else "—",
             "state": "none"}
    steps.append({"key": "review", "label": "Review", **r, "href": f"/dashboard/ops/files/{f.id}" if f and review else None})

    others = (db.query(Stay).filter(Stay.tenant_id == tenant_id, Stay.guest_id == gid, Stay.id != stay.id)
              .order_by(Stay.check_in.desc()).limit(5).all())
    open_tasks = db.query(func.count(Task.id)).filter(Task.tenant_id == tenant_id, Task.guest_id == gid,
                                                      Task.is_done.is_(False)).scalar() or 0
    linked = [{"label": "Guest profile", "value": f"{len(others) + 1} booking{'s' if others else ''}", "href": f"/dashboard/guests/{gid}"}]
    for c in sorted(convs, key=lambda c: c.last_message_at or "", reverse=True)[:3]:
        linked.append({"label": f"{getattr(c.channel, 'value', str(c.channel)).replace('_', ' ').title()} chat",
                       "value": (c.last_message_at or "")[:10] or None, "href": f"/dashboard/inbox?conversation={c.id}"})
    if calls:
        linked.append({"label": "Calls", "value": str(calls), "href": f"/dashboard/guests/{gid}"})
    if inq:
        linked.append({"label": "Lead", "value": next((s["value"].split(" · ")[-1] for s in steps if s["key"] == "enquiry"), None),
                       "href": f"/dashboard/leads/{inq.id}"})
    if open_tasks:
        linked.append({"label": "Tasks", "value": f"{open_tasks} open", "href": "/dashboard/my-day", "attention": True})
    for o in others:
        linked.append({"label": "Other booking", "value": o.check_in.strftime("%b %Y"),
                       "href": f"/dashboard/bookings/{o.id}"})
    return {"steps": steps, "linked": linked, "money_restricted": not money}
