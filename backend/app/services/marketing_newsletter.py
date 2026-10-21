"""Email newsletters from approved posts (agency M3). Sent through Resend (email_service._send), never automatically.

  * Content: up to MAX_ITEMS approved (or posted) Studio items, in the order chosen, each as its rendered image, its
    headline and the caption's first paragraphs, with one button (the profile's website, else WhatsApp). The HTML is
    built here from the approved text -- no AI -- and escaped.
  * Audience: guests with an email address whose latest marketing consent (any channel) is a grant, minus anyone who
    unsubscribed from email (Consent channel="email", scope="marketing", granted=False). The sender also confirms,
    at every send, that these people agreed to marketing email (DPDP), and that confirmation is audited.
  * Every email has a one-click unsubscribe link (signed token with tenant, guest and newsletter ids, no email in the
    URL) and List-Unsubscribe / List-Unsubscribe-Post headers. Guest addresses are kept out of the logs.
  * Sending: one recipient row per guest (unique), batches of BATCH via Celery `marketing_newsletter.send_batch`.
"""
import base64
import hashlib
import hmac
import html
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.core.config import settings
from app.models.consent import Consent
from app.models.guest import Guest
from app.models.marketing import MarketingContent, MarketingNewsletter, MarketingNewsletterRecipient
from app.models.tenant import Tenant
from app.models.user import User
from app.services import marketing_content_service as content_svc
from app.services.marketing_content_service import MarketingError

log = structlog.get_logger()

MAX_ITEMS = 4
BATCH = 50
IMAGE_DAYS = 7 * 24 * 3600              # presigned image links in the email (S3 allows at most 7 days)
_PLACEHOLDER = "HAIP-UNSUBSCRIBE-LINK"  # rendered once per batch, then replaced with each guest's own link


# ── Audience ────────────────────────────────────────────────────────────────────────────────────────────────────────

def audience(db: Session, tenant_id: str) -> list[Guest]:
    guests = (db.query(Guest).filter(Guest.tenant_id == tenant_id, Guest.email.isnot(None), Guest.email != "")
              .limit(20000).all())
    if not guests:
        return []
    ids = [g.id for g in guests]
    latest: dict[str, Consent] = {}
    email_out: set[str] = set()
    for c in (db.query(Consent).filter(Consent.tenant_id == tenant_id, Consent.scope == "marketing", Consent.guest_id.in_(ids))
              .order_by(Consent.recorded_at.asc())):
        latest[c.guest_id] = c
        if c.channel == "email" and not c.granted:
            email_out.add(c.guest_id)
        elif c.channel == "email" and c.granted:
            email_out.discard(c.guest_id)
    return [g for g in guests if g.id in latest and latest[g.id].granted and g.id not in email_out and "@" in g.email]


# ── Unsubscribe tokens ──────────────────────────────────────────────────────────────────────────────────────────────

def _sig(msg: str) -> str:
    return base64.urlsafe_b64encode(hmac.new(settings.SECRET_KEY.encode(), msg.encode(), hashlib.sha256).digest()[:18]).decode()


def unsubscribe_token(tenant_id: str, guest_id: str, newsletter_id: str) -> str:
    msg = f"{tenant_id}.{guest_id}.{newsletter_id}"
    return base64.urlsafe_b64encode(msg.encode()).decode().rstrip("=") + "." + _sig(msg)


def read_token(token: str) -> Optional[tuple[str, str, str]]:
    try:
        body, sig = token.rsplit(".", 1)
        msg = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)).decode()
    except (ValueError, UnicodeDecodeError):
        return None
    if not hmac.compare_digest(sig, _sig(msg)):
        return None
    parts = msg.split(".")
    return (parts[0], parts[1], parts[2]) if len(parts) == 3 else None


def unsubscribe(db: Session, token: str) -> bool:
    parsed = read_token(token)
    if parsed is None:
        return False
    tenant_id, guest_id, newsletter_id = parsed
    if db.query(Guest.id).filter_by(id=guest_id, tenant_id=tenant_id).first() is None:
        return False
    now = datetime.now(timezone.utc).isoformat()
    db.add(Consent(tenant_id=tenant_id, guest_id=guest_id, channel="email", scope="marketing", granted=False,
                   source="email_unsubscribe", recorded_at=now, withdrawn_at=now, withdrawal_reason="user_link",
                   consent_payload={"newsletter_id": newsletter_id}))
    (db.query(MarketingNewsletterRecipient).filter_by(tenant_id=tenant_id, newsletter_id=newsletter_id, guest_id=guest_id)
     .update({"status": "unsubscribed"}, synchronize_session=False))
    append_audit(db, tenant_id=tenant_id, action="marketing.email.unsubscribed", actor_user_id=None,
                 target_type="guest", target_id=guest_id, payload={"newsletter_id": newsletter_id})
    return True


def unsubscribe_url(token: str) -> str:
    return f"{(settings.API_BASE_URL or '').rstrip('/')}/api/v1/public/email/unsubscribe/{token}"


