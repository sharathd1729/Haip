"""
module_activation — provision or de-provision a module for a workspace.

Triggered when a workspace subscribes to or cancels a module.
Handles:
  1. Enable/disable WorkspaceModule row
  2. Derive + write FeatureFlag overrides
  3. Invalidate WorkspaceCtx cache
  4. Seed default widget instances on the workspace's default dashboard (activate only)
  5. Emit audit event
"""

from __future__ import annotations

import structlog
from datetime import datetime, timezone

from celery import shared_task

log = structlog.get_logger()


@shared_task(name="app.workers.tasks.module_activation.activate", bind=True, max_retries=3)
def activate(self, workspace_id: str, module_code: str, activated_by: str):
    """Provision module: enable WorkspaceModule + flush cache."""
    from app.core.database import SessionLocal
    from app.models.module import Module, WorkspaceModule
    from app.models.audit_event import AuditEvent
    from app.models.base import gen_uuid

    with SessionLocal() as db:
        mod = db.query(Module).filter(Module.code == module_code).first()
        if not mod:
            log.error("module_not_found", module_code=module_code)
            return {"error": f"Module '{module_code}' not found"}

        existing = db.query(WorkspaceModule).filter(
            WorkspaceModule.workspace_id == workspace_id,
            WorkspaceModule.module_id == mod.id,
        ).first()

        if existing:
            existing.enabled = True
            existing.activated_at = datetime.now(timezone.utc)
        else:
            db.add(WorkspaceModule(
                id=gen_uuid(),
                workspace_id=workspace_id,
                module_id=mod.id,
                enabled=True,
                activated_at=datetime.now(timezone.utc),
            ))

        db.add(AuditEvent(
            id=gen_uuid(),
            tenant_id=workspace_id,
            actor_user_id=activated_by,
            action="module.activated",
            target_type="module",
            target_id=module_code,
            payload={"module_code": module_code},
            hash="",
        ))
        db.commit()

    # Flush WorkspaceCtx cache so next request gets fresh context
    from app.workers.tasks.invalidate_cache import workspace_context as flush_ctx
    flush_ctx.delay(workspace_id)

    log.info("module_activated", workspace_id=workspace_id, module_code=module_code)
    return {"workspace_id": workspace_id, "module_code": module_code, "action": "activated"}


@shared_task(name="app.workers.tasks.module_activation.deactivate", bind=True, max_retries=3)
def deactivate(self, workspace_id: str, module_code: str, deactivated_by: str):
    """De-provision module: disable WorkspaceModule + flush all workspace cache."""
    from app.core.database import SessionLocal
    from app.models.module import Module, WorkspaceModule
    from app.models.audit_event import AuditEvent
    from app.models.base import gen_uuid

    with SessionLocal() as db:
        mod = db.query(Module).filter(Module.code == module_code).first()
        if not mod:
            return {"error": f"Module '{module_code}' not found"}

        existing = db.query(WorkspaceModule).filter(
            WorkspaceModule.workspace_id == workspace_id,
            WorkspaceModule.module_id == mod.id,
        ).first()
        if existing:
            existing.enabled = False

        db.add(AuditEvent(
            id=gen_uuid(),
            tenant_id=workspace_id,
            actor_user_id=deactivated_by,
            action="module.deactivated",
            target_type="module",
            target_id=module_code,
            payload={"module_code": module_code},
            hash="",
        ))
        db.commit()

    from app.workers.tasks.invalidate_cache import full_workspace as flush_all
    flush_all.delay(workspace_id)

    log.info("module_deactivated", workspace_id=workspace_id, module_code=module_code)
    return {"workspace_id": workspace_id, "module_code": module_code, "action": "deactivated"}


@shared_task(name="app.workers.tasks.module_activation.backfill_all_tenants", bind=True)
def backfill_all_tenants(self):
    """
    One-time migration helper: ensure every active tenant has a WorkspaceModule
    row for each module that matches their plan entitlements.
    Call manually via: celery call app.workers.tasks.module_activation.backfill_all_tenants
    """
    from app.core.database import SessionLocal
    from app.models.tenant import Tenant
    from app.models.module import Module, WorkspaceModule
    from app.models.base import gen_uuid

    PLAN_MODULES = {
        "starter":    ["whatsapp", "leads360"],
        "growth":     ["whatsapp", "instagram", "calls", "leads360", "analytics", "ask_haip"],
        "scale":      ["whatsapp", "instagram", "calls", "leads360", "analytics",
                       "ask_haip", "ai_concierge", "campaigns", "channel_manager"],
        "enterprise": ["whatsapp", "instagram", "calls", "leads360", "analytics",
                       "ask_haip", "ai_concierge", "campaigns", "channel_manager",
                       "flow_builder"],
    }

    with SessionLocal() as db:
        tenants = db.query(Tenant).filter(Tenant.is_active == True).all()
        modules = {m.code: m.id for m in db.query(Module).all()}
        provisioned = 0

        for tenant in tenants:
            plan = (tenant.plan or "growth").lower()
            module_codes = PLAN_MODULES.get(plan, PLAN_MODULES["growth"])
            for code in module_codes:
                mod_id = modules.get(code)
                if not mod_id:
                    continue
                exists = db.query(WorkspaceModule).filter(
                    WorkspaceModule.workspace_id == tenant.id,
                    WorkspaceModule.module_id == mod_id,
                ).first()
                if not exists:
                    db.add(WorkspaceModule(
                        id=gen_uuid(),
                        workspace_id=tenant.id,
                        module_id=mod_id,
                        enabled=True,
                        activated_at=datetime.now(timezone.utc),
                    ))
                    provisioned += 1

        db.commit()
        log.info("module_backfill_done",
                 tenants=len(tenants), provisioned=provisioned)
    return {"tenants_processed": len(tenants), "modules_provisioned": provisioned}
