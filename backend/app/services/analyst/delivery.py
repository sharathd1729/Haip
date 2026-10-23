"""Delivering a report to owners / managers, and the signed view-only page behind the link.

  email     Resend (email_service._send), to active owners / managers with an email who did not switch it off
            (``notification_prefs.analyst_email``), only when ``brand_config.analyst.delivery.email`` is on
  whatsapp  template ``haip_analyst_brief_v1`` (DOCUMENT header = the PDF, body = headline, URL button = the signed page),
            only to staff who opted in to WhatsApp alerts (users.whatsapp_alerts_opt_in_at) with a phone, only when
            ``delivery.whatsapp`` is on AND Meta approved the template (a draft is never sent). Staff are not guests: no
            Message row, the record is ``analyst_reports.delivery``.

Signed link: a JWT (type ``analyst_view``) naming the report, the tenant and the RECIPIENT, valid 7 days. It shows the brief
read-only (money only if that recipient may read revenue). The PDF is rendered on request from the same token.

Tap-to-assign lives on the signed page, NOT on WhatsApp list replies: the staff inbound handler (webhook ``_staff_reply``) only
understands ``la:`` alert taps, and a second payload family there would widen what an inbound message can do. Assigning from
the page needs a one-time 6-digit code e-mailed to the recipient (10 minutes, single use, hashed), then
lead_assignment_service._set_owner(method="analyst_page") + audit ``analyst.lead_assigned``.
"""
from __future__ import annotations

import asyncio
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from html import escape
from typing import Optional

import structlog
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.core.config import settings
from app.models.analyst import AnalystReport
from app.models.tenant import Tenant
from app.models.user import User, UserRole

log = structlog.get_logger()

TOKEN_TYPE = "analyst_view"
TOKEN_DAYS = 7
CODE_MINUTES = 10
TEMPLATE = "haip_analyst_brief_v1"
EMAIL_PREF = "analyst_email"
_ALG = "HS256"


class DeliveryError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


# ── tokens ──────────────────────────────────────────────────────────────────────────────────────────────────

def make_token(report: AnalystReport, user_id: str, now: Optional[datetime] = None) -> str:
    now = now or datetime.now(timezone.utc)
    return jwt.encode({"type": TOKEN_TYPE, "rid": report.id, "tid": report.tenant_id, "sub": user_id,
                       "exp": now + timedelta(days=TOKEN_DAYS)}, settings.SECRET_KEY, algorithm=_ALG)


def read_token(token: str) -> Optional[dict]:
    try:
        data = jwt.decode(token, settings.SECRET_KEY, algorithms=[_ALG])
    except JWTError:
        return None
    return data if data.get("type") == TOKEN_TYPE and data.get("rid") and data.get("tid") and data.get("sub") else None


def resolve(db: Session, token: str) -> tuple[AnalystReport, User]:
    data = read_token(token)
    if data is None:
        raise DeliveryError(404, "link_invalid", "This link has expired or is not valid.")
    from app.core.database import set_tenant_context
    set_tenant_context(db, data["tid"])
    report = db.query(AnalystReport).filter_by(id=data["rid"], tenant_id=data["tid"]).first()
    user = db.query(User).filter_by(id=data["sub"], tenant_id=data["tid"]).first()
    if report is None or user is None or not user.is_active or user.is_deleted:
        raise DeliveryError(404, "link_invalid", "This link has expired or is not valid.")
    return report, user


def page_url(token: str) -> str:
    return f"{(settings.FRONTEND_URL or '').rstrip('/')}/r/analyst/{token}"


def pdf_url(token: str) -> str:
    base = (settings.API_BASE_URL or settings.FRONTEND_URL or "").rstrip("/")
    return f"{base}/api/v1/public/analyst/{token}/report.pdf"


# ── recipients ──────────────────────────────────────────────────────────────────────────────────────────────

def _staff(db: Session, tenant_id: str) -> list[User]:
    return db.query(User).filter(User.tenant_id == tenant_id, User.role.in_([UserRole.OWNER, UserRole.MANAGER]),
                                 User.is_active.is_(True), User.is_deleted.is_(False)).all()


def email_recipients(db: Session, tenant_id: str) -> list[User]:
    return [u for u in _staff(db, tenant_id) if u.email and (u.notification_prefs or {}).get(EMAIL_PREF, True) is not False]


def whatsapp_recipients(db: Session, tenant_id: str) -> list[User]:
    return [u for u in _staff(db, tenant_id) if u.phone and u.whatsapp_alerts_opt_in_at is not None]


