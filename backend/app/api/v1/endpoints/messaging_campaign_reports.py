"""
WhatsApp campaign report + audience import.

  GET  /messaging/campaigns/{id}/report          summary, why messages failed, per-guest list
  GET  /messaging/campaigns/{id}/recipients.csv  the same list as a file
  POST /messaging/subscribers/import             bulk CSV import into the subscriber list
"""

import csv
import io
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.v1.deps import require_roles
from app.api.v1.endpoints.messaging import WACampaign, WATemplate
from app.core.audit import append_audit
from app.core.database import get_db
from app.models.user import User, UserRole
from app.services import wa_campaign_delivery as delivery
from app.services import wa_subscriber_import as importer

router = APIRouter(prefix="/messaging", tags=["messaging"])
log = structlog.get_logger()

_MARKETERS = (UserRole.OWNER, UserRole.MANAGER, UserRole.MARKETING)
_STATUS_FILTER = "^(queued|sent|delivered|read|failed)$"


def _campaign_or_404(db: Session, tenant_id: str, campaign_id: str) -> WACampaign:
    campaign = db.query(WACampaign).filter_by(id=campaign_id, tenant_id=tenant_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign


def _rate(part: int, whole: int) -> Optional[float]:
    return round(part / whole * 100, 1) if whole else None


@router.get("/campaigns/{campaign_id}/report")
def campaign_report(
    campaign_id: str,
    status: Optional[str] = Query(default=None, pattern=_STATUS_FILTER),
    search: Optional[str] = Query(default=None, max_length=60),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(require_roles(*_MARKETERS)),
    db: Session = Depends(get_db),
):
    campaign = _campaign_or_404(db, current_user.tenant_id, campaign_id)
    tmpl = db.query(WATemplate).filter_by(id=campaign.template_id, tenant_id=current_user.tenant_id).first() if campaign.template_id else None

    counts = delivery.cumulative(delivery.status_counts(db, campaign_id))
    query = delivery.recipients_query(db, current_user.tenant_id, campaign_id, status, search)
    total_matching = query.count()
    rows = query.order_by(delivery.Recipient.created_at.asc(), delivery.Recipient.id.asc()).offset(offset).limit(limit).all()

    attempted = counts["sent"] + counts["failed"]
    return {
        "campaign": {
            "id": campaign.id, "name": campaign.name, "status": campaign.status.value,
            "template_name": tmpl.name if tmpl else None, "scheduled_at": campaign.scheduled_at,
        },
        "summary": {
            **counts,
            "delivery_rate": _rate(counts["delivered"], counts["sent"]),
            "read_rate": _rate(counts["read"], counts["delivered"]),
            "failure_rate": _rate(counts["failed"], attempted),
        },
        "failures": delivery.failure_breakdown(db, campaign_id),
        "recipients": [delivery.recipient_dict(r) for r in rows],
        "total_matching": total_matching,
        "limit": limit,
        "offset": offset,
    }


def _safe(value):
    """A guest-typed name must not run as a spreadsheet formula."""
    if isinstance(value, str) and value and value[0] in "=+-@\t\r" and not value.startswith("+91"):
        return "'" + value
    return value


@router.get("/campaigns/{campaign_id}/recipients.csv")
def campaign_recipients_csv(
    campaign_id: str,
    status: Optional[str] = Query(default=None, pattern=_STATUS_FILTER),
    current_user: User = Depends(require_roles(*_MARKETERS)),
    db: Session = Depends(get_db),
):
    campaign = _campaign_or_404(db, current_user.tenant_id, campaign_id)
    rows = delivery.recipients_query(db, current_user.tenant_id, campaign_id, status).order_by(
        delivery.Recipient.created_at.asc(), delivery.Recipient.id.asc()
    ).limit(100_000).all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Phone", "Name", "Status", "Reason", "Sent at", "Delivered at", "Read at"])
    for r in rows:
        d = delivery.recipient_dict(r)
        writer.writerow([_safe(x) if x is not None else "" for x in (
            d["phone"], d["name"], d["status"], d["error_reason"], d["sent_at"], d["delivered_at"], d["read_at"],
        )])

    # Phone numbers leave the system: on the audit trail, like report downloads.
    append_audit(
        db, tenant_id=current_user.tenant_id, action="campaigns.recipients_export",
        actor_user_id=current_user.id, target_type="wa_campaign", target_id=campaign_id,
        payload={"status_filter": status, "row_count": len(rows)},
    )
    db.commit()

    safe_name = "".join(ch if ch.isalnum() else "-" for ch in campaign.name)[:40].strip("-") or "campaign"
    return StreamingResponse(
        iter([buf.getvalue().encode("utf-8-sig")]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}-recipients.csv"'},
    )


@router.get("/subscribers/stats")
def subscriber_stats(
    current_user: User = Depends(require_roles(*_MARKETERS)),
    db: Session = Depends(get_db),
):
    """Real totals for the Subscribers page (the list it shows is paged)."""
    from sqlalchemy import func
    from app.api.v1.endpoints.messaging import WASubscriber
    rows = (
        db.query(WASubscriber.opted_in, func.count(WASubscriber.id))
        .filter(WASubscriber.tenant_id == current_user.tenant_id)
        .group_by(WASubscriber.opted_in).all()
    )
    opted_in = sum(n for flag, n in rows if flag)
    opted_out = sum(n for flag, n in rows if not flag)
    return {"total": opted_in + opted_out, "opted_in": opted_in, "opted_out": opted_out}


@router.get("/subscribers/tags")
def subscriber_tags(
    current_user: User = Depends(require_roles(*_MARKETERS)),
    db: Session = Depends(get_db),
):
    """Every tag in use among opted-in subscribers with how many people carry
    it -- the choices for a campaign's audience."""
    from app.api.v1.endpoints.messaging import WASubscriber
    counts: dict[str, int] = {}
    for (tags,) in db.query(WASubscriber.tags).filter_by(tenant_id=current_user.tenant_id, opted_in=True):
        for tag in dict.fromkeys(t for t in (tags or []) if isinstance(t, str) and t.strip()):
            counts[tag] = counts.get(tag, 0) + 1
    return [{"tag": t, "count": n} for t, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower()))]


