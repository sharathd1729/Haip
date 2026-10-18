"""HAIP's own website leads: store durably, then copy into HAIP's sales workspace as a Leads360 lead.

Order matters (the old forms lost every lead):
  1. the submission is committed to ``platform_leads`` FIRST, under its browser-generated ``submission_id`` (a retry
     returns the same row, so one form fill is one lead);
  2. only then the lead is copied into the workspace named by ``PLATFORM_LEADS_TENANT_SLUG``
     (the tenant is NEVER taken from the request): guest via ``identity_service`` (phone first, else email), a web_form
     consent row, and a WEBSITE inquiry. A failure there marks the row ``failed`` and keeps it;
  3. the workspace owners are notified by Celery (``platform_leads.notify``), never inline.

A honeypot hit is stored as spam (so it can be reviewed) and goes no further. A known guest's record is never changed
from a public form: an existing guest only gets the new inquiry, not the visitor's other details.
PII is never logged: log lines carry the lead id and kind only.
"""
from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.platform_lead import PlatformLead

log = structlog.get_logger()

# The privacy notice shown next to the form's checkbox, by version. The frontend shows the same words
# (frontend/src/lib/publicLeads.ts NOTICE_TEXT); change both together and add a new version, never edit one in place.
NOTICE_TEXTS: dict[str, str] = {
    "web-v1": (
        "HAIP will use your name, phone number and email to reply to this request and follow up about HAIP. "
        "We keep it for up to 24 months and never sell it. You can ask us to correct or delete it at any time "
        "on our grievance page."
    ),
}
# Per visitor (hashed IP), counted in the database so it holds when Redis is down (the middleware limit fails open).
MAX_PER_IP_PER_HOUR = 10
_KIND_LABEL = {"demo": "Demo request", "contact": "Contact message", "assessment": "Property assessment"}


class RateLimited(Exception):
    """Too many submissions from one visitor in the last hour."""


def notice_hash(version: str) -> Optional[str]:
    text = NOTICE_TEXTS.get(version)
    return hashlib.sha256(text.encode()).hexdigest() if text else None


def ip_hash(ip: Optional[str]) -> Optional[str]:
    """Keyed hash: lets us count submissions per visitor without storing the address."""
    if not ip:
        return None
    return hmac.new(settings.SECRET_KEY.encode(), f"platform-lead-ip:{ip}".encode(), hashlib.sha256).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def find_by_submission(db: Session, submission_id: str) -> Optional[PlatformLead]:
    return db.query(PlatformLead).filter_by(submission_id=submission_id).first()


def _check_rate(db: Session, ip_h: Optional[str]) -> None:
    if not ip_h:
        return
    since = _now() - timedelta(hours=1)
    recent = db.query(PlatformLead).filter(PlatformLead.ip_hash == ip_h, PlatformLead.created_at >= since).count()
    if recent >= MAX_PER_IP_PER_HOUR:
        raise RateLimited()


def submit(db: Session, body, *, ip: Optional[str], user_agent: Optional[str],
           assessment_snapshot: Optional[dict] = None) -> tuple[PlatformLead, bool]:
    """Store one website submission. Returns (lead, duplicate). Raises RateLimited, or ValueError for an unknown notice."""
    existing = find_by_submission(db, body.submission_id)
    if existing is not None:
        return existing, True
    text_hash = notice_hash(body.notice_version)
    if text_hash is None:
        raise ValueError("Unknown privacy notice version.")
    ip_h = ip_hash(ip)
    _check_rate(db, ip_h)

    spam = bool((body.website or "").strip())
    details = body.details.model_dump(exclude_none=True) if hasattr(body.details, "model_dump") else dict(body.details or {})
    lead = PlatformLead(
        id=str(uuid.uuid4()), kind=body.kind, submission_id=body.submission_id,
        name=body.name, email=(str(body.email).lower() if body.email else None), phone=body.phone,
        company=body.company or None, message=body.message or None, details=details,
        assessment=assessment_snapshot,
        consent_given=True, marketing_opt_in=bool(body.marketing_opt_in),
        notice_version=body.notice_version, notice_text_hash=text_hash, consent_at=_now(),
        ip_hash=ip_h, user_agent=(user_agent or "")[:255] or None,
        is_spam=spam, routing_status="spam" if spam else "stored",
    )
    db.add(lead)
    try:
        db.commit()
    except IntegrityError:
        # Two copies of the same submission arrived at once; the unique submission_id let one win. Use it.
        db.rollback()
        winner = find_by_submission(db, body.submission_id)
        if winner is None:
            raise
        return winner, True

    if spam:
        log.warning("platform_lead_honeypot", lead_id=lead.id, kind=lead.kind)
        return lead, False
    log.info("platform_lead_stored", lead_id=lead.id, kind=lead.kind)
    route_to_workspace(db, lead)
    _queue_notify(lead.id)
    return lead, False


