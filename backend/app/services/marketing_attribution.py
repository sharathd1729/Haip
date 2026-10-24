"""Which post or ad brought a booking (agency M6): every MEASURED touch of a lead, first and last side by side, plus
what the guest SAID ("How did you first hear about us?"), never mixed together.

Touches, from what HAIP already records:
  * ad / post referral  -- lead_attribution (Instagram/WhatsApp click-to-chat and post referrals). A post referral's URL
                           is matched to the post HAIP published; a Meta ad id to the HAIP ad draft that made it;
  * website             -- utm_* kept on the enquiry or booking (inquiry.custom_fields.utm); a HAIP utm_campaign
                           ("c-..." post, "a-..." ad) names the content (marketing_links);
  * first contact       -- guests.first_touch_channel, written once when HAIP first heard from the person.
A booking is "traced" when one of its lead's touches names a specific post or ad. Credit goes to the LAST such touch
before the booking (the first one is shown too). Everything else is counted as unknown, never guessed.
"""
from collections import defaultdict
from datetime import date, datetime, time, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.models.conversation import Conversation
from app.models.guest import Guest
from app.models.inquiry import Inquiry
from app.models.lead_attribution import LeadAttribution
from app.models.marketing import MarketingContent
from app.models.marketing_ads import MarketingAdDraft
from app.models.property import Property, Stay
from app.services import marketing_links as links
from app.services.marketing_content_service import MarketingError

HEARD_ABOUT = {"instagram": "Instagram", "facebook": "Facebook", "google": "Google search or Maps",
               "whatsapp": "WhatsApp", "friend": "A friend or family", "repeat_guest": "Stayed before",
               "travel_agent": "A travel agent", "influencer": "A creator or influencer", "website": "Our website",
               "ota": "Airbnb / Booking.com", "other": "Something else"}


def _utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def set_heard_about(db: Session, tenant_id: str, inquiry_id: str, value: Optional[str], note: Optional[str],
                    actor_id: str) -> Inquiry:
    if value is not None and value not in HEARD_ABOUT:
        raise MarketingError(422, "bad_answer", "Pick one of the listed answers.")
    inq = db.query(Inquiry).filter_by(id=inquiry_id, tenant_id=tenant_id).first()
    if inq is None:
        raise MarketingError(404, "not_found", "No such lead in this workspace.")
    before = {"heard_about": inq.heard_about, "note": inq.heard_about_note}
    inq.heard_about, inq.heard_about_note = value, ((note or "").strip()[:200] or None)
    append_audit(db, tenant_id=tenant_id, action="lead.heard_about_set", actor_user_id=actor_id, target_type="inquiry",
                 target_id=inq.id, payload={"before": before, "after": {"heard_about": value}})
    return inq


def _ad_drafts_by_meta(db: Session, tenant_id: str) -> dict[str, MarketingAdDraft]:
    return {(d.meta or {}).get("ad_id"): d for d in db.query(MarketingAdDraft).filter(
        MarketingAdDraft.tenant_id == tenant_id, MarketingAdDraft.meta.isnot(None)) if (d.meta or {}).get("ad_id")}


