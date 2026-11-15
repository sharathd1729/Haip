"""Automatic SOP checks. Each returns {result: ok|fail|unknown, detail}; `unknown` = HAIP could not check (not connected,
the platform did not answer), so the step asks for a screenshot instead. Only HAIP's own data and APIs the workspace
connected with its own token: nothing is scraped and HAIP never logs in anywhere. Run from Celery (sops.check_instance),
never in a request handler, because some call Meta.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

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


def _ig_fields(db: Session, tenant: Tenant, inst: SopInstance) -> dict | str:
    """The account's profile fields, read once per check run (cached on the instance object); a str = why not."""
    from app.adapters.instagram.meta_graph import InstagramGraphAdapter
    from app.core.encryption import decrypt_credentials

    cached = getattr(inst, "_ig_fields_cache", None)
    if cached is not None:
        return cached
    integ = _instagram_integration(db, tenant.id)
    if integ is None or not integ.credentials_kms_blob:
        out: dict | str = "Connect Instagram to HAIP so it can read your profile, or add a screenshot."
    else:
        creds = decrypt_credentials(integ.credentials_kms_blob)
        account = (integ.config or {}).get("instagram_business_account_id", "")
        try:
            out = InstagramGraphAdapter(
                access_token=creds.get("access_token", ""), ig_account_id=account
            ).get_account_fields() or {}
        except Exception as exc:  # noqa: BLE001 -- a platform hiccup is "could not check", never a crash
            out = f"HAIP couldn't read your Instagram profile ({type(exc).__name__}). Try again later."
    inst._ig_fields_cache = out
    return out


def _rubric(item: str, fn) -> Callable[[Session, Tenant, SopInstance], dict]:
    """A profile-score item (marketing_profile_score): ok only at full marks; the points are stored with the result."""
    from app.services import marketing_profile_score as profile

    def check(db: Session, tenant: Tenant, inst: SopInstance) -> dict:
        fields = _ig_fields(db, tenant, inst)
        if isinstance(fields, str):
            return _r("unknown", fields)
        from app.services.marketing_ai_service import get_profile

        points, detail = fn(fields, tenant, get_profile(tenant).get("city"))
        full = profile.ITEMS[item]["points"]
        return {**_r("ok" if points >= full else "fail", detail), "points": points, "max": full}

    return check


instagram_bio = _rubric("bio_first_line", lambda f, t, city: _ps().bio_line_points(f.get("biography") or "", city))


def _ps():
    from app.services import marketing_profile_score
    return marketing_profile_score


def instagram_recent(db: Session, tenant: Tenant, inst: SopInstance) -> dict:
    """Recent posts for the profile score: a post in 7 days = full marks, in 30 days = half (any app's posts)."""
    from app.models.marketing import InstagramPostMetricDaily

    if _instagram_integration(db, tenant.id) is None:
        return _r("unknown", "Connect Instagram to HAIP so it can see your posts, or add a screenshot.")

    def posts(days: int) -> int:
        return (
            db.query(InstagramPostMetricDaily.media_id)
            .filter(InstagramPostMetricDaily.tenant_id == tenant.id,
                    InstagramPostMetricDaily.posted_at >= _since(days).isoformat())
            .distinct()
            .count()
        )

    if posts(7):
        return {**_r("ok", "Posted in the last 7 days."), "points": 10, "max": 10}
    if posts(30):
        return {**_r("fail", "Last post is more than a week old."), "points": 5, "max": 10}
    return {**_r("fail", "No post in the last 30 days: the account reads as closed."), "points": 0, "max": 10}


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


def _since(days: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)


