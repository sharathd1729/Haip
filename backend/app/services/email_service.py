"""
Email service — Resend API when key is configured, console log fallback otherwise.

Usage:
    from app.services.email_service import send_invitation_email, send_welcome_email
    await send_invitation_email(to_email="ravi@villa.com", name="Ravi", invite_link="...", inviter_name="...", role="concierge")

To activate real sending: set RESEND_API_KEY in .env
"""
import httpx
import structlog
from app.core.config import settings

log = structlog.get_logger()

RESEND_API_URL = "https://api.resend.com/emails"


async def _send(to: str, subject: str, html: str) -> bool:
    """Send via Resend when key is set, otherwise log to console."""
    if not settings.RESEND_API_KEY:
        log.info(
            "email_not_sent_no_key",
            to=to,
            subject=subject,
            note="Set RESEND_API_KEY in .env to enable real email sending",
        )
        # Log the email body in dev so you can still copy the invite link
        log.info("email_preview", to=to, subject=subject, html_snippet=html[:300])
        return True  # Treat as success so invite flow doesn't break

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
        <a href="https://app.haip.in/dashboard"
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