# ── Compose ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def _items(db: Session, tenant_id: str, content_ids: list[str]) -> list[tuple[MarketingContent, dict]]:
    out = []
    for cid in content_ids:
        item = content_svc.get_item(db, tenant_id, cid)
        if item.status not in ("approved", "scheduled", "published") or not item.approved_version_id:
            raise MarketingError(409, "not_approved", f"“{item.title}” is not approved yet.")
        out.append((item, content_svc.get_version(db, tenant_id, item.approved_version_id).payload))
    return out


def create(db: Session, tenant_id: str, subject: str, intro: Optional[str], content_ids: list[str], actor_id: str) -> MarketingNewsletter:
    subject = (subject or "").strip()
    if not 3 <= len(subject) <= 200:
        raise MarketingError(422, "bad_subject", "The subject needs 3 to 200 characters.")
    ids = list(dict.fromkeys(content_ids))
    if not 1 <= len(ids) <= MAX_ITEMS:
        raise MarketingError(422, "bad_items", f"Choose 1 to {MAX_ITEMS} approved posts.")
    _items(db, tenant_id, ids)
    problems = content_svc.check_text(db, tenant_id, {"caption": f"{subject}\n{intro or ''}"})
    if problems:
        raise MarketingError(422, "text_rejected", "This text can't be sent.", problems)
    row = MarketingNewsletter(tenant_id=tenant_id, subject=subject, intro=(intro or "").strip()[:2000] or None,
                              content_ids=ids, created_by=actor_id)
    db.add(row)
    db.flush()
    return row


def _button(tenant: Tenant) -> tuple[str, str]:
    from app.services.marketing_ai_service import get_profile
    profile = get_profile(tenant)
    site = ((profile.get("socials") or {}).get("website") or "").strip()
    if site.startswith("https://"):
        return "See dates and stays", site
    phone = "".join(ch for ch in (profile.get("contact_phone") or "") if ch.isdigit())
    return ("Message us on WhatsApp", f"https://wa.me/{phone}") if len(phone) >= 10 else ("", "")


def render(db: Session, tenant: Tenant, nl: MarketingNewsletter, unsubscribe_link: str, *, image_url=None) -> tuple[str, str]:
    """(html, text). Deterministic from the approved payloads; every piece of text escaped."""
    from app.services import marketing_render
    from app.services.media_library_service import _panel_colour
    from app.services.media_storage import get_presigned_media_url
    colour, brand = _panel_colour(tenant), html.escape(tenant.brand_name or tenant.name)
    label, href = _button(tenant)
    if href.startswith("https://") and "wa.me" not in href:      # agency M6: the website knows it came from this email
        from app.services import marketing_links as links
        href = links.tag_url(href, links.utm(source="newsletter", medium="email", campaign=f"n-{nl.id.replace('-', '')[:8]}"))
    blocks, texts = [], [nl.subject, "", nl.intro or ""]
    for item, payload in _items(db, tenant.id, nl.content_ids):
        frames = marketing_render.frames(item.kind, payload)
        headline = next((f["headline"] for f in frames if f.get("headline")), None) or item.title
        body = "\n\n".join((payload.get("caption") or "").split("\n\n")[:2]).strip()
        img = ""
        if frames and frames[0].get("asset_id"):
            from app.models.media_asset import MediaAsset
            asset = db.query(MediaAsset).filter_by(id=frames[0]["asset_id"], tenant_id=tenant.id).first()
            src = (image_url or (lambda a: get_presigned_media_url(a.storage_key, expires_in=IMAGE_DAYS)))(asset) if asset else None
            if src:
                img = f'<img src="{html.escape(src)}" alt="" width="560" style="width:100%;max-width:560px;border-radius:12px;display:block">'
        blocks.append(f'<tr><td style="padding:16px 0">{img}<h2 style="font:600 20px/1.3 Arial,sans-serif;color:#1f2937;margin:16px 0 8px">'
                      f'{html.escape(headline)}</h2><p style="font:15px/1.6 Arial,sans-serif;color:#374151;margin:0;white-space:pre-line">'
                      f'{html.escape(body)}</p></td></tr>')
        texts += ["", headline, body]
    button = (f'<tr><td style="padding:8px 0 24px"><a href="{html.escape(href)}" style="background:{colour};color:#fff;'
              f'padding:12px 20px;border-radius:999px;font:600 15px Arial,sans-serif;text-decoration:none;display:inline-block">'
              f'{html.escape(label)}</a></td></tr>') if href else ""
    intro = f'<p style="font:15px/1.6 Arial,sans-serif;color:#374151;white-space:pre-line">{html.escape(nl.intro)}</p>' if nl.intro else ""
    page = (f'<!doctype html><html><body style="margin:0;background:#f6f5f1"><table role="presentation" width="100%" '
            f'cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:24px 12px"><table role="presentation" '
            f'width="100%" style="max-width:560px;background:#fff;border-radius:16px;padding:24px"><tr><td>'
            f'<p style="font:700 14px Arial,sans-serif;color:{colour};letter-spacing:.04em;margin:0">{brand}</p>{intro}</td></tr>'
            f'{"".join(blocks)}{button}<tr><td style="font:12px/1.5 Arial,sans-serif;color:#6b7280;border-top:1px solid #eee;'
            f'padding-top:16px">You get this because you agreed to hear from {brand}. '
            f'<a href="{html.escape(unsubscribe_link)}" style="color:#6b7280">Unsubscribe</a></td></tr></table></td></tr>'
            f'</table></body></html>')
    texts += ["", f"{label}: {href}" if href else "", "", f"Unsubscribe: {unsubscribe_link}"]
    return page, "\n".join(texts).strip()