def touches(db: Session, tenant_id: str, inquiries: list[Inquiry]) -> dict[str, list[dict]]:
    """inquiry id -> its touches, oldest first."""
    if not inquiries:
        return {}
    by_id = {i.id: i for i in inquiries}
    out: dict[str, list[dict]] = defaultdict(list)
    conv_inq = dict(db.query(Conversation.id, Conversation.inquiry_id).filter(
        Conversation.tenant_id == tenant_id, Conversation.inquiry_id.in_(list(by_id))))
    atts = db.query(LeadAttribution).filter(LeadAttribution.tenant_id == tenant_id,
                                            (LeadAttribution.inquiry_id.in_(list(by_id)))
                                            | (LeadAttribution.conversation_id.in_(list(conv_inq)))).all()
    drafts = _ad_drafts_by_meta(db, tenant_id)
    posts = links.content_by_permalink(db, tenant_id, [a.source_url for a in atts if a.source_type == "post"])
    for a in atts:
        inq_id = a.inquiry_id if a.inquiry_id in by_id else conv_inq.get(a.conversation_id)
        if inq_id not in by_id:
            continue
        draft = drafts.get(a.ad_id) if a.ad_id else None
        ref = (a.raw_referral or {}).get("ref") if isinstance(a.raw_referral, dict) else None
        by_code = links.resolve_campaign(db, tenant_id, ref) if ref else {}      # ig.me/...?ref=c-xxxxxxxx (organic)
        out[inq_id].append({
            "at": _utc(a.first_message_at or a.created_at), "kind": "ad" if a.source_type == "ad" or a.ad_id else "post",
            "channel": a.destination_channel, "ad_id": a.ad_id, "ad_draft_id": draft.id if draft else None,
            "content_id": (draft.content_id if draft else None) or posts.get(a.source_url) or by_code.get("content_id"),
            "detail": a.headline or a.campaign_id or a.source_url or ref})
    for conv_id, inq_id, at, content_id, code in first_message_codes(db, tenant_id, conv_inq):
        out[inq_id].append({"at": _utc(at), "kind": "post", "channel": "whatsapp", "ad_id": None, "ad_draft_id": None,
                            "content_id": content_id, "detail": code})
    for inq in inquiries:
        u = (inq.custom_fields or {}).get("utm") or {}
        if u:
            found = links.resolve_campaign(db, tenant_id, u.get("utm_campaign"))
            out[inq.id].append({"at": _utc(inq.created_at), "kind": "website", "channel": "website",
                                "ad_id": None, "ad_draft_id": found.get("ad_draft_id"), "content_id": found.get("content_id"),
                                "creator_deal_id": found.get("creator_deal_id"),
                                "detail": " / ".join(x for x in (u.get("utm_source"), u.get("utm_medium"),
                                                                 u.get("utm_campaign")) if x)})
    guests = {g.id: g for g in db.query(Guest).filter(Guest.tenant_id == tenant_id,
                                                      Guest.id.in_({i.guest_id for i in inquiries}))}
    for inq in inquiries:
        g = guests.get(inq.guest_id)
        if g is not None and g.first_touch_channel:
            out[inq.id].append({"at": _utc(g.first_touch_at), "kind": "first_contact", "channel": g.first_touch_channel,
                                "ad_id": None, "ad_draft_id": None, "content_id": None, "detail": None})
    epoch = datetime(2000, 1, 1, tzinfo=timezone.utc)
    return {k: sorted(v, key=lambda t: t["at"] or epoch) for k, v in out.items()}


def first_message_codes(db: Session, tenant_id: str, conv_inq: dict) -> list[tuple]:
    """(conversation, inquiry, at, content id, code) for chats whose FIRST guest message carries a post's tracking code
    (the WhatsApp link from marketing_links.tracking prefills it)."""
    from sqlalchemy import and_, func

    from app.models.conversation import Message, MessageDirection
    if not conv_inq:
        return []
    inbound = (Message.tenant_id == tenant_id, Message.conversation_id.in_(list(conv_inq)),
               Message.direction == MessageDirection.INBOUND)
    firsts = (db.query(Message.conversation_id.label("cid"), func.min(Message.created_at).label("at"))
              .filter(*inbound).group_by(Message.conversation_id).subquery())
    first = {m.conversation_id: m for m in db.query(Message).join(
        firsts, and_(Message.conversation_id == firsts.c.cid, Message.created_at == firsts.c.at)).filter(*inbound)}
    out = []
    for conv_id, m in first.items():
        found = links.CODE_IN_TEXT.search(m.body or "")
        cid = links.resolve_campaign(db, tenant_id, found.group(1)).get("content_id") if found else None
        if cid:
            out.append((conv_id, conv_inq[conv_id], m.created_at, cid, found.group(1).lower()))
    return out


def chain(ts: list[dict], before: Optional[datetime] = None) -> dict:
    """First touch, last touch, and the post/ad credited (the last touch that names one, before the booking)."""
    before = _utc(before)
    upto = [t for t in ts if before is None or t["at"] is None or t["at"] <= before] or ts
    named = [t for t in upto if t["content_id"] or t["ad_draft_id"] or t["ad_id"] or t.get("creator_deal_id")]
    return {"first": ts[0] if ts else None, "last": upto[-1] if upto else None,
            "credited": named[-1] if named else None, "known": bool(named), "touches": len(ts)}


def _titles(db: Session, tenant_id: str, ids: set) -> dict[str, str]:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return dict(db.query(MarketingContent.id, MarketingContent.title).filter(
        MarketingContent.tenant_id == tenant_id, MarketingContent.id.in_(ids)))


