"""What the copywriter sees besides the business facts, so a draft fits the plan and the account's history.

  * the plan: goals, audience, position, pillars, out-of-scope, and this entry's pillar and idea;
  * the other posts planned for the same week (so seven drafts do not say the same thing);
  * openings of recent posts (so captions do not repeat);
  * reviewers' notes: on this post first, then recent notes on other posts (so feedback is not lost);
  * the descriptions of photos in the library (so each slot asks for a photo the workspace actually has).
Everything here is the workspace's own data, read-only, capped in size.

`business_facts` is the other half of what every Studio step (brand voice, audit, plan, copywriter, critic, brief)
knows: the owner-approved knowledge base and the published business records, read through the same rules the
concierge uses. It is part of `marketing_ai_service._facts`, so the number grounding accepts figures from it too.
"""
from typing import Any, Optional

import structlog
from sqlalchemy.orm import Session

from app.models.marketing import MarketingApproval, MarketingContent, MarketingContentVersion, MarketingPlan
from app.models.media_asset import MediaAsset

MAX_SIBLINGS = 14
MAX_RECENT = 8
MAX_NOTES = 6
MAX_PHOTOS = 40
MAX_KB_ENTRIES = 40
MAX_KB_CHARS = 8000
MAX_KB_ENTRY_CHARS = 1200
MAX_RECORDS = 12               # per kind (packages, destinations, itineraries)

log = structlog.get_logger()


