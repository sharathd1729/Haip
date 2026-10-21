"""Site versions: autosave, submit, approve + publish, reject, restore, and the publish checklist.

Rules (same integrity model as Marketing Studio content):
  * Only the head draft (site.draft_version_id, status "draft") is ever rewritten, and only by a save that names the
    sha256 it was based on (a stale editor gets 409 version_changed, never a silent overwrite).
  * Saving over a submitted / approved / published head makes a NEW draft version; a pending review is withdrawn.
  * Approving publishes. An approval binds to the version's sha256, re-checked at publish time.
  * Nobody approves a version they wrote, submitted or asked the AI for, except the owner (decision D3).
"""
import hashlib
import json
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.models.media_asset import MediaAsset
from app.models.user import User
from app.models.website import Site, SiteVersion
from app.services import website_blocks as wb
from app.services.website_service import WebsiteError, site_settings

FROZEN = ("in_review", "approved", "published", "superseded", "rejected", "withdrawn")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def sha_of(doc: dict) -> str:
    return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def _role(user: User) -> str:
    r = getattr(user, "role", "")
    return getattr(r, "value", r) or ""


def get_version(db: Session, site: Site, version_id: str) -> SiteVersion:
    v = db.query(SiteVersion).filter_by(id=version_id, tenant_id=site.tenant_id, site_id=site.id).first()
    if not v:
        raise WebsiteError(404, "version_not_found", "That version doesn't exist.")
    return v


def head(db: Session, site: Site) -> SiteVersion:
    if not site.draft_version_id:
        raise WebsiteError(409, "no_draft", "This site has no draft.")
    return get_version(db, site, site.draft_version_id)


def usable_assets(db: Session, tenant_id: str, ids: set[str]) -> set[str]:
    if not ids:
        return set()
    rows = db.query(MediaAsset.id).filter(MediaAsset.tenant_id == tenant_id, MediaAsset.id.in_(list(ids)),
                                         MediaAsset.status == "active").all()
    return {r[0] for r in rows}


def clean_for_tenant(db: Session, tenant_id: str, doc: dict) -> tuple[dict, list[str]]:
    clean, problems = wb.validate_doc(doc)
    ids = wb.asset_ids(clean)
    keep = usable_assets(db, tenant_id, ids)
    removed = wb.strip_assets(clean, keep)
    if removed:
        problems.append(f"{removed} photo{'s' if removed != 1 else ''} not in your approved library {'were' if removed != 1 else 'was'} removed")
    return clean, problems


def _next_number(db: Session, site: Site) -> int:
    return (db.query(func.max(SiteVersion.number)).filter_by(site_id=site.id).scalar() or 0) + 1


def _withdraw(db: Session, site: Site, v: SiteVersion, actor_id: Optional[str]) -> None:
    if v.status in ("in_review", "approved"):
        v.status = "withdrawn"
        v.updated_at = _now()
        append_audit(db, tenant_id=site.tenant_id, actor_user_id=actor_id, action="website.version_withdrawn",
                     target_type="site_version", target_id=v.id, payload={"number": v.number, "reason": "edited"})


def new_draft(db: Session, site: Site, doc: dict, *, actor_id: Optional[str], origin: str = "human",
              note: Optional[str] = None) -> SiteVersion:
    cur = head(db, site) if site.draft_version_id else None
    if cur:
        _withdraw(db, site, cur, actor_id)
    v = SiteVersion(tenant_id=site.tenant_id, site_id=site.id, number=_next_number(db, site), doc=doc, sha256=sha_of(doc),
                    status="draft", origin=origin, note=note, created_by=actor_id)
    db.add(v)
    db.flush()
    site.draft_version_id = v.id
    site.updated_at = _now()
    return v


def save_draft(db: Session, site: Site, doc: dict, base_sha256: str, *, actor_id: str, origin: str = "human",
               note: Optional[str] = None) -> tuple[SiteVersion, list[str]]:
    cur = head(db, site)
    if cur.sha256 != base_sha256:
        raise WebsiteError(409, "version_changed", "Someone else changed this site. Reload to see their changes.")
    clean, problems = clean_for_tenant(db, site.tenant_id, doc)
    new_sha = sha_of(clean)
    if new_sha == cur.sha256:
        return cur, problems
    if cur.status == "draft":
        n = (db.query(SiteVersion)
             .filter_by(id=cur.id, tenant_id=site.tenant_id, status="draft", sha256=base_sha256)
             .update({"doc": clean, "sha256": new_sha, "updated_at": _now(), "origin": origin if cur.origin == "seed" else cur.origin},
                     synchronize_session=False))
        if n != 1:
            raise WebsiteError(409, "version_changed", "Someone else changed this site. Reload to see their changes.")
        db.refresh(cur)
        v = cur
    else:
        v = new_draft(db, site, clean, actor_id=actor_id, origin=origin, note=note)
    return v, problems


