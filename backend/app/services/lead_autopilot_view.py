"""Lead autopilot: what the lead page and the Leads list show (read-only, no LLM, no writes).

  lead_block()       -> LeadDetailSchema.autopilot: mode, pinned, the last automatic move (with Undo while it is still
                        the lead's stage), the open suggestion, and a short history
  batch_moves()      -> LeadCardSchema.autopilot_move badge for one page of leads (one query)
  moved_filter()     -> the Leads list "Moved by autopilot" filter
  as_recommended_action() -> an open suggestion in the RecommendedAction shape the lead page already renders with Apply
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.models.lead_autopilot import LeadAutopilotEvent
from app.services.lead_autopilot_service import LOST_REASON_LABEL, settings_from_config


def _stage_labels(db: Session, tenant_id: str, ids: set) -> dict:
    from app.models.pipeline_stage import PipelineStage
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return {s.id: s.label for s in db.query(PipelineStage).filter(PipelineStage.tenant_id == tenant_id,
                                                                  PipelineStage.id.in_(ids)).all()}


def event_dict(e: LeadAutopilotEvent, labels: dict, *, can_undo: bool = False) -> dict:
    return {
        "id": e.id,
        "status": e.status,
        "rule": e.rule,
        "source": e.source,
        "from_stage_id": e.from_stage_id,
        "from_stage_label": labels.get(e.from_stage_id),
        "to_stage_id": e.to_stage_id,
        "to_stage_label": labels.get(e.to_stage_id),
        "reason": e.reason,
        "lost_reason": e.lost_reason,
        "lost_reason_label": LOST_REASON_LABEL.get(e.lost_reason) if e.lost_reason else None,
        "confidence": float(e.confidence) if e.confidence is not None else None,
        "evidence": e.evidence or [],
        "blocked_reason": e.blocked_reason,
        "created_at": e.created_at.isoformat() if e.created_at else None,
        "resolved_at": e.resolved_at.isoformat() if e.resolved_at else None,
        "can_undo": can_undo,
    }


def lead_block(db: Session, tenant_id: str, inquiry) -> dict:
    from app.models.tenant import Tenant
    tenant = db.query(Tenant).filter_by(id=tenant_id).first()
    settings = settings_from_config(tenant.brand_config if tenant else None)
    events = (db.query(LeadAutopilotEvent)
              .filter_by(tenant_id=tenant_id, inquiry_id=inquiry.id)
              .order_by(LeadAutopilotEvent.created_at.desc()).limit(10).all())
    labels = _stage_labels(db, tenant_id, {e.from_stage_id for e in events} | {e.to_stage_id for e in events})
    last_move = next((e for e in events if e.status in ("applied", "undone")), None)
    suggestion = next((e for e in events if e.status in ("suggested", "blocked")), None)
    can_undo = bool(last_move is not None and last_move.status == "applied"
                    and last_move.to_stage_id == inquiry.stage_id and last_move.from_stage_id)
    return {
        "mode": settings["mode"],
        "pinned": inquiry.autopilot_paused_at is not None,
        "pinned_at": inquiry.autopilot_paused_at.isoformat() if inquiry.autopilot_paused_at else None,
        "last_move": event_dict(last_move, labels, can_undo=can_undo) if last_move else None,
        "suggestion": event_dict(suggestion, labels) if suggestion else None,
        "history": [event_dict(e, labels) for e in events[:5]],
    }


def as_recommended_action(block: dict) -> Optional[dict]:
    """The open suggestion as a move_stage RecommendedAction (Apply = the existing audited one-click action)."""
    s = block.get("suggestion") if block else None
    if not s or block.get("pinned") or s["status"] != "suggested":
        return None
    label = f"Mark Lost — {s['to_stage_label']}" if s.get("lost_reason") else f"Move to {s['to_stage_label']}"
    return {
        "action_type": "move_stage",
        "label": label,
        "reason": s["reason"],
        "action_config": {"new_stage_id": s["to_stage_id"], "reason": f"Autopilot suggestion: {s['reason']}"},
        "confirm": True,
    }


def batch_moves(db: Session, tenant_id: str, inquiry_ids: list) -> dict:
    """{inquiry_id: {event_id, to_stage_label, reason, at, source}} for leads whose current stage was set by the autopilot."""
    if not inquiry_ids:
        return {}
    rows = (db.query(LeadAutopilotEvent)
            .filter(LeadAutopilotEvent.tenant_id == tenant_id, LeadAutopilotEvent.inquiry_id.in_(inquiry_ids),
                    LeadAutopilotEvent.status == "applied")
            .order_by(LeadAutopilotEvent.created_at.desc()).all())
    labels = _stage_labels(db, tenant_id, {r.to_stage_id for r in rows})
    out: dict = {}
    for r in rows:
        out.setdefault(r.inquiry_id, {
            "event_id": r.id, "to_stage_label": labels.get(r.to_stage_id), "reason": r.reason,
            "source": r.source, "lost_reason": r.lost_reason,
            "at": r.created_at.isoformat() if r.created_at else None,
        })
    return out


def moved_filter(db: Session, tenant_id: str):
    """SQL predicate for Inquiry: its current stage was set by the autopilot (an applied, not undone, move)."""
    from app.models.inquiry import Inquiry
    sub = (db.query(LeadAutopilotEvent.inquiry_id)
           .filter(LeadAutopilotEvent.tenant_id == tenant_id, LeadAutopilotEvent.status == "applied"))
    return Inquiry.id.in_(sub)
