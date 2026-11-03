"""The AI Executive's Celery tasks (exact-name routes: detection on ``default``, explanations on ``ai_scoring``).

  chief.detect_all_tenants   beat: every 5 min with cadence "urgent", 06:30 IST with "daily"; queues each workspace that has
                             ``brand_config.chief.enabled``
  chief.detect_tenant        run the due detectors for one workspace (services/chief/findings.run), commit, then queue the
                             explanations when the kill switch is off
  chief.explain_tenant       grounded explanations for new / changed findings (router ``chief_explain``)
  chief.execute_proposal     run an APPROVED proposal's steps (services/chief/executor.run); queue whatsapp (steps may
                             submit to Meta or message guests, only after an owner's approval)
  chief.outcomes_all_tenants beat 06:50 IST: did each finished fix work (services/chief/outcomes.py), then offer autopilot
                             to the owners for detectors that earned it
  chief.advance_all_tenants  beat every 5 min: approved proposals not started / held by the daily cap, and waiting ones
                             whose re-check time has come (e.g. a template Meta has not decided yet)

Detection, proposals and explanations never act. Only execute_proposal does, and only for a proposal an owner approved.
"""

from __future__ import annotations

import structlog
from celery import shared_task

from app.core.database import SessionLocal, set_tenant_context
from app.models.tenant import Tenant

log = structlog.get_logger()


@shared_task(name="chief.detect_all_tenants")
def detect_all_tenants(cadence: str = "urgent") -> dict:
    from app.services.chief import settings as s

    queued = 0
    db = SessionLocal()
    try:
        for tenant in db.query(Tenant).all():
            if s.get(tenant).enabled:
                detect_tenant.delay(tenant.id, cadence)
                queued += 1
    finally:
        db.close()
    return {"queued": queued}


@shared_task(name="chief.detect_tenant")
def detect_tenant(tenant_id: str, cadence: str = "urgent") -> dict:
    from app.services.chief import findings
    from app.services.chief import settings as s

    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        tenant = db.query(Tenant).filter_by(id=tenant_id).first()
        if tenant is None:
            return {"status": "no_tenant"}
        out = findings.run(db, tenant, cadence)
        db.commit()
        cfg = s.get(tenant)
        if cfg.enabled and not cfg.paused:  # the kill switch stops new proposals too
            from app.services.chief import approvals, plans

            new = plans.propose_for_tenant(db, tenant)
            db.commit()
            out["proposed"] = len(new)
            asking = [p for p in new if p.status == "awaiting_approval"]
            if asking:
                approvals.notify_new(db, tenant, asking)
                db.commit()
            for p in new:  # autopilot (E4): the owner's standing OK, internal drafts only
                if p.status == "approved":
                    execute_proposal.delay(tenant_id, p.id)
        if out["open"] and not cfg.paused:
            explain_tenant.delay(tenant_id)
        return out
    except Exception:
        db.rollback()
        log.exception("chief_detect_failed", tenant_id=tenant_id, cadence=cadence)
        raise
    finally:
        db.close()


@shared_task(name="chief.explain_tenant")
def explain_tenant(tenant_id: str) -> dict:
    from app.services.chief import explain

    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        tenant = db.query(Tenant).filter_by(id=tenant_id).first()
        if tenant is None:
            return {"status": "no_tenant"}
        out = explain.explain_tenant(db, tenant)
        db.commit()
        return out
    finally:
        db.close()


@shared_task(name="chief.execute_proposal")
def execute_proposal(tenant_id: str, proposal_id: str) -> dict:
    from app.models.chief import ChiefProposal
    from app.services.chief import executor

    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        tenant = db.query(Tenant).filter_by(id=tenant_id).first()
        p = db.query(ChiefProposal).filter_by(id=proposal_id, tenant_id=tenant_id).first()
        if tenant is None or p is None:
            return {"status": "not_found"}
        return {"status": executor.run(db, tenant, p)}
    except Exception:
        db.rollback()
        log.exception("chief_execute_failed", tenant_id=tenant_id, proposal_id=proposal_id)
        raise
    finally:
        db.close()


@shared_task(name="chief.advance_all_tenants")
def advance_all_tenants() -> dict:
    from app.services.chief import executor
    from app.services.chief import settings as s

    queued = 0
    db = SessionLocal()
    try:
        for tenant in db.query(Tenant).all():
            cfg = s.get(tenant)
            if not cfg.enabled or cfg.paused:
                continue
            set_tenant_context(db, tenant.id)
            for p in executor.due(db, tenant.id):
                execute_proposal.delay(tenant.id, p.id)
                queued += 1
    finally:
        db.close()
    return {"queued": queued}


@shared_task(name="chief.outcomes_all_tenants")
def outcomes_all_tenants() -> dict:
    from app.services.chief import outcomes
    from app.services.chief import settings as s

    checked = 0
    db = SessionLocal()
    try:
        for tenant in db.query(Tenant).all():
            if not s.get(tenant).enabled:
                continue
            set_tenant_context(db, tenant.id)
            try:
                checked += outcomes.check_tenant(db, tenant)["checked"]
                db.commit()
            except Exception:  # noqa: BLE001 -- one workspace never stops the others
                db.rollback()
                log.exception("chief_outcomes_failed", tenant_id=tenant.id)
    finally:
        db.close()
    return {"checked": checked}