def submit(db: Session, site: Site, version_id: str, actor: User, note: Optional[str] = None) -> SiteVersion:
    v = get_version(db, site, version_id)
    if v.id != site.draft_version_id or v.status != "draft":
        raise WebsiteError(409, "not_submittable", "Only the current draft can be sent for approval.")
    problems = [c["title"] for c in checks(db, site, v.doc) if c["level"] == "block"]
    if problems:
        raise WebsiteError(422, "checks_failed", "Fix these before sending for approval.", problems)
    n = (db.query(SiteVersion).filter_by(id=v.id, status="draft", sha256=v.sha256)
         .update({"status": "in_review", "submitted_by": actor.id, "submitted_at": _now(), "updated_at": _now(),
                  "note": note or v.note}, synchronize_session=False))
    if n != 1:
        raise WebsiteError(409, "version_changed", "This draft changed while you were sending it. Try again.")
    db.refresh(v)
    append_audit(db, tenant_id=site.tenant_id, actor_user_id=actor.id, action="website.version_submitted",
                 target_type="site_version", target_id=v.id, payload={"number": v.number, "sha256": v.sha256})
    return v


def _may_approve(actor: User, v: SiteVersion) -> bool:
    if _role(actor) == "owner":
        return True
    return actor.id not in {v.created_by, v.submitted_by}


def publish(db: Session, site: Site, version_id: str, actor: User, seen_sha256: Optional[str] = None) -> SiteVersion:
    """Approve + publish. An in-review version may be published by an approver who didn't write it; the owner may also
    publish the current draft directly."""
    v = get_version(db, site, version_id)
    if seen_sha256 and seen_sha256 != v.sha256:
        raise WebsiteError(409, "version_changed", "This version changed since you looked at it.")
    if wb.validate_doc(v.doc)[0] != v.doc or sha_of(v.doc) != v.sha256:
        raise WebsiteError(409, "integrity_failed", "This version failed its integrity check and can't be published.")
    if v.status == "draft":
        if v.id != site.draft_version_id or _role(actor) != "owner":
            raise WebsiteError(403, "approval_required", "Send this draft for approval; an owner or manager publishes it.")
        problems = [c["title"] for c in checks(db, site, v.doc) if c["level"] == "block"]
        if problems:
            raise WebsiteError(422, "checks_failed", "Fix these before publishing.", problems)
    elif v.status == "in_review":
        if not _may_approve(actor, v):
            raise WebsiteError(403, "self_approval", "Someone else has to approve a version you made or sent.")
    else:
        raise WebsiteError(409, "not_publishable", f"A {v.status.replace('_', ' ')} version can't be published.")
    n = (db.query(SiteVersion).filter_by(id=v.id, status=v.status, sha256=v.sha256)
         .update({"status": "published", "approved_by": actor.id, "approved_at": _now(), "published_by": actor.id,
                  "published_at": _now(), "updated_at": _now()}, synchronize_session=False))
    if n != 1:
        raise WebsiteError(409, "version_changed", "This version changed while you were publishing it.")
    if site.live_version_id and site.live_version_id != v.id:
        db.query(SiteVersion).filter_by(id=site.live_version_id, status="published").update(
            {"status": "superseded", "updated_at": _now()}, synchronize_session=False)
    site.live_version_id = v.id
    site.status = "live"
    site.updated_at = _now()
    db.refresh(v)
    append_audit(db, tenant_id=site.tenant_id, actor_user_id=actor.id, action="website.version_published",
                 target_type="site_version", target_id=v.id, payload={"number": v.number, "sha256": v.sha256})
    return v


def reject(db: Session, site: Site, version_id: str, actor: User, note: Optional[str]) -> SiteVersion:
    v = get_version(db, site, version_id)
    n = (db.query(SiteVersion).filter_by(id=v.id, status="in_review")
         .update({"status": "rejected", "note": (note or "")[:500] or v.note, "updated_at": _now()}, synchronize_session=False))
    if n != 1:
        raise WebsiteError(409, "not_in_review", "Only a version waiting for approval can be sent back.")
    db.refresh(v)
    append_audit(db, tenant_id=site.tenant_id, actor_user_id=actor.id, action="website.version_rejected",
                 target_type="site_version", target_id=v.id, payload={"number": v.number, "note": (note or "")[:500]})
    return v