# ── Send ────────────────────────────────────────────────────────────────────────────────────────────────────────────

def start_send(db: Session, tenant: Tenant, newsletter_id: str, actor: User, *, consent_confirmed: bool) -> MarketingNewsletter:
    nl = db.query(MarketingNewsletter).filter_by(id=newsletter_id, tenant_id=tenant.id).first()
    if nl is None:
        raise MarketingError(404, "not_found", "No such newsletter.")
    if nl.status != "draft":
        raise MarketingError(409, "already_sent", "This newsletter has already been sent.")
    if consent_confirmed is not True:
        raise MarketingError(422, "consent_required", "Confirm these guests agreed to receive marketing email.")
    role = actor.role.value if hasattr(actor.role, "value") else str(actor.role)
    if nl.created_by == actor.id and role != "owner":
        raise MarketingError(403, "self_approval", "You wrote this newsletter, so someone else must send it.")
    if not settings.RESEND_API_KEY:
        raise MarketingError(503, "email_not_configured", "Email sending is not set up on this HAIP server.")
    _items(db, tenant.id, nl.content_ids)                          # still approved?
    people = audience(db, tenant.id)
    if not people:
        raise MarketingError(422, "no_audience", "No guest has an email address and marketing consent yet.")
    for g in people:
        db.add(MarketingNewsletterRecipient(tenant_id=tenant.id, newsletter_id=nl.id, guest_id=g.id, email=g.email.strip()))
    nl.status, nl.sent_by, nl.recipients = "sending", actor.id, len(people)
    append_audit(db, tenant_id=tenant.id, action="marketing.newsletter.sent", actor_user_id=actor.id,
                 target_type="marketing_newsletter", target_id=nl.id,
                 payload={"recipients": len(people), "consent_confirmed": True, "subject": nl.subject})
    return nl


def send_batch(db: Session, tenant_id: str, newsletter_id: str, *, sender=None, image_url=None) -> int:
    """Send the next BATCH queued emails. Returns how many are still queued after this batch."""
    import asyncio
    from app.services import email_service
    nl = db.query(MarketingNewsletter).filter_by(id=newsletter_id, tenant_id=tenant_id).one()
    tenant = db.query(Tenant).filter_by(id=tenant_id).one()
    rows = (db.query(MarketingNewsletterRecipient).filter_by(tenant_id=tenant_id, newsletter_id=nl.id, status="queued")
            .limit(BATCH).all())
    send = sender or (lambda **kw: asyncio.run(email_service._send(**kw)))
    page_t, text_t = render(db, tenant, nl, _PLACEHOLDER, image_url=image_url) if rows else ("", "")
    for r in rows:
        link = unsubscribe_url(unsubscribe_token(tenant_id, r.guest_id, nl.id))
        page, text = page_t.replace(_PLACEHOLDER, html.escape(link)), text_t.replace(_PLACEHOLDER, link)
        ok = send(to=r.email, subject=nl.subject, html=page, text=text, log_to=False,
                  headers={"List-Unsubscribe": f"<{link}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"})
        r.status, r.sent_at = ("sent", datetime.now(timezone.utc)) if ok else ("failed", None)
        r.error = None if ok else "The email service did not accept it."
        db.commit()                                 # one by one: a crash never re-sends what went out
    left = db.query(MarketingNewsletterRecipient).filter_by(tenant_id=tenant_id, newsletter_id=nl.id, status="queued").count()
    if left == 0:
        counts = dict(db.query(MarketingNewsletterRecipient.status, func.count())
                      .filter_by(tenant_id=tenant_id, newsletter_id=nl.id).group_by(MarketingNewsletterRecipient.status).all())
        nl.status, nl.sent_at = "sent", datetime.now(timezone.utc)
        nl.delivered, nl.failed = counts.get("sent", 0), counts.get("failed", 0)
        db.commit()
    return left


def listing(db: Session, tenant_id: str) -> list[dict]:
    rows = db.query(MarketingNewsletter).filter_by(tenant_id=tenant_id).order_by(MarketingNewsletter.created_at.desc()).limit(20)
    return [{"id": n.id, "subject": n.subject, "status": n.status, "recipients": n.recipients, "delivered": n.delivered,
             "failed": n.failed, "created_by": n.created_by, "sent_at": n.sent_at, "created_at": n.created_at,
             "content_ids": n.content_ids} for n in rows]
