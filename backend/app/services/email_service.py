"""
Email service — Resend API when key is configured, console log fallback otherwise.

Usage:
    from app.services.email_service import send_invitation_email, send_welcome_email
    await send_invitation_email(to_email="ravi@villa.com", name="Ravi", invite_link="...", inviter_name="...", role="concierge")

To activate real sending: set RESEND_API_KEY in .env
"""
from html import escape as _escape

import httpx
import structlog
from app.core.config import settings

log = structlog.get_logger()

RESEND_API_URL = "https://api.resend.com/emails"


async def _send(to: str, subject: str, html: str, text: str | None = None) -> bool:
    """Send via Resend when key is set, otherwise log to console."""
    if not settings.RESEND_API_KEY:
        # Returns False, not True. This previously reported success when
        # nothing had been sent, so every caller counting results -- and the
        # scheduled report in particular -- logged a healthy "sent" for mail
        # that never left the process. No current caller checks the return
        # value, so reporting the truth breaks nothing.
        log.warning(
            "email_not_sent_no_key",
            to=to,
            subject=subject,
            note="Set RESEND_API_KEY in .env to enable real email sending",
        )
        # Deliberately NOT logging the body: it carries password-reset links
        # and invite tokens, and application logs are not the place for
        # either. Use a real key against a test inbox to inspect content.
        return False

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                RESEND_API_URL,
                headers={
                    "Authorization": f"Bearer {settings.RESEND_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": settings.EMAIL_FROM,
                    "to": [to],
                    "subject": subject,
                    "html": html,
                    **({"text": text} if text else {}),   # plain-text part: better deliverability, readable anywhere
                },
            )
            if resp.status_code in (200, 201):
                log.info("email_sent", to=to, subject=subject)
                return True
            else:
                log.error("email_send_failed", to=to, status=resp.status_code, body=resp.text[:200])
                return False
    except Exception as exc:
        log.error("email_send_error", to=to, error=str(exc))
        return False


async def send_invitation_email(
    *,
    to_email: str,
    name: str,
    invite_link: str,
    inviter_name: str,
    tenant_name: str,
    role: str,
) -> bool:
    role_label = role.replace("_", " ").title()
    subject = f"You've been invited to join {tenant_name} on HAIP"
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 520px; margin: 0 auto; padding: 40px 24px; color: #1a1a2e;">
      <div style="text-align: center; margin-bottom: 32px;">
        <div style="display: inline-block; background: #0B1F3A; color: white; font-size: 18px; font-weight: 800; padding: 8px 20px; border-radius: 10px; letter-spacing: 1px;">
          HAIP
        </div>
      </div>

      <h1 style="font-size: 22px; font-weight: 700; margin-bottom: 8px; color: #0B1F3A;">
        Hi {name}, you're invited!
      </h1>
      <p style="color: #6b7280; font-size: 15px; line-height: 1.6; margin-bottom: 24px;">
        <strong>{inviter_name}</strong> has invited you to join <strong>{tenant_name}</strong> on HAIP
        as a <strong>{role_label}</strong>.
      </p>

      <div style="text-align: center; margin: 32px 0;">
        <a href="{invite_link}"
           style="display: inline-block; background: #14b8a6; color: white; text-decoration: none;
                  font-weight: 700; font-size: 15px; padding: 14px 32px; border-radius: 12px;">
          Accept Invitation →
        </a>
      </div>

      <p style="color: #9ca3af; font-size: 12px; text-align: center; margin-top: 24px;">
        This invitation expires in 7 days.<br/>
        If you weren't expecting this, you can safely ignore this email.
      </p>

      <hr style="border: none; border-top: 1px solid #f3f4f6; margin: 32px 0;" />
      <p style="color: #d1d5db; font-size: 11px; text-align: center;">
        HAIP · Hospitality AI Intelligence Platform
      </p>
    </div>
    """
    return await _send(to=to_email, subject=subject, html=html)


async def send_welcome_email(*, to_email: str, name: str, tenant_name: str) -> bool:
    subject = f"Welcome to HAIP, {name}!"
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 520px; margin: 0 auto; padding: 40px 24px; color: #1a1a2e;">
      <div style="text-align: center; margin-bottom: 32px;">
        <div style="display: inline-block; background: #0B1F3A; color: white; font-size: 18px; font-weight: 800; padding: 8px 20px; border-radius: 10px; letter-spacing: 1px;">
          HAIP
        </div>
      </div>

      <h1 style="font-size: 22px; font-weight: 700; margin-bottom: 8px; color: #0B1F3A;">
        Welcome aboard, {name}!
      </h1>
      <p style="color: #6b7280; font-size: 15px; line-height: 1.6; margin-bottom: 24px;">
        Your workspace <strong>{tenant_name}</strong> is ready. Here's what you can do first:
      </p>

      <ul style="color: #374151; font-size: 14px; line-height: 2; padding-left: 20px;">
        <li>Upload a call recording to see AI-powered QA scoring</li>
        <li>Invite your team from Settings → Team</li>
        <li>Set up your IVR integration in Settings → Integrations</li>
      </ul>

      <div style="text-align: center; margin: 32px 0;">
        <a href="https://www.genhaip.com/dashboard"
           style="display: inline-block; background: #0B1F3A; color: white; text-decoration: none;
                  font-weight: 700; font-size: 15px; padding: 14px 32px; border-radius: 12px;">
          Go to dashboard →
        </a>
      </div>

      <hr style="border: none; border-top: 1px solid #f3f4f6; margin: 32px 0;" />
      <p style="color: #d1d5db; font-size: 11px; text-align: center;">
        HAIP · Hospitality AI Intelligence Platform
      </p>
    </div>
    """
    return await _send(to=to_email, subject=subject, html=html)