def _strip(value: Any) -> Any:
    from app.services.price_policy import strip_prices
    if isinstance(value, str):
        return strip_prices(value)
    if isinstance(value, dict):
        return {k: _strip(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_strip(v) for v in value]
    return value


def business_facts(db: Session, tenant, property_id: Optional[str] = None) -> dict:
    """{"knowledge": [...], "business_data": {...}}, each left out when empty. No prices: price figures are stripped
    from all text and money keys withheld (price_policy), and payment / cancellation terms appear only in the
    "grounded" price mode, exactly as in the concierge prompt."""
    from app.services import knowledge_service, price_policy, sales_gateway

    out: dict = {}
    kb, used = [], 0
    for e in knowledge_service.usable_entries(db, tenant.id, property_id=property_id, limit=MAX_KB_ENTRIES):
        line = _strip(f"Q: {e.question}\nA: {e.content}" if e.question else e.content)[:MAX_KB_ENTRY_CHARS]
        if used + len(line) > MAX_KB_CHARS:
            break
        kb.append(line)
        used += len(line)
    if kb:
        out["knowledge"] = kb
    try:                                           # best effort, like the concierge: a failed read leaves it out
        facts = sales_gateway.concierge_business_facts(db, tenant.id)
    except Exception as exc:  # noqa: BLE001
        log.warning("marketing_business_facts_failed", tenant_id=tenant.id, error=str(exc)[:200])
        facts = []
    body = dict(facts[0]["result"]) if facts else {}
    if price_policy.price_mode(tenant) != "grounded":
        body.pop("payment_policy", None)
        body.pop("cancellation_policy", None)
    for k in ("packages", "destinations", "itineraries"):
        if isinstance(body.get(k), list):
            body[k] = body[k][:MAX_RECORDS]        # shortcut: count cap, not a char budget; fine for a few dozen records
    if body:
        out["business_data"] = _strip(price_policy.redact_price_facts(body))
    return out


def _opening(kind: str, payload: dict) -> Optional[str]:
    if kind == "story":
        text = next((f.get("text") for f in payload.get("frames", []) if f.get("text")), None)
    else:
        text = payload.get("caption")
    return (text or "").strip().split("\n", 1)[0][:160] or None


def plan_part(db: Session, item: MarketingContent) -> tuple[Optional[dict], list[dict]]:
    """(the plan's strategy + this item's entry, the other entries of the plan)."""
    if not item.plan_id:
        return None, []
    plan = db.query(MarketingPlan).filter_by(id=item.plan_id, tenant_id=item.tenant_id).first()
    body = (plan.body or {}) if plan is not None else {}
    if not body:
        return None, []
    cal = body.get("calendar") or []
    mine = next((e for e in cal if e.get("date") == item.planned_for and e.get("kind") == item.kind
                 and (e.get("idea") or "") in (item.title or "")), None)
    strategy = {k: body.get(k) for k in ("goals", "audience", "position", "pillars", "out_of_scope")}
    strategy["this_entry"] = mine
    others = [{k: e.get(k) for k in ("date", "kind", "pillar", "idea")} for e in cal if e is not mine][:MAX_SIBLINGS]
    return strategy, others


def recent_openings(db: Session, tenant_id: str, exclude_item: str) -> list[str]:
    rows = (db.query(MarketingContent.kind, MarketingContentVersion.payload)
            .join(MarketingContentVersion, MarketingContentVersion.id == MarketingContent.current_version_id)
            .filter(MarketingContent.tenant_id == tenant_id, MarketingContent.id != exclude_item,
                    MarketingContent.status != "archived")
            .order_by(MarketingContent.updated_at.desc()).limit(MAX_RECENT * 2).all())
    out = []
    for kind, payload in rows:
        line = _opening(kind, payload or {})
        if line and line not in out:
            out.append(line)
    return out[:MAX_RECENT]


def reviewer_notes(db: Session, tenant_id: str, item_id: str) -> tuple[list[str], list[str]]:
    """(notes on this item, recent notes on other items), newest first. Only people's 'changes needed' notes."""
    rows = (db.query(MarketingApproval.content_id, MarketingApproval.note, MarketingContent.title)
            .join(MarketingContent, MarketingContent.id == MarketingApproval.content_id)
            .filter(MarketingApproval.tenant_id == tenant_id, MarketingApproval.decision == "rejected",
                    MarketingApproval.note.isnot(None), MarketingApproval.note != "")
            .order_by(MarketingApproval.created_at.desc()).limit(MAX_NOTES * 3).all())
    mine = [n for cid, n, _ in rows if cid == item_id][:MAX_NOTES]
    others = [f"{title}: {n}" for cid, n, title in rows if cid != item_id][:MAX_NOTES]
    return mine, others


def photo_descriptions(db: Session, tenant_id: str) -> list[str]:
    rows = (db.query(MediaAsset.alt_text)
            .filter(MediaAsset.tenant_id == tenant_id, MediaAsset.status == "active", MediaAsset.alt_text.isnot(None),
                    MediaAsset.alt_text != "")
            .order_by(MediaAsset.created_at.desc()).limit(MAX_PHOTOS).all())
    return sorted({r[0].strip()[:120] for r in rows})


def build(db: Session, tenant_id: str, item: MarketingContent) -> str:
    """The context block appended to the content prompt. Empty sections are left out."""
    strategy, siblings = plan_part(db, item)
    mine, others = reviewer_notes(db, tenant_id, item.id)
    parts = []
    if strategy:
        parts.append(f"Plan (follow its audience, position and this entry's pillar):\n{strategy}")
    if siblings:
        parts.append(f"Other posts planned around it (cover different ground):\n{siblings}")
    recent = recent_openings(db, tenant_id, item.id)
    if recent:
        parts.append("Openings of recent posts (do not repeat these hooks or ideas):\n- " + "\n- ".join(recent))
    if mine:
        parts.append("The reviewer asked for these changes to THIS post (apply them):\n- " + "\n- ".join(mine))
    if others:
        parts.append("Recent reviewer feedback on other posts (keep it in mind):\n- " + "\n- ".join(others))
    photos = photo_descriptions(db, tenant_id)
    parts.append("Photos in the library (describe each slot's photo with words from one of these):\n- "
                 + "\n- ".join(photos) if photos else
                 "The photo library has no described photos yet; describe the photo each slot needs plainly.")
    return "\n\n".join(parts)