def _creator_names(db: Session, tenant_id: str, deal_ids: set) -> dict[str, str]:
    deal_ids = {d for d in deal_ids if d}
    if not deal_ids:
        return {}
    from app.models.marketing_partners import MarketingCreator, MarketingCreatorDeal
    rows = (db.query(MarketingCreatorDeal.id, MarketingCreator.handle)
            .join(MarketingCreator, MarketingCreator.id == MarketingCreatorDeal.creator_id)
            .filter(MarketingCreatorDeal.tenant_id == tenant_id, MarketingCreatorDeal.id.in_(deal_ids)))
    return {d: f"Creator @{h}" for d, h in rows}


def bookings(db: Session, tenant_id: str, since: date, until: date) -> dict:
    """Bookings made in [since, until] with the post or ad behind each, and how much is unknown."""
    ist = ZoneInfo("Asia/Kolkata")                       # the workspace's day, not UTC's
    start = datetime.combine(since, time.min, tzinfo=ist).astimezone(timezone.utc)
    end = datetime.combine(until, time.max, tzinfo=ist).astimezone(timezone.utc)
    stays = (db.query(Stay).filter(Stay.tenant_id == tenant_id, Stay.status != "cancelled",
                                   (Stay.channel_source.is_(None)) | (Stay.channel_source != "creator"),   # comped (M7)
                                   Stay.created_at >= start, Stay.created_at <= end)
             .order_by(Stay.created_at.asc()).all())
    inq = {i.id: i for i in db.query(Inquiry).filter(Inquiry.tenant_id == tenant_id,
                                                      Inquiry.id.in_({s.inquiry_id for s in stays if s.inquiry_id}))}
    ts = touches(db, tenant_id, list(inq.values()))
    props = dict(db.query(Property.id, Property.name).filter(Property.tenant_id == tenant_id))
    rows, credited_ids = [], set()
    for s in stays:
        i = inq.get(s.inquiry_id)
        c = chain(ts.get(s.inquiry_id, []), s.created_at)
        if c["credited"]:
            credited_ids.add(c["credited"]["content_id"])
        rows.append({"stay_id": s.id, "amount": float(s.total_amount or 0), "check_in": s.check_in.isoformat(),
                     "property": props.get(s.property_id), "created_at": s.created_at, "chain": c,
                     "heard_about": HEARD_ABOUT.get(i.heard_about) if i is not None and i.heard_about else None,
                     "channel_source": s.channel_source})
    titles = _titles(db, tenant_id, credited_ids)
    creators = _creator_names(db, tenant_id, {(r["chain"]["credited"] or {}).get("creator_deal_id") for r in rows})
    by_post = defaultdict(lambda: {"bookings": 0, "revenue": 0.0})
    for r in rows:
        cr = r["chain"]["credited"]
        r["credited_title"] = titles.get(cr["content_id"]) if cr and cr["content_id"] else (
            f"Meta ad {cr['ad_id']}" if cr and cr["ad_id"] else
            creators.get(cr.get("creator_deal_id")) if cr and cr.get("creator_deal_id") else None)
        if r["credited_title"]:
            by_post[r["credited_title"]]["bookings"] += 1
            by_post[r["credited_title"]]["revenue"] += r["amount"]
    known = sum(1 for r in rows if r["chain"]["known"])
    said = sum(1 for r in rows if r["heard_about"])
    return {"since": since.isoformat(), "until": until.isoformat(), "bookings": rows, "total": len(rows),
            "traced": known, "unknown": len(rows) - known,
            "unknown_share": round((len(rows) - known) / len(rows), 3) if rows else None,
            "self_reported": said, "revenue": round(sum(r["amount"] for r in rows), 2),
            "by_post": sorted(({"title": k, **v} for k, v in by_post.items()), key=lambda x: -x["revenue"])}


def lead_view(db: Session, tenant_id: str, inquiry_id: str) -> dict:
    """First and last touch next to what the guest said, for the lead page."""
    inq = db.query(Inquiry).filter_by(id=inquiry_id, tenant_id=tenant_id).first()
    if inq is None:
        raise MarketingError(404, "not_found", "No such lead in this workspace.")
    ts = touches(db, tenant_id, [inq]).get(inq.id, [])
    c = chain(ts)
    titles = _titles(db, tenant_id, {t["content_id"] for t in ts})

    def view(t):
        return None if t is None else {**t, "content_title": titles.get(t["content_id"])}
    return {"first": view(c["first"]), "last": view(c["last"]), "credited": view(c["credited"]),
            "heard_about": inq.heard_about, "heard_about_note": inq.heard_about_note,
            "choices": [{"value": k, "label": v} for k, v in HEARD_ABOUT.items()]}
