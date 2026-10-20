"""lead_autopilot_view: the lead page block, the suggestion as a RecommendedAction (Apply), list badges -- tenant-scoped."""
from app.services import lead_autopilot_service as svc
from app.services import lead_autopilot_view as view
from app.services.leads_service import get_lead_detail
from tests.services._autopilot_fixtures import NOW, lead, msg, tenant


def _suggested(db):
    t, s = tenant(db)                                        # default mode: suggest
    _, inq, conv = lead(db, t.id, s["active"])
    msg(db, t.id, conv, "We have cancelled the trip, thanks")
    ev = svc.evaluate(db, t.id, inq.id, now=NOW)
    db.commit()
    return t, s, inq, ev


def test_a_suggestion_becomes_the_lead_pages_apply_action(db):
    t, s, inq, ev = _suggested(db)
    block = view.lead_block(db, t.id, inq)
    assert block["mode"] == "suggest" and block["last_move"] is None and block["suggestion"]["id"] == ev.id
    action = view.as_recommended_action(block)
    assert action["action_type"] == "move_stage" and action["action_config"]["new_stage_id"] == s["lost"].id
    assert action["label"] == "Mark Lost — Lost" and action["confirm"] is True
    detail = get_lead_detail(db, t.id, inq.id)
    assert detail.recommended_actions == [action] and detail.autopilot["suggestion"]["id"] == ev.id


def test_a_pinned_lead_shows_no_suggestion(db):
    t, s, inq, ev = _suggested(db)
    svc.set_pinned(db, t.id, inq, None, True)
    db.commit()
    block = view.lead_block(db, t.id, inq)
    assert block["pinned"] is True and view.as_recommended_action(block) is None
    assert get_lead_detail(db, t.id, inq.id).recommended_actions == []


def test_badges_only_for_applied_moves_of_the_same_tenant(db):
    t, s, inq, ev = _suggested(db)
    assert view.batch_moves(db, t.id, [inq.id]) == {}          # suggested, not applied
    ev.status = "applied"
    db.commit()
    assert view.batch_moves(db, t.id, [inq.id])[inq.id]["to_stage_label"] == "Lost"
    other, _ = tenant(db)
    assert view.batch_moves(db, other.id, [inq.id]) == {}
