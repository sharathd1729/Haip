"""POST /bookings/compose: make the booking the new-booking page describes, and say what HAIP did.

One transaction for the database writes: the lead (a new guest's lead from the chosen source, or the guest's open lead), the
booking through booking_service.create_booking (lead tied and moved to Sold through the audited stage move, so every stage
hook fires), the quote it started from marked accepted (guarded UPDATE; the lead's other quotes withdrawn), the payment
schedule, the security deposit (kept apart: never in the total, never revenue), a payment received now, and reminder tasks.
Only the person comes first: identity_service saves a new guest on its own (an exact normalised phone match reuses the person,
never a duplicate). External steps (Razorpay link, WhatsApp confirmation) run after the commit (booking_compose_send) and their
outcome, good or bad, is a receipt line.

Lead rules (owner decision): a new guest (or a known number typed as new) with no open lead gets a lead from the chosen source,
marked Sold, so source reports count the booking; a guest with an open lead has that lead tied and marked Sold; a known guest
with no open lead gets no lead.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta
from decimal import Decimal
from typing import Optional
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.models.guest import Guest
from app.models.inquiry_360 import InquiryQuote
from app.models.property import Stay
from app.models.stay_finance import StayDeposit, StayInstalment, StayPayment
from app.models.task import Task
from app.models.user import User
from app.schemas.booking_compose import ComposeIn
from app.services import booking_clash as bc
from app.services import booking_compose_people as people
from app.services import booking_compose_send as send
from app.services import booking_compose_service as svc
from app.services import booking_service as bsvc
from app.services import quote_calc_leads as qcl
from app.services import quote_send_service as qss
from app.services.invoice_service import booking_ref

log = structlog.get_logger()
IST = ZoneInfo("Asia/Kolkata")
inr = send.inr


def _due(d) -> datetime:
    return datetime.combine(d, time(10, 0), tzinfo=IST)


def _claim_quote(db: Session, tid: str, quote: InquiryQuote) -> tuple[list[str], int]:
    """issued -> accepted for this quote; the other live quotes of the same lead -> withdrawn. (live link ids to cancel,
    how many other quotes were closed). Raises ComposeError when the quote changed meanwhile (paid, re-quoted)."""
    n = db.execute(update(InquiryQuote).where(InquiryQuote.id == quote.id, InquiryQuote.tenant_id == tid, InquiryQuote.status == "issued")
                   .values(status="accepted").execution_options(synchronize_session=False)).rowcount
    if n != 1:
        raise svc.ComposeError(f"Quote {qss.quote_number(quote)} was just booked or changed. Reload the page and pick again.", 409,
                               code="quote_changed")
    others = (db.query(InquiryQuote).filter(InquiryQuote.tenant_id == tid, InquiryQuote.inquiry_id == quote.inquiry_id,
                                            InquiryQuote.id != quote.id, InquiryQuote.status.in_(("issued", "pending_approval")))
              .all())
    for o in others:
        o.status, o.is_active = "withdrawn", False
    db.refresh(quote)
    links = qss.latest_links(db, tid, [o.id for o in others])
    groups = {qss.group_id(o) for o in others}
    return [lk.id for lk in links.values() if qss.is_live(lk)], len(groups)


def _lead_line(first: str, plan, lead_before: Optional[dict], created: bool, matched: bool, src: Optional[str]) -> dict:
    if created:
        who = "the person who already had this number" if matched else "a new guest"
        return {"done": True, "kind": "lead", "text": f"{first} added as {who}, with a lead from {svc.SOURCE_LABELS.get(src or 'other')} "
                                                      "marked Sold, so source reports count this booking."}
    if lead_before is not None:
        return {"done": True, "kind": "lead", "text": f"{first}'s lead moved from {lead_before['stage_label']} to Sold. Source "
                                                      f"({lead_before['source_label']}) and owner kept."}
    return {"done": False, "kind": "lead", "text": f"{first} has no open lead, so the booking is not tied to one."}


def compose(db: Session, user: User, body: ComposeIn) -> dict:
    from app.services import identity_service, inquiry_service
    tid = user.tenant_id
    plan = svc.evaluate(db, user, body)
    if plan.problems:
        raise svc.ComposeError(plan.problems[0]["message"], 422, plan.problems, code="still_needed")
    tenant = svc._tenant(db, tid)
    stages = qcl._stages(db, tid)

    # 1 the person (identity_service commits a new one on its own)
    matched = False
    if body.guest_id:
        guest = plan.guest
    else:
        gid, created_person = identity_service.resolve_person_by_phone(db, tid, plan.new_phone, name=body.new_guest.name or None,
                                                                       source="agent_manual", actor_user_id=user.id)
        matched = not created_person
        guest = db.query(Guest).filter_by(id=gid, tenant_id=tid).first()
        if body.new_guest.name and not guest.name:
            guest.name = body.new_guest.name.strip()[:120]
    first = send.first_name(guest.name)

    # 2 the lead
    lead = plan.lead if plan.lead is not None and plan.lead.guest_id == guest.id else people.open_lead(db, tid, guest.id, stages)
    lead_before = people.lead_view(lead, stages, db) if lead is not None else None
    lead_created = False
    new_trip = None                                  # the lead already has a booking: this trip gets its own lead
    if lead is not None and lead_before["booking"] is not None:
        origin = lead
        lead = inquiry_service.create_lead_for_guest(
            db, tid, guest.id, source=origin.source, has_phone=bool(guest.phone and not str(guest.phone).startswith("DELETED_")),
            check_in=body.check_in.isoformat(), check_out=body.check_out.isoformat(), adults=body.guests,
            assigned_to=origin.assigned_to or user.id, commit=False)
        new_trip = {"from_lead": origin.id, **lead_before["booking"]}
        append_audit(db, tenant_id=tid, actor_user_id=user.id, action="lead.created_for_new_trip", target_type="inquiry",
                     target_id=lead.id, payload={"guest_id": guest.id, "previous_lead": origin.id,
                                                 "previous_booking": lead_before["booking"]["booking_id"]})
    if lead is None and body.new_guest is not None:
        lead = inquiry_service.create_lead_for_guest(
            db, tid, guest.id, source=svc.SOURCES.get(body.new_guest.source or "other"), has_phone=True,
            check_in=body.check_in.isoformat(), check_out=body.check_out.isoformat(), adults=body.guests, assigned_to=user.id,
            commit=False)
        lead_created = True
        append_audit(db, tenant_id=tid, actor_user_id=user.id, action="lead.created_from_booking", target_type="inquiry",
                     target_id=lead.id, payload={"guest_id": guest.id, "matched_existing_person": matched, "source": body.new_guest.source})

    # 3 the quote it started from
    cancel_links, closed_quotes = [], 0
    if plan.quote is not None:
        cancel_links, closed_quotes = _claim_quote(db, tid, plan.quote)

    # 4 the booking (time-aware clash re-checked inside this transaction)
    prop = plan.prop
    if bsvc.find_conflicts(db, tid, prop.id, body.check_in, body.check_out, check_in_time=body.check_in_time,
                           check_out_time=body.check_out_time):
        db.rollback()
        msg = bc.refuse_message(db, tid, prop, bsvc.find_conflicts(db, tid, prop.id, body.check_in, body.check_out,
                                                                   check_in_time=body.check_in_time, check_out_time=body.check_out_time),
                                body.check_in, body.check_out, body.check_in_time, body.check_out_time)
        raise svc.ComposeError(msg, 409, [{"section": "veh", "message": msg, "live": True}], code="clash")
    t = plan.calc.t
    price_audit = {"lines": [{"label": ln["label"], "amount": str(ln["amount"])} for ln in plan.calc.lines], "total": str(plan.total),
                   "gst_percent": str(t["gst_percent"]), "inclusive": t["prices_include_gst"],
                   "override": {"price": str(t["override_price"]), "reason": body.override.reason} if t["overridden"] else None}
    try:
        stay = bsvc.create_booking(
            db, tid, guest_id=guest.id, prop=prop, check_in=body.check_in, check_out=body.check_out, adults=body.guests, children=0,
            total_amount=plan.total, inquiry_id=lead.id if lead is not None else None, channel_source="direct",
            check_in_time=body.check_in_time, check_out_time=body.check_out_time, internal_notes=svc.staff_notes(body)[:4000] or None,
            actor_user_id=user.id, actor_role=user.role.value, reason="Booked in HAIP (new booking)", gst_percent=t["gst_percent"],
            audit_extra={"source": "new_booking", "quote_id": plan.quote.id if plan.quote else None, "price": price_audit})
    except bsvc.BookingCreateError as exc:
        db.rollback()
        raise svc.ComposeError(exc.message, exc.status, code="booking")
    except inquiry_service.InvalidStageTransition as exc:
        db.rollback()
        raise svc.ComposeError(f"The lead could not be marked Sold: {exc.detail}", 409, code="lead_stage")
    ref = booking_ref(stay)

    # 5 money: schedule, deposit, a payment received now
    full = plan.advance >= plan.total
    db.add(StayInstalment(tenant_id=tid, stay_id=stay.id, amount=plan.advance, due_date=plan.advance_due,
                          label="Full payment" if full else (f"Advance {svc.cat.num_str(body.advance.percent)}%"
                                                             if body.advance.amount is None and body.advance.percent else "Advance")))
    if plan.balance > 0:
        db.add(StayInstalment(tenant_id=tid, stay_id=stay.id, label="Balance", amount=plan.balance, due_date=plan.balance_due))
    if body.deposit_amount > 0:
        db.add(StayDeposit(tenant_id=tid, stay_id=stay.id, amount=body.deposit_amount, status="pending",
                           notes="Collect at pickup" if body.deposit_collect == "pickup" else "Collect with the balance"))
    pay = body.payment
    if pay.kind == "paid":
        ref_txt = (pay.reference or "").strip() or None
        db.add(StayPayment(tenant_id=tid, stay_id=stay.id, kind="payment", amount=plan.paid, method=pay.method, reference=ref_txt,
                           external_id=ref_txt if pay.method == "razorpay" and ref_txt and ref_txt.startswith("pay_") else None,
                           paid_on=plan.today, created_by=user.id,
                           notes=f"Received by {user.name}" if pay.method == "cash" else "Recorded when the booking was made"))
        append_audit(db, tenant_id=tid, actor_user_id=user.id, action="booking.payment_recorded", target_type="booking", target_id=stay.id,
                     payload={"amount": str(plan.paid), "method": pay.method, "reference": ref_txt})
    tasks = []
    if pay.kind == "none" and plan.advance > 0:
        tasks.append((f"Collect the {inr(plan.advance)} advance from {guest.name or 'the guest'} ({ref})", plan.advance_due))
    if plan.balance > 0:
        tasks.append((f"Collect the {inr(plan.balance)} balance from {guest.name or 'the guest'} ({ref})",
                      max(plan.today, plan.balance_due - timedelta(days=1))))
    for title, d in tasks:
        db.add(Task(tenant_id=tid, title=title[:255], due_date=_due(d), priority="medium", guest_id=guest.id,
                    inquiry_id=stay.inquiry_id, assigned_to=user.id, created_by=user.id))
    append_audit(db, tenant_id=tid, actor_user_id=user.id, action="booking.composed", target_type="booking", target_id=stay.id,
                 payload={"schedule": {"advance": str(plan.advance), "advance_due": plan.advance_due.isoformat(),
                                       "balance": str(plan.balance), "balance_due": plan.balance_due.isoformat() if plan.balance_due else None},
                          "deposit": str(body.deposit_amount), "payment_now": pay.kind, "lead_created": lead_created})
    db.commit()
    db.refresh(stay)

    if cancel_links:
        from app.workers.tasks import quote_tasks
        try:
            quote_tasks.cancel_payment_links.delay(tenant_id=tid, link_ids=cancel_links)
        except Exception as exc:  # noqa: BLE001 -- the booking stands; the links simply stay open
            log.error("compose_cancel_links_enqueue_failed", tenant_id=tid, error=str(exc))

    # 6 the receipt
    lead_item = _lead_line(first, plan, lead_before, lead_created, matched, body.new_guest.source if body.new_guest else None)
    if new_trip is not None:
        lead_item = {"done": True, "kind": "lead", "text": f"{first}'s lead already has booking {new_trip['ref']} ({new_trip['span']}), so "
                     f"this trip got its own lead ({lead_before['source_label']}, same owner), marked Sold."}
    items = [{"done": True, "kind": "booking", "text": f"Booking {ref} created on {prop.name}: {bc.day(body.check_in)} "
              f"{bc.clock(body.check_in_time)} → {bc.day(body.check_out)} {bc.clock(body.check_out_time)}, {body.guests} guests."},
             lead_item]
    if plan.quote is not None:
        extra = "" if not closed_quotes else (" The other quote for this lead is closed." if closed_quotes == 1
                                              else f" The other {closed_quotes} quotes for this lead are closed.")
        items.append({"done": True, "kind": "quote", "text": f"Quote {qss.quote_number(plan.quote)} marked Booked.{extra}"})
    paid_all = pay.kind == "paid" and plan.paid >= plan.advance
    items.append({"done": True, "kind": "schedule", "text":
                  f"Payment schedule: advance {inr(plan.advance)} {'paid' if paid_all else 'due ' + bc.day(plan.advance_due)}"
                  + (f", balance {inr(plan.balance)} due {bc.day(plan.balance_due)}{' before pickup' if body.balance_rule == 'pickup' else ''}"
                     if plan.balance > 0 else "") + "."})
    if body.deposit_amount > 0:
        items.append({"done": True, "kind": "deposit", "text": f"Security deposit {inr(body.deposit_amount)} to collect "
                      f"{'at pickup' if body.deposit_collect == 'pickup' else 'with the balance'}. Kept apart, not revenue."})
    if pay.kind == "paid":
        items.append({"done": True, "kind": "payment", "text": f"{inr(plan.paid)} recorded: {svc.METHOD_LABELS[pay.method]}"
                      f"{' · ' + pay.reference.strip() if (pay.reference or '').strip() else ''}."})
    elif pay.kind == "none":
        items.append({"done": False, "kind": "payment", "text": f"Nothing paid yet. Reminder for {send.first_name(user.name)} on "
                      f"{bc.day(plan.advance_due)} to collect the {inr(plan.advance)} advance."})
    items.append({"done": True, "kind": "calendar", "text": f"Calendar: {prop.name} blocked {bc.span(body.check_in, body.check_out)}. "
                  "Shared calendar links update within 30 min."})
    notes = svc.staff_notes(body)
    items.append({"done": True, "kind": "notes", "text": f"Staff notes: “{notes}”"} if body.interior else
                 {"done": False, "kind": "notes", "text": "Interior not picked yet. Add Black or White to the booking's staff notes "
                                                         "before pickup." + (f" Saved: “{notes}”" if notes else "")})
    make = svc.text_maker(db, tenant, body, plan, guest.name, prop.name)
    items += send.after_commit(db, tenant, user, stay, plan=plan, body=body, make_text=make)
    if plan.balance > 0:
        items.append({"done": True, "kind": "followup", "text": f"Follow-up for {send.first_name(user.name)}: collect the "
                      f"{inr(plan.balance)} balance on {bc.day(max(plan.today, plan.balance_due - timedelta(days=1)))}."})
    return {"booking_id": stay.id, "ref": ref, "vehicle": prop.name, "guest_name": guest.name, "total": str(plan.total),
            "inquiry_id": stay.inquiry_id, "new_trip_lead": new_trip is not None, "items": items}
