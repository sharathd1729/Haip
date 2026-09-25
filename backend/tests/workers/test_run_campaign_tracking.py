"""The campaign runner records every recipient, never double-sends on a retry,
stops on account-level failures, and the scheduler starts due campaigns."""
import os
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest
from cryptography.fernet import Fernet

os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())

from app.api.v1.endpoints.messaging import (
    CampaignStatus, TemplateStatus, WACampaign, WASubscriber, WATemplate,
)
from app.models.integration import Integration
from app.models.tenant import Tenant
from app.models.wa_campaign_recipient import WACampaignRecipient as Recipient
from app.workers.tasks import campaign_scheduler as scheduler_mod
from app.workers.tasks import run_campaign as runner_mod


def _tid(tu):
    t = tu["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


def _meta_error(code, message="boom"):
    body = {"error": {"code": code, "message": message}}
    resp = httpx.Response(400, json=body, request=httpx.Request("POST", "https://graph.facebook.com/x"))
    return httpx.HTTPStatusError("400", request=resp.request, response=resp)


class FakeAdapter:
    """Records every send; `fail` maps a phone to the exception to raise."""
    def __init__(self, fail=None):
        self.calls = []
        self.fail = fail or {}

    async def send_template(self, to, template_name, language_code="en", components=None):
        self.calls.append({"to": to, "components": components})
        if to in self.fail:
            raise self.fail[to]
        return {"messages": [{"id": f"wamid.{len(self.calls)}"}]}


@pytest.fixture()
def world(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    db.add(Integration(id=str(uuid.uuid4()), tenant_id=tid, kind="whatsapp_meta", status="active",
                       config={"waba_id": "w", "phone_number_id": "pn"}))
    tmpl = WATemplate(id=str(uuid.uuid4()), tenant_id=tid, name="offer", language="en", status=TemplateStatus.APPROVED,
                      meta_template_id="m1", components=[{"type": "BODY", "text": "Hi {{1}}"}])
    db.add(tmpl)
    camp = WACampaign(id=str(uuid.uuid4()), tenant_id=tid, name="c", template_id=tmpl.id, audience_filter={},
                      variable_map={"body": {"1": {"source": "first_name", "fallback": "Guest"}}},
                      status=CampaignStatus.RUNNING)
    db.add(camp)
    for i, name in enumerate(["Priya Sharma", "Arjun Rao", None]):
        db.add(WASubscriber(id=str(uuid.uuid4()), tenant_id=tid, phone=f"+91980000000{i}", name=name, opted_in=True, tags=[]))
    db.commit()
    return SimpleNamespace(tid=tid, camp=camp, camp_id=camp.id, tmpl=tmpl)


def _run(db, w, adapter):
    with patch.object(runner_mod, "SessionLocal", return_value=db), \
         patch("app.adapters.whatsapp.meta_cloud.get_wa_adapter", return_value=adapter), \
         patch("app.workers.tasks.whatsapp._get_wa_access_token", return_value="tok"):
        runner_mod.run_campaign.apply(kwargs={"campaign_id": w.camp_id, "tenant_id": w.tid}).get()
    db.expire_all()


def _relaunch(db, w):
    db.query(WACampaign).filter_by(id=w.camp_id).update({"status": CampaignStatus.RUNNING})
    db.commit()


def _rows(db, w):
    return {r.phone: r for r in db.query(Recipient).filter_by(campaign_id=w.camp_id)}


def test_every_guest_gets_a_record_with_metas_message_id(db, world):
    adapter = FakeAdapter()
    _run(db, world, adapter)
    rows = _rows(db, world)
    assert len(rows) == 3 and all(r.status == "sent" and r.wa_message_id.startswith("wamid.") and r.sent_at for r in rows.values())
    camp = db.query(WACampaign).get(world.camp_id)
    assert camp.status == CampaignStatus.COMPLETED and (camp.sent_count, camp.failed_count) == ("3", "0")
    assert adapter.calls[2]["components"][0]["parameters"][0]["text"] == "Guest"     # the nameless guest got the fallback


def test_a_failure_keeps_metas_reason_and_does_not_stop_the_rest(db, world):
    adapter = FakeAdapter(fail={"+919800000001": _meta_error(131026, "Message undeliverable")})
    _run(db, world, adapter)
    rows = _rows(db, world)
    bad = rows["+919800000001"]
    assert bad.status == "failed" and bad.error_code == "131026" and "isn't on WhatsApp" in bad.error_reason
    assert rows["+919800000000"].status == "sent" and rows["+919800000002"].status == "sent"
    camp = db.query(WACampaign).get(world.camp_id)
    assert camp.status == CampaignStatus.COMPLETED and (camp.sent_count, camp.failed_count) == ("2", "1")


def test_a_missing_variable_fails_that_guest_only(db, world):
    world.camp.variable_map = {"body": {"1": {"source": "first_name"}}}     # no fallback
    db.commit()
    adapter = FakeAdapter()
    _run(db, world, adapter)
    rows = _rows(db, world)
    assert rows["+919800000002"].status == "failed" and rows["+919800000002"].error_code == "HAIP_VARIABLE"
    assert "body {{1}}" in rows["+919800000002"].error_reason
    assert rows["+919800000000"].status == "sent" and len(adapter.calls) == 2


def test_running_again_never_messages_the_same_guest_twice(db, world):
    first = FakeAdapter(fail={"+919800000001": _meta_error(131026)})
    _run(db, world, first)
    assert len(first.calls) == 3
    _relaunch(db, world)
    second = FakeAdapter()
    _run(db, world, second)
    assert db.query(WACampaign).get(world.camp_id).status == CampaignStatus.COMPLETED    # it really ran again...
    assert second.calls == []                       # ...and sent nothing: two were sent, the third is "not on WhatsApp" and final


def test_a_fixable_failure_is_retried_on_the_next_run(db, world):
    first = FakeAdapter(fail={"+919800000001": _meta_error(132015, "template paused")})
    _run(db, world, first)
    assert _rows(db, world)["+919800000001"].status == "failed"
    _relaunch(db, world)
    second = FakeAdapter()
    _run(db, world, second)
    assert [c["to"] for c in second.calls] == ["+919800000001"]
    assert _rows(db, world)["+919800000001"].status == "sent"


def test_repeated_account_failures_pause_the_campaign(db, world):
    for i in range(3, 12):                          # 12 guests in all
        db.add(WASubscriber(id=str(uuid.uuid4()), tenant_id=world.tid, phone=f"+9198000000{i:02d}", name="X", opted_in=True, tags=[]))
    db.commit()
    adapter = FakeAdapter(fail={f"+9198000000{i:02d}": _meta_error(190, "expired") for i in range(0, 12)}
                          | {f"+91980000000{i}": _meta_error(190, "expired") for i in range(0, 3)})
    _run(db, world, adapter)
    camp = db.query(WACampaign).get(world.camp_id)
    assert camp.status == CampaignStatus.PAUSED
    assert len(adapter.calls) == 5                  # stopped after five in a row, not all 12
    assert all(r.error_code == "190" for r in _rows(db, world).values() if r.status == "failed")


def test_an_unrelated_failure_between_does_not_trip_the_breaker(db, world):
    adapter = FakeAdapter(fail={"+919800000000": _meta_error(190), "+919800000001": _meta_error(131026), "+919800000002": _meta_error(190)})
    _run(db, world, adapter)
    assert db.query(WACampaign).get(world.camp_id).status == CampaignStatus.COMPLETED


# ─── scheduler ───────────────────────────────────────────────────────────────

def _scheduled(db, tid, when, status=CampaignStatus.SCHEDULED):
    c = WACampaign(id=str(uuid.uuid4()), tenant_id=tid, name="s", audience_filter={}, variable_map={},
                   status=status, scheduled_at=when.isoformat())
    db.add(c); db.commit()
    return c


def test_the_scheduler_starts_only_due_scheduled_campaigns(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    now = datetime.now(timezone.utc)
    due = _scheduled(db, tid, now - timedelta(minutes=1))
    later = _scheduled(db, tid, now + timedelta(hours=2))
    draft = _scheduled(db, tid, now - timedelta(minutes=5), status=CampaignStatus.DRAFT)
    running = _scheduled(db, tid, now - timedelta(minutes=5), status=CampaignStatus.RUNNING)
    ids = {"due": due.id, "later": later.id, "draft": draft.id, "running": running.id}
    with patch.object(scheduler_mod, "SessionLocal", return_value=db), \
         patch("app.workers.tasks.run_campaign.run_campaign.apply_async") as enqueue:
        out = scheduler_mod.launch_due_campaigns.apply().get()
    db.expire_all()
    assert out == {"launched": 1}
    enqueue.assert_called_once()
    assert enqueue.call_args.kwargs["kwargs"] == {"campaign_id": ids["due"], "tenant_id": tid}
    assert enqueue.call_args.kwargs["queue"] == "whatsapp"
    status = lambda key: db.query(WACampaign).get(ids[key]).status
    assert (status("due"), status("later"), status("draft"), status("running")) == (
        CampaignStatus.RUNNING, CampaignStatus.SCHEDULED, CampaignStatus.DRAFT, CampaignStatus.RUNNING)


def test_a_second_tick_does_not_launch_it_again(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _scheduled(db, tid, datetime.now(timezone.utc) - timedelta(minutes=1))
    with patch.object(scheduler_mod, "SessionLocal", return_value=db), \
         patch("app.workers.tasks.run_campaign.run_campaign.apply_async") as enqueue:
        scheduler_mod.launch_due_campaigns.apply().get()
        scheduler_mod.launch_due_campaigns.apply().get()
    assert enqueue.call_count == 1


# ─── status callbacks reach the campaign ─────────────────────────────────────

def test_the_webhook_status_handler_updates_the_campaign_recipient(db, world):
    from app.workers.tasks import whatsapp as wa
    _run(db, world, FakeAdapter())
    wamid = _rows(db, world)["+919800000000"].wa_message_id
    wa._handle_status_update(db, SimpleNamespace(id=world.tid), {"id": wamid, "status": "read", "timestamp": "1790000000"})
    db.commit(); db.expire_all()
    assert _rows(db, world)["+919800000000"].status == "read"
    camp = db.query(WACampaign).get(world.camp_id)
    assert (camp.sent_count, camp.delivered_count, camp.read_count) == ("3", "1", "1")


# ─── a campaign to CRM leads ─────────────────────────────────────────────────

def test_a_leads_campaign_messages_the_leads_and_records_the_guest(db, world):
    from app.models.guest import Guest
    from app.models.inquiry import Inquiry, InquirySource
    now = datetime.now(timezone.utc)
    guests = {}
    for name, phone in (("Priya Sharma", "+919876500001"), ("Arjun Rao", "+919876500002"), ("No number", "")):
        g = Guest(id=str(uuid.uuid4()), tenant_id=world.tid, name=name, phone=phone)
        db.add(g); db.flush()
        db.add(Inquiry(id=str(uuid.uuid4()), tenant_id=world.tid, guest_id=g.id, source=InquirySource.META_IG, created_at=now, updated_at=now))
        guests[name] = g.id
    db.query(WASubscriber).filter_by(tenant_id=world.tid).delete()          # the subscriber list must not be what's used
    db.query(WACampaign).filter_by(id=world.camp_id).update({"audience_filter": {"type": "leads", "consent_confirmed": True}})
    db.commit()
    adapter = FakeAdapter()
    _run(db, world, adapter)
    rows = _rows(db, world)
    assert sorted(rows) == ["+919876500001", "+919876500002"]
    assert rows["+919876500001"].guest_id == guests["Priya Sharma"] and rows["+919876500001"].subscriber_id is None
    assert adapter.calls[0]["components"][0]["parameters"][0]["text"] in ("Priya", "Arjun")     # first name from the CRM guest
    assert db.query(WACampaign).get(world.camp_id).status == CampaignStatus.COMPLETED


# ─── STOP keeps the subscriber list in step ──────────────────────────────────

def test_a_stop_reply_also_removes_the_person_from_the_subscriber_list(db, world):
    from app.models.guest import Guest
    from app.services.opt_out_responder import process_opt_out_event
    g = Guest(id=str(uuid.uuid4()), tenant_id=world.tid, name="Priya", phone="+919800000000")
    db.add(g); db.commit()
    process_opt_out_event(db, world.tid, g.id, "+919800000000", "opt_out", "stop")
    sub = db.query(WASubscriber).filter_by(tenant_id=world.tid, phone="+919800000000").one()
    assert sub.opted_in is False and sub.opt_out_at
    assert db.query(WASubscriber).filter_by(tenant_id=world.tid, phone="+919800000001").one().opted_in is True    # others untouched
    process_opt_out_event(db, world.tid, g.id, "+919800000000", "opt_in", "start")
    assert db.query(WASubscriber).filter_by(tenant_id=world.tid, phone="+919800000000").one().opted_in is True
