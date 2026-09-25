"""Campaign delivery tracking: status callbacks, error translation, counters."""
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.api.v1.endpoints.messaging import WACampaign, CampaignStatus
from app.models.wa_campaign_recipient import WACampaignRecipient as Recipient
from app.services import wa_campaign_delivery as d


def _tid(tu):
    t = tu["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


@pytest.fixture()
def campaign(db, tenant_and_user):
    c = WACampaign(id=str(uuid.uuid4()), tenant_id=_tid(tenant_and_user), name="c", audience_filter={}, variable_map={},
                   status=CampaignStatus.RUNNING)
    db.add(c)
    db.commit()
    return c


def _row(db, campaign, phone="+919811111111", status="sent", wamid=None, **kw):
    r = Recipient(id=str(uuid.uuid4()), tenant_id=campaign.tenant_id, campaign_id=campaign.id, phone=phone,
                  status=status, wa_message_id=wamid or f"wamid.{uuid.uuid4().hex[:8]}", **kw)
    db.add(r)
    db.commit()
    return r


def _cb(wamid, status, ts="1790000000", **extra):
    return {"id": wamid, "status": status, "timestamp": ts, **extra}


# ─── error translation ───────────────────────────────────────────────────────

def test_known_meta_codes_become_plain_language_with_a_next_step():
    info = d.describe_error(131026)
    assert info.group == "not_reachable" and "isn't on WhatsApp" in info.reason and info.hint
    assert d.describe_error("131049").group == "marketing_limit"
    assert d.describe_error("131050").group == "opted_out"
    assert d.describe_error("190").group == "account"
    assert d.describe_error("132015").group == "template"


def test_unknown_codes_keep_metas_own_words():
    info = d.describe_error("999999", "Something specific from Meta")
    assert info.group == "other" and info.reason == "Something specific from Meta"
    assert "Meta reported error 12345" in d.describe_error("12345").reason


def test_our_own_codes():
    assert d.describe_error(d.HAIP_VARIABLE, "No value for body {{1}}").group == "missing_value"
    assert d.describe_error(d.HAIP_SEND).group == "other"


def test_error_from_exception_reads_metas_json_body():
    resp = SimpleNamespace(json=lambda: {"error": {"code": 131026, "message": "Message undeliverable",
                                                   "error_data": {"details": "Not a WhatsApp user"}}})
    code, msg = d.error_from_exception(SimpleNamespace(response=resp))
    assert code == "131026" and msg == "Not a WhatsApp user"


def test_error_from_exception_without_a_response():
    code, msg = d.error_from_exception(RuntimeError("connection reset"))
    assert code is None and "connection reset" in msg
    bad = SimpleNamespace(response=SimpleNamespace(json=lambda: (_ for _ in ()).throw(ValueError("not json"))))
    assert d.error_from_exception(bad)[0] is None


# ─── status callbacks ────────────────────────────────────────────────────────

def test_status_moves_forward_and_counters_are_cumulative(db, campaign):
    r = _row(db, campaign, wamid="w1")
    assert d.apply_status_callback(db, campaign.tenant_id, _cb("w1", "delivered")) is True
    db.commit(); db.refresh(r); db.refresh(campaign)
    assert r.status == "delivered" and r.delivered_at is not None
    assert (campaign.sent_count, campaign.delivered_count, campaign.read_count) == ("1", "1", "0")

    d.apply_status_callback(db, campaign.tenant_id, _cb("w1", "read"))
    db.commit(); db.refresh(r); db.refresh(campaign)
    assert r.status == "read" and r.read_at is not None
    assert (campaign.sent_count, campaign.delivered_count, campaign.read_count) == ("1", "1", "1")


def test_read_arriving_before_delivered_still_fills_both_times(db, campaign):
    r = _row(db, campaign, wamid="w2")
    d.apply_status_callback(db, campaign.tenant_id, _cb("w2", "read"))
    db.commit(); db.refresh(r)
    assert r.status == "read" and r.delivered_at is not None and r.read_at is not None


def test_late_or_repeated_callbacks_never_move_a_status_backwards(db, campaign):
    r = _row(db, campaign, status="read", wamid="w3")
    assert d.apply_status_callback(db, campaign.tenant_id, _cb("w3", "sent")) is True
    assert d.apply_status_callback(db, campaign.tenant_id, _cb("w3", "delivered")) is True
    db.commit(); db.refresh(r)
    assert r.status == "read"


def test_failed_callback_records_the_reason(db, campaign):
    r = _row(db, campaign, wamid="w4")
    d.apply_status_callback(db, campaign.tenant_id, _cb("w4", "failed", errors=[{"code": 131026, "title": "Message undeliverable"}]))
    db.commit(); db.refresh(r); db.refresh(campaign)
    assert r.status == "failed" and r.error_code == "131026" and "isn't on WhatsApp" in r.error_reason
    assert campaign.failed_count == "1" and campaign.sent_count == "0"


def test_a_stray_failure_does_not_undo_a_delivery(db, campaign):
    r = _row(db, campaign, status="delivered", wamid="w5")
    d.apply_status_callback(db, campaign.tenant_id, _cb("w5", "failed", errors=[{"code": 131026}]))
    db.commit(); db.refresh(r)
    assert r.status == "delivered" and r.error_code is None


def test_unknown_message_and_unknown_status_are_not_ours(db, campaign):
    assert d.apply_status_callback(db, campaign.tenant_id, _cb("nope", "delivered")) is False
    _row(db, campaign, wamid="w6")
    assert d.apply_status_callback(db, campaign.tenant_id, _cb("w6", "deleted")) is False
    assert d.apply_status_callback(db, campaign.tenant_id, {"status": "read"}) is False


def test_callbacks_only_match_within_the_same_tenant(db, campaign):
    _row(db, campaign, wamid="w7")
    assert d.apply_status_callback(db, "some-other-tenant", _cb("w7", "delivered")) is False


def test_callback_timestamp_is_used(db, campaign):
    r = _row(db, campaign, wamid="w8")
    d.apply_status_callback(db, campaign.tenant_id, _cb("w8", "delivered", ts="1790000000"))
    db.commit(); db.refresh(r)
    assert r.delivered_at.replace(tzinfo=timezone.utc) == datetime.fromtimestamp(1790000000, tz=timezone.utc)


# ─── retry / resume rules ────────────────────────────────────────────────────

def test_should_skip_only_what_a_second_attempt_cannot_fix(db, campaign):
    assert d.should_skip(_row(db, campaign, phone="+911", status="sent")) is True
    assert d.should_skip(_row(db, campaign, phone="+912", status="read")) is True
    assert d.should_skip(_row(db, campaign, phone="+913", status="queued")) is False
    not_on_wa = _row(db, campaign, phone="+914", status="failed", error_code="131026")
    assert d.should_skip(not_on_wa) is True
    opted = _row(db, campaign, phone="+915", status="failed", error_code="131050")
    assert d.should_skip(opted) is True
    fixable = _row(db, campaign, phone="+916", status="failed", error_code="132015")
    assert d.should_skip(fixable) is False        # template was paused: worth trying again once fixed


def test_mark_sent_takes_the_message_id_from_metas_response():
    row = Recipient(phone="+911", status="queued")
    d.mark_sent(row, {"messages": [{"id": "wamid.ABC"}]})
    assert row.status == "sent" and row.wa_message_id == "wamid.ABC" and row.sent_at is not None
    d.mark_sent(row, None)                          # a malformed response must not raise
    assert row.wa_message_id is None


# ─── breakdown ───────────────────────────────────────────────────────────────

def test_failure_breakdown_groups_and_counts(db, campaign):
    for i in range(3):
        _row(db, campaign, phone=f"+9100{i}", status="failed", error_code="131026", error_reason="x")
    _row(db, campaign, phone="+91009", status="failed", error_code="131050", error_reason="y")
    _row(db, campaign, phone="+91010", status="read")
    out = d.failure_breakdown(db, campaign.id)
    assert [(f["group"], f["count"]) for f in out] == [("not_reachable", 3), ("opted_out", 1)]
    assert out[0]["group_label"] == "Number can't receive it" and out[0]["hint"]
