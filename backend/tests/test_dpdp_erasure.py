"""DPDP right-to-erasure (dpdp_erasure_service + the nightly job): every row about the person goes, merged duplicates too,
files are deleted only after the commit, other guests and other workspaces are untouched, and the nightly job only reports
until DPDP_ERASURE_ENABLED is on."""
import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from app.api.v1.endpoints.messaging import WASubscriber
from app.models.audit_event import AuditEvent
from app.models.call import Call, CallDirection
from app.models.consent import Consent
from app.models.conversation import ChannelType, Conversation, Message, MessageDirection
from app.models.guest import Guest
from app.models.guest_event import GuestEvent
from app.models.guest_identity import GuestIdentity
from app.models.guest_merge_event import GuestMergeEvent
from app.models.inquiry import Inquiry
from app.models.inquiry_360 import InquiryQuote, InquiryStageLog
from app.models.lead_workflow import LeadJourney, PlaybookAction, PlaybookRun
from app.models.property import Property, Stay
from app.models.task import Task
from app.models.tenant import Tenant
from app.models.transcript import Transcript
from app.models.wa_campaign_recipient import WACampaignRecipient
from app.services import dpdp_erasure_service as erasure

PHONE = "+919876512345"


def _tid(tu):
    t = tu["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


def _person(db, tid, phone=PHONE, name="Kiran Rao"):
    """A guest with data in every table the erase must reach."""
    g = Guest(id=str(uuid.uuid4()), tenant_id=tid, name=name, phone=phone, email="kiran@example.com", city="Mysuru")
    db.add(g)
    db.flush()
    inq = Inquiry(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id)
    db.add(inq)
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, inquiry_id=inq.id, channel=ChannelType.WHATSAPP, is_open=True)
    db.add(conv)
    db.flush()
    db.add(Message(id=str(uuid.uuid4()), tenant_id=tid, conversation_id=conv.id, direction=MessageDirection.INBOUND,
                   channel=ChannelType.WHATSAPP, body="My dates are 30 Oct", media_url=f"{tid}/whatsapp/m1/media.jpg"))
    call = Call(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, inquiry_id=inq.id, ivr_provider="vobiz",
                ivr_call_id=f"c-{uuid.uuid4().hex[:8]}", direction=CallDirection.INBOUND, from_number=phone, to_number="+91",
                duration_seconds=60, recording_s3_key=f"{tid}/recordings/c1.mp3")
    db.add(call)
    db.flush()
    db.add(Transcript(tenant_id=tid, call_id=call.id, provider="sarvam", raw_text="hello"))
    db.add(InquiryQuote(tenant_id=tid, inquiry_id=inq.id, amount=45000))
    db.add(InquiryStageLog(tenant_id=tid, inquiry_id=inq.id, to_stage="active", changed_at=datetime.now(timezone.utc)))
    db.add(LeadJourney(tenant_id=tid, inquiry_id=inq.id, guest_id=g.id, auto_messages=0, outcome="active"))
    run = PlaybookRun(tenant_id=tid, playbook_key="missed_inbound_call", trigger_ref=f"call:{call.id}", inquiry_id=inq.id,
                      guest_id=g.id, status="done", step=0, context={})
    db.add(run)
    db.flush()
    db.add(PlaybookAction(tenant_id=tid, run_id=run.id, playbook_key="missed_inbound_call", inquiry_id=inq.id, guest_id=g.id,
                          action="wa_text", status="queued", payload={}))
    db.add(Task(tenant_id=tid, title="Call back Kiran", guest_id=g.id, inquiry_id=inq.id))
    prop = Property(id=str(uuid.uuid4()), tenant_id=tid, name="Ratha 1", slug=f"r1-{uuid.uuid4().hex[:6]}")
    db.add(prop)
    db.flush()
    db.add(Stay(tenant_id=tid, guest_id=g.id, property_id=prop.id, inquiry_id=inq.id, check_in=date.today(),
                check_out=date.today() + timedelta(days=2), status="confirmed"))
    db.add(Consent(tenant_id=tid, guest_id=g.id, channel="whatsapp", scope="marketing", granted=True,
                   recorded_at=datetime.now(timezone.utc).isoformat()))
    db.add(GuestIdentity(tenant_id=tid, guest_id=g.id, identity_type="phone", identity_value=phone, confidence=0.9))
    db.add(GuestEvent(tenant_id=tid, guest_id=g.id, inquiry_id=inq.id, entity_type="message", entity_id=str(uuid.uuid4()),
                      event_type="message.received", source_module="inbox", occurred_at=datetime.now(timezone.utc),
                      preview="My dates are 30 Oct", payload={}))
    db.add(WASubscriber(tenant_id=tid, phone=phone, name=name))
    db.add(WACampaignRecipient(tenant_id=tid, campaign_id="camp1", guest_id=g.id, phone=phone, name=name))
    db.commit()
    return g, inq


def _request(db, guest, days_ago):
    guest.deletion_state = "pending"
    guest.is_deleted = True
    guest.deletion_requested_at = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    db.commit()


