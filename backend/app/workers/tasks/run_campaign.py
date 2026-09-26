"""
Campaign runner — batch-sends a WhatsApp template to opted-in subscribers.

Flow:
  launch_campaign (endpoint) → run_campaign.apply_async()
    → builds recipient list from WASubscriber (audience_filter applied)
    → sends template via MetaCloudAdapter for each recipient
    → updates campaign counters in real-time
    → sets campaign.status = COMPLETED when done

Audience filter schema (stored in WACampaign.audience_filter JSON):
  {}                          → all opted-in subscribers
  {"tags": ["vip", "june"]}   → subscribers who have ANY of these tags
  {"source": ["import"]}      → subscribers acquired via that source
  {"tags": [...], "source": [...]}  → AND between tags and source
"""
import asyncio
from datetime import datetime, timezone
from app.workers.celery_app import celery_app
from app.core.database import SessionLocal
import structlog

log = structlog.get_logger()

BATCH_SIZE = 50          # recipients per sub-batch (respects Meta rate limits)
INTER_BATCH_DELAY = 1.0  # seconds between batches


@celery_app.task(bind=True, max_retries=2, default_retry_delay=60, name="tasks.run_campaign")
def run_campaign(self, campaign_id: str, tenant_id: str):
    """Execute a WhatsApp campaign broadcast."""
    from app.core.database import set_tenant_context
    from app.api.v1.endpoints.messaging import (
        WACampaign, WASubscriber, WATemplate, CampaignStatus,
    )
    from app.models.integration import Integration
    from app.adapters.whatsapp.meta_cloud import get_wa_adapter

    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)

        campaign = db.query(WACampaign).filter_by(
            id=campaign_id, tenant_id=tenant_id,
        ).first()
        if not campaign:
            log.error("run_campaign_not_found", campaign_id=campaign_id)
            return

        if campaign.status not in (CampaignStatus.RUNNING,):
            log.warning(
                "run_campaign_wrong_status",
                campaign_id=campaign_id,
                status=campaign.status,
            )
            return

        # ── Resolve template ───────────────────────────────────────────────
        template = db.query(WATemplate).filter_by(
            id=campaign.template_id, tenant_id=tenant_id,
        ).first()
        if not template:
            log.error("run_campaign_template_missing", campaign_id=campaign_id)
            _set_status(db, campaign, CampaignStatus.PAUSED)
            return

        if not template.meta_template_id:
            log.error(
                "run_campaign_template_not_submitted",
                template_id=template.id,
            )
            _set_status(db, campaign, CampaignStatus.PAUSED)
            return

        # ── Resolve WA integration credentials ────────────────────────────
        integration = db.query(Integration).filter_by(
            tenant_id=tenant_id, kind="whatsapp_meta", status="active",
        ).first()
        if not integration:
            integration = db.query(Integration).filter_by(
                tenant_id=tenant_id, kind="whatsapp", status="active",
            ).first()
        if not integration:
            log.error("run_campaign_no_integration", tenant_id=tenant_id)
            _set_status(db, campaign, CampaignStatus.PAUSED)
            return

        from app.workers.tasks.whatsapp import _get_wa_access_token
        phone_number_id = (integration.config or {}).get("phone_number_id")
        access_token = _get_wa_access_token(db, tenant_id)
        if not phone_number_id or not access_token:
            log.error("run_campaign_missing_creds", tenant_id=tenant_id)
            _set_status(db, campaign, CampaignStatus.PAUSED)
            return

        adapter = get_wa_adapter(phone_number_id, access_token)

        # ── Build recipient list ───────────────────────────────────────────
        from app.services import wa_campaign_delivery as _audience
        recipients = _audience.audience_members(db, tenant_id, campaign.audience_filter)

        total = len(recipients)
        log.info(
            "run_campaign_recipients",
            campaign_id=campaign_id,
            count=total,
        )

        if total == 0:
            log.warning("run_campaign_empty_audience", campaign_id=campaign_id)
            _set_status(db, campaign, CampaignStatus.COMPLETED)
            return

        # ── Header media + variable mapping ────────────────────────────────
        # One link for the whole run (good for 24h, so a long campaign can't
        # outlive it): the header file is the same for every recipient.
        from app.services import wa_template_service as wts
        header_link = None
        if template.header_media_key:
            from app.services.media_storage import get_presigned_media_url
            header_link = get_presigned_media_url(template.header_media_key, expires_in=86400)
            if not header_link:
                log.error("run_campaign_header_media_unavailable", campaign_id=campaign_id)
                _set_status(db, campaign, CampaignStatus.PAUSED)
                return
        variable_map = campaign.variable_map or {}
        still_unmapped = wts.unmapped_variables(template.components, variable_map)
        if still_unmapped:
            log.error("run_campaign_unmapped_variables", campaign_id=campaign_id, missing=still_unmapped)
            _set_status(db, campaign, CampaignStatus.PAUSED)
            return

        # ── Send in batches ────────────────────────────────────────────────
        from app.services import wa_campaign_delivery as delivery
        from app.models.wa_campaign_recipient import WACampaignRecipient

        # Rows from an earlier attempt at this campaign (a retried task, or a
        # paused campaign launched again): anyone Meta already accepted is
        # skipped, so a retry can never message the same guest twice.
        existing = {
            r.phone: r for r in db.query(WACampaignRecipient).filter_by(campaign_id=campaign_id)
        }
        # Several failures in a row that point at the account or the template
        # (expired token, locked account, paused template) will fail for
        # everyone. Stop and let a person fix it instead of failing the whole list.
        MAX_CONSECUTIVE_FATAL = 5
        consecutive_fatal = 0
        skipped = 0

        def _run_async(coro):
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(coro)
            finally:
                loop.close()

        for i in range(0, total, BATCH_SIZE):
            batch = recipients[i : i + BATCH_SIZE]
            for sub in batch:
                row = existing.get(sub.phone)
                if row is None:
                    row = delivery.get_or_create_recipient(db, tenant_id, campaign_id, sub)
                    existing[sub.phone] = row
                if delivery.should_skip(row):
                    skipped += 1
                    continue
                try:
                    components = wts.build_send_components(
                        template.components, variable_map, sub, header_media_link=header_link,
                    )
                    response = _run_async(
                        adapter.send_template(
                            to=sub.phone,
                            template_name=template.name,
                            language_code=template.language or "en",
                            components=components,
                        )
                    )
                    delivery.mark_sent(row, response)
                    from app.services import wa_campaign_inbox
                    wa_campaign_inbox.record_send(db, tenant_id, campaign, template, sub, components, response)
                    consecutive_fatal = 0
                except Exception as exc:
                    if isinstance(exc, wts.TemplateError):
                        info = delivery.mark_failed(row, delivery.HAIP_VARIABLE, str(exc))
                    else:
                        code, message = delivery.error_from_exception(exc)
                        info = delivery.mark_failed(row, code, message or delivery.HAIP_SEND)
                    log.warning(
                        "run_campaign_send_failed",
                        phone_token=sub.phone[:4] + "****",
                        code=info.code, group=info.group, error=info.reason,
                    )
                    if info.group in ("account", "template"):
                        consecutive_fatal += 1
                    else:
                        consecutive_fatal = 0

                if consecutive_fatal >= MAX_CONSECUTIVE_FATAL:
                    delivery.refresh_campaign_counters(db, tenant_id, campaign_id)
                    campaign.status = CampaignStatus.PAUSED
                    db.commit()
                    log.error(
                        "run_campaign_paused_on_repeated_failure",
                        campaign_id=campaign_id, code=info.code, reason=info.reason,
                    )
                    return

            # Persist after each batch, counters included
            delivery.refresh_campaign_counters(db, tenant_id, campaign_id)
            db.commit()

            if i + BATCH_SIZE < total:
                import time
                time.sleep(INTER_BATCH_DELAY)

        # ── Finalise ───────────────────────────────────────────────────────
        delivery.refresh_campaign_counters(db, tenant_id, campaign_id)
        campaign.status = CampaignStatus.COMPLETED
        db.commit()

        log.info(
            "run_campaign_completed",
            campaign_id=campaign_id,
            sent=campaign.sent_count,
            failed=campaign.failed_count,
            skipped_already_sent=skipped,
        )

    except Exception as exc:
        log.error("run_campaign_error", campaign_id=campaign_id, error=str(exc))
        raise self.retry(exc=exc)
    finally:
        db.close()


def _set_status(db, campaign, status) -> None:
    campaign.status = status
    db.commit()