def sales_workspace(db: Session):
    """HAIP's own sales workspace (from config only), or None."""
    slug = (settings.PLATFORM_LEADS_TENANT_SLUG or "").strip()
    if not slug:
        return None
    from app.models.tenant import Tenant
    return db.query(Tenant).filter_by(slug=slug).first()


def route_to_workspace(db: Session, lead: PlatformLead) -> None:
    """Copy the lead into the sales workspace as guest + consent + inquiry. Never raises; the row says what happened."""
    tenant = sales_workspace(db)
    if tenant is None:
        lead.routing_status = "not_configured"
        lead.routing_error = "PLATFORM_LEADS_TENANT_SLUG is not set" if not settings.PLATFORM_LEADS_TENANT_SLUG \
            else "PLATFORM_LEADS_TENANT_SLUG names no workspace"
        db.commit()
        log.error("platform_lead_unrouted", lead_id=lead.id, kind=lead.kind, reason=lead.routing_error)
        return
    lead_id, tenant_id = lead.id, tenant.id
    try:
        from app.core.database import set_tenant_context
        set_tenant_context(db, tenant_id)
        # No savepoint: lead assignment commits on its own. The lead row is already committed, so a rollback
        # below only undoes this copy, never the stored submission.
        guest_id, inquiry_id = _create_inquiry(db, tenant.id, lead)
        from app.core.audit import append_audit
        append_audit(db, tenant_id=tenant.id, action="platform_lead.routed", target_type="inquiry",
                     target_id=inquiry_id, payload={"platform_lead_id": lead.id, "kind": lead.kind})
        lead.routing_status = "routed"
        lead.routing_error = None
        lead.workspace_tenant_id = tenant.id
        lead.workspace_guest_id = guest_id
        lead.workspace_inquiry_id = inquiry_id
        db.commit()
        log.info("platform_lead_routed", lead_id=lead.id, kind=lead.kind, tenant_id=tenant.id, inquiry_id=inquiry_id)
    except Exception as exc:  # noqa: BLE001 -- the lead is already stored; record why the copy failed
        db.rollback()
        row = db.query(PlatformLead).filter_by(id=lead_id).first()
        if row is not None:
            row.routing_status = "failed"
            row.routing_error = f"{type(exc).__name__}: {exc}"[:300]
            row.workspace_tenant_id = tenant_id
            db.commit()
        log.error("platform_lead_route_failed", lead_id=lead_id, tenant_id=tenant_id, error=type(exc).__name__)


def _summary_text(lead: PlatformLead) -> str:
    parts = [_KIND_LABEL.get(lead.kind, lead.kind) + " from the HAIP website"]
    if lead.company:
        parts.append(f"Company: {lead.company}")
    for key, value in (lead.details or {}).items():
        parts.append(f"{key.capitalize()}: {value}")
    if lead.message:
        parts.append(lead.message)
    return "\n".join(parts)[:4000]


def _write_consents(db: Session, tenant_id: str, guest_id: str, lead: PlatformLead) -> None:
    from app.models.consent import Consent
    base = dict(
        tenant_id=tenant_id, guest_id=guest_id, channel="web_form", granted=True, source="web_form",
        recorded_at=(lead.consent_at or _now()).isoformat(), proof_ip=lead.ip_hash,
        proof_user_agent=lead.user_agent, proof_source=f"haip-website/{lead.kind}",
        notice_version=lead.notice_version, notice_text_hash=lead.notice_text_hash,
        consent_payload={"platform_lead_id": lead.id, "marketing_opt_in": lead.marketing_opt_in},
    )
    db.add(Consent(id=str(uuid.uuid4()), scope="profiling", **base))
    if lead.marketing_opt_in:
        db.add(Consent(id=str(uuid.uuid4()), scope="marketing", **base))


