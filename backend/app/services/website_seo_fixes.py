"""The technical checker's fixes: ONLY what HAIP itself draws on the site (owner doc fix #9).

* Photo descriptions: a site photo with no description gets its photo tag's description (marketing_vision tags, made
  when the photo was added). That is the photo library's own field, so it shows on the live site at once.
* Search titles: a page whose search title is not 10-70 characters gets "<page title> | <business name>" in the site
  DRAFT. The live site changes only when a person publishes the draft (website approval, unchanged).

``plan`` never writes; ``apply`` re-plans from the current state, so a stale plan can never overwrite a person's edit.
Everything else the checker finds is reported, never changed.
"""

from __future__ import annotations

import copy

from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.models.media_asset import MediaAsset
from app.models.tenant import Tenant
from app.models.website import Site, SiteVersion
from app.services import website_bindings
from app.services import website_public_service as pub
from app.services import website_spec_service as wspec
from app.services import website_version_service as versions

TITLE_MIN, TITLE_MAX, ALT_MAX = 10, 70, 200


def load(db: Session, tenant: Tenant, site: Site) -> dict | None:
    """The live doc (else the draft) with its bound data and photos, as the launch report reads it. None = not v2."""
    live = db.get(SiteVersion, site.live_version_id) if site.live_version_id else None
    doc = live.doc if live is not None else versions.head(db, site).doc
    if not wspec.is_v2(doc):
        return None
    data = website_bindings.resolve(db, tenant, doc, site=site)
    return {"doc": doc, "bound": data["bound"], "assets": pub.asset_urls(db, tenant.id, doc, extra=data["asset_ids"])}


def _title_for(page: dict, brand: str) -> str | None:
    t = f"{(page.get('title') or '').strip()} | {brand}"[:TITLE_MAX].rstrip(" |")
    return t if TITLE_MIN <= len(t) <= TITLE_MAX else None


def plan(db: Session, tenant: Tenant, site: Site, loaded: dict | None = None) -> dict:
    loaded = loaded or load(db, tenant, site)
    if loaded is None:
        return {"alt": [], "titles": []}
    no_alt = [a for a, v in loaded["assets"].items() if not (v.get("alt") or "").strip()]
    alt = []
    if no_alt:
        for m in db.query(MediaAsset).filter(MediaAsset.tenant_id == tenant.id, MediaAsset.id.in_(no_alt)):
            desc = ((m.tags or {}).get("description") or "").strip()
            if desc and not (m.alt_text or "").strip():
                alt.append({"asset_id": m.id, "text": desc[:ALT_MAX]})
    brand = tenant.brand_name or tenant.name or ""
    titles = []
    head = versions.head(db, site)
    if wspec.is_v2(head.doc):
        for p in head.doc.get("pages") or []:
            cur = ((p.get("seo") or {}).get("title") or "").strip()
            new = None if TITLE_MIN <= len(cur) <= TITLE_MAX else _title_for(p, brand)
            if new:
                titles.append({"slug": p["slug"], "from": cur, "title": new})
    return {"alt": alt, "titles": titles}


def apply(db: Session, tenant: Tenant, site: Site, given: dict | None = None, *, actor_id: str | None) -> dict:
    """Apply the CURRENT plan (``given`` is only a hint; it is re-planned). Returns what changed."""
    fresh = plan(db, tenant, site)
    done = {"alt": 0, "titles": 0, "draft_version_id": None}
    for f in fresh["alt"]:
        n = (
            db.query(MediaAsset)
            .filter(
                MediaAsset.id == f["asset_id"],
                MediaAsset.tenant_id == tenant.id,
                (MediaAsset.alt_text.is_(None)) | (MediaAsset.alt_text == ""),
            )
            .update({"alt_text": f["text"]}, synchronize_session=False)
        )
        done["alt"] += n
    if fresh["titles"]:
        head = versions.head(db, site)
        doc = copy.deepcopy(head.doc)
        want = {t["slug"]: t["title"] for t in fresh["titles"]}
        for p in doc["pages"]:
            if p["slug"] in want:
                p.setdefault("seo", {})["title"] = want[p["slug"]]
        v, _ = versions.save_draft(
            db, site, doc, head.sha256, actor_id=actor_id, origin="ai", note="SEO agency: search titles"
        )
        db.flush()  # the site's new draft pointer must survive a later refresh
        done["titles"], done["draft_version_id"] = len(want), v.id
    if done["alt"] or done["titles"]:
        append_audit(
            db,
            tenant_id=tenant.id,
            actor_user_id=actor_id,
            action="website.seo_fixes_applied",
            target_type="site",
            target_id=site.id,
            payload={**done, **({} if actor_id else {"actor": "seo_agency"})},
        )
    return done
