"""scripts/bulk_move_leads_to_lost.py: dry run changes nothing, apply moves only the right leads."""
import importlib.util
import os
import sys
import uuid
from datetime import date, timedelta
from unittest.mock import patch

from app.models.base import gen_uuid
from app.models.guest import Guest
from app.models.inquiry import Inquiry
from app.models.pipeline_stage import PipelineStage
from app.models.tenant import Tenant

_SCRIPT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts", "bulk_move_leads_to_lost.py")


def _load():
    spec = importlib.util.spec_from_file_location("bulk_move_leads_to_lost", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _stage(db, tid, key, order, **kw):
    s = PipelineStage(id=str(uuid.uuid4()), tenant_id=tid, key=key, label=key.title(), order=order, **kw)
    db.add(s)
    return s


def _lead(db, tid, stage, **kw):
    g = Guest(id=gen_uuid(), tenant_id=tid, name="G", phone=f"+9198{uuid.uuid4().int % 10**8:08d}")
    db.add(g)
    db.flush()
    i = Inquiry(id=gen_uuid(), tenant_id=tid, guest_id=g.id, stage_id=stage.id, **kw)
    db.add(i)
    return i


def _world(db):
    t = Tenant(id=str(uuid.uuid4()), name="Ratha", slug=f"rathaa-{uuid.uuid4().hex[:5]}", plan="growth")
    db.add(t)
    db.flush()
    stages = {
        "enquiry": _stage(db, t.id, "general_enquiry", 0, category="invalid", is_default_entry=True),
        "active": _stage(db, t.id, "active", 1, category="valid"),
        "sold": _stage(db, t.id, "sold", 5, category="valid", is_closed_won=True),
        "lost": _stage(db, t.id, "lost", 6, category="valid", is_closed_lost=True),
        "collab": _stage(db, t.id, "collaboration_engagement", 7, category="marketing", is_collab_entry=True),
    }
    db.flush()
    past = (date.today() - timedelta(days=30)).isoformat()
    future = (date.today() + timedelta(days=30)).isoformat()
    leads = {
        "enquiry_future": _lead(db, t.id, stages["enquiry"], check_in=future, check_out=future),
        "active_past": _lead(db, t.id, stages["active"], check_in=past, check_out=past),
        "active_nodates": _lead(db, t.id, stages["active"]),
        "sold": _lead(db, t.id, stages["sold"], check_in=future, check_out=future),
        "lost": _lead(db, t.id, stages["lost"]),
        "collab": _lead(db, t.id, stages["collab"]),
    }
    db.commit()
    return t, stages, leads


def _run(db, *argv):
    mod = _load()
    with patch.object(mod, "SessionLocal", return_value=db), patch.object(db, "close"), patch.object(sys, "argv", ["x", *argv]):
        return mod.main()


def test_dry_run_changes_nothing(db, capsys):
    t, stages, leads = _world(db)
    assert _run(db, "--tenant-slug", t.slug) == 0
    out = capsys.readouterr().out
    assert "to move: 3" in out and "Dry run only" in out
    for lead in leads.values():
        db.refresh(lead)
    assert leads["active_past"].stage_id == stages["active"].id and leads["enquiry_future"].stage_id == stages["enquiry"].id


def test_apply_moves_open_leads_regardless_of_dates_and_spares_the_rest(db, capsys):
    t, stages, leads = _world(db)
    assert _run(db, "--tenant-slug", t.slug, "--apply") == 0
    for lead in leads.values():
        db.refresh(lead)
    lost = stages["lost"].id
    assert [leads[k].stage_id for k in ("enquiry_future", "active_past", "active_nodates")] == [lost, lost, lost]
    assert leads["sold"].stage_id == stages["sold"].id        # a sale stays a sale
    assert leads["lost"].stage_id == lost
    assert leads["collab"].stage_id == stages["collab"].id    # marketing entries are not sales leads
    assert "Moved to 'Lost': 3" in capsys.readouterr().out


def test_second_apply_is_a_no_op_and_history_is_written(db, capsys):
    t, stages, leads = _world(db)
    _run(db, "--tenant-slug", t.slug, "--apply")
    capsys.readouterr()
    assert _run(db, "--tenant-slug", t.slug, "--apply") == 0
    assert "Nothing to do" in capsys.readouterr().out

    from app.models.audit_event import AuditEvent
    events = db.query(AuditEvent).filter_by(tenant_id=t.id, action="inquiry.stage_changed").all()
    assert len(events) == 3 and all(e.payload["to_stage"] == "lost" for e in events)


def test_only_touches_the_named_workspace(db, capsys):
    t, stages, leads = _world(db)
    other, other_stages, other_leads = _world(db)
    _run(db, "--tenant-slug", t.slug, "--apply")
    db.refresh(other_leads["active_past"])
    assert other_leads["active_past"].stage_id == other_stages["active"].id


def test_unknown_workspace_and_missing_lost_stage(db, capsys):
    assert _run(db, "--tenant-slug", "no-such-workspace") == 1
    t = Tenant(id=str(uuid.uuid4()), name="NoLost", slug=f"nl-{uuid.uuid4().hex[:5]}", plan="growth")
    db.add(t)
    db.flush()
    _stage(db, t.id, "active", 1, category="valid")
    db.commit()
    assert _run(db, "--tenant-slug", t.slug, "--apply") == 1
    assert "no Lost stage" in capsys.readouterr().out