async def send_token_expiring_alert_email(
    *, to_email: str, tenant_name: str, channel: str, days_left: int, expires_on: str,
) -> bool:
    """Heads-up that a Meta access token is about to expire. Sent before sending breaks, unlike
    send_integration_expired_alert_email, which fires after."""
    channel_label = {"whatsapp": "WhatsApp", "instagram": "Instagram"}.get(channel, channel.title())
    if days_left <= 0:
        when, subject = "has expired", f"Action needed: {channel_label} access token has expired for {tenant_name}"
    elif days_left == 1:
        when, subject = "expires tomorrow", f"Action needed: {channel_label} access token expires tomorrow for {tenant_name}"
    else:
        when, subject = f"expires in {days_left} days", f"{channel_label} access token expires in {days_left} days for {tenant_name}"
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 520px; margin: 0 auto; padding: 40px 24px; color: #1a1a2e;">
      <div style="text-align: center; margin-bottom: 32px;">
        <div style="display: inline-block; background: #0B1F3A; color: white; font-size: 18px; font-weight: 800; padding: 8px 20px; border-radius: 10px; letter-spacing: 1px;">HAIP</div>
      </div>
      <h1 style="font-size: 22px; font-weight: 700; margin-bottom: 8px; color: #b45309;">
        The {channel_label} access token {when}
      </h1>
      <p style="color: #6b7280; font-size: 15px; line-height: 1.6; margin-bottom: 16px;">
        <strong>{tenant_name}</strong>'s {channel_label} connection uses a Meta access token that ends on
        <strong>{expires_on}</strong>. After that, every {channel_label} message HAIP sends (AI drafts and messages
        your team sends by hand) will fail until a new token is saved.
      </p>
      <p style="color: #6b7280; font-size: 15px; line-height: 1.6; margin-bottom: 24px;">
        To fix it: in Meta Business Settings open Users, System users, choose your system user, generate a new token
        with expiry set to <strong>Never</strong>, then paste it into HAIP under Settings, Integrations.
      </p>
      <div style="text-align: center; margin: 32px 0;">
        <a href="https://www.genhaip.com/dashboard/settings/integrations"
           style="display: inline-block; background: #14b8a6; color: white; text-decoration: none; font-weight: 700; font-size: 15px; padding: 14px 32px; border-radius: 12px;">
          Open Integrations →
        </a>
      </div>
      <p style="color: #9ca3af; font-size: 12px; text-align: center; margin-top: 24px;">
        You get this reminder at 30, 14, 7, 3 and 1 days before the token ends.
      </p>
      <hr style="border: none; border-top: 1px solid #f3f4f6; margin: 32px 0;" />
      <p style="color: #d1d5db; font-size: 11px; text-align: center;">HAIP · Hospitality AI Intelligence Platform</p>
    </div>
    """
    return await _send(to=to_email, subject=subject, html=html)


async def send_integration_expired_alert_email(
    *, to_email: str, tenant_name: str, channel: str, detail: str,
) -> bool:
    channel_label = {"whatsapp": "WhatsApp", "instagram": "Instagram"}.get(channel, channel.title())
    subject = f"Action needed: {channel_label} messaging is down for {tenant_name}"
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 520px; margin: 0 auto; padding: 40px 24px; color: #1a1a2e;">
      <div style="text-align: center; margin-bottom: 32px;">
        <div style="display: inline-block; background: #0B1F3A; color: white; font-size: 18px; font-weight: 800; padding: 8px 20px; border-radius: 10px; letter-spacing: 1px;">
          HAIP
        </div>
      </div>

      <h1 style="font-size: 22px; font-weight: 700; margin-bottom: 8px; color: #b91c1c;">
        {channel_label} messages are failing to send
      </h1>
      <p style="color: #6b7280; font-size: 15px; line-height: 1.6; margin-bottom: 16px;">
        HAIP tried a routine check on <strong>{tenant_name}</strong>'s {channel_label} connection and it was
        rejected. This usually means the access token expired or was revoked -- every outbound
        {channel_label} message (both AI drafts and messages your team sends manually) is failing silently
        until this is fixed.
      </p>

      <div style="background: #fef2f2; border: 1px solid #fecaca; border-radius: 12px; padding: 14px 16px; margin-bottom: 24px; font-size: 13px; color: #7f1d1d; font-family: ui-monospace, monospace;">
        {detail}
      </div>

      <div style="text-align: center; margin: 32px 0;">
        <a href="https://www.genhaip.com/dashboard/settings/integrations"
           style="display: inline-block; background: #14b8a6; color: white; text-decoration: none;
                  font-weight: 700; font-size: 15px; padding: 14px 32px; border-radius: 12px;">
          Reconnect {channel_label} →
        </a>
      </div>

      <p style="color: #9ca3af; font-size: 12px; text-align: center; margin-top: 24px;">
        You'll get this alert at most once every 24 hours per channel while the issue persists.
      </p>

      <hr style="border: none; border-top: 1px solid #f3f4f6; margin: 32px 0;" />
      <p style="color: #d1d5db; font-size: 11px; text-align: center;">
        HAIP · Hospitality AI Intelligence Platform
      </p>
    </div>
    """
    return await _send(to=to_email, subject=subject, html=html)


