"""The STOP / START confirmation WhatsApp (opt_out_responder -> wa_booking_messages.send_guest_template).

Until 7 Nov 2026 the responder imported a task that never existed (``send_template_message``) inside a bare
``except``: every confirmation was skipped with one warning line. These tests import the real send path, so a broken
import fails CI instead of hiding.
"""
import uuid
from unittest.mock import MagicMock, patch

from app.api.v1.endpoints.messaging import TemplateStatus, WATemplate
from app.models.conversation import ChannelType, Conversation, Message
from app.models.guest import Guest
from app.models.tenant import Tenant
from app.services import opt_out_responder as oor

DELAY = "app.workers.tasks.send_whatsapp.send_whatsapp_template.delay"
PHONE = "+919845012345"


def test_the_real_send_path_imports():
    # send_guest_template imports these lazily at send time; if either goes missing the confirmation breaks again.
    from app.workers.tasks.send_whatsapp import _bad_number_reason, send_whatsapp_template  # noqa: F401
    assert oor.wbm.send_guest_template and oor._phone_token


def _world(db, *, status=TemplateStatus.APPROVED, bridge=False):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"oo-{uuid.uuid4().hex[:8]}", plan="growth")
    db.add(t)
    db.flush()
    for name in (oor.OPT_OUT_REPLY_TEMPLATE, oor.OPT_IN_REPLY_TEMPLATE):
        db.add(WATemplate(id=str(uuid.uuid4()), tenant_id=t.id, name=name, language="en", category="UTILITY", status=status,
                          components=[{"type": "BODY", "text": "You will not get automated messages from us."}]))
    g = Guest(id=str(uuid.uuid4()), tenant_id=t.id, name="G", phone=PHONE)
    db.add(g)
    db.flush()
    db.add(Conversation(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=g.id, channel=ChannelType.WHATSAPP, is_open=True,
                        source="personal_bridge" if bridge else None))
    db.commit()
    return t, g


def _run(db, t, g, direction="opt_out"):
    log = MagicMock()
    with patch.object(oor, "log", log), patch(DELAY) as delay:
        oor.process_opt_out_event(db, t.id, g.id, PHONE, direction, "stop" if direction == "opt_out" else "start")
    return delay, log


def _confirmations(db, tenant_id):
    return db.query(Message).filter(Message.tenant_id == tenant_id, Message.idempotency_key.like("oo:%")).all()


def _warned(log, reason):
    return [c for c in log.warning.call_args_list if c.args[0] == "opt_out_confirm_not_sent" and c.kwargs.get("reason") == reason]


def test_stop_sends_exactly_one_confirmation(db):
    t, g = _world(db)
    delay, _ = _run(db, t, g)
    assert delay.call_count == 1 and delay.call_args.kwargs["template_name"] == oor.OPT_OUT_REPLY_TEMPLATE
    [m] = _confirmations(db, t.id)
    assert m.sender_kind == "system" and m.channel_metadata["consent_event"] == "opt_out"


def test_opt_in_sends_one_confirmation(db):
    t, g = _world(db)
    delay, _ = _run(db, t, g, "opt_in")
    assert delay.call_count == 1 and delay.call_args.kwargs["template_name"] == oor.OPT_IN_REPLY_TEMPLATE
    assert len(_confirmations(db, t.id)) == 1


def test_a_repeated_stop_does_not_send_twice(db):
    t, g = _world(db)
    _run(db, t, g)
    delay, _ = _run(db, t, g)
    assert delay.call_count == 0 and len(_confirmations(db, t.id)) == 1


def test_template_not_approved_sends_nothing_and_warns(db):
    t, g = _world(db, status=TemplateStatus.PENDING)
    delay, log = _run(db, t, g)
    assert delay.call_count == 0 and _confirmations(db, t.id) == []
    assert _warned(log, "template not approved")


def test_never_sent_into_a_personal_bridge_thread(db):
    t, g = _world(db, bridge=True)
    delay, log = _run(db, t, g)
    assert delay.call_count == 0 and _confirmations(db, t.id) == []
    assert _warned(log, "personal_bridge")


def test_another_tenants_approved_template_is_never_used(db):
    a, _ = _world(db)
    b, gb = _world(db, status=TemplateStatus.PENDING)
    delay, log = _run(db, b, gb)
    assert delay.call_count == 0 and _confirmations(db, b.id) == [] and _confirmations(db, a.id) == []
    assert _warned(log, "template not approved")


def test_a_send_failure_is_logged_with_a_hashed_phone_and_never_raised(db):
    t, g = _world(db)
    tid, gid = t.id, g.id       # the responder rolls back on failure; on SQLite that also drops the test's rows
    log = MagicMock()
    with patch.object(oor, "log", log), patch.object(oor.wbm, "send_guest_template", side_effect=RuntimeError("boom")):
        oor.process_opt_out_event(db, tid, gid, PHONE, "opt_out", "stop")     # must not raise
    [call] = [c for c in log.error.call_args_list if c.args[0] == "opt_out_confirm_failed"]
    assert call.kwargs["tenant_id"] == tid and call.kwargs["phone"] == oor._phone_token(PHONE)
    assert PHONE[-10:] not in repr(call)
