"""Website builder background work (exact-name routes in celery_app.py).

  website.ai_job          AI developer run (queue default). Only a transient provider error is retried (2x, backoff).
  website.after_booking   confirmation email + WhatsApp + staff push + GST invoice after a paid website booking (whatsapp).
  website.expire_holds    every 5 min: lapsed holds free their dates; their Razorpay links are cancelled best-effort.
  website.verify_domains  hourly: pending custom domains re-check DNS.
  website.revalidate      after a publish: tell the sites renderer to refresh that site's pages.
Every task sets the tenant context before touching tenant rows, and uses one transaction per tenant.
"""
from html import escape

import httpx
import structlog
from celery import shared_task

from app.core.database import SessionLocal, set_tenant_context

log = structlog.get_logger()
MAX_RETRIES = 2
BASE_COUNTDOWN = 30


def _tenant_ids() -> list[str]:
    """Tenants with a website. Read per tenant afterwards (RLS: a cross-tenant query returns nothing)."""
    from app.models.tenant import Tenant
    from app.models.website import Site
    with SessionLocal() as db:
        ids = [t for (t,) in db.query(Tenant.id).filter(Tenant.is_active.is_(True)).all()]
    out = []
    for tid in ids:
        with SessionLocal() as db:
            set_tenant_context(db, tid)
            if db.query(Site.id).filter(Site.tenant_id == tid).first():
                out.append(tid)
    return out


@shared_task(name="website.ai_job", bind=True, max_retries=MAX_RETRIES)
def ai_job(self, tenant_id: str, job_id: str):
    from app.services import website_ai_service as svc
    from app.services.marketing_ai_service import LLMTransientError

    with SessionLocal() as db:
        set_tenant_context(db, tenant_id)
        try:
            svc.run_job(db, tenant_id, job_id)
            db.commit()
        except LLMTransientError as exc:
            db.rollback()
            if self.request.retries < MAX_RETRIES:
                raise self.retry(exc=exc, countdown=BASE_COUNTDOWN * (2 ** self.request.retries))
            set_tenant_context(db, tenant_id)
            svc.mark_failed(db, tenant_id, job_id, "The AI service is busy right now. Try again in a few minutes.")
            db.commit()
        except Exception as exc:  # noqa: BLE001 -- never leave a job stuck in running
            db.rollback()
            set_tenant_context(db, tenant_id)
            svc.mark_failed(db, tenant_id, job_id, f"The AI developer hit a problem ({type(exc).__name__}). Try again.")
            db.commit()
            log.exception("website_ai_job_crashed", tenant_id=tenant_id, job_id=job_id)


def _email_html(name: str, prop: str, stay, ref: str, total: str, paid: str, manage_url: str, site_name: str) -> str:
    return (f"<div style=\"font-family:system-ui,sans-serif;max-width:560px;margin:auto;color:#1c1917\">"
            f"<h2 style=\"margin:0 0 8px\">Your booking is confirmed</h2>"
            f"<p>Hi {escape(name)}, thank you for booking {escape(prop)} with {escape(site_name)}.</p>"
            f"<table style=\"width:100%;border-collapse:collapse;font-size:15px\">"
            f"<tr><td style=\"padding:6px 0;color:#5f5a55\">Booking</td><td style=\"text-align:right\"><b>{escape(ref)}</b></td></tr>"
            f"<tr><td style=\"padding:6px 0;color:#5f5a55\">Dates</td><td style=\"text-align:right\">{stay.check_in:%a %d %b %Y} to {stay.check_out:%a %d %b %Y}</td></tr>"
            f"<tr><td style=\"padding:6px 0;color:#5f5a55\">Total incl. GST</td><td style=\"text-align:right\">Rs {escape(total)}</td></tr>"
            f"<tr><td style=\"padding:6px 0;color:#5f5a55\">Paid</td><td style=\"text-align:right\">Rs {escape(paid)}</td></tr></table>"
            f"<p><a href=\"{escape(manage_url)}\" style=\"display:inline-block;background:#1e7a5a;color:#fff;padding:10px 16px;"
            f"border-radius:10px;text-decoration:none\">View or manage your booking</a></p>"
            f"<p style=\"color:#78716c;font-size:13px\">Keep this email: the link is how you see your booking, pay the balance "
            f"or reach us.</p></div>")