def _money(db: Session, user: User) -> bool:
    from app.services.authz_service import has_capability
    return has_capability(db, user, "revenue.read")


# ── the read-only view ──────────────────────────────────────────────────────────────────────────────────────

def public_view(db: Session, report: AnalystReport, user: User) -> dict:
    from app.services.analyst.reports import view
    out = view(report)
    money = _money(db, user)
    facts = dict(out["facts"])
    if not money:
        j = dict(facts.get("journey") or {})
        j["revenue"] = {"restricted": True}
        facts["journey"] = j
        out["brief"] = {**out["brief"], "money": ""}
    out["facts"] = facts
    out.pop("validation", None)
    out.pop("delivery", None)
    out.pop("followups", None)
    out["viewer"] = {"first_name": (user.name or "").split(" ")[0], "money": money}
    out["assign"] = assign_options(db, report.tenant_id)
    return out


def assign_options(db: Session, tenant_id: str) -> dict:
    """Waiting new leads with no owner (from the ONE work queue) and the team members who can take them."""
    from app.services import lead_assignment_service as las
    from app.services import work_queue_service
    tenant = db.query(Tenant).filter_by(id=tenant_id).first()
    q = work_queue_service.build(db, tenant, None, kinds=["new_lead"]) if tenant else {"items": []}
    leads = [{"inquiry_id": i["inquiry_id"], "who": (i.get("title") or "Guest").split(" ")[0], "since": i.get("since"),
              "severity": i.get("severity")}
             for i in q["items"] if i.get("kind") == "new_lead" and i.get("inquiry_id") and not i.get("owner_id")][:15]
    team = [{"user_id": u.id, "name": u.name} for u in las.eligible_agents(db, tenant_id)]
    return {"leads": leads, "team": team}


# ── tap-to-assign with a one-time code ──────────────────────────────────────────────────────────────────────

