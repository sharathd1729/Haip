"""DPDP right-to-erasure: delete everything HAIP holds about one guest, and fulfil requests after their grace period.

How a request flows: POST /guests/{id}/dpdp/delete (owner / compliance) marks the guest ``deletion_state="pending"`` with
``deletion_requested_at`` and hides them; after GRACE_DAYS (30, the period that endpoint promises) the nightly job
(workers/tasks/dpdp_purge.py) calls ``erase_guest`` for each due request, one workspace per transaction, and marks the
guest ``deletion_state="deleted"``. Until the owner switches the job on (``DPDP_ERASURE_ENABLED``) it only REPORTS what is
due; ``scripts/dpdp_erasure_report.py`` shows the same report and can erase on demand.

``erase_guest`` removes every row that carries the person's data, children before parents (no table cascades from guests
on PostgreSQL): conversations and messages (+ AI draft outcomes), calls (+ transcripts, scores), enquiries and everything
hanging off them (quotes, stage log, autopilot decisions, sales actions, lead journey / views, playbook runs and actions,
tasks, ad attribution), bookings and their money lines (issued invoices are tax records: detached, kept), consents,
identities (phone / email / Instagram values), the event ledger, WhatsApp subscriber and campaign-recipient rows (by
phone), flow runs, merge history, and the duplicate guest records that were merged into this person. The guest row stays
as an anonymised tombstone so audit rows still point at something. Nothing here is undoable: callers check first.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from sqlalchemy import or_
from sqlalchemy.orm import Session

log = structlog.get_logger()

GRACE_DAYS = 30


def _aware(value) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _merged_into(db: Session, tenant_id: str, guest_id: str) -> list[str]:
    """Duplicate guest records an identity merge folded into this person (they still carry the same person's data)."""
    from app.models.guest_merge_event import GuestMergeEvent
    return [d for (d,) in db.query(GuestMergeEvent.deprecated_id).filter(
        GuestMergeEvent.tenant_id == tenant_id, GuestMergeEvent.survivor_id == guest_id).all() if d != guest_id]


def _erase_one(db: Session, tenant_id: str, guest_id: str, counts: dict, files: list) -> None:
    from app.api.v1.endpoints.messaging import WASubscriber
    from app.models.ai_draft_outcome import AIDraftOutcome
    from app.models.call import Call
    from app.models.score import CallScore
    from app.models.consent import Consent
    from app.models.conversation import Conversation, Message
    from app.models.flow_execution import FlowPendingExecution, WAFlowRun
    from app.models.guest import Guest
    from app.models.guest_event import GuestEvent
    from app.models.guest_identity import GuestIdentity
    from app.models.guest_merge_event import GuestMergeEvent
    from app.models.inquiry import Inquiry
    from app.models.inquiry_360 import InquiryQuote, InquiryStageLog
    from app.models.invoice import Invoice
    from app.models.lead_attribution import LeadAttribution
    from app.models.lead_autopilot import LeadAutopilotEvent
    from app.models.lead_workflow import LeadJourney, LeadView, PlaybookAction, PlaybookRun
    from app.models.property import Stay
    from app.models.sales_action import SalesAction
    from app.models.stay_finance import (StayAddOn, StayDeposit, StayInstalment, StayPayment, StayPaymentLink,
                                         StayServiceRequest)
    from app.models.task import Task
    from app.models.transcript import Transcript
    from app.models.wa_campaign_recipient import WACampaignRecipient

    def gone(name: str, n: int) -> None:
        counts[name] = counts.get(name, 0) + (n or 0)

    def delete(model, *criteria, name: str) -> None:
        gone(name, db.query(model).filter(*criteria).delete(synchronize_session=False))

    guest = db.query(Guest).filter_by(id=guest_id, tenant_id=tenant_id).first()
    if guest is None:
        return
    phone = guest.phone if guest.phone and not str(guest.phone).startswith("DELETED_") else None

    inq_ids = [i for (i,) in db.query(Inquiry.id).filter_by(tenant_id=tenant_id, guest_id=guest_id).all()]
    conv_ids = [c for (c,) in db.query(Conversation.id).filter_by(tenant_id=tenant_id, guest_id=guest_id).all()]
    call_ids = [c for (c,) in db.query(Call.id).filter_by(tenant_id=tenant_id, guest_id=guest_id).all()]
    stay_ids = [s for (s,) in db.query(Stay.id).filter_by(tenant_id=tenant_id, guest_id=guest_id).all()]
    run_ids = [r for (r,) in db.query(PlaybookRun.id).filter(
        PlaybookRun.tenant_id == tenant_id,
        or_(PlaybookRun.guest_id == guest_id, PlaybookRun.inquiry_id.in_(inq_ids or ["-"]))).all()]

    # Lead workflows, tasks, attribution: they point at enquiries, conversations and the guest.
    delete(PlaybookAction, PlaybookAction.tenant_id == tenant_id,
           or_(PlaybookAction.guest_id == guest_id, PlaybookAction.inquiry_id.in_(inq_ids or ["-"]),
               PlaybookAction.run_id.in_(run_ids or ["-"])), name="playbook_actions")
    delete(PlaybookRun, PlaybookRun.tenant_id == tenant_id, PlaybookRun.id.in_(run_ids or ["-"]), name="playbook_runs")
    delete(LeadView, LeadView.tenant_id == tenant_id, LeadView.inquiry_id.in_(inq_ids or ["-"]), name="lead_views")
    delete(LeadJourney, LeadJourney.tenant_id == tenant_id,
           or_(LeadJourney.guest_id == guest_id, LeadJourney.inquiry_id.in_(inq_ids or ["-"])), name="lead_journeys")
    delete(Task, Task.tenant_id == tenant_id,
           or_(Task.guest_id == guest_id, Task.inquiry_id.in_(inq_ids or ["-"]), Task.conversation_id.in_(conv_ids or ["-"])),
           name="tasks")
    delete(LeadAttribution, LeadAttribution.tenant_id == tenant_id,
           or_(LeadAttribution.guest_id == guest_id, LeadAttribution.conversation_id.in_(conv_ids or ["-"]),
               LeadAttribution.inquiry_id.in_(inq_ids or ["-"])), name="lead_attribution")

    # Stored files (WhatsApp media, call recordings): collected now, deleted after the erase commits.
    if conv_ids:
        files += [k for (k,) in db.query(Message.media_url).filter(Message.conversation_id.in_(conv_ids),
                                                                  Message.media_url.isnot(None)).all()
                  if k and not str(k).startswith("http")]
    if call_ids:
        files += [k for (k,) in db.query(Call.recording_s3_key).filter(Call.id.in_(call_ids),
                                                                      Call.recording_s3_key.isnot(None)).all() if k]

    # Conversations and messages.
    if conv_ids:
        msg_ids = [m for (m,) in db.query(Message.id).filter(Message.conversation_id.in_(conv_ids)).all()]
        if msg_ids:
            delete(AIDraftOutcome, AIDraftOutcome.draft_message_id.in_(msg_ids), name="ai_draft_outcomes")
            db.query(Message).filter(Message.id.in_(msg_ids)).update({Message.replied_to_message_id: None},
                                                                     synchronize_session=False)
        delete(Message, Message.conversation_id.in_(conv_ids), name="messages")
    delete(Conversation, Conversation.tenant_id == tenant_id, Conversation.id.in_(conv_ids or ["-"]), name="conversations")

    # Calls (another guest's call may be the one that returned this guest's missed call, and vice versa).
    if call_ids:
        db.query(Call).filter(Call.tenant_id == tenant_id, Call.recovered_by_call_id.in_(call_ids)).update(
            {Call.recovered_by_call_id: None}, synchronize_session=False)
        delete(Transcript, Transcript.call_id.in_(call_ids), name="transcripts")
        delete(CallScore, CallScore.call_id.in_(call_ids), name="call_scores")
    delete(Call, Call.tenant_id == tenant_id, Call.id.in_(call_ids or ["-"]), name="calls")

    # Bookings and their money lines (issued invoices are tax records: detached from the booking, kept).
    if stay_ids:
        for model in (StayAddOn, StayPayment, StayPaymentLink, StayInstalment, StayDeposit, StayServiceRequest):
            delete(model, model.tenant_id == tenant_id, model.stay_id.in_(stay_ids), name=model.__tablename__)
        db.query(Invoice).filter(Invoice.tenant_id == tenant_id, Invoice.stay_id.in_(stay_ids)).update(
            {Invoice.stay_id: None}, synchronize_session=False)
    delete(Stay, Stay.tenant_id == tenant_id, Stay.id.in_(stay_ids or ["-"]), name="stays")

    # Enquiries and everything hanging off them.
    if inq_ids:
        quote_ids = [q for (q,) in db.query(InquiryQuote.id).filter(InquiryQuote.inquiry_id.in_(inq_ids)).all()]
        if quote_ids:
            db.query(StayPaymentLink).filter(StayPaymentLink.inquiry_quote_id.in_(quote_ids)).update(
                {StayPaymentLink.inquiry_quote_id: None}, synchronize_session=False)
        delete(InquiryQuote, InquiryQuote.inquiry_id.in_(inq_ids), name="inquiry_quotes")
        delete(InquiryStageLog, InquiryStageLog.inquiry_id.in_(inq_ids), name="inquiry_stage_log")
        delete(LeadAutopilotEvent, LeadAutopilotEvent.inquiry_id.in_(inq_ids), name="lead_autopilot_events")
        delete(SalesAction, SalesAction.inquiry_id.in_(inq_ids), name="sales_actions")
    delete(Inquiry, Inquiry.tenant_id == tenant_id, Inquiry.id.in_(inq_ids or ["-"]), name="inquiries")

    # Everything else that names the person.
    delete(Consent, Consent.tenant_id == tenant_id, Consent.guest_id == guest_id, name="consents")
    delete(GuestEvent, GuestEvent.tenant_id == tenant_id,
           or_(GuestEvent.guest_id == guest_id, GuestEvent.inquiry_id.in_(inq_ids or ["-"])), name="guest_events")
    delete(GuestIdentity, GuestIdentity.tenant_id == tenant_id, GuestIdentity.guest_id == guest_id, name="guest_identities")
    delete(FlowPendingExecution, FlowPendingExecution.tenant_id == tenant_id, FlowPendingExecution.guest_id == guest_id,
           name="flow_pending_executions")
    delete(WAFlowRun, WAFlowRun.tenant_id == tenant_id, WAFlowRun.guest_id == guest_id, name="wa_flow_runs")
    delete(GuestMergeEvent, GuestMergeEvent.tenant_id == tenant_id,
           or_(GuestMergeEvent.survivor_id == guest_id, GuestMergeEvent.deprecated_id == guest_id), name="guest_merge_events")
    if phone:
        delete(WASubscriber, WASubscriber.tenant_id == tenant_id, WASubscriber.phone == phone, name="wa_subscribers")
    # Campaign reports keep their counts: the recipient row stays, without who it was. Each row gets its own placeholder
    # (recipients are unique per campaign + phone).
    recipients = db.query(WACampaignRecipient).filter(
        WACampaignRecipient.tenant_id == tenant_id,
        or_(WACampaignRecipient.guest_id == guest_id, WACampaignRecipient.phone == (phone or "-"))).all()
    for rec in recipients:
        rec.phone, rec.name, rec.guest_id = f"DELETED_{rec.id[:8]}", None, None
    gone("wa_campaign_recipients", len(recipients))

    # The tombstone: no personal data left on the row.
    guest.phone = f"DELETED_{guest_id[:8]}"
    guest.email = None
    guest.name = "[Deleted]"
    guest.is_deleted = True
    guest.deleted_at = datetime.now(timezone.utc)
    guest.alt_phone = None
    guest.city = None
    guest.nationality = None
    guest.tags = []
    guest.preferences = {}
    guest.deletion_state = "deleted"
    guest.deletion_completed_at = datetime.now(timezone.utc).isoformat()
    gone("guests", 1)


def erase_guest(db: Session, tenant_id: str, guest_id: str) -> dict:
    """Erase this person: the guest and every duplicate record merged into them. Returns {"rows": {table: n},
    "files": [storage keys]}. Flushes; the caller commits (or rolls back), THEN deletes the files
    (media_storage.delete_tenant_objects), so a rolled-back erase never loses files."""
    counts: dict[str, int] = {}
    files: list[str] = []
    for gid in [guest_id, *_merged_into(db, tenant_id, guest_id)]:
        _erase_one(db, tenant_id, gid, counts, files)
    db.flush()
    log.info("dpdp_erasure_completed", tenant_id=tenant_id, guest_id=guest_id, rows=sum(counts.values()), files=len(files))
    return {"rows": counts, "files": files}


def pending_requests(db: Session, tenant_id: str, now: Optional[datetime] = None) -> list[dict]:
    """Every open erasure request of the workspace: requested when, and whether its grace period has passed."""
    from app.models.guest import Guest
    now = now or datetime.now(timezone.utc)
    out = []
    for g in db.query(Guest).filter(Guest.tenant_id == tenant_id, Guest.deletion_state == "pending").all():
        at = _aware(g.deletion_requested_at)
        due = at is not None and now - at >= timedelta(days=GRACE_DAYS)
        out.append({"guest_id": g.id, "requested_at": at.isoformat() if at else None, "due": due,
                    "due_on": (at + timedelta(days=GRACE_DAYS)).date().isoformat() if at else None})
    return out


def run_tenant(db: Session, tenant_id: str, *, apply: bool, now: Optional[datetime] = None) -> dict:
    """Erase every due request of one workspace (apply=True) or only report them. One transaction; commits when applying.
    A request that fails is rolled back on its own savepoint and reported; the others still go."""
    from app.core.audit import append_audit
    requests = pending_requests(db, tenant_id, now)
    due = [r for r in requests if r["due"]]
    out = {"pending": len(requests), "due": len(due), "erased": 0, "failed": [], "rows": {}, "files": 0}
    if not apply:
        return out
    files: list[str] = []
    for r in due:
        try:
            with db.begin_nested():
                result = erase_guest(db, tenant_id, r["guest_id"])
                counts = result["rows"]
                append_audit(db, tenant_id=tenant_id, actor_user_id=None, action="dpdp.erasure_completed",
                             target_type="guest", target_id=r["guest_id"],
                             payload={"requested_at": r["requested_at"], "rows": counts, "files": len(result["files"])})
        except Exception as exc:  # noqa: BLE001 -- one bad request must not stop the others; it stays pending, logged
            log.error("dpdp_erasure_failed", tenant_id=tenant_id, guest_id=r["guest_id"], error=str(exc)[:300])
            out["failed"].append(r["guest_id"])
            continue
        out["erased"] += 1
        files += result["files"]
        for k, v in counts.items():
            out["rows"][k] = out["rows"].get(k, 0) + v
    db.commit()
    if files:
        from app.services.media_storage import delete_tenant_objects
        out["files"] = delete_tenant_objects(tenant_id, files)
    return out
