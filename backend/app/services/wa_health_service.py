"""
WhatsApp connection health: is Meta able to tell us about replies and delivery?

Real incident (Ratha, Sep 2026): templates were accepted by Meta ("sent") but
never showed as delivered, and a guest's reply never appeared. Sending only
needs the access token; replies and delivery updates arrive through Meta's
webhook, which we reject (401) unless the tenant's App Secret is saved and the
signature matches. The connect form called the App Secret "recommended" and a
reconnect with the box blank overwrote the saved one, so sending kept working
while everything coming back was silently thrown away.

This checks each link in that chain, in words, and remembers when the webhook
last worked or was refused.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
import structlog
from sqlalchemy import func
from sqlalchemy.orm import Session

log = structlog.get_logger()

_GRAPH = "https://graph.facebook.com/v20.0"
_OK_TOUCH_EVERY = timedelta(minutes=5)      # don't write to the DB on every single webhook

REJECT_REASONS = {
    "no_app_secret": "Meta's calls are being refused because no App Secret is saved for this WhatsApp connection.",
    "bad_signature": "Meta's calls are being refused because the App Secret saved here doesn't match your Meta app's.",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(iso: Optional[str]) -> Optional[datetime]:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def note_webhook(db: Session, integration, ok: bool, reason: Optional[str] = None) -> None:
    """Remember that Meta's webhook call was accepted, or refused and why.
    Never lets bookkeeping break the webhook itself."""
    try:
        cfg = dict(integration.config or {})
        now = _now()
        if ok:
            last = _parse(cfg.get("webhook_ok_at"))
            if last and now - last < _OK_TOUCH_EVERY:
                return
            cfg["webhook_ok_at"] = now.isoformat()
        else:
            cfg["webhook_rejected_at"] = now.isoformat()
            cfg["webhook_rejected_reason"] = reason
        integration.config = cfg
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        log.warning("wa_webhook_note_failed", error=str(exc))


def _check(key: str, status: str, title: str, detail: str, fix: Optional[str] = None) -> dict:
    return {"key": key, "status": status, "title": title, "detail": detail, "fix": fix}


def _meta_get(path: str, token: str, params: Optional[dict] = None) -> tuple[Optional[dict], Optional[str]]:
    """(json, error message). Never raises: a health check must not crash on a network blip."""
    try:
        resp = httpx.get(f"{_GRAPH}/{path}", params={"access_token": token, **(params or {})}, timeout=8)
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        return None, f"Couldn't reach Meta ({type(exc).__name__})."
    if isinstance(data, dict) and data.get("error"):
        err = data["error"]
        return None, f"{err.get('message', 'Meta returned an error')} (code {err.get('code')})"
    return data, None


def token_access(token: str) -> tuple[list, list, Optional[str]]:
    """(scopes, WhatsApp Business Account ids the token can manage, error).
    Asked of Meta itself: the token's own description names the accounts it may
    manage, which is the one reliable way to tell a wrong account ID from a
    missing permission."""
    data, err = _meta_get("debug_token", token, {"input_token": token})
    if err:
        return [], [], err
    d = (data or {}).get("data") or {}
    targets: list[str] = []
    for g in d.get("granular_scopes") or []:
        if g.get("scope") == "whatsapp_business_management":
            targets = [str(t) for t in (g.get("target_ids") or [])]
    return list(d.get("scopes") or []), targets, None


def candidate_wabas(token: str) -> tuple[list[str], list[str], Optional[str]]:
    """(scopes, WhatsApp Business Account ids this token can reach, error).
    First what the token itself says it manages; failing that, the accounts
    owned by the businesses it can see."""
    scopes, targets, err = token_access(token)
    if targets:
        return scopes, targets, None
    found: list[str] = []
    biz, berr = _meta_get("me/businesses", token, {"fields": "id", "limit": 20})
    for b in ((biz or {}).get("data") or [])[:10]:
        owned, _ = _meta_get(f"{b['id']}/owned_whatsapp_business_accounts", token, {"fields": "id", "limit": 50})
        found += [str(w["id"]) for w in ((owned or {}).get("data") or []) if w.get("id")]
    return scopes, found, (err if not found else None)


def apply_waba(db: Session, tenant_id: str, waba_id: str) -> str:
    """Save a WhatsApp Business Account ID -- but only one Meta says the token
    can manage, never whatever a client asks for. Returns the saved id."""
    from app.core.encryption import decrypt_credentials, encrypt_credentials
    from app.models.integration import Integration

    integ = None
    for kind in ("whatsapp_meta", "whatsapp"):
        integ = db.query(Integration).filter_by(tenant_id=tenant_id, kind=kind, status="active").first()
        if integ:
            break
    if not integ or not integ.credentials_kms_blob:
        raise ValueError("WhatsApp isn't connected.")
    creds = decrypt_credentials(integ.credentials_kms_blob)
    _, targets, err = candidate_wabas(creds.get("access_token", ""))
    if err:
        raise ValueError(f"Couldn't check with Meta: {err}")
    if waba_id not in targets:
        raise ValueError("Meta doesn't say this token can manage that WhatsApp Business Account.")
    integ.credentials_kms_blob = encrypt_credentials({**creds, "waba_id": waba_id})
    integ.config = {**(integ.config or {}), "waba_id": waba_id}
    db.commit()
    return waba_id


def check(db: Session, tenant_id: str, webhook_url: str) -> dict:
    from app.core.encryption import decrypt_credentials
    from app.models.conversation import ChannelType, Message, MessageDeliveryState, MessageDirection
    from app.models.integration import Integration

    checks: list[dict] = []
    integ = None
    for kind in ("whatsapp_meta", "whatsapp"):
        integ = db.query(Integration).filter_by(tenant_id=tenant_id, kind=kind, status="active").first()
        if integ:
            break
    if not integ:
        checks.append(_check("connection", "fail", "WhatsApp isn't connected",
                             "There's no active WhatsApp connection for this workspace.",
                             "Connect it under Settings → Integrations → WhatsApp."))
        return {"status": "fail", "checks": checks, "webhook_url": webhook_url, "facts": {}}

    try:
        creds = decrypt_credentials(integ.credentials_kms_blob) if integ.credentials_kms_blob else {}
    except Exception:  # noqa: BLE001
        creds = {}
    cfg = integ.config or {}
    token = creds.get("access_token", "")
    phone_id = cfg.get("phone_number_id") or creds.get("phone_number_id", "")
    waba_id = cfg.get("waba_id") or creds.get("waba_id", "")

    # ── 1. sending credentials ──
    if not token:
        checks.append(_check("token", "fail", "No access token saved", "Messages can't be sent.", "Reconnect WhatsApp and paste the token."))
    else:
        data, err = _meta_get(phone_id, token, {"fields": "display_phone_number,verified_name,quality_rating,webhook_configuration"})
        if err:
            checks.append(_check("token", "fail", "Meta rejected the access token", err,
                                 "Create a permanent System User token in Meta Business Settings and reconnect WhatsApp."))
        else:
            checks.append(_check("token", "ok", "Access token works",
                                 f"{data.get('verified_name') or 'Your number'} · {data.get('display_phone_number', '')}".strip(" ·")))
            override = ((data.get("webhook_configuration") or {}).get("application")) or ""
            if override and override.rstrip("/") != webhook_url.rstrip("/"):
                checks.append(_check("override", "fail", "This number sends its events somewhere else",
                                     f"A webhook set on the phone number itself points to {override}, which takes priority over the app's webhook.",
                                     "In Meta App Dashboard → WhatsApp → Configuration, remove the phone-number-level webhook override."))

    # ── 1b. Can this token manage templates on the saved WhatsApp Business Account? ──
    suggested_waba = None
    if token:
        scopes, targets, err = token_access(token)
        need = "whatsapp_business_management"
        if err or not targets:
            # Couldn't ask Meta which accounts this token manages; say so
            # rather than hiding it (that silence hid the real problem once).
            scopes, targets, err = candidate_wabas(token)
        if err:
            checks.append(_check("templates_access", "warn", "Couldn't verify template access", err))
        elif scopes and need not in scopes:
            checks.append(_check("templates_access", "fail", "The token can't manage templates",
                                 f"It doesn't have the {need} permission, so templates can't be created or submitted.",
                                 "Create a System User token with whatsapp_business_management and whatsapp_business_messaging, and reconnect WhatsApp."))
        elif targets and waba_id and waba_id not in targets:
            suggested_waba = targets[0] if len(targets) == 1 else None
            fix = (f"The token manages WhatsApp Business Account {targets[0]}. Use that ID."
                   if suggested_waba else f"This token manages: {', '.join(targets)}. Save the right one in Settings → Integrations → WhatsApp.")
            checks.append(_check("templates_access", "fail", "The saved WhatsApp Business Account ID is wrong",
                                 f"Meta says this token can't manage {waba_id} — that's why template submissions fail with “Object with ID … does not exist”.",
                                 fix))
        elif targets:
            checks.append(_check("templates_access", "ok", "Templates can be managed", f"The token can manage WhatsApp Business Account {waba_id}."))

    # ── 2. App Secret (without it every call from Meta is refused) ──
    if not creds.get("app_secret"):
        checks.append(_check("app_secret", "fail", "App Secret isn't saved",
                             "Sending works, but Meta's replies and delivery updates are refused without it — that's why messages stay at “sent” and replies don't appear.",
                             "Copy the App Secret from Meta App Dashboard → Settings → Basic, paste it in Settings → Integrations → WhatsApp, and save."))
    else:
        checks.append(_check("app_secret", "ok", "App Secret is saved", "Meta's calls can be verified."))

    # ── 3. Is the Meta app subscribed to this WhatsApp account? ──
    if token and waba_id:
        data, err = _meta_get(f"{waba_id}/subscribed_apps", token)
        if err and "nonexisting field" in err:
            # Meta answers this way when the ID isn't a WhatsApp Business Account at all.
            if not suggested_waba:
                _, found, _ = candidate_wabas(token)
                found = [w for w in found if w != waba_id]
                suggested_waba = found[0] if len(found) == 1 else None
            fix = (f"Meta lists WhatsApp Business Account {suggested_waba} for this token. Use that ID." if suggested_waba
                   else "Copy the WhatsApp Business Account ID from WhatsApp Manager → Account tools, and save it in Settings → Integrations → WhatsApp.")
            checks.append(_check("subscription", "fail", "The saved WhatsApp Business Account ID isn't a WhatsApp account",
                                 f"Meta doesn't recognise {waba_id} as one (it may be a business, phone number or app ID). That also stops templates from being created or synced.",
                                 fix))
        elif err:
            checks.append(_check("subscription", "warn", "Couldn't check the app subscription", err))
        elif not (data or {}).get("data"):
            checks.append(_check("subscription", "fail", "Your Meta app isn't subscribed to this WhatsApp account",
                                 "Meta has no app to send this account's replies and delivery updates to.",
                                 "In Meta App Dashboard → WhatsApp → Configuration → Webhook fields, subscribe to “messages”."))
        else:
            checks.append(_check("subscription", "ok", "Meta app is subscribed", "Replies and delivery updates are routed to your app."))

    # ── 4. What has actually happened ──
    ok_at, rejected_at = _parse(cfg.get("webhook_ok_at")), _parse(cfg.get("webhook_rejected_at"))
    last_inbound = db.query(func.max(Message.created_at)).filter(
        Message.tenant_id == tenant_id, Message.channel == ChannelType.WHATSAPP, Message.direction == MessageDirection.INBOUND).scalar()
    stuck = db.query(func.count(Message.id)).filter(
        Message.tenant_id == tenant_id, Message.channel == ChannelType.WHATSAPP, Message.direction == MessageDirection.OUTBOUND,
        Message.delivery_state == MessageDeliveryState.SENT, Message.channel_message_id.isnot(None),
        Message.created_at < _now() - timedelta(minutes=30), Message.created_at > _now() - timedelta(days=7)).scalar() or 0

    if rejected_at and (not ok_at or rejected_at > ok_at):
        reason = REJECT_REASONS.get(cfg.get("webhook_rejected_reason") or "", "Meta's last call was refused.")
        checks.append(_check("activity", "fail", "Meta is calling us but we're refusing it", reason,
                             "Save the correct App Secret in Settings → Integrations → WhatsApp."))
    elif stuck and (not ok_at or ok_at < _now() - timedelta(hours=24)):
        since = f"since {ok_at.astimezone(timezone(timedelta(hours=5, minutes=30))).strftime('%d %b')}" if ok_at else "ever"
        checks.append(_check("activity", "warn", f"{stuck} message{'s' if stuck != 1 else ''} sent but never confirmed",
                             f"We haven't received anything from Meta {since}, so delivery and replies can't show up.",
                             "Check the items above; if they're all fine, confirm the callback URL in Meta matches the address below."))
    elif ok_at:
        checks.append(_check("activity", "ok", "Meta is reaching us", f"Last update received {ok_at.strftime('%d %b, %H:%M UTC')}."))
    else:
        checks.append(_check("activity", "ok", "Nothing received yet", "No replies or delivery updates have come in since checks began. Send a template to a real number to test."))

    rank = {"ok": 0, "warn": 1, "fail": 2}
    status = max((c["status"] for c in checks), key=lambda s: rank[s])
    return {
        "status": status, "checks": checks, "webhook_url": webhook_url, "suggested_waba_id": suggested_waba,
        "facts": {
            "last_inbound_at": last_inbound.isoformat() if last_inbound else None,
            "stuck_sent": stuck,
            "webhook_ok_at": ok_at.isoformat() if ok_at else None,
            "webhook_rejected_at": rejected_at.isoformat() if rejected_at else None,
        },
    }
