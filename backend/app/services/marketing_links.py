"""Links that say where a guest came from (agency M6): UTM tags on every link HAIP puts out, and the link-in-bio page.

utm_campaign names the content or ad itself: "c-<first 8 of the content id>" for a post, "a-<first 8 of the ad draft
id>" for an ad, "cr-<first 8 of the deal id>" for a creator's link (agency M7). The website already keeps utm_* on every enquiry and booking (inquiry.custom_fields.utm), so a
booking made after tapping a bio link or a Google post button traces back to the exact post (marketing_attribution).
No cookies, no personal data in the URL.
"""
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy.orm import Session

from app.models.marketing import MarketingContent, MarketingPublishAttempt
from app.models.marketing_ads import MarketingAdDraft

BIO_ITEMS = 12


def campaign_for_content(content_id: str) -> str:
    return f"c-{content_id.replace('-', '')[:8]}"


def campaign_for_ad(draft_id: str) -> str:
    return f"a-{draft_id.replace('-', '')[:8]}"


def utm(*, source: str, medium: str, campaign: str, content: Optional[str] = None) -> dict:
    out = {"utm_source": source, "utm_medium": medium, "utm_campaign": campaign}
    if content:
        out["utm_content"] = content
    return out


def tag_url(url: str, params: dict) -> str:
    """Add UTM parameters, keeping the link's own query and any utm_* it already carries."""
    if not url:
        return url
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    for k, v in params.items():
        query.setdefault(k, v)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _match(db: Session, model, tenant_id: str, short: str) -> Optional[str]:
    if not short or len(short) != 8 or not short.isalnum():
        return None
    ids = [i for (i,) in db.query(model.id).filter(model.tenant_id == tenant_id).limit(5000)
           if i.replace("-", "")[:8] == short.lower()]
    return ids[0] if len(ids) == 1 else None


def resolve_campaign(db: Session, tenant_id: str, campaign: Optional[str]) -> dict:
    """{content_id} / {ad_draft_id, content_id} / {creator_deal_id} for a HAIP utm_campaign, {} for anything else."""
    c = (campaign or "").strip().lower()
    if c.startswith("cr-"):                                  # a creator deal's link (agency M7)
        from app.models.marketing_partners import MarketingCreatorDeal
        did = _match(db, MarketingCreatorDeal, tenant_id, c[3:])
        return {"creator_deal_id": did} if did else {}
    if c.startswith("c-"):
        cid = _match(db, MarketingContent, tenant_id, c[2:])
        return {"content_id": cid} if cid else {}
    if c.startswith("a-"):
        did = _match(db, MarketingAdDraft, tenant_id, c[2:])
        if did:
            draft = db.query(MarketingAdDraft).filter_by(id=did, tenant_id=tenant_id).first()
            return {"ad_draft_id": did, "content_id": draft.content_id if draft else None}
    return {}


def content_by_permalink(db: Session, tenant_id: str, urls: list[str]) -> dict[str, str]:
    """Instagram post URL (as a referral reports it) -> HAIP content id, for posts HAIP published."""
    def norm(u: str) -> str:
        p = urlsplit(u or "")
        return (p.netloc.replace("www.", "") + p.path).rstrip("/").lower()
    wanted = {norm(u): u for u in urls if u}
    if not wanted:
        return {}
    out = {}
    for content_id, link in (db.query(MarketingPublishAttempt.content_id, MarketingPublishAttempt.permalink)
                             .filter(MarketingPublishAttempt.tenant_id == tenant_id,
                                     MarketingPublishAttempt.permalink.isnot(None))):
        key = norm(link)
        if key in wanted:
            out[wanted[key]] = content_id
    return out


def bio_items(db: Session, tenant_id: str, site_url: str) -> list[dict]:
    """The latest posts HAIP published on Instagram, each with a link to the website tagged with that post."""
    rows = (db.query(MarketingPublishAttempt, MarketingContent)
            .join(MarketingContent, MarketingContent.id == MarketingPublishAttempt.content_id)
            .filter(MarketingPublishAttempt.tenant_id == tenant_id, MarketingPublishAttempt.status == "published",
                    MarketingPublishAttempt.channel == "instagram")
            .order_by(MarketingPublishAttempt.published_at.desc()).limit(BIO_ITEMS * 2).all())
    seen, out = set(), []
    for attempt, item in rows:
        if item.id in seen:
            continue
        seen.add(item.id)
        out.append({"title": item.title, "kind": item.kind, "permalink": attempt.permalink,
                    "url": tag_url(site_url, utm(source="instagram", medium="bio", campaign=campaign_for_content(item.id),
                                                 content=item.kind))})
        if len(out) == BIO_ITEMS:
            break
    return out