async def send_instagram_dm_access_alert_email(*, to_email: str, tenant_name: str) -> bool:
    """Instagram is refusing HAIP access to the account's messages because the
    account owner switched "Allow access to messages" off. Not an expired
    token, so it gets its own wording and its own fix -- the generic
    "messages are failing to send / token expired" email would point the team
    at the wrong problem while incoming DMs pile up unseen."""
    tenant = _escape(tenant_name)
    subject = f"Action needed: Instagram messages aren't reaching HAIP for {tenant_name}"
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 520px; margin: 0 auto; padding: 40px 24px; color: #1a1a2e;">
      <div style="text-align: center; margin-bottom: 32px;">
        <div style="display: inline-block; background: #0B1F3A; color: white; font-size: 18px; font-weight: 800; padding: 8px 20px; border-radius: 10px; letter-spacing: 1px;">
          HAIP
        </div>
      </div>

      <h1 style="font-size: 22px; font-weight: 700; margin-bottom: 8px; color: #b91c1c;">
        New Instagram messages aren't arriving
      </h1>
      <p style="color: #6b7280; font-size: 15px; line-height: 1.6; margin-bottom: 16px;">
        HAIP's hourly check found that Instagram is blocking access to messages on
        <strong>{tenant}</strong>'s account. Instagram's own words:
        <em>"the account owner has disabled access to Instagram Direct Messaging."</em>
      </p>
      <p style="color: #6b7280; font-size: 15px; line-height: 1.6; margin-bottom: 16px;">
        While this is off, new DMs are <strong>not delivered to your HAIP inbox</strong> and HAIP cannot
        reply to them. Guests who write in are getting no answer.
      </p>

      <div style="background: #fef2f2; border: 1px solid #fecaca; border-radius: 12px; padding: 14px 16px; margin-bottom: 24px; font-size: 14px; line-height: 1.6; color: #7f1d1d;">
        <strong>To fix it (about a minute):</strong><br/>
        Reconnect Instagram in HAIP with the button below &mdash; approving it switches message access
        back on.<br/>
        Or, in the Instagram app: Settings and privacy &rarr; Messages and story replies &rarr;
        Connected tools &rarr; turn on <em>Allow access to messages</em> (menu names can differ a little
        between app versions).
      </div>

      <div style="text-align: center; margin: 32px 0;">
        <a href="https://www.genhaip.com/dashboard/settings/integrations"
           style="display: inline-block; background: #14b8a6; color: white; text-decoration: none;
                  font-weight: 700; font-size: 15px; padding: 14px 32px; border-radius: 12px;">
          Reconnect Instagram &rarr;
        </a>
      </div>

      <p style="color: #6b7280; font-size: 13px; line-height: 1.6;">
        Messages sent while this was off can be brought into HAIP afterwards &mdash; tell us roughly
        when it stopped. Instagram only lets you reply within 24 hours of a guest's last message, so
        it's worth doing today.
      </p>

      <p style="color: #9ca3af; font-size: 12px; text-align: center; margin-top: 24px;">
        You'll get this alert at most once every 24 hours while it stays off.
      </p>

      <hr style="border: none; border-top: 1px solid #f3f4f6; margin: 32px 0;" />
      <p style="color: #d1d5db; font-size: 11px; text-align: center;">
        HAIP · Hospitality AI Intelligence Platform
      </p>
    </div>
    """
    return await _send(to=to_email, subject=subject, html=html)


async def send_password_reset_email(*, to_email: str, name: str, reset_link: str) -> bool:
    subject = "Reset your HAIP password"
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 520px; margin: 0 auto; padding: 40px 24px; color: #1a1a2e;">
      <h1 style="font-size: 22px; font-weight: 700; margin-bottom: 8px; color: #0B1F3A;">
        Reset your password
      </h1>
      <p style="color: #6b7280; font-size: 15px; line-height: 1.6; margin-bottom: 24px;">
        Hi {name}, we received a request to reset your HAIP password.
      </p>
      <div style="text-align: center; margin: 32px 0;">
        <a href="{reset_link}"
           style="display: inline-block; background: #ef4444; color: white; text-decoration: none;
                  font-weight: 700; font-size: 15px; padding: 14px 32px; border-radius: 12px;">
          Reset password →
        </a>
      </div>
      <p style="color: #9ca3af; font-size: 12px; text-align: center; margin-top: 24px;">
        This link expires in 1 hour. If you didn't request a reset, ignore this email.
      </p>
    </div>
    """
    return await _send(to=to_email, subject=subject, html=html)