def restore(db: Session, site: Site, version_id: str, actor: User) -> SiteVersion:
    old = get_version(db, site, version_id)
    clean, _ = clean_for_tenant(db, site.tenant_id, old.doc)
    v = new_draft(db, site, clean, actor_id=actor.id, origin="restore", note=f"Restored from version {old.number}")
    append_audit(db, tenant_id=site.tenant_id, actor_user_id=actor.id, action="website.version_restored",
                 target_type="site_version", target_id=v.id, payload={"from": old.number, "to": v.number})
    return v


def set_paused(db: Session, site: Site, paused: bool, actor: User) -> Site:
    if paused:
        site.status = "paused"
    else:
        site.status = "live" if site.live_version_id else "draft"
    site.updated_at = _now()
    append_audit(db, tenant_id=site.tenant_id, actor_user_id=actor.id, action="website.paused" if paused else "website.resumed",
                 target_type="site", target_id=site.id, payload={})
    return site


def history(db: Session, site: Site, limit: int = 30) -> list[dict]:
    rows = (db.query(SiteVersion).filter_by(tenant_id=site.tenant_id, site_id=site.id)
            .order_by(SiteVersion.number.desc()).limit(limit).all())
    return [{"id": v.id, "number": v.number, "status": v.status, "origin": v.origin, "note": v.note,
             "sha256": v.sha256, "created_by": v.created_by, "submitted_by": v.submitted_by,
             "approved_by": v.approved_by, "published_at": v.published_at.isoformat() if v.published_at else None,
             "updated_at": v.updated_at.isoformat() if v.updated_at else None} for v in rows]


def checks(db: Session, site: Site, doc: dict) -> list[dict]:
    """The publish checklist. level "block" stops publishing; "warn" is shown but allowed."""
    from app.models.tenant import Tenant
    from app.services import business_data_service as bds
    from app.services.invoice_service import get_profile
    from app.services.payment_link_service import razorpay_credentials
    from app.services.website_service import bookable_properties

    tenant = db.get(Tenant, site.tenant_id)
    cfg = site_settings(site)
    out: list[dict] = []

    def add(key: str, ok: bool, title: str, detail: str, level: str = "warn", fix: Optional[str] = None) -> None:
        out.append({"key": key, "ok": ok, "level": "ok" if ok else level, "title": title, "detail": detail, "fix": fix})

    keys = {p["key"] for p in doc.get("pages", [])}
    add("contact_page", "contact" in keys, "Contact page", "Razorpay checks for it before activating payments.", "block", "page:contact")
    add("policies_page", "policies" in keys, "Policies page", "Cancellation and refund terms must be public.", "block", "page:policies")
    contact = (doc.get("site") or {}).get("contact") or {}
    add("contact_details", bool(contact.get("phone") or contact.get("whatsapp") or contact.get("email")),
        "A phone, WhatsApp or email to reach you", "Shown in the footer and on the Contact page.", "block", "site:contact")
    bad_seo = [p["title"] for p in doc.get("pages", []) if p["key"] not in ("stay", "manage", "book")
               and (not p["seo"]["title"] or not 50 <= len(p["seo"]["description"]) <= 160)]
    add("seo", not bad_seo, "Search previews", "Needs a title and a 50–160 character description: " + ", ".join(bad_seo) if bad_seo
        else "Every page has a title and description.", "warn", "seo")
    props = bookable_properties(db, site.tenant_id, cfg.property_ids or None)
    add("stays", bool(props), "Stays to show", f"{len(props)} active stay{'s' if len(props) != 1 else ''} from HAIP Properties.", "block", "settings")
    if cfg.booking_mode in ("instant", "deposit"):
        add("razorpay", bool(razorpay_credentials(db, site.tenant_id)), "Razorpay connected",
            "Guests pay through your own Razorpay account.", "block", "payments")
    try:
        cancel = bds.get_effective(db, site.tenant_id, "cancellation_policy", "default")
        pay = bds.get_effective(db, site.tenant_id, "payment_policy", "default")
    except Exception:  # noqa: BLE001
        cancel = pay = None
    add("cancellation_policy", bool(cancel), "Cancellation policy published",
        "Set it in Knowledge › Structured business data; the site shows it word for word.",
        "block" if cfg.booking_mode in ("instant", "deposit") else "warn", "business_data")
    add("payment_policy", bool(pay), "Payment policy published", "Advance and balance terms shown before guests pay.", "warn", "business_data")
    prof = get_profile(tenant) if tenant else None
    add("legal", bool(prof and prof.legal_name and prof.address), "Legal name and address",
        "Shown on the Policies page and on invoices (Settings › Invoices).", "warn", "invoice_profile")
    add("gstin", bool(prof and prof.gstin), "GSTIN", "Shown in the footer and needed on GST invoices.", "warn", "invoice_profile")
    return out
