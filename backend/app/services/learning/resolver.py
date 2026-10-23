"""THE single hook between the experiments and the sales agent: what this conversation's reply path should read.

``for_conversation`` = the base settings (sales playbook, learning_base controls) with every RUNNING experiment's diff applied
when THIS conversation is in its treatment arm. Read by concierge_draft (prompt playbook, price mode for the turn, consult
threshold, route suggestions) and lead_followup_service (first follow-up delay). Control arm = the base settings, unchanged.

Assignment (``assign``): only conversations OPENED after the experiment started take part; the arm is sticky per conversation
(unique row) and per guest (a guest's later conversation gets the arm their first one got); otherwise a deterministic hash of
experiment id + conversation id splits 50/50. With ``brand_config.learning.paused`` every conversation reads the base, at once.
Guardrails are not here: the code guards downstream apply to both arms, and the catalogue refused anything that would widen them.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.analyst import AgentExperiment, AgentExperimentAssignment
from app.services.kpi_metrics import as_datetime

log = structlog.get_logger()


@dataclass
class Effective:
    playbook: dict = field(default_factory=dict)
    price_packages: set = field(default_factory=set)
    consult_price_above: Optional[int] = None
    route_map: dict = field(default_factory=dict)
    followup_first_hours: dict = field(default_factory=dict)
    arms: dict = field(default_factory=dict)            # experiment id -> arm, for this conversation

    def prompt_playbook(self, db: Session, tenant_id: str) -> Optional[dict]:
        """What the concierge prompt renders (None = nothing to say, prompt unchanged)."""
        from app.schemas.sales_playbook import SalesPlaybook
        from app.services.learning import catalogue
        names = {}
        if self.route_map:
            routes = {**catalogue.published(db, tenant_id, "destination"), **catalogue.published(db, tenant_id, "package")}
            names = {ask: routes[k] for ask, k in self.route_map.items() if k in routes}   # unpublished since: dropped
        pb = catalogue.playbook_after(self.playbook, "none", {}, route_names=names) if names else self.playbook
        return None if pb == SalesPlaybook().model_dump() else pb


def split_value(experiment_id: str, conversation_id: str) -> float:
    h = hashlib.sha256(f"{experiment_id}:{conversation_id}".encode()).hexdigest()[:8]
    return int(h, 16) / 0xFFFFFFFF


def arm_by_hash(experiment_id: str, conversation_id: str, split: float = 0.5) -> str:
    return "treatment" if split_value(experiment_id, conversation_id) < split else "control"


def base(db: Session, tenant) -> Effective:
    from app.services import sales_playbook
    from app.services.learning import settings as ls
    b = ls.base(tenant)
    return Effective(playbook=sales_playbook.get(tenant).model_dump(), price_packages=set(b["price_disclosure_packages"]),
                     consult_price_above=b["consult_price_above"], route_map=dict(b["route_map"]),
                     followup_first_hours=dict(b["followup_first_hours"]))


def running(db: Session, tenant_id: str) -> list[AgentExperiment]:
    return db.query(AgentExperiment).filter_by(tenant_id=tenant_id, status="running").all()


def assign(db: Session, exp: AgentExperiment, conversation, guest_id: Optional[str], *, guest_was_lead: bool = False) -> Optional[str]:
    row = db.query(AgentExperimentAssignment).filter_by(experiment_id=exp.id, conversation_id=conversation.id).first()
    if row is not None:
        return row.arm
    if exp.started_at is None or conversation.created_at is None or as_datetime(conversation.created_at) < as_datetime(exp.started_at):
        return None                                   # an older conversation never takes part
    arm = None
    if guest_id:
        prior = (db.query(AgentExperimentAssignment.arm).filter_by(tenant_id=exp.tenant_id, experiment_id=exp.id, guest_id=guest_id)
                 .order_by(AgentExperimentAssignment.assigned_at).first())
        arm = prior[0] if prior else None
    arm = arm or arm_by_hash(exp.id, conversation.id, float((exp.assignment_rule or {}).get("split", 0.5)))
    try:
        with db.begin_nested():
            db.add(AgentExperimentAssignment(tenant_id=exp.tenant_id, experiment_id=exp.id, conversation_id=conversation.id,
                                             guest_id=guest_id, arm=arm, guest_was_lead=guest_was_lead,
                                             assigned_at=datetime.now(timezone.utc)))
    except IntegrityError:                            # a concurrent reply assigned it first: read theirs
        row = db.query(AgentExperimentAssignment).filter_by(experiment_id=exp.id, conversation_id=conversation.id).first()
        return row.arm if row else None
    return arm


def apply(db: Session, eff: Effective, exp: AgentExperiment) -> None:
    from app.services.learning import catalogue
    ct, d = exp.change_type, exp.diff or {}
    if catalogue.TYPES[ct].control == "sales_playbook":
        eff.playbook = catalogue.playbook_after(eff.playbook, ct, d)
    elif ct == "price_disclosure_per_package":
        eff.price_packages |= set(d.get("packages") or [])
    elif ct == "consult_threshold":
        above = int(d["above_inr"])
        eff.consult_price_above = above if eff.consult_price_above is None else min(eff.consult_price_above, above)
    elif ct == "route_suggestion":
        eff.route_map[d["ask"]] = d["route_key"]
    elif ct == "followup_timing":
        eff.followup_first_hours[d["playbook"]] = float(d["first_hours"])


def for_conversation(db: Session, tenant, conversation, *, guest_id: Optional[str] = None, guest_was_lead: bool = False) -> Effective:
    from app.services.learning import settings as ls
    eff = base(db, tenant)
    if ls.get(tenant).paused or conversation is None:
        return eff
    for exp in running(db, tenant.id):
        try:
            arm = assign(db, exp, conversation, guest_id or conversation.guest_id, guest_was_lead=guest_was_lead)
            if arm:
                eff.arms[exp.id] = arm
            if arm == "treatment":
                apply(db, eff, exp)
        except Exception as exc:  # noqa: BLE001 -- a broken experiment never breaks a reply: this one reads the base
            log.warning("learning_resolve_failed", experiment_id=exp.id, error=type(exc).__name__)
    return eff


def price_mode_for_turn(base_mode: str, eff: Effective, package_key: Optional[str], quote_total: Optional[float]) -> str:
    """handoff -> grounded only for a listed published package; grounded -> handoff when a consult threshold says a person
    should talk about this amount. Never anything else."""
    mode = base_mode
    if mode == "handoff" and package_key and package_key in eff.price_packages:
        mode = "grounded"
    if mode == "grounded" and eff.consult_price_above is not None and quote_total is not None and quote_total > eff.consult_price_above:
        mode = "handoff"
    return mode


def followup_first_delay(db: Session, tenant, playbook_key: str, guest_id: Optional[str], default: timedelta) -> timedelta:
    """The first follow-up delay for this guest: the base value, or a running followup_timing treatment when the guest's latest
    assigned conversation is in its treatment arm. Never assigns (follow-ups do not open conversations)."""
    from app.services.learning import settings as ls
    eff = base(db, tenant)
    hours = eff.followup_first_hours.get(playbook_key)
    if not ls.get(tenant).paused and guest_id:
        for exp in running(db, tenant.id):
            if exp.change_type != "followup_timing" or (exp.diff or {}).get("playbook") != playbook_key:
                continue
            row = (db.query(AgentExperimentAssignment.arm).filter_by(experiment_id=exp.id, guest_id=guest_id)
                   .order_by(AgentExperimentAssignment.assigned_at.desc()).first())
            if row and row[0] == "treatment":
                hours = float(exp.diff["first_hours"])
    return timedelta(hours=float(hours)) if hours else default
