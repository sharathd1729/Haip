"""The daily lead report by email (sales meetings 23 Oct 2026). Off by default; Rathaa on (scripts/seed_ratha_lead_settings.py).

``brand_config.reports.daily_lead_email`` = {enabled (default False), hour 11, minute 0 (IST), reminder (default True),
last_sent / last_reminder (IST dates, written here)}. Changed only through PUT /reports/daily-lead-email/settings (owner /
manager, audited ``reports.daily_lead_email_changed``); PATCH /tenants/me refuses ``reports``.

``tick`` (Celery ``lead_reports.daily_email_tick``, beat every 5 minutes) per workspace, IST:
  reminder   30 minutes before the send time, until the send time: a push + a live in-app event (SSE
             ``leads_update_reminder``) to every active RESERVATIONS / CONCIERGE user: "Update your leads before 11:00".
  email      from the send time for 3 hours: YESTERDAY's daily lead report (lead_daily_report.build, the same numbers as
             Reports > Daily lead report) to every active OWNER / MANAGER with an email, through email_service._send (Resend).
Each at most once per day per workspace: the date is stored in brand_config AND a Redis key (``idem_check_and_set``) guards
two workers ticking at once. Audited ``reports.daily_lead_email_sent``. Phone numbers / guest names are not in the email.
"""
from __future__ import annotations

import asyncio
import html
from datetime import date, datetime, timedelta
from typing import Callable, Optional

import structlog
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.services.date_presets import IST

log = structlog.get_logger()

SECTION, KEY = "reports", "daily_lead_email"
DEFAULTS = {"enabled": False, "hour": 11, "minute": 0, "reminder": True}
EDITABLE = tuple(DEFAULTS)
REMINDER_BEFORE = timedelta(minutes=30)
SEND_WINDOW = timedelta(hours=3)
REMINDER_ROLES = ("reservations", "concierge")


def _raw(tenant) -> dict:
    return dict((((getattr(tenant, "brand_config", None) or {}).get(SECTION) or {}).get(KEY)) or {})


def settings_of(tenant) -> dict:
    raw = _raw(tenant)
    out = {**DEFAULTS, **{k: raw[k] for k in EDITABLE if k in raw}}
    out["enabled"], out["reminder"] = bool(out["enabled"]), bool(out["reminder"])
    out["hour"] = min(max(int(out["hour"]), 0), 23)
    out["minute"] = min(max(int(out["minute"]), 0), 59)
    out["last_sent"], out["last_reminder"] = raw.get("last_sent"), raw.get("last_reminder")
    return out


def _write(tenant, values: dict) -> None:
    cfg = dict(tenant.brand_config or {})
    section = dict(cfg.get(SECTION) or {})
    section[KEY] = {**(section.get(KEY) or {}), **values}
    cfg[SECTION] = section
    tenant.brand_config = cfg
    flag_modified(tenant, "brand_config")


def put_settings(db: Session, tenant, user, body: dict, actor: Optional[str] = None) -> dict:
    from app.core.audit import append_audit
    before = {k: settings_of(tenant)[k] for k in EDITABLE}
    _write(tenant, {k: body[k] for k in EDITABLE if k in body and body[k] is not None})
    after = {k: settings_of(tenant)[k] for k in EDITABLE}
    append_audit(db, tenant_id=tenant.id, action="reports.daily_lead_email_changed", actor_user_id=getattr(user, "id", None),
                 target_type="tenant", target_id=tenant.id, payload={"before": before, "after": after, **({"actor": actor} if actor else {})})
    return settings_of(tenant)


def _send_at(day: date, cfg: dict) -> datetime:
    return datetime(day.year, day.month, day.day, cfg["hour"], cfg["minute"], tzinfo=IST)


def render(report: dict, tenant_name: str, app_url: str) -> tuple[str, str, str]:
    """(subject, html, text) of one day's report. Aggregates and teammates' names only -- no guest data."""
    day = report["date"]
    t_auto, t_human = report["total"]["automatic"], report["total"]["human"]
    subject = f"{tenant_name}: daily lead report for {day} ({t_auto['received']} enquiries, {t_human['not_yet_reviewed']} not reviewed)"
    cols = [("received", "Received"), ("handled", "Handled"), ("valid_now", "Valid"), ("conversions", "Bookings")]
    hcols = [("reviewed", "Reviewed"), ("not_yet_reviewed", "Not reviewed yet")]
    head = "".join(f"<th align='right' style='padding:4px 8px'>{html.escape(lbl)}</th>" for _, lbl in cols + hcols)
    body_rows = []
    text_rows = []
    for r in report["agents"] + [{"name": "Total", **report["total"]}]:
        cells = [r["automatic"].get(k, 0) for k, _ in cols] + [r["human"].get(k, 0) for k, _ in hcols]
        body_rows.append(f"<tr><td style='padding:4px 8px'>{html.escape(r['name'])}</td>"
                         + "".join(f"<td align='right' style='padding:4px 8px'>{c}</td>" for c in cells) + "</tr>")
        text_rows.append(f"{r['name']}: " + ", ".join(f"{lbl} {c}" for (_, lbl), c in zip(cols + hcols, cells)))
    link = f"{app_url}/dashboard/reports" if app_url else ""
    body = (f"<div style='font-family:sans-serif;font-size:14px;line-height:1.5'><p>Daily lead report for <strong>{html.escape(day)}</strong> "
            f"(IST). Valid = a person's review, else the workspace's valid-lead rule.</p>"
            f"<table style='border-collapse:collapse'><tr><th align='left' style='padding:4px 8px'>Agent</th>{head}</tr>{''.join(body_rows)}</table>"
            + (f"<p><a href='{html.escape(link)}'>Open Reports in HAIP</a></p>" if link else "") + "</div>")
    text = f"Daily lead report for {day} (IST)\n" + "\n".join(text_rows) + (f"\n{link}" if link else "")
    return subject, body, text