def _hash(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def assign_start(db: Session, report: AnalystReport, user: User, inquiry_id: str, assignee_id: str) -> dict:
    from app.models.inquiry import Inquiry
    from app.services import lead_assignment_service as las
    if not user.email:
        raise DeliveryError(409, "no_email", "Assigning from this page needs an email address on your HAIP profile.")
    if db.query(Inquiry.id).filter_by(id=inquiry_id, tenant_id=report.tenant_id).first() is None:
        raise DeliveryError(404, "lead_not_found", "That lead is not in this workspace.")
    if assignee_id not in {u.id for u in las.eligible_agents(db, report.tenant_id)}:
        raise DeliveryError(422, "assignee_not_eligible", "That person cannot take leads.")
    code = f"{secrets.randbelow(10 ** 6):06d}"
    nonce = secrets.token_urlsafe(9)
    delivery = dict(report.delivery or {})
    pending = {k: v for k, v in (delivery.get("assign") or {}).items()
               if datetime.fromisoformat(v["expires_at"]) > datetime.now(timezone.utc)}
    pending[nonce] = {"code": _hash(code), "inquiry_id": inquiry_id, "assignee_id": assignee_id, "by": user.id,
                      "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=CODE_MINUTES)).isoformat()}
    delivery["assign"] = pending
    report.delivery = delivery
    db.commit()
    from app.services.email_service import _send
    ok = asyncio.run(_send(user.email, "Your HAIP confirmation code",
                           f"<p>Your code to confirm the lead assignment is <b>{code}</b>. It works once, for {CODE_MINUTES} minutes.</p>",
                           f"Your code to confirm the lead assignment is {code}. It works once, for {CODE_MINUTES} minutes."))
    return {"nonce": nonce, "sent": bool(ok)}


def assign_confirm(db: Session, report: AnalystReport, user: User, nonce: str, code: str) -> dict:
    from app.models.inquiry import Inquiry
    from app.services import lead_assignment_service as las
    delivery = dict(report.delivery or {})
    pending = dict(delivery.get("assign") or {})
    item = pending.pop(nonce, None)
    if item is None or item["by"] != user.id or datetime.fromisoformat(item["expires_at"]) <= datetime.now(timezone.utc):
        raise DeliveryError(410, "code_expired", "This confirmation has expired. Start again.")
    delivery["assign"] = pending
    report.delivery = delivery                               # single use: removed whether or not the code matches
    if not secrets.compare_digest(item["code"], _hash((code or "").strip())):
        db.commit()
        raise DeliveryError(422, "code_wrong", "That code is not right. Start again to get a new one.")
    inq = db.query(Inquiry).filter_by(id=item["inquiry_id"], tenant_id=report.tenant_id).first()
    if inq is None:
        db.commit()
        raise DeliveryError(404, "lead_not_found", "That lead is not in this workspace.")
    previous = inq.assigned_to
    las._set_owner(db, inq, item["assignee_id"], "analyst_page")
    append_audit(db, tenant_id=report.tenant_id, actor_user_id=user.id, action="analyst.lead_assigned", target_type="inquiry",
                 target_id=inq.id, payload={"from": previous, "to": item["assignee_id"], "report_id": report.id})
    db.commit()
    return {"inquiry_id": inq.id, "assigned_to": item["assignee_id"]}


# ── sending ─────────────────────────────────────────────────────────────────────────────────────────────────

def email_html(report: AnalystReport, brand: str, link: str) -> str:
    b = report.brief or {}
    items = "".join(f"<li>{escape(x)}</li>" for x in (b.get("not_working") or [])[:4])
    recs = "".join(f"<li>{escape(r.get('action', ''))}</li>" for r in (b.get("recommendations") or [])[:4])
    return (f"<div style=\"font-family:Arial,sans-serif;color:#1F2A27\"><h2>{escape(brand)} · {escape(report.kind.replace('_', ' '))}</h2>"
            f"<p><b>{escape(b.get('headline') or '')}</b></p>"
            + (f"<p>Needs attention:</p><ul>{items}</ul>" if items else "")
            + (f"<p>Recommended:</p><ul>{recs}</ul>" if recs else "")
            + f"<p><a href=\"{escape(link)}\">Open the full report</a> (link valid {TOKEN_DAYS} days, just for you).</p></div>")


def deliver(db: Session, tenant: Tenant, report: AnalystReport) -> dict:
    """Send by the channels the owner switched on. Never raises; every outcome is kept on ``report.delivery``."""
    from app.services.analyst.settings import get as get_settings
    s = get_settings(tenant)
    brand = tenant.brand_name or tenant.name
    out: dict = {"email": {"status": "off"}, "whatsapp": {"status": "off"}}
    if s.delivery.email:
        sent = failed = 0
        from app.services.email_service import _send
        for u in email_recipients(db, tenant.id):
            link = page_url(make_token(report, u.id))
            ok = asyncio.run(_send(u.email, f"{brand}: {(report.brief or {}).get('headline') or 'your report'}"[:150],
                                   email_html(report, brand, link)))
            sent, failed = sent + bool(ok), failed + (not ok)
        out["email"] = {"status": "done", "sent": sent, "failed": failed}
    if s.delivery.whatsapp:
        out["whatsapp"] = _whatsapp(db, report, brand)
    report.delivery = {**(report.delivery or {}), **out, "at": datetime.now(timezone.utc).isoformat()}
    db.commit()
    log.info("analyst_report_delivered", tenant_id=tenant.id, report_id=report.id,
             email=out["email"].get("status"), whatsapp=out["whatsapp"].get("status"))
    return out


def _whatsapp(db: Session, report: AnalystReport, brand: str) -> dict:
    from app.services import lead_alert_sender as las
    language = las.template_approved(db, report.tenant_id, TEMPLATE)
    if language is None:
        return {"status": "not_sent", "reason": f"template {TEMPLATE} is not approved by Meta yet"}
    phone_number_id, token = las.wa_credentials(db, report.tenant_id)
    if not phone_number_id or not token:
        return {"status": "not_sent", "reason": "WhatsApp is not connected"}
    sent, failed, reasons = 0, 0, []
    for u in whatsapp_recipients(db, report.tenant_id):
        t = make_token(report, u.id)
        components = [
            {"type": "header", "parameters": [{"type": "document", "document": {"link": pdf_url(t), "filename": "report.pdf"}}]},
            {"type": "body", "parameters": [{"type": "text", "text": las.clean(v)} for v in
                                            (brand, report.kind.replace("_", " "), (report.brief or {}).get("headline") or "-")]},
            {"type": "button", "sub_type": "url", "index": "0", "parameters": [{"type": "text", "text": t}]},
        ]
        try:
            las._run(las._adapter(phone_number_id, token).send_template(
                to=u.phone, template_name=TEMPLATE, language_code=language, components=components))
            sent += 1
        except Exception as exc:  # noqa: BLE001 -- kept on the report; email still went
            failed += 1
            reasons.append(las.meta_error(exc)[1])
    return {"status": "done", "sent": sent, "failed": failed, "reasons": reasons[:3]}