def _mask(phone: str) -> str:
    return f"{phone[:5]}••••{phone[-3:]}" if len(phone) > 8 else phone


@router.post("/campaigns/audience-count")
def audience_count(
    body: dict,
    current_user: User = Depends(require_roles(*_MARKETERS)),
    db: Session = Depends(get_db),
):
    """How many people a campaign with this audience would go to."""
    af = body.get("audience_filter") or {}
    if not isinstance(af, dict):
        raise HTTPException(status_code=400, detail="audience_filter must be an object")
    return {"count": len(delivery.audience_members(db, current_user.tenant_id, af))}


@router.get("/campaigns/audience-options")
def audience_options(
    current_user: User = Depends(require_roles(*_MARKETERS)),
    db: Session = Depends(get_db),
):
    """The choices for a CRM-leads audience -- stages, sources, owners, and
    ready-made segments -- with how many people (and how many with a phone
    number) are behind each."""
    from app.services import wa_lead_audience
    return wa_lead_audience.options(db, current_user.tenant_id)


@router.post("/campaigns/audience-preview")
def audience_preview(
    body: dict,
    current_user: User = Depends(require_roles(*_MARKETERS)),
    db: Session = Depends(get_db),
):
    """Who a CRM-leads audience would reach right now, and who is left out and
    why. Nothing is sent."""
    from app.services import wa_lead_audience
    af = body.get("audience_filter") or {}
    if not isinstance(af, dict):
        raise HTTPException(status_code=400, detail="audience_filter must be an object")
    result = wa_lead_audience.resolve(db, current_user.tenant_id, {**af, "type": "leads"})
    heat = {"hot": 0, "warm": 0, "cold": 0}
    for m in result.members:
        heat[m.heat or "cold"] += 1
    return {
        **result.breakdown(),
        "heat": heat,
        "sample": [
            {"name": m.name, "phone": _mask(m.phone), "heat": m.heat, "why": m.why[:3]}
            for m in result.members[:8]
        ],
    }


@router.post("/subscribers/import")
def import_subscribers(
    file: UploadFile = File(...),
    consent: bool = Form(default=False),
    tag: Optional[str] = Form(default=None),
    current_user: User = Depends(require_roles(*_MARKETERS)),
    db: Session = Depends(get_db),
):
    """Add people from a CSV. The person importing must confirm these contacts
    have agreed to hear from the business on WhatsApp -- marketing templates to
    people who haven't is how numbers get blocked. Someone who already opted
    out is never opted back in by a file."""
    if not consent:
        raise HTTPException(
            status_code=400,
            detail="Confirm these contacts have agreed to receive WhatsApp messages from you before importing.",
        )
    content = file.file.read(importer.MAX_BYTES + 1)
    try:
        rows = importer.parse_csv(content)
    except importer.ImportError_ as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    result = importer.import_rows(db, current_user.tenant_id, rows, batch_tag=tag)
    append_audit(
        db, tenant_id=current_user.tenant_id, action="subscribers.import",
        actor_user_id=current_user.id, target_type="wa_subscribers", target_id=None,
        payload={
            "rows": result.total_rows, "added": result.added, "updated": result.updated,
            "opted_out_skipped": result.opted_out_skipped, "invalid": len(result.invalid),
            "tag": (tag or "")[:importer.MAX_TAG_LEN] or None, "consent_confirmed": True,
        },
    )
    db.commit()
    log.info("wa_subscribers_imported", tenant_id=current_user.tenant_id, added=result.added, rows=result.total_rows)
    return {
        "total_rows": result.total_rows,
        "added": result.added,
        "updated": result.updated,
        "opted_out_skipped": result.opted_out_skipped,
        "duplicates_in_file": result.duplicates_in_file,
        "invalid_count": len(result.invalid),
        "invalid": result.invalid,
        "opted_out": result.opted_out,
    }