async def send_platform_lead_email(*, to_email: str, kind_label: str, name: str, company: str | None,
                                   phone: str | None, email: str | None, link: str) -> bool:
    """A visitor filled in a form on HAIP's own website (platform_lead_service.notify). Goes to the owners of HAIP's
    sales workspace only. Every visitor-typed value is escaped."""
    rows = [("Name", name), ("Company", company), ("Phone", phone), ("Email", email)]
    cells = "".join(
        f'<tr><td style="padding:4px 12px 4px 0;color:#6b7280;">{_escape(k)}</td>'
        f'<td style="padding:4px 0;color:#1a1a2e;font-weight:600;">{_escape(v)}</td></tr>'
        for k, v in rows if v
    )
    subject = f"New website lead: {kind_label}"
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 520px; margin: 0 auto; padding: 32px 24px; color: #1a1a2e;">
      <h1 style="font-size: 20px; font-weight: 700; margin-bottom: 8px;">{_escape(kind_label)} from the HAIP website</h1>
      <p style="color: #6b7280; font-size: 14px; line-height: 1.6;">It is already a lead in Leads360. Reply within 2 working hours, as the site promises.</p>
      <table style="font-size: 14px; margin: 16px 0;">{cells}</table>
      <a href="{_escape(link)}" style="display:inline-block;background:#1E7A5A;color:white;text-decoration:none;font-weight:700;font-size:14px;padding:12px 24px;border-radius:12px;">Open the lead &rarr;</a>
    </div>
    """
    return await _send(to=to_email, subject=subject, html=html)
