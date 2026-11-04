"""Google reviews on the HAIP website (website phase 5). Reuses marketing_guest_reviews: Google Business Profile reviews
arrive there hourly (marketing_reviews.sync_tenant; "Import now" queues it at once). A review shows on the website only
after a PERSON records how the guest agreed to share it (`consent_note/by/at`, the same columns the review -> post flow
writes), first name only, with its source and month (website_bindings._reviews). Taking consent back hides it again.
Both are audited. The site's star average still counts every rated review (honest aggregate, website_seo).
"""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.models.marketing import MarketingGuestReview
from app.services.website_service import WebsiteError


def listing(db: Session, tenant_id: str, limit: int = 100) -> list[dict]:
    rows = (
        db.query(MarketingGuestReview)
        .filter(MarketingGuestReview.tenant_id == tenant_id)
        .order_by(MarketingGuestReview.reviewed_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id,
            "source": r.source,
            "reviewer": r.reviewer,
            "rating": r.rating,
            "comment": r.comment,
            "reviewed_at": r.reviewed_at,
            "shown": bool(r.consent_at and (r.rating or 0) >= 4 and (r.comment or "").strip()),
            "consent_note": r.consent_note,
        }
        for r in rows
    ]


def _get(db: Session, tenant_id: str, review_id: str) -> MarketingGuestReview:
    r = db.query(MarketingGuestReview).filter_by(id=review_id, tenant_id=tenant_id).first()
    if r is None:
        raise WebsiteError(404, "not_found", "No such review.")
    return r


def set_consent(
    db: Session, tenant_id: str, review_id: str, *, note: str | None, actor_id: str
) -> MarketingGuestReview:
    """note = how the guest agreed (e.g. "Asked on WhatsApp 3 Nov, said yes"); None = take it off the website."""
    r = _get(db, tenant_id, review_id)
    if note:
        r.consent_note, r.consent_by, r.consent_at = note.strip()[:300], actor_id, datetime.now(UTC)
        action = "website.review_consent_recorded"
    else:
        r.consent_at = None
        action = "website.review_consent_withdrawn"
    append_audit(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_id,
        action=action,
        target_type="marketing_guest_review",
        target_id=r.id,
        payload={"note": r.consent_note if note else None, "source": r.source},
    )
    db.flush()
    return r
