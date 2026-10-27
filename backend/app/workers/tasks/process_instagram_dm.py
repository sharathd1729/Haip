"""
Celery task: process an inbound Instagram DM.

Flow (M2 — Instagram Identity Flow):
  receive webhook → resolve_or_create(instagram_user_id)
                 → find/create conversation → store message
                 → trigger concierge_draft

Identity is now managed by the progressive identity graph.
A guest is created with just their Instagram ID — phone is not required.
Later, when they share a WhatsApp number or book, enrich_guest() links the signals.
"""

from __future__ import annotations
import logging
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.core.database import SessionLocal
from app.models.integration import INSTAGRAM_INBOUND_STATUSES, Integration
from app.models.guest import Guest
from app.models.conversation import Conversation, Message, ChannelType, MessageDirection
from app.core.encryption import decrypt_credentials
from app.adapters.instagram.meta_graph import validate_media_url
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60, name="process_instagram_dm")
def process_instagram_dm(self, payload: dict) -> dict:
    """
    payload keys:
      ig_account_id  — the business Instagram account ID
      sender_id      — Instagram-scoped user ID of the sender
      message_id     — Meta message ID (mid)
      text           — message text (may be empty for media)
      attachments    — list of attachment objects
      timestamp      — Unix ms timestamp
    """
    from app.core.database import set_tenant_context
    db: Session = SessionLocal()
    try:
        ig_account_id = payload.get("ig_account_id", "")
        sender_id = payload.get("sender_id", "")
        mid = payload.get("message_id", "")
        text = payload.get("text", "")
        attachments = payload.get("attachments", [])
        referral = payload.get("referral") or None  # T0.3: ad-attribution, if present

        if not sender_id:
            return {"status": "skipped", "reason": "no sender_id"}

        # ── Find the tenant's Instagram integration by ig_account_id ───────
        # Multiple tenants may each have an active Instagram integration, so
        # matching must be scoped to the account this webhook was for, not
        # just "the first active one" (which picks an arbitrary tenant).
        candidates = (
            db.query(Integration)
            .filter(Integration.kind == "instagram", Integration.status.in_(INSTAGRAM_INBOUND_STATUSES))
            .all()
        )
        integration = next(
            (c for c in candidates if (c.config or {}).get("instagram_business_account_id") == ig_account_id),
            None,
        )
        if not integration:
            # error, not warning: this drops a customer's message for good --
            # Meta already got its 200 and will not send it again.
            logger.error("Instagram DM received but no matching integration for account %s", ig_account_id)
            return {"status": "skipped", "reason": "no integration"}

        tenant_id = integration.tenant_id
        set_tenant_context(db, tenant_id)

        # ── Dedup by message_id ────────────────────────────────────────────
        if mid:
            existing = db.query(Message).filter_by(channel_message_id=mid).first()
            if existing:
                return {"status": "duplicate", "message_id": mid}

        # ── Resolve or create guest via Identity Resolution Engine (M2) ─────
        # T0.4: use the placeholder name immediately rather than blocking this
        # latency-critical path on a Graph API round trip for every new guest.
        # backfill_instagram_guest_name (below) fetches the real name as a
        # fire-and-forget follow-up after the message is already visible.
        display_name = f"IG User {sender_id[-6:]}"

        from app.services.identity_service import resolve_gid
        guest_id, created = resolve_gid(
            db=db,
            tenant_id=tenant_id,
            signal_type="instagram_user_id",
            value=sender_id,
            source="instagram",
            guest_fields={"name": display_name},
        )
        guest = db.query(Guest).filter_by(id=guest_id, tenant_id=tenant_id).first()
        if created:
            logger.info("Created new guest from Instagram DM: %s (%s)", guest_id, display_name)
        else:
            logger.debug("Resolved existing guest from Instagram DM: %s", guest_id)

        # T0.4: fire-and-forget real-name fetch. Dispatched whenever the guest
        # still has a placeholder name (new guest, or an earlier message whose
        # own backfill attempt failed) -- never blocks this task.
        if guest and guest.name and guest.name.startswith("IG User "):
            backfill_instagram_guest_name.apply_async(
                kwargs={"tenant_id": tenant_id, "guest_id": guest_id, "sender_id": sender_id},
                countdown=1,
            )

        # ── Find or create open conversation ────────────────────────────────
        channel_val = ChannelType.INSTAGRAM if hasattr(ChannelType, "INSTAGRAM") else "instagram"
        conversation = (
            db.query(Conversation)
            .filter_by(tenant_id=tenant_id, guest_id=guest_id, is_open=True)
            .filter(Conversation.channel == channel_val)
            .first()
        )

        is_new_conversation = conversation is None
        if not conversation:
            conversation = Conversation(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                guest_id=guest_id,
                channel=channel_val,
                is_open=True,
                # T3.2: inherit the tenant's Instagram AI default rather than
                # a hardcoded "shadow" for every tenant regardless of risk tolerance.
                ai_mode=integration.tenant.ig_ai_mode_default if integration.tenant else "shadow",
            )
            # Real bug, reported live: two webhook deliveries for the same
            # guest arriving milliseconds apart both saw "no open
            # conversation" above and both tried to create one -- the
            # guest's messages then split across two "twin" conversations,
            # only one of which ever got linked to an inquiry, so
            # generate_ai_summary.py silently missed whatever the guest
            # said in the orphan twin (in the real case that broke, their
            # travel dates and guest count -- never showed up anywhere in
            # Leads360). Migration 099 makes this a hard DB constraint
            # (partial unique index on tenant_id+guest_id+channel where
            # is_open) instead of a race-prone check-then-insert.
            #
            # A SAVEPOINT (begin_nested), not a full db.rollback(), so
            # losing this race only undoes the conversation insert -- not
            # set_tenant_context()'s `SET LOCAL app.tenant_id` from earlier
            # in this task (a full rollback would also revert that, since
            # it's scoped to the outer transaction, and every query after
            # would then silently return nothing under RLS) or the guest
            # row (already committed by identity_service by this point).
            try:
                with db.begin_nested():
                    db.add(conversation)
                    db.flush()
            except IntegrityError:
                conversation = (
                    db.query(Conversation)
                    .filter_by(tenant_id=tenant_id, guest_id=guest_id, is_open=True)
                    .filter(Conversation.channel == channel_val)
                    .first()
                )
                is_new_conversation = False
                if conversation is None:
                    raise

        # An ad referral that arrived before this chat existed was held; it belongs to this first message.
        if not referral and is_new_conversation:
            from app.services.attribution_service import take_stashed_referral
            referral = take_stashed_referral(tenant_id, sender_id)

        # ── Store message ──────────────────────────────────────────────────
        body = text or ""
        media_url = None
        media_type = None
        shared_post_url = None
        # Post/story-share attachments (type "ig_post"/"share"/"story_mention") link
        # to a permalink, not a fetchable CDN media file -- validate_media_url()
        # correctly rejects these (they're not on Meta's CDN host allowlist), but
        # the permalink itself is still useful to show, just as an outbound link
        # rather than fetched/rendered media. Only genuine CDN attachment URLs are
        # ever treated as media_url.
        if attachments:
            att = attachments[0]
            att_type = att.get("type", "media")
            att_url = (att.get("payload") or {}).get("url", "")
            if not body:
                body = f"[{att_type}]"  # fallback caption, not a replacement for the URL
            if att_url and validate_media_url(att_url):
                media_url = att_url
                media_type = att_type
            elif att_url:
                if att_type in ("ig_post", "share", "story_mention"):
                    shared_post_url = att_url
                else:
                    logger.warning(
                        "Instagram attachment URL failed SSRF allowlist check, dropping media_url: host=%s",
                        urlparse(att_url).netloc,
                    )

        channel_metadata = {}
        if referral:
            channel_metadata["referral"] = referral
        if shared_post_url:
            channel_metadata["shared_post_url"] = shared_post_url

        # Meta's own event time, when it was supplied. Live webhooks carry
        # it within a second of now, so this is a no-op there -- but a
        # backfill replays messages that are days old, and without this they
        # all landed stamped with the import time. The inbox then showed a
        # week of history as having arrived "1m" ago, in the wrong order.
        occurred_at = None
        raw_ts = payload.get("timestamp")
        if raw_ts:
            try:
                occurred_at = datetime.fromtimestamp(int(raw_ts) / 1000, tz=timezone.utc)
            except (TypeError, ValueError, OSError, OverflowError):
                occurred_at = None

        message = Message(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            channel_message_id=mid or str(uuid.uuid4()),
            direction=MessageDirection.INBOUND,
            channel=channel_val,
            body=body,
            media_url=media_url,
            media_type=media_type,
            channel_status="received",
            channel_metadata=channel_metadata or None,
            **({"created_at": occurred_at} if occurred_at else {}),
        )
        db.add(message)
        # Only ever move the conversation's clock forward: importing an old
        # message must not drag a thread back down the inbox below newer
        # traffic that arrived while the backfill was running.
        new_last = (occurred_at or datetime.now(timezone.utc)).isoformat()
        if not conversation.last_message_at or str(conversation.last_message_at) < new_last:
            conversation.last_message_at = new_last
        db.flush()
        db.commit()

        logger.info(
            "Stored Instagram DM: message=%s guest=%s conversation=%s",
            message.id, guest_id, conversation.id,
        )

        # Capture a phone number the guest types in chat -- Instagram has no inherent phone identity like WhatsApp does, so this is
        # the only source for it. Runs on every inbound message, not just the first (a guest often shares the number several
        # messages in). chat_phone_capture does the whole job: the strict matcher (a number next to dates is still found; dates,
        # prices and pincodes are not phones), the signal via identity_service (the person becomes a lead), the default-entry ->
        # valid-lead stage move, and closing an open "declined phone number" task. Do NOT set conversation.human_owned here: it
        # used to, and permanently downgraded the thread to shadow mode the moment a phone appeared.
        if body and not body.startswith("["):
            try:
                from app.services import chat_phone_capture
                if chat_phone_capture.capture_from_text(db, tenant_id, guest_id, body, source="message_text", conversation=conversation):
                    db.commit()
            except Exception as exc:
                db.rollback()
                logger.warning("ig_phone_signal_capture_failed: %s", exc)

        # Ad attribution -- captured once, on the thread's first inbound DM
        # (Dashboard Metrics Plan Phase 1). `referral` is only ever present
        # on that first message; a repeat message on an existing
        # conversation never carries one.
        if referral:
            try:
                from app.services.attribution_service import record_referral_attribution
                record_referral_attribution(
                    db, tenant_id,
                    conversation_id=conversation.id,
                    guest_id=guest_id,
                    destination_channel="instagram",
                    ad_id=referral.get("ad_id"),
                    source_type="ad" if referral.get("ad_id") else "post",
                    headline=referral.get("headline") or (referral.get("ads_context_data") or {}).get("ad_title"),
                    media_type=referral.get("media_type"),
                    raw_referral=referral,
                    first_message_at=message.created_at,
                )
                db.commit()
            except Exception as exc:
                db.rollback()
                logger.warning("ig_attribution_capture_failed: %s", exc)

        # Leads360 chat auto-create. Real bug, reported live: this used to
        # gate on is_new_conversation, which is True exactly once -- on the
        # literal first message of the conversation. A guest whose opener
        # is a shared post/reel (body="[ig_post]", excluded by the
        # startswith("[") check below) got is_new_conversation=True on that
        # excluded message and False on every message after, so no inquiry
        # was ever created for them -- not then, not on their next real
        # message, not ever. Confirmed live: a guest opened with [ig_post],
        # then asked "How much do your services cost?" two seconds later,
        # and inquiry_id stayed NULL for the entire conversation -- every
        # field on the Guest 360 panel that depends on inquiry_id (AI
        # summary, trip details, lead stage, everything) silently never
        # populated, and the frontend query itself is disabled without an
        # inquiry_id, so there wasn't even an error to notice. Gating on
        # "no inquiry yet" instead of "first message" means this correctly
        # retries on every subsequent message until one has real text, and
        # still only ever creates one (conversation.inquiry_id gets set
        # the first time this fires, so it never fires again after).
        # A guest writing again to a Lost lead brings it back to Active (lead_reopen).
        from app.services import lead_reopen
        if lead_reopen.on_contact(db, tenant_id, guest_id, trigger="instagram_message", by_guest=True):
            db.commit()

        if not conversation.inquiry_id and body and not body.startswith("["):
            try:
                from app.services.inquiry_service import get_or_create_from_chat
                from app.models.inquiry import InquirySource
                lead_inquiry = get_or_create_from_chat(
                    db, tenant_id, guest_id, source=InquirySource.META_IG.value, message_text=body,
                )
                conversation.inquiry_id = lead_inquiry.id
                if referral:
                    from app.services.attribution_service import link_attribution_to_inquiry
                    link_attribution_to_inquiry(db, tenant_id, conversation.id, lead_inquiry.id)
                db.commit()
            except Exception as exc:
                db.rollback()
                logger.warning("ig_lead_auto_create_failed: %s", exc)

        # Notify SSE subscribers so the inbox updates without a page refresh
        try:
            import redis as _redis
            from app.core.config import settings as _settings
            _r = _redis.Redis.from_url(_settings.REDIS_URL, decode_responses=True, socket_connect_timeout=2)
            import json as _json
            _r.publish(f"sse:{tenant_id}", _json.dumps({
                "event": "message_received",
                "conversation_id": conversation.id,
                "channel": "instagram",
                "guest_name": guest.name if guest else display_name,
                "preview": body[:120],
            }))
            _r.close()
        except Exception as _sse_exc:
            logger.warning("sse_publish_failed: %s", _sse_exc)

        # Push notification (for staff with PWA on mobile / browser closed).
        # WhatsApp/wrap_up/automation_engine inbound events already did this
        # (see whatsapp.py) -- Instagram DMs never did, so a new IG message
        # showed up in the in-app bell (SSE, only reaches an already-open
        # tab) but never reached a phone with the app backgrounded/closed.
        try:
            from app.services.push_service import send_to_tenant
            guest_name = guest.name if guest else display_name
            send_to_tenant(
                db=db,
                tenant_id=tenant_id,
                title="New Instagram DM",
                body=f"{guest_name}: {(body or '')[:80]}",
                url=f"/dashboard/inbox?id={conversation.id}",
                tag="haip-message",
                user_id=conversation.assigned_to or None,
            )
        except Exception as _push_exc:
            logger.warning("push_send_failed: %s", _push_exc)

        # ── T2/T3: keyword-match first; AI concierge draft is fallback only ──
        # Priority 3 requirement: auto-reply always wins when both would
        # otherwise fire. AI is strictly for messages no rule matched.
        matched_rule = None
        if body and body.strip() and not body.startswith("["):
            from app.services.ig_keyword_match import find_matching_rule
            matched_rule = find_matching_rule(db, tenant_id, "ig_dm_received", body)

        # Phase 2.5 agent-accountability instrumentation
        # (HAIP_Agent_Analytics_Dashboard_Plan_1.md #2.5.2): record which of
        # this decision's branches fired, since find_matching_rule() returns
        # None with no side effect by design and an unmatched, un-drafted
        # message otherwise leaves no trace it was ever missed. Only the 3
        # outcomes this if/elif can actually produce are used here --
        # "matched_ai_drafted" from the plan doc's naming has no reachable
        # branch in this mutually-exclusive if/elif (a matched rule always
        # takes the auto-reply path, never the AI-draft one).
        # Backfill guard: importing historical DMs must not fire the
        # auto-reply/concierge path. Replaying three days of messages would
        # otherwise blast quick-replies and AI drafts at guests for
        # conversations that have long since moved on -- and for anything
        # older than 24h Meta refuses the send anyway, so it produces
        # nothing but noise and failed rows. Webhooks never set this, so
        # live behaviour is unchanged.
        if payload.get("suppress_automation"):
            message.automation_outcome = "backfilled_no_automation"
        elif matched_rule:
            from app.services.ig_quick_reply import dispatch_quick_reply
            dispatch_quick_reply(
                db, tenant_id, matched_rule,
                recipient_id=sender_id, guest_id=guest_id, conversation_id=conversation.id,
            )
            message.automation_outcome = "matched_auto_replied"
        elif body and body.strip() and not body.startswith("[") and conversation.ai_mode != "off":
            message.automation_outcome = "no_match_ai_drafted"
            try:
                from app.workers.tasks.concierge_draft import concierge_draft
                from app.services.concierge_service import mark_pending_draft, DEBOUNCE_SECONDS
                # Message-burst debounce -- see whatsapp.py's identical
                # wiring and concierge_service.py for the reasoning.
                mark_pending_draft(tenant_id, conversation.id, message.id)
                concierge_draft.apply_async(
                    kwargs={
                        "message_id": message.id,
                        "conversation_id": conversation.id,
                        "tenant_id": tenant_id,
                    },
                    countdown=DEBOUNCE_SECONDS,
                )
            except Exception as exc:
                logger.error("Failed to queue Instagram concierge draft: %s", exc)
        else:
            message.automation_outcome = "no_match_no_response"
        db.commit()

        return {
            "status": "ok",
            "message_id": message.id,
            "guest_id": guest_id,
            "conversation_id": conversation.id,
        }

    except Exception as exc:
        logger.error("process_instagram_dm failed: %s", exc)
        db.rollback()
        raise self.retry(exc=exc)
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60, name="process_instagram_echo")
def process_instagram_echo(self, payload: dict) -> dict:
    """
    Store a message the business account sent to a guest via a client other
    than HAIP (e.g. an agent replying directly in the native Instagram app).
    Meta calls this an "echo" webhook event. Mirrors process_instagram_dm's
    identity/conversation lookup but writes an OUTBOUND message and never
    triggers AI drafts or keyword auto-replies (this is our own reply, not
    something to respond to).

    payload keys:
      ig_account_id  — the business Instagram account ID
      recipient_id   — Instagram-scoped user ID of the guest who was messaged
      message_id     — Meta message ID (mid)
      text           — message text (may be empty for media)
      attachments    — list of attachment objects
      timestamp      — Unix ms timestamp
    """
    from app.core.database import set_tenant_context
    db: Session = SessionLocal()
    try:
        ig_account_id = payload.get("ig_account_id", "")
        recipient_id = payload.get("recipient_id", "")
        mid = payload.get("message_id", "")
        text = payload.get("text", "")
        attachments = payload.get("attachments", [])

        if not recipient_id:
            return {"status": "skipped", "reason": "no recipient_id"}

        candidates = (
            db.query(Integration)
            .filter(Integration.kind == "instagram", Integration.status.in_(INSTAGRAM_INBOUND_STATUSES))
            .all()
        )
        integration = next(
            (c for c in candidates if (c.config or {}).get("instagram_business_account_id") == ig_account_id),
            None,
        )
        if not integration:
            logger.error("Instagram echo received but no matching integration for account %s", ig_account_id)
            return {"status": "skipped", "reason": "no integration"}

        tenant_id = integration.tenant_id
        set_tenant_context(db, tenant_id)

        if mid:
            existing = db.query(Message).filter_by(channel_message_id=mid).first()
            if existing:
                return {"status": "duplicate", "message_id": mid}

        # Guests are only ever created from an inbound signal -- an echo to a
        # guest HAIP has never seen (e.g. a cold outbound DM sent manually)
        # has nowhere to file the message, so skip rather than fabricate a
        # guest record with no other identity signal.
        from app.services.identity_service import resolve_gid
        guest_id, created = resolve_gid(
            db=db,
            tenant_id=tenant_id,
            signal_type="instagram_user_id",
            value=recipient_id,
            source="instagram",
            guest_fields={"name": f"IG User {recipient_id[-6:]}"},
        )
        guest = db.query(Guest).filter_by(id=guest_id, tenant_id=tenant_id).first()

        channel_val = ChannelType.INSTAGRAM if hasattr(ChannelType, "INSTAGRAM") else "instagram"
        conversation = (
            db.query(Conversation)
            .filter_by(tenant_id=tenant_id, guest_id=guest_id, is_open=True)
            .filter(Conversation.channel == channel_val)
            .first()
        )
        if not conversation:
            conversation = Conversation(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                guest_id=guest_id,
                channel=channel_val,
                is_open=True,
                ai_mode=integration.tenant.ig_ai_mode_default if integration.tenant else "shadow",
            )
            db.add(conversation)
            db.flush()

        body = text or ""
        media_url = None
        media_type = None
        if attachments:
            att = attachments[0]
            att_type = att.get("type", "media")
            att_url = (att.get("payload") or {}).get("url", "")
            if not body:
                body = f"[{att_type}]"
            if att_url and validate_media_url(att_url):
                media_url = att_url
                media_type = att_type

        message = Message(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            channel_message_id=mid or str(uuid.uuid4()),
            direction=MessageDirection.OUTBOUND,
            channel=channel_val,
            body=body,
            media_url=media_url,
            media_type=media_type,
            channel_status="sent",
            sender_name="Instagram app",
        )
        db.add(message)
        conversation.last_message_at = datetime.now(timezone.utc).isoformat()
        db.flush()
        db.commit()

        logger.info(
            "Stored Instagram echo (sent outside HAIP): message=%s guest=%s conversation=%s",
            message.id, guest_id, conversation.id,
        )

        try:
            import redis as _redis
            from app.core.config import settings as _settings
            _r = _redis.Redis.from_url(_settings.REDIS_URL, decode_responses=True, socket_connect_timeout=2)
            import json as _json
            _r.publish(f"sse:{tenant_id}", _json.dumps({
                "event": "message_received",
                "conversation_id": conversation.id,
                "channel": "instagram",
                "guest_name": guest.name if guest else recipient_id,
                "preview": body[:120],
            }))
            _r.close()
        except Exception as _sse_exc:
            logger.warning("sse_publish_failed: %s", _sse_exc)

        return {
            "status": "ok",
            "message_id": message.id,
            "guest_id": guest_id,
            "conversation_id": conversation.id,
        }

    except Exception as exc:
        logger.error("process_instagram_echo failed: %s", exc)
        db.rollback()
        raise self.retry(exc=exc)
    finally:
        db.close()