def gbp_posted_7d(db: Session, tenant: Tenant, inst: SopInstance) -> dict:
    """A Google post published FROM HAIP in the last 7 days (marketing_publish_attempts). Posts made in Google directly
    are invisible to HAIP: those need a screenshot."""
    from app.models.marketing import MarketingPublishAttempt

    n = (
        db.query(MarketingPublishAttempt)
        .filter(
            MarketingPublishAttempt.tenant_id == tenant.id,
            MarketingPublishAttempt.channel == "google",
            MarketingPublishAttempt.status == "published",
            MarketingPublishAttempt.published_at >= _since(7),
        )
        .count()
    )
    if n:
        return _r("ok", f"{n} Google post(s) from HAIP in the last 7 days.")
    return _r("fail", "No Google post from HAIP in the last 7 days. Posted in Google directly? Add a screenshot.")


def google_reviews_answered(db: Session, tenant: Tenant, inst: SopInstance) -> dict:
    """Every Google review older than 2 days has a posted reply (marketing_guest_reviews, synced hourly)."""
    from app.models.marketing import MarketingGuestReview

    if _active(db, tenant.id, "google_business") is None:
        return _r("unknown", "Connect Google to HAIP so it can see your reviews, or add a screenshot.")
    cutoff = _since(2).isoformat()
    n = (
        db.query(MarketingGuestReview)
        .filter(
            MarketingGuestReview.tenant_id == tenant.id,
            MarketingGuestReview.source == "google",
            MarketingGuestReview.reply_status != "posted",
            MarketingGuestReview.reviewed_at.isnot(None),
            MarketingGuestReview.reviewed_at <= cutoff,
        )
        .count()
    )
    if n:
        return _r("fail", f"{n} Google review(s) older than 2 days have no reply.")
    return _r("ok", "Every Google review older than 2 days has a reply.")


def instagram_posted_7d(db: Session, tenant: Tenant, inst: SopInstance) -> dict:
    """A post on the account in the last 7 days, from the insights poller's copy of the latest posts (any app)."""
    from app.models.marketing import InstagramPostMetricDaily

    if _instagram_integration(db, tenant.id) is None:
        return _r("unknown", "Connect Instagram to HAIP so it can see your posts, or add a screenshot.")
    n = (
        db.query(InstagramPostMetricDaily.media_id)
        .filter(
            InstagramPostMetricDaily.tenant_id == tenant.id, InstagramPostMetricDaily.posted_at >= _since(7).isoformat()
        )
        .distinct()
        .count()
    )
    if n:
        return _r("ok", f"{n} Instagram post(s) in the last 7 days.")
    return _r("fail", "No Instagram post in the last 7 days.")


def website_live(db: Session, tenant: Tenant, inst: SopInstance) -> dict:
    from app.services import website_service

    site = website_service.get_site(db, tenant.id)
    if site is not None and site.live_version_id and site.status == "live":
        return _r("ok", f"Your website is live at {website_service.primary_host(db, site)}.")
    return _r("fail", "Your website is not live yet.")


CHECKS: dict[str, Callable[[Session, Tenant, SopInstance], dict]] = {
    "connected:google_business": _connected("google_business", "Google Business Profile"),
    "connected:instagram": _connected("instagram", "Instagram"),
    "connected:facebook_page": _connected("facebook_page", "Facebook Page"),
    "ical_import": ical_import,
    "gbp_posted_7d": gbp_posted_7d,
    "google_reviews_answered": google_reviews_answered,
    "instagram_posted_7d": instagram_posted_7d,
    "website_live": website_live,
    "instagram_bio": instagram_bio,
    "instagram_name": _rubric(
        "name_field", lambda f, t, city: _ps().name_points(f.get("name") or "", t.brand_name or t.name or "", city)
    ),
    "instagram_bio_body": _rubric("bio_body", lambda f, t, city: _ps().bio_body_points(f.get("biography") or "")),
    "instagram_link": _rubric("link", lambda f, t, city: _ps().link_points(f.get("website") or "")),
    "instagram_handle": _rubric("handle", lambda f, t, city: _ps().handle_points(f.get("username") or "")),
    "instagram_recent": instagram_recent,
    "whatsapp_name": whatsapp_name,
}


def run(key: str, db: Session, tenant: Tenant, inst: SopInstance) -> dict:
    return {**CHECKS[key](db, tenant, inst), "at": datetime.now(UTC).isoformat()}
