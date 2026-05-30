"""
classify_intent — nightly Celery task that normalizes occasion text
→ intent_tag on inquiries and calls.

Runs nightly at 03:00 IST, only processing records where intent_tag IS NULL.
Uses keyword-based normalization (no LLM cost).
"""

from datetime import date as date_cls
import logging

from sqlalchemy import func
from app.workers.celery_app import celery_app
from app.core.database import SessionLocal, set_tenant_context
from app.models.tenant import Tenant
from app.models.inquiry import Inquiry
from app.models.call import Call
from app.services.intent_classifier import normalize_intent

log = logging.getLogger(__name__)

BATCH_SIZE = 500


@celery_app.task(name="app.workers.tasks.classify_intent.run", bind=True, max_retries=2)
def run(self, tenant_id: str | None = None):
    """
    Normalize intent_tag for all unclassified inquiries + calls.
    If tenant_id is None, processes all active tenants.
    """
    db = SessionLocal()
    try:
        if tenant_id:
            _process_tenant(db, tenant_id)
        else:
            tenants = db.query(Tenant).filter_by(is_active=True).all()
            for t in tenants:
                try:
                    _process_tenant(db, str(t.id))
                except Exception as exc:
                    log.error("classify_intent failed for tenant %s: %s", t.id, exc)
    except Exception as exc:
        log.error("classify_intent task failed: %s", exc)
        raise self.retry(exc=exc, countdown=120)
    finally:
        db.close()


def _process_tenant(db, tenant_id: str) -> None:
    set_tenant_context(db, tenant_id)

    # ── Classify inquiries ────────────────────────────────────────────────────
    inq_batch = db.query(Inquiry).filter(
        Inquiry.tenant_id == tenant_id,
        Inquiry.intent_tag.is_(None),
        Inquiry.occasion.isnot(None),
    ).limit(BATCH_SIZE).all()

    updated_inq = 0
    for inq in inq_batch:
        try:
            nights = None
            weekday = None
            if inq.check_in and inq.check_out:
                try:
                    ci = date_cls.fromisoformat(inq.check_in)
                    co = date_cls.fromisoformat(inq.check_out)
                    nights  = max(0, (co - ci).days)
                    weekday = ci.weekday()
                except Exception:
                    pass
            inq.intent_tag = normalize_intent(inq.occasion, nights, weekday)
            updated_inq += 1
        except Exception as exc:
            log.debug("classify_intent: inquiry %s failed: %s", inq.id, exc)

    # ── Classify calls ────────────────────────────────────────────────────────
    call_batch = db.query(Call).filter(
        Call.tenant_id == tenant_id,
        Call.intent_tag.is_(None),
        Call.occasion.isnot(None),
    ).limit(BATCH_SIZE).all()

    updated_calls = 0
    for call in call_batch:
        try:
            call.intent_tag = normalize_intent(call.occasion)
            updated_calls += 1
        except Exception as exc:
            log.debug("classify_intent: call %s failed: %s", call.id, exc)

    if updated_inq or updated_calls:
        db.commit()
        log.info(
            "classify_intent: tenant=%s inquiries=%d calls=%d",
            tenant_id, updated_inq, updated_calls,
        )