def test_erase_removes_everything_about_the_person_and_their_merged_duplicate(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    g, inq = _person(db, tid)
    dup, dup_inq = _person(db, tid, phone="+919876500777", name="Kiran R")       # an older duplicate merged into g
    db.add(GuestMergeEvent(tenant_id=tid, survivor_id=g.id, deprecated_id=dup.id, reason="exact_identity_match", moved={}))
    other, other_inq = _person(db, tid, phone="+919876599999", name="Someone Else")
    db.commit()

    inq_ids = [inq.id, dup_inq.id]
    other_inq_id = other_inq.id
    result = erasure.erase_guest(db, tid, g.id)
    db.commit()

    for model, col in ((Inquiry, Inquiry.guest_id), (Conversation, Conversation.guest_id), (Call, Call.guest_id),
                       (Stay, Stay.guest_id), (Consent, Consent.guest_id), (GuestIdentity, GuestIdentity.guest_id),
                       (GuestEvent, GuestEvent.guest_id), (LeadJourney, LeadJourney.guest_id), (Task, Task.guest_id),
                       (PlaybookRun, PlaybookRun.guest_id), (PlaybookAction, PlaybookAction.guest_id)):
        assert db.query(model).filter(model.tenant_id == tid, col.in_([g.id, dup.id])).count() == 0, model.__tablename__
    assert db.query(InquiryQuote).filter(InquiryQuote.inquiry_id.in_(inq_ids)).count() == 0
    assert db.query(InquiryStageLog).filter(InquiryStageLog.inquiry_id.in_(inq_ids)).count() == 0
    assert db.query(WASubscriber).filter_by(tenant_id=tid, phone=PHONE).count() == 0
    assert db.query(GuestMergeEvent).filter_by(tenant_id=tid, survivor_id=g.id).count() == 0
    rec = db.query(WACampaignRecipient).filter(WACampaignRecipient.tenant_id == tid,
                                               WACampaignRecipient.phone.like("DELETED_%")).all()
    assert len(rec) == 2
    assert rec and all(r.name is None and r.guest_id is None for r in rec)    # campaign counts survive, the person does not
    for guest in (g, dup):
        db.refresh(guest)
        assert guest.phone.startswith("DELETED_") and guest.name == "[Deleted]" and guest.email is None and guest.city is None
        assert guest.deletion_state == "deleted" and guest.deleted_at is not None
    assert f"{tid}/whatsapp/m1/media.jpg" in result["files"] and f"{tid}/recordings/c1.mp3" in result["files"]
    # The other guest keeps everything.
    assert db.query(Inquiry).filter_by(id=other_inq_id).count() == 1
    assert db.query(Message).join(Conversation).filter(Conversation.guest_id == other.id).count() == 1
    db.refresh(other)
    assert other.phone == "+919876599999"


def test_run_tenant_reports_until_applied_and_erases_only_due_requests(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    due, _ = _person(db, tid)
    fresh, fresh_inq = _person(db, tid, phone="+919876511111")
    _request(db, due, days_ago=31)
    _request(db, fresh, days_ago=5)
    fresh_inq_id = fresh_inq.id

    report = erasure.run_tenant(db, tid, apply=False)
    assert (report["pending"], report["due"], report["erased"]) == (2, 1, 0)
    db.refresh(due)
    assert due.phone == PHONE                                                   # a report writes nothing

    with patch("app.services.media_storage.delete_tenant_objects", return_value=2) as files:
        out = erasure.run_tenant(db, tid, apply=True)
    assert out["erased"] == 1 and out["failed"] == [] and out["files"] == 2
    assert set(files.call_args.args[1]) == {f"{tid}/whatsapp/m1/media.jpg", f"{tid}/recordings/c1.mp3"}
    db.refresh(due)
    db.refresh(fresh)
    assert due.deletion_state == "deleted" and fresh.deletion_state == "pending"
    assert db.query(Inquiry).filter_by(id=fresh_inq_id).count() == 1           # inside its grace period: kept
    audit = db.query(AuditEvent).filter_by(tenant_id=tid, action="dpdp.erasure_completed").one()
    assert audit.target_id == due.id and PHONE not in str(audit.payload)


def test_other_workspace_never_touched(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    g, inq = _person(db, other.id)
    _request(db, g, days_ago=40)
    out = erasure.run_tenant(db, tid, apply=True)
    assert out["pending"] == 0
    assert db.query(Inquiry).filter_by(id=inq.id).count() == 1
    assert erasure.erase_guest(db, tid, g.id) == {"rows": {}, "files": []}   # another workspace's guest: not found


def test_file_delete_only_inside_the_tenant_prefix():
    from app.services import media_storage
    with patch.object(media_storage, "_s3_client") as client:
        n = media_storage.delete_tenant_objects("t1", ["t1/whatsapp/a.jpg", "t2/whatsapp/b.jpg", "../t1/x", None, "t1/whatsapp/a.jpg"])
    assert n == 1
    keys = client.return_value.delete_objects.call_args.kwargs["Delete"]["Objects"]
    assert keys == [{"Key": "t1/whatsapp/a.jpg"}]


def test_nightly_job_reports_when_off_and_erases_when_on(db, tenant_and_user):
    from sqlalchemy.orm import Session as SASession
    from app.workers.tasks import dpdp_purge as job
    tid = _tid(tenant_and_user)
    g, _ = _person(db, tid)
    _request(db, g, days_ago=45)
    with patch.object(job, "SessionLocal", lambda: SASession(bind=db.connection())), \
         patch("app.services.media_storage.delete_tenant_objects", return_value=0):
        with patch.object(job.settings, "DPDP_ERASURE_ENABLED", False):
            off = job.dpdp_purge.run()
        db.refresh(g)
        assert off["applied"] is False and off["tenants"][tid]["due"] == 1 and g.deletion_state == "pending"
        with patch.object(job.settings, "DPDP_ERASURE_ENABLED", True):
            on = job.dpdp_purge.run()
    db.expire_all()
    assert on["applied"] is True and on["tenants"][tid]["erased"] == 1
    assert db.query(Guest).filter_by(id=g.id).one().deletion_state == "deleted"
