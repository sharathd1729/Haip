"""inquiry_service.reopen_lost_inquiry and scripts/reopen_lost_leads.py."""
import importlib.util
import os
import sys
import uuid
from unittest.mock import patch

import pytest

from app.models.base import gen_uuid
from app.models.guest import Guest
from app.models.inquiry import Inquiry
from app.models.pipeline_stage import PipelineStage
from app.models.tenant import Tenant
from app.services import inquiry_service
from app.services.inquiry_service import InvalidStageTransition

_SCRIPT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts", "reopen_lost_leads.py")


def _world(db):
    t = Tenant(id=str(uuid.uuid4()), name="Ratha", slug=f"rathaa-{uuid.uuid4().hex[:5]}", plan="growth")
    db.add(t)
    db.flush()

    def stage(key, order, **kw):
        s = PipelineStage(id=str(uuid.uuid4()), tenant_id=t.id, key=key, label=key.title(), order=order, **kw)
        db.add(s)
        return s
    st = {"active": stage("active", 1, category="valid"), "sold": stage("sold", 5, category="valid", is_closed_won=True),
          "lost": stage("lost", 6, category="valid", is_closed_lost=True)}
    db.flush()
    return t, st


def _lead(db, t, stage, phone, name="Garry"):
    g = Guest(id=gen_uuid(), tenant_id=t.id, name=name, phone=phone)
    db.add(g)
    db.flush()
    i = Inquiry(id=gen_uuid(), tenant_id=t.id, guest_id=g.id, stage_id=stage.id)
    db.add(i)
    db.flush()
    return g, i


def test_reopen_moves_lost_to_active_and_writes_history(db):
    t, st = _world(db)
    _, lead = _lead(db, t, st["lost"], "+919742077710")
    lead.lost_reason, lead.lost_note = None, "gave up"
    db.commit()
    inquiry_service.reopen_lost_inquiry(db, tenant_id=t.id, inquiry_id=lead.id, new_stage_id=st["active"].id,
                                        actor_user_id=None, actor_role="system", reason="Still talking")
    db.commit()
    db.refresh(lead)
    assert lead.stage_id == st["active"].id and lead.lost_note is None

    from app.models.audit_event import AuditEvent
    ev = db.query(AuditEvent).filter_by(tenant_id=t.id, action="inquiry.stage_changed").one()
    assert ev.payload["from_stage"] == "lost" and ev.payload["to_stage"] == "active" and ev.payload["reason"] == "Still talking"


def test_reopen_guards(db):
    t, st = _world(db)
    _, lost = _lead(db, t, st["lost"], "+919742077711")
    _, sold = _lead(db, t, st["sold"], "+919742077712")
    _, open_ = _lead(db, t, st["active"], "+919742077713")
    db.commit()

    def go(inq, stage=st["active"], role="owner", reason="r"):
        return inquiry_service.reopen_lost_inquiry(db, tenant_id=t.id, inquiry_id=inq.id, new_stage_id=stage.id,
                                                   actor_user_id=None, actor_role=role, reason=reason)

    with pytest.raises(InvalidStageTransition):
        go(lost, role="reservations")                      # only owner/manager
    with pytest.raises(InvalidStageTransition):
        go(lost, reason="  ")                               # a reason is mandatory
    with pytest.raises(InvalidStageTransition):
        go(sold)                                            # a sale is not reopened
    with pytest.raises(InvalidStageTransition):
        go(open_)                                           # not lost
    with pytest.raises(InvalidStageTransition):
        go(lost, stage=st["sold"])                          # must reopen into an open stage
    assert go(lost, role="manager").stage_id == st["active"].id


def test_a_persons_move_out_of_lost_is_a_reopen_and_automatic_moves_stay_blocked(db):
    """28 Oct 2026: an owner/manager moving a Lost lead to an open stage reopens it (reopen_lost_inquiry); an automatic
    caller (role "system") still can't move it through the ordinary path (lead_reopen has its own rule)."""
    t, st = _world(db)
    _, lost = _lead(db, t, st["lost"], "+919742077714")
    db.commit()
    with pytest.raises(InvalidStageTransition):
        inquiry_service.update_stage_by_id(db, tenant_id=t.id, inquiry_id=lost.id, new_stage_id=st["active"].id,
                                           actor_user_id=None, actor_role="system", reason="x")
    inquiry_service.update_stage_by_id(db, tenant_id=t.id, inquiry_id=lost.id, new_stage_id=st["active"].id,
                                       actor_user_id=None, actor_role="owner", reason="x")
    assert lost.stage_id == st["active"].id


def _run(db, *argv):
    spec = importlib.util.spec_from_file_location("reopen_lost_leads", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    with patch.object(mod, "SessionLocal", return_value=db), patch.object(db, "close"), patch.object(sys, "argv", ["x", *argv]):
        return mod.main()


def test_script_dry_run_then_apply_by_phone_any_format(db, capsys):
    t, st = _world(db)
    _, garry = _lead(db, t, st["lost"], "+919742077710", "Garry Regan")
    _, other = _lead(db, t, st["lost"], "+919000000001", "Someone Else")
    db.commit()

    assert _run(db, "--tenant-slug", t.slug, "--phone", "97420 77710") == 0
    out = capsys.readouterr().out
    assert "Garry Regan" in out and "******7710" in out and "9742077710" not in out      # phone is masked in output
    assert "would move to 'Active'" in out and "Dry run only" in out
    db.refresh(garry)
    assert garry.stage_id == st["lost"].id

    assert _run(db, "--tenant-slug", t.slug, "--phone", "+91 97420 77710", "--apply") == 0
    db.refresh(garry)
    db.refresh(other)
    assert garry.stage_id == st["active"].id
    assert other.stage_id == st["lost"].id                                               # only the named lead


def test_script_reports_unknown_numbers_and_leaves_non_lost_alone(db, capsys):
    t, st = _world(db)
    _, active = _lead(db, t, st["active"], "+919742077715")
    db.commit()
    assert _run(db, "--tenant-slug", t.slug, "--phone", "9742077715", "--phone", "9999999999", "--apply") == 2
    out = capsys.readouterr().out
    assert "not in Lost, left as is" in out and "no guest in this workspace has that number" in out
    db.refresh(active)
    assert active.stage_id == st["active"].id
    assert _run(db, "--tenant-slug", "nope", "--phone", "9742077715") == 1
