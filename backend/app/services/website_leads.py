"""A website visitor becomes a person and a lead: identity through identity_service (phone = a usable lead signal),
consent rows with proof (DPDP), and one open website lead per person (a second enquiry or booking attempt within 30
days joins it instead of adding a Leads card). Mirrors platform_lead_service, but per tenant."""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.models.inquiry import Inquiry, InquirySource, InquiryStage
from app.models.pipeline_stage import PipelineStage

NOTICE_TEXT_HASH_LEN = 64


def _now() -> datetime:
    return datetime.now(timezone.utc)


def resolve_guest(db: Session, tenant_id: str, *, name: str, phone: str, email: Optional[str]) -> str:
    from app.services import identity_service
    from app.services.phone_identity import normalize, region_for_tenant

    e164 = normalize(phone, region_for_tenant(db, tenant_id))
    if not e164:
        raise ValueError("invalid_phone")
    guest_id, _created = identity_service.resolve_gid(db, tenant_id, signal_type="phone", value=e164,
                                                      source="website", guest_fields={"name": name.strip()[:120]})
    if email:
        identity_service.add_signal(db, tenant_id=tenant_id, guest_id=guest_id, signal_type="email",
                                    value=email.strip().lower(), source="website")
    return guest_id


def write_consents(db: Session, tenant_id: str, guest_id: str, *, marketing: bool, notice_version: str,
                   ip_hash: Optional[str], user_agent: Optional[str], host: str, ref: str) -> None:
    from app.models.consent import Consent

    base = dict(tenant_id=tenant_id, guest_id=guest_id, channel="web_form", granted=True, source="web_form",
                recorded_at=_now().isoformat(), proof_ip=ip_hash, proof_user_agent=(user_agent or "")[:300] or None,
                proof_source=f"website/{host}", notice_version=notice_version, notice_text_hash=None,
                consent_payload={"ref": ref, "marketing_opt_in": marketing})
    db.add(Consent(id=str(uuid.uuid4()), scope="profiling", **base))
    if marketing:
        db.add(Consent(id=str(uuid.uuid4()), scope="marketing", **base))


def upsert_inquiry(db: Session, tenant_id: str, guest_id: str, *, summary: str, property_id: Optional[str] = None,
                   check_in: Optional[str] = None, check_out: Optional[str] = None, adults: Optional[int] = None,
                   children: Optional[int] = None, fields: Optional[dict] = None) -> str:
    """Return the person's open website lead from the last 30 days, updated, or a new one at the entry stage."""
    from app.services import inquiry_service
    from app.services.lead_auto_create import resolve_entry_stage_id

    closed_ids = [s.id for s in db.query(PipelineStage.id).filter(
        PipelineStage.tenant_id == tenant_id,
        (PipelineStage.is_closed_won.is_(True)) | (PipelineStage.is_closed_lost.is_(True))).all()]
    q = db.query(Inquiry).filter(Inquiry.tenant_id == tenant_id, Inquiry.guest_id == guest_id,
                                 Inquiry.source == InquirySource.WEBSITE,
                                 Inquiry.created_at >= _now() - timedelta(days=30))
    if closed_ids:
        q = q.filter((Inquiry.stage_id.is_(None)) | (~Inquiry.stage_id.in_(closed_ids)))
    inquiry = q.order_by(Inquiry.created_at.desc()).first()
    extra = dict(fields or {})
    if inquiry is not None:
        merged = dict(inquiry.custom_fields or {})
        merged.update({k: v for k, v in extra.items() if v is not None})
        inquiry.custom_fields = merged
        inquiry.special_requests = ((inquiry.special_requests or "") + "\n\n" + summary).strip()[:8000]
        for attr, val in (("property_id", property_id), ("check_in", check_in), ("check_out", check_out),
                          ("adults", adults), ("children", children)):
            if val is not None:
                setattr(inquiry, attr, val)
        db.flush()
        return inquiry.id
    stage_id = resolve_entry_stage_id(db, tenant_id, is_collab=False, has_phone=True)
    inquiry = Inquiry(
        id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest_id, stage=InquiryStage.NEW,
        stage_id=stage_id or inquiry_service._stage_id_for(db, tenant_id, InquiryStage.NEW),
        source=InquirySource.WEBSITE, special_requests=summary[:8000], custom_fields=extra,
        property_id=property_id, check_in=check_in, check_out=check_out, adults=adults, children=children,
    )
    db.add(inquiry)
    db.flush()
    from app.services.lead_assignment_service import assign_new_lead
    assign_new_lead(db, inquiry)
    return inquiry.id


def enquiry(db: Session, tenant_id: str, site_id: str, host: str, body, *, ip_hash: Optional[str],
            user_agent: Optional[str]) -> dict:
    """A contact-form enquiry. The honeypot answers like a success so bots learn nothing."""
    if body.website:
        return {"status": "received"}
    guest_id = resolve_guest(db, tenant_id, name=body.name, phone=body.phone, email=body.email)
    write_consents(db, tenant_id, guest_id, marketing=body.consent.marketing, notice_version=body.consent.notice_version,
                   ip_hash=ip_hash, user_agent=user_agent, host=host, ref="enquiry")
    lines = ["Website enquiry"]
    if body.check_in and body.check_out:
        lines.append(f"Dates: {body.check_in.isoformat()} to {body.check_out.isoformat()}")
    if body.adults:
        lines.append(f"Guests: {body.adults}")
    if body.message:
        lines.append(body.message.strip())
    inquiry_id = upsert_inquiry(
        db, tenant_id, guest_id, summary="\n".join(lines), property_id=body.property_id,
        check_in=body.check_in.isoformat() if body.check_in else None,
        check_out=body.check_out.isoformat() if body.check_out else None, adults=body.adults,
        fields={"website_form": "enquiry", "website_site_id": site_id, "website_path": body.path,
                "utm": {k: str(v)[:100] for k, v in (body.utm or {}).items() if k.startswith("utm_")} or None},
    )
    append_audit(db, tenant_id=tenant_id, action="website.enquiry_received", target_type="inquiry",
                 target_id=inquiry_id, payload={"site_id": site_id, "path": body.path})
    return {"status": "received", "inquiry_id": inquiry_id}
