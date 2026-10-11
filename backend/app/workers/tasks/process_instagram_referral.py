"""Record an Instagram ad referral that Meta sent as its own event.

For a Click-to-Instagram-Direct ad Meta can deliver the referral (which ad the person came from) separately
from the message, so the DM worker never sees it next to the text. Without this, most ad chats had no ad on
them: in a 30-day window HAIP held an ad for 4 of 481 Instagram leads.

If the chat already exists the ad is recorded and linked to its lead now. If the referral arrives first, it is
held for a few hours and the DM worker picks it up when the first message creates the chat.
"""
import logging

from sqlalchemy.orm import Session

from app.core.database import SessionLocal, set_tenant_context
from app.models.conversation import ChannelType, Conversation
from app.models.integration import INSTAGRAM_INBOUND_STATUSES, Integration
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=2, default_retry_delay=30, name="process_instagram_referral")
def process_instagram_referral(self, payload: dict) -> dict:
    """payload: ig_account_id, sender_id (the person), referral (Meta's object), timestamp."""
    from app.services import attribution_service
    from app.services.identity_service import resolve_gid

    db: Session = SessionLocal()
    try:
        ig_account_id, sender_id = payload.get("ig_account_id", ""), payload.get("sender_id", "")
        referral = payload.get("referral") or {}
        if not sender_id or not referral:
            return {"status": "skipped", "reason": "no sender or referral"}

        integration = next(
            (c for c in db.query(Integration).filter(
                Integration.kind == "instagram", Integration.status.in_(INSTAGRAM_INBOUND_STATUSES)).all()
             if (c.config or {}).get("instagram_business_account_id") == ig_account_id), None)
        if not integration:
            logger.error("Instagram referral received but no matching integration for account %s", ig_account_id)
            return {"status": "skipped", "reason": "no integration"}
        tenant_id = integration.tenant_id
        set_tenant_context(db, tenant_id)

        guest_id, _ = resolve_gid(
            db=db, tenant_id=tenant_id, signal_type="instagram_user_id", value=sender_id, source="instagram",
            guest_fields={"name": f"IG User {sender_id[-6:]}"},
        )
        conversation = (
            db.query(Conversation)
            .filter_by(tenant_id=tenant_id, guest_id=guest_id, is_open=True)
            .filter(Conversation.channel == ChannelType.INSTAGRAM)
            .first()
        )
        if conversation is None:
            attribution_service.stash_referral(tenant_id, sender_id, referral)
            return {"status": "stashed"}

        f = attribution_service.referral_fields(referral)
        attribution_service.record_referral_attribution(
            db, tenant_id, conversation_id=conversation.id, guest_id=guest_id, destination_channel="instagram",
            ad_id=f["ad_id"], source_type=f["source_type"], source_url=f["source_url"], headline=f["headline"],
            media_type=f["media_type"], raw_referral=referral,
        )
        if conversation.inquiry_id:
            attribution_service.link_attribution_to_inquiry(db, tenant_id, conversation.id, conversation.inquiry_id)
        db.commit()
        return {"status": "recorded", "ad_id": f["ad_id"]}
    except Exception as exc:
        db.rollback()
        logger.warning("ig_referral_capture_failed: %s", exc)
        raise self.retry(exc=exc)
    finally:
        db.close()
