"""The studio Home's setup checklist: what is still missing before the agency can run on its own, each with ONE fix.

Every check reuses the rule that already decides it elsewhere (publish preflight, photo picker, agency settings, ads
cap, channel connections); nothing here is a second definition. Server keys are reported by NAME only ("ask your HAIP
admin to set X"), never their values.

Item: {key, label, done, required, detail, fix: {tab, label} | None, admin_keys: [names]}.
`tab` is a Studio tab value the page opens (deep link); "integrations" means Settings > Integrations.
"""
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.integration import Integration
from app.models.tenant import Tenant
from app.services import marketing_agency_service as agency
from app.services import marketing_ai_service as ai
from app.services import marketing_ads_service as ads
from app.services import marketing_photos as photos
from app.services import marketing_publish_service as publish

MIN_PHOTOS = 12        # about two weeks of posts without repeating a photo
MIN_CLIPS = 2          # a reel needs at least two clips (marketing_reel)


def _active(db: Session, tenant_id: str, kind: str) -> bool:
    return db.query(Integration.id).filter_by(tenant_id=tenant_id, kind=kind, status="active").first() is not None


def missing_server_keys() -> list[str]:
    """Server settings the studio needs that are empty on this HAIP server (names only)."""
    need = {"NVIDIA_API_KEY": bool(settings.NVIDIA_API_KEY or settings.NVIDIA_API_KEY_MID),
            "GEMINI_API_KEY": bool(settings.GEMINI_API_KEY),
            "INSTAGRAM_APP_ID": bool(settings.INSTAGRAM_APP_ID), "API_BASE_URL": bool(settings.API_BASE_URL),
            "S3_BUCKET_NAME": bool(settings.S3_BUCKET_NAME)}
    return [k for k, ok in need.items() if not ok]


def _item(key, label, done, *, required=True, detail="", tab=None, fix=None, keys=()) -> dict:
    return {"key": key, "label": label, "done": bool(done), "required": required, "detail": detail,
            "fix": {"tab": tab, "label": fix} if tab and not done else None, "admin_keys": list(keys)}


def _research_item(db: Session, tenant: Tenant) -> dict:
    """Optional: outside research sources the owner switched on but the server or Facebook connection can't serve yet."""
    from app.services import marketing_research_sources as research
    on = [s for s in research.status(db, tenant) if s["on"]]
    stuck = [s for s in on if not s["ready"]]
    keys = sorted({k for s in stuck for k in s["missing_keys"]})
    detail = ("Switched on but not working yet: " + "; ".join(
        s["label"] + (" (needs the Facebook connection)" if s["needs_facebook_login"] else "") for s in stuck) + "."
              if stuck else ("Off. Switch sources on in Plan > Sources." if not on else f"{len(on)} sources on."))
    return _item("research", "Outside research sources working", bool(on) and not stuck, required=False, detail=detail,
                 tab="sources", fix="Open sources", keys=keys)


def checklist(db: Session, tenant: Tenant) -> dict:
    profile = ai.get_profile(tenant)
    lib = photos.library(db, tenant.id, videos=True)
    n_clips = sum(1 for a in lib if (a.mime_type or "").startswith("video/"))
    n_photos = len(lib) - n_clips
    ig = publish.instagram_problem(db, tenant.id)
    section = ((tenant.brand_config or {}).get(agency.SETTINGS_KEY) or {})
    cap = ads.get_settings(tenant)["monthly_cap_inr"]
    missing = missing_server_keys()
    items = [
        _item("module", "Marketing Studio switched on", True),
        _item("profile", "Brand profile and voice confirmed", profile.get("description") and profile.get("voice"),
              detail="Describe the business and pick how you sound (We are / We are not).", tab="profile",
              fix="Fill in the profile"),
        _item("photos", f"At least {MIN_PHOTOS} photos in the library", n_photos >= MIN_PHOTOS,
              detail=f"{n_photos} of {MIN_PHOTOS} approved photos. Drafts without a photo wait as \"Needs photos\".",
              tab="library", fix="Upload photos"),
        _item("clips", f"At least {MIN_CLIPS} video clips for Reels", n_clips >= MIN_CLIPS, required=False,
              detail=f"{n_clips} clips. Without them the plan makes posts instead of Reels.", tab="library",
              fix="Upload clips"),
        _item("instagram", "Instagram connected with permission to post", ig is None, detail=ig or "",
              tab="integrations", fix="Connect Instagram", keys=[k for k in ("INSTAGRAM_APP_ID", "API_BASE_URL") if k in missing]),
        _item("facebook_login", "Facebook connection for competitor research", _active(db, tenant.id, "instagram_fb"),
              required=False, detail="Optional: public numbers of competitor accounts.", tab="research",
              fix="Connect Facebook", keys=[] if settings.META_APP_ID else ["META_APP_ID"]),
        _item("autonomy", "Autonomy chosen for each AI role", isinstance(section, dict) and "agency" in section,
              detail="Decide what runs on its own and what waits for you.", tab="agency", fix="Choose autonomy"),
        _item("ads_budget", "Monthly ads budget set", cap > 0, required=False,
              detail="0 means HAIP never spends on ads.", tab="ads", fix="Set a budget"),
        _research_item(db, tenant),
        _item("server", "AI and storage keys on the HAIP server", not missing,
              detail="" if not missing else "Ask your HAIP admin to set: " + ", ".join(missing) + ".", keys=missing),
    ]
    required = [i for i in items if i["required"]]
    return {"items": items, "done": sum(i["done"] for i in required), "total": len(required),
            "ready": all(i["done"] for i in required)}