@shared_task(name="website.after_booking", bind=True, max_retries=2)
def after_booking(self, tenant_id: str, hold_id: str):
    import asyncio
    from app.models.guest import Guest
    from app.models.property import Property, Stay
    from app.models.tenant import Tenant
    from app.models.website import BookingHold, Site
    from app.services import email_service, push_service
    from app.services.invoice_service import InvoiceError, booking_ref, issue_invoice
    from app.services.website_booking_service import issue_manage_token
    from app.services.website_service import primary_host

    with SessionLocal() as db:
        set_tenant_context(db, tenant_id)
        hold = db.query(BookingHold).filter_by(id=hold_id, tenant_id=tenant_id).first()
        if not hold or hold.status != "confirmed" or not hold.stay_id:
            return "skipped"
        tenant = db.get(Tenant, tenant_id)
        stay = db.get(Stay, hold.stay_id)
        site = db.get(Site, hold.site_id)
        prop = db.get(Property, hold.property_id)
        guest = db.get(Guest, stay.guest_id) if stay else None
        if not (tenant and stay and site and prop and guest):
            return "skipped"
        ref = booking_ref(stay)
        token = issue_manage_token(db, tenant_id, stay.id)
        manage_url = f"https://{primary_host(db, site)}/my-booking?t={token}"
        if hold.gst_percent is not None:
            try:
                issue_invoice(db, tenant, stay, buyer_gstin=(hold.guest_details or {}).get("gstin"))
            except InvoiceError as exc:
                log.info("website_invoice_skipped", tenant_id=tenant_id, stay_id=stay.id, reason=str(exc)[:200])
            except Exception:  # noqa: BLE001 -- the invoice can be issued from the booking page later
                log.exception("website_invoice_failed", tenant_id=tenant_id, stay_id=stay.id)
        db.commit()
        set_tenant_context(db, tenant_id)
        email = (hold.guest_details or {}).get("email") or guest.email
        if email:
            try:
                asyncio.run(email_service._send(
                    email, f"Booking confirmed: {prop.name}, {stay.check_in:%d %b}",
                    _email_html(guest.name or "there", prop.name, stay, ref, str(hold.total), str(hold.pay_now), manage_url, site.name)))
            except Exception:  # noqa: BLE001
                log.exception("website_confirmation_email_failed", tenant_id=tenant_id, hold_id=hold_id)
        try:
            from app.services.wa_booking_messages import send_booking_template
            send_booking_template(db, tenant_id, stay, "haip_booking_confirmed_v1",
                                  [(guest.name or "there").split(" ")[0], prop.name, f"{stay.check_in:%d %b}", ref],
                                  event="website_confirmed")
        except Exception:  # noqa: BLE001 -- template missing or not approved: email above is the confirmation
            log.info("website_confirmation_whatsapp_skipped", tenant_id=tenant_id, hold_id=hold_id)
        push_service.send_to_tenant(db, tenant_id, "New website booking",
                                    f"{guest.name or 'A guest'} booked {prop.name} for {stay.check_in:%d %b}. Paid Rs {hold.pay_now}.",
                                    url=f"/dashboard/bookings/{stay.id}", tag="website-booking")
        return "sent"


@shared_task(name="website.expire_holds")
def expire_holds():
    from app.adapters.payments import razorpay as rzp
    from app.services.payment_link_service import razorpay_credentials
    from app.services.website_booking_service import expire_holds as expire

    done = 0
    for tid in _tenant_ids():
        with SessionLocal() as db:
            set_tenant_context(db, tid)
            lapsed = expire(db, tid)
            if not lapsed:
                continue
            done += len(lapsed)
            db.commit()
            creds = razorpay_credentials(db, tid) if any(link for _, link in lapsed) else None
            for hold_id, link in lapsed:
                if link and creds:
                    try:
                        rzp.cancel_payment_link(creds["key_id"], creds["key_secret"], link)
                    except Exception as exc:  # noqa: BLE001 -- a paid-after-expiry link is handled by the webhook
                        log.info("website_link_cancel_failed", tenant_id=tid, hold_id=hold_id, error=type(exc).__name__)
    return done