@celery_app.task(bind=True, name="backfill_instagram_guest_name", max_retries=3, default_retry_delay=30)
def backfill_instagram_guest_name(self, tenant_id: str, guest_id: str, sender_id: str) -> dict:
    """
    T0.4: fire-and-forget follow-up to process_instagram_dm. Fetches the
    guest's real Instagram display name via the Graph API and updates it if
    it's still the "IG User ######" placeholder -- run off the critical path
    so new-guest messages never wait on this external round trip.
    """
    from app.core.database import set_tenant_context
    db: Session = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        guest = db.query(Guest).filter_by(id=guest_id, tenant_id=tenant_id).first()
        if not guest or not guest.name or not guest.name.startswith("IG User "):
            return {"status": "skipped", "reason": "guest already named or not found"}

        integration = db.query(Integration).filter_by(
            tenant_id=tenant_id, kind="instagram", status="active"
        ).first()
        if not integration:
            return {"status": "skipped", "reason": "no integration"}

        creds = decrypt_credentials(integration.credentials_kms_blob)
        access_token = creds.get("access_token", "")
        account_id = (integration.config or {}).get("instagram_business_account_id", "")
        if not access_token or not account_id:
            return {"status": "skipped", "reason": "missing credentials"}

        from app.adapters.instagram.meta_graph import InstagramGraphAdapter
        ig_adapter = InstagramGraphAdapter(access_token=access_token, ig_account_id=account_id)
        profile = ig_adapter.get_user_profile(sender_id)
        real_name = profile.get("name", "")
        username = profile.get("username", "")

        # Meta's Send API user-profile endpoint no longer reliably returns
        # "name" for most business integrations (platform restriction) --
        # "username" (the @handle) is still returned and is a real
        # improvement over the numeric placeholder even when "name" is empty.
        resolved_name = real_name or (f"@{username}" if username else "")

        if resolved_name and not resolved_name.startswith("IG User "):
            guest.name = resolved_name
            db.commit()
            logger.info("Backfilled Instagram guest name: %s -> %s", guest_id, resolved_name)
            return {"status": "ok", "guest_id": guest_id, "name": resolved_name}

        return {"status": "no_name_available"}
    except Exception as exc:
        # 4xx from the Graph API (permission denied, user not found, etc.) will
        # never succeed on retry -- give up permanently on those. Anything else
        # (timeouts, 5xx, network errors) is transient -- retry with backoff.
        #
        # One exception to the status-code rule: Meta wraps IGApiException
        # code 230 ("User consent is required to access user profile") in an
        # HTTP 500, even though it's a permanent per-user privacy restriction,
        # not a server error -- some Instagram users simply haven't granted
        # the consent Meta requires before any app can fetch their profile,
        # and no amount of retrying changes that. Confirmed live: this fires
        # for most Instagram senders, while a plain "5xx, retry" treatment
        # would burn all 5 retries (with backoff) on every single one of them,
        # forever, since this task re-fires on every new message from a guest
        # still on the placeholder name.
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)
        is_consent_required = False
        if response is not None:
            try:
                is_consent_required = response.json().get("error", {}).get("code") == 230
            except Exception:
                pass

        if is_consent_required or (status_code and 400 <= status_code < 500):
            logger.warning(
                "backfill_instagram_guest_name permanently failed for guest %s: %s", guest_id, exc
            )
            return {"status": "error", "reason": str(exc)}
        logger.warning(
            "backfill_instagram_guest_name failed for guest %s (will retry): %s", guest_id, exc
        )
        raise self.retry(exc=exc)
    finally:
        db.close()