def _create_inquiry(db: Session, tenant_id: str, lead: PlatformLead) -> tuple[str, str]:
    from app.models.inquiry import Inquiry, InquirySource, InquiryStage
    from app.models.pipeline_stage import PipelineStage
    from app.services import identity_service, inquiry_service
    from app.services.lead_auto_create import resolve_entry_stage_id

    signal_type, value = ("phone", lead.phone) if lead.phone else ("email", lead.email)
    guest_id, created = identity_service.resolve_gid(
        db, tenant_id, signal_type=signal_type, value=value, source="web_form",
        guest_fields={"name": lead.name},
    )
    if created and lead.phone and lead.email:
        identity_service.add_signal(db, tenant_id=tenant_id, guest_id=guest_id, signal_type="email",
                                    value=lead.email, source="web_form")
    _write_consents(db, tenant_id, guest_id, lead)

    # One open website lead per person: a second form fill within 30 days joins it instead of adding a card.
    closed_ids = [s.id for s in db.query(PipelineStage.id).filter(
        PipelineStage.tenant_id == tenant_id,
        (PipelineStage.is_closed_won.is_(True)) | (PipelineStage.is_closed_lost.is_(True))).all()]
    q = db.query(Inquiry).filter(Inquiry.tenant_id == tenant_id, Inquiry.guest_id == guest_id,
                                 Inquiry.source == InquirySource.WEBSITE,
                                 Inquiry.created_at >= _now() - timedelta(days=30))
    if closed_ids:
        q = q.filter((Inquiry.stage_id.is_(None)) | (~Inquiry.stage_id.in_(closed_ids)))
    inquiry = q.order_by(Inquiry.created_at.desc()).first()
    if inquiry is not None:
        fields = dict(inquiry.custom_fields or {})
        fields["platform_lead_ids"] = list(fields.get("platform_lead_ids") or []) + [lead.id]
        inquiry.custom_fields = fields
        inquiry.special_requests = ((inquiry.special_requests or "") + "\n\n" + _summary_text(lead)).strip()[:8000]
        db.flush()
        return guest_id, inquiry.id

    stage_id = resolve_entry_stage_id(db, tenant_id, is_collab=False, has_phone=bool(lead.phone))
    inquiry = Inquiry(
        id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest_id,
        stage=InquiryStage.NEW,
        stage_id=stage_id or inquiry_service._stage_id_for(db, tenant_id, InquiryStage.NEW),
        source=InquirySource.WEBSITE, special_requests=_summary_text(lead),
        custom_fields={"platform_lead_ids": [lead.id], "website_form": lead.kind,
                       **({"company": lead.company} if lead.company else {})},
    )
    db.add(inquiry)
    db.flush()
    from app.services.lead_assignment_service import assign_new_lead
    assign_new_lead(db, inquiry)
    return guest_id, inquiry.id


def _queue_notify(lead_id: str) -> None:
    try:
        from app.workers.tasks.platform_leads import notify_owners
        notify_owners.delay(lead_id)
    except Exception as exc:  # noqa: BLE001 -- the lead is stored and visible in the list; only the alert is late
        log.error("platform_lead_notify_dispatch_failed", lead_id=lead_id, error=type(exc).__name__)


def notify(db: Session, lead_id: str) -> dict:
    """Push + email the sales workspace's owners about one lead. Once per lead (notified_at)."""
    import asyncio

    from app.models.user import User, UserRole
    from app.services import email_service
    from app.services.push_service import send_to_tenant

    lead = db.query(PlatformLead).filter_by(id=lead_id).first()
    if lead is None or lead.is_spam or lead.notified_at is not None:
        return {"status": "skipped"}
    if not lead.workspace_tenant_id:
        return {"status": "unrouted"}
    owners = (db.query(User).filter(User.tenant_id == lead.workspace_tenant_id, User.role == UserRole.OWNER,
                                    User.is_active.is_(True), User.is_deleted.is_(False)).all())
    label = _KIND_LABEL.get(lead.kind, lead.kind)
    url = f"/dashboard/leads/{lead.workspace_inquiry_id}" if lead.workspace_inquiry_id else "/dashboard/settings/platform-leads"
    who = lead.name + (f" ({lead.company})" if lead.company else "")
    sent = 0
    for owner in owners:
        send_to_tenant(db, lead.workspace_tenant_id, title=f"New website lead: {label}", body=who, url=url,
                       tag="platform-lead", user_id=owner.id)
        if owner.email:
            ok = asyncio.run(email_service.send_platform_lead_email(
                to_email=owner.email, kind_label=label, name=lead.name, company=lead.company,
                phone=lead.phone, email=lead.email, link=f"{settings.FRONTEND_URL.rstrip('/')}{url}"))
            sent += 1 if ok else 0
    lead.notified_at = _now()
    db.commit()
    log.info("platform_lead_notified", lead_id=lead.id, owners=len(owners), emails_sent=sent)
    return {"status": "notified", "owners": len(owners), "emails_sent": sent}


def list_leads(db: Session, *, kind: Optional[str] = None, include_spam: bool = False, limit: int = 100) -> list[PlatformLead]:
    q = db.query(PlatformLead)
    if kind:
        q = q.filter(PlatformLead.kind == kind)
    if not include_spam:
        q = q.filter(PlatformLead.is_spam.is_(False))
    return q.order_by(PlatformLead.created_at.desc()).limit(max(1, min(limit, 500))).all()