@shared_task(name="website.verify_domains")
def verify_domains():
    from app.services import website_domain_service as dom

    checked = 0
    for tid in _tenant_ids():
        with SessionLocal() as db:
            set_tenant_context(db, tid)
            for d in dom.pending(db, tid):
                dom.verify(db, d)
                checked += 1
            db.commit()
    return checked


@shared_task(name="website.revalidate", bind=True, max_retries=3)
def revalidate(self, tenant_id: str, site_id: str):
    from app.core.config import settings
    from app.services.website_service import domains
    from app.models.website import Site

    if not (settings.SITES_RENDERER_URL and settings.SITES_REVALIDATE_SECRET):
        return "renderer_not_configured"
    with SessionLocal() as db:
        set_tenant_context(db, tenant_id)
        site = db.query(Site).filter_by(id=site_id, tenant_id=tenant_id).first()
        hosts = [d.hostname for d in domains(db, site) if d.status in ("active", "verified")] if site else []
    if not hosts:
        return "no_hosts"
    try:
        r = httpx.post(settings.SITES_RENDERER_URL.rstrip("/") + "/_haip/revalidate", json={"hosts": hosts},
                       headers={"x-haip-secret": settings.SITES_REVALIDATE_SECRET}, timeout=10.0, follow_redirects=False)
        r.raise_for_status()
    except Exception as exc:  # noqa: BLE001 -- pages refresh on their own within 5 minutes anyway
        if self.request.retries < 3:
            raise self.retry(exc=exc, countdown=20 * (2 ** self.request.retries))
        log.warning("website_revalidate_failed", tenant_id=tenant_id, site_id=site_id, error=type(exc).__name__)
        return "failed"
    return "ok"


@shared_task(name="website.send_manage_link")
def send_manage_link(tenant_id: str, stay_id: str, host: str):
    """A guest asked for their booking on the website: email (and WhatsApp when the template is approved) a fresh link."""
    import asyncio
    from app.models.guest import Guest
    from app.models.property import Property, Stay
    from app.services import email_service
    from app.services.invoice_service import booking_ref
    from app.services.website_booking_service import issue_manage_token

    with SessionLocal() as db:
        set_tenant_context(db, tenant_id)
        stay = db.query(Stay).filter_by(id=stay_id, tenant_id=tenant_id).first()
        guest = db.get(Guest, stay.guest_id) if stay else None
        if not stay or not guest:
            return "skipped"
        prop = db.get(Property, stay.property_id)
        token = issue_manage_token(db, tenant_id, stay.id)
        db.commit()
        url = f"https://{host}/my-booking?t={token}"
        sent = []
        if guest.email:
            try:
                asyncio.run(email_service._send(
                    guest.email, f"Your booking {booking_ref(stay)}",
                    f"<p>Hi {escape(guest.name or 'there')},</p><p>Here is the link to your booking at "
                    f"{escape(prop.name if prop else '')}: <a href=\"{escape(url)}\">view my booking</a>. "
                    f"It works for 45 days.</p>"))
                sent.append("email")
            except Exception:  # noqa: BLE001
                log.exception("website_manage_email_failed", tenant_id=tenant_id, stay_id=stay_id)
        try:
            from app.services.wa_booking_messages import send_booking_template
            res = send_booking_template(db, tenant_id, stay, "haip_manage_booking_v1",
                                        [(guest.name or "there").split(" ")[0], booking_ref(stay), url],
                                        event=f"website_manage_{token[:8]}")
            if (res or {}).get("status") == "queued":
                sent.append("whatsapp")
        except Exception:  # noqa: BLE001
            log.info("website_manage_whatsapp_skipped", tenant_id=tenant_id, stay_id=stay_id)
        return ",".join(sent) or "nothing_sent"