def _remind(db: Session, tenant, send_at: datetime, pusher: Optional[Callable] = None) -> int:
    from app.models.user import User, UserRole
    users = (db.query(User).filter(User.tenant_id == tenant.id, User.is_active.is_(True), User.is_deleted.is_(False),
                                   User.role.in_([UserRole(r) for r in REMINDER_ROLES])).all())
    title, msg = "Update your leads", f"Update your leads before {send_at:%H:%M}: the daily lead report goes to the owners then."
    if pusher is None:
        from app.services.push_service import send_to_tenant

        def pusher(user_id):
            send_to_tenant(db=db, tenant_id=tenant.id, title=title, body=msg, url="/dashboard/leads", tag="haip-lead-update", user_id=user_id)
    for u in users:
        pusher(u.id)
    try:   # live in-app banner for anyone with HAIP open; best-effort (push already went)
        import json

        import redis

        from app.core.config import settings
        redis.from_url(settings.REDIS_URL).publish(f"sse:{tenant.id}", json.dumps({"event": "leads_update_reminder", "message": msg,
                                                                                    "roles": list(REMINDER_ROLES)}))
    except Exception as exc:  # noqa: BLE001
        log.warning("lead_update_reminder_sse_failed", tenant_id=tenant.id, error=str(exc)[:200])
    return len(users)


def tick(db: Session, tenant, *, now: Optional[datetime] = None, sender: Optional[Callable[..., bool]] = None,
         pusher: Optional[Callable] = None, app_url: str = "") -> dict:
    """One workspace, once. Returns what it did. Commits its own writes."""
    from app.core.audit import append_audit
    from app.core.cache import cache_key, idem_check_and_set
    from app.models.user import User, UserRole
    from app.services import lead_daily_report

    cfg = settings_of(tenant)
    if not cfg["enabled"]:
        return {"status": "off"}
    now = (now or datetime.now(IST)).astimezone(IST)
    today = now.date()
    send_at = _send_at(today, cfg)
    done: dict = {"status": "idle"}

    if cfg["reminder"] and send_at - REMINDER_BEFORE <= now < send_at and cfg["last_reminder"] != today.isoformat():
        if idem_check_and_set(cache_key("lead_update_reminder", tenant.id, day=today.isoformat()), ttl=36 * 3600):
            n = _remind(db, tenant, send_at, pusher)
            _write(tenant, {"last_reminder": today.isoformat()})
            db.commit()
            done = {"status": "reminded", "people": n}

    if send_at <= now < send_at + SEND_WINDOW and cfg["last_sent"] != today.isoformat():
        if not idem_check_and_set(cache_key("daily_lead_email", tenant.id, day=today.isoformat()), ttl=36 * 3600):
            return {"status": "already_sending"}
        day = today - timedelta(days=1)
        report = lead_daily_report.build(db, tenant.id, day)
        subject, body, text = render(report, tenant.brand_name or tenant.name, app_url)
        if sender is None:
            from app.services import email_service

            def sender(**kw) -> bool:
                return asyncio.run(email_service._send(**kw))
        send = sender
        users = (db.query(User).filter(User.tenant_id == tenant.id, User.is_active.is_(True), User.is_deleted.is_(False),
                                       User.role.in_([UserRole.OWNER, UserRole.MANAGER])).all())
        sent = 0
        for u in users:
            if "@" not in (u.email or ""):
                continue
            try:
                sent += 1 if send(to=u.email, subject=subject, html=body, text=text) else 0
            except Exception as exc:  # noqa: BLE001 -- one address failing must not stop the others
                log.warning("daily_lead_email_failed", tenant_id=tenant.id, user_id=u.id, error=str(exc)[:200])
        _write(tenant, {"last_sent": today.isoformat()})
        append_audit(db, tenant_id=tenant.id, action="reports.daily_lead_email_sent", actor_user_id=None, target_type="tenant",
                     target_id=tenant.id, payload={"actor": "system", "report_day": day.isoformat(), "sent": sent})
        db.commit()
        log.info("daily_lead_email_sent", tenant_id=tenant.id, report_day=day.isoformat(), sent=sent)
        done = {"status": "sent", "sent": sent, "report_day": day.isoformat()}
    return done
