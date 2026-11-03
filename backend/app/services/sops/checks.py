"""Automatic SOP checks. Each returns {result: ok|fail|unknown, detail}; `unknown` = HAIP could not check (not connected,
the platform did not answer), so the step asks for a screenshot instead. Only HAIP's own data and APIs the workspace
connected with its own token: nothing is scraped and HAIP never logs in anywhere. Run from Celery (sops.check_instance),
never in a request handler, because some call Meta.
"""

from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.ical_feed import ICalFeed
from app.models.integration import Integration
from app.models.sop import SopInstance
from app.models.tenant import Tenant
from app.services.knowledge_sources import _instagram_integration


def _r(result: str, detail: str) -> dict:
    return {"result": result, "detail": detail}


def _active(db: Session, tenant_id: str, kind: str):
    return db.query(Integration).filter_by(tenant_id=tenant_id, kind=kind, status="active").first()


def _connected(kind: str, label: str) -> Callable[[Session, Tenant, SopInstance], dict]:
    def check(db: Session, tenant: Tenant, inst: SopInstance) -> dict:
        if _active(db, tenant.id, kind) is not None:
            return _r("ok", f"{label} is connected to HAIP.")
        return _r("fail", f"{label} is not connected to HAIP yet.")

    return check


def instagram_bio(db: Session, tenant: Tenant, inst: SopInstance) -> dict:
    from app.adapters.instagram.meta_graph import InstagramGraphAdapter
    from app.core.encryption import decrypt_credentials

    integ = _instagram_integration(db, tenant.id)
    if integ is None or not integ.credentials_kms_blob:
        return _r("unknown", "Connect Instagram to HAIP so it can read your bio, or add a screenshot.")
    creds = decrypt_credentials(integ.credentials_kms_blob)
    account = (integ.config or {}).get("instagram_business_account_id", "")
    try:
        fields = InstagramGraphAdapter(
            access_token=creds.get("access_token", ""), ig_account_id=account
        ).get_account_fields()
    except Exception as exc:  # noqa: BLE001 -- a platform hiccup is "could not check", never a crash
        return _r("unknown", f"HAIP couldn't read your Instagram profile ({type(exc).__name__}). Try again later.")
    if (fields.get("biography") or "").strip():
        return _r("ok", "Your Instagram bio is filled in.")
    return _r("fail", "Your Instagram bio is empty.")


def whatsapp_name(db: Session, tenant: Tenant, inst: SopInstance) -> dict:
    from app.services import wa_health_service
    from app.services.lead_alert_sender import wa_credentials

    phone_id, token = wa_credentials(db, tenant.id)
    if not phone_id or not token:
        return _r(
            "unknown", "Connect your WhatsApp number to HAIP so it can read the display name, or add a screenshot."
        )
    data, err = wa_health_service._meta_get(phone_id, token, {"fields": "verified_name"})
    if err:
        return _r("unknown", f"HAIP couldn't read your WhatsApp profile: {err}")
    shown, brand = (data or {}).get("verified_name") or "", tenant.brand_name or tenant.name or ""
    if shown and brand and (brand.casefold() in shown.casefold() or shown.casefold() in brand.casefold()):
        return _r("ok", f"WhatsApp shows “{shown}”.")
    return _r("fail", f"WhatsApp shows “{shown or 'no name'}”, your brand is “{brand}”.")


def ical_import(db: Session, tenant: Tenant, inst: SopInstance) -> dict:
    """The OTA's own calendar link is added in HAIP for this property and its last read worked (ical_feeds)."""
    from app.services.sops.catalogue import BY_KEY
    from app.services.sops.inputs_ota import matching_feed

    feeds = db.query(ICalFeed).filter_by(tenant_id=tenant.id, property_id=inst.property_id, is_active=True).all()
    f = matching_feed(feeds, BY_KEY[inst.template_key].platform)
    if f is None:
        return _r("fail", "This platform's calendar link is not added in HAIP yet (name the link after the platform).")
    if f.last_status == "error":
        return _r("fail", f"HAIP could not read that calendar link: {f.last_error or 'unknown error'}")
    if f.last_status != "ok":
        return _r("unknown", "HAIP has not read that calendar link yet. Check again in 30 minutes.")
    return _r("ok", f"HAIP reads the {f.name} calendar for this property.")


CHECKS: dict[str, Callable[[Session, Tenant, SopInstance], dict]] = {
    "connected:google_business": _connected("google_business", "Google Business Profile"),
    "connected:instagram": _connected("instagram", "Instagram"),
    "connected:facebook_page": _connected("facebook_page", "Facebook Page"),
    "ical_import": ical_import,
    "instagram_bio": instagram_bio,
    "whatsapp_name": whatsapp_name,
}


def run(key: str, db: Session, tenant: Tenant, inst: SopInstance) -> dict:
    return {**CHECKS[key](db, tenant, inst), "at": datetime.now(UTC).isoformat()}
