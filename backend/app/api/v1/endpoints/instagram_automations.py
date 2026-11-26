"""Instagram automations: the post/reel picker, per-automation stats, and the tracked-link redirect.

Rules themselves are created and edited through /automations (validated by schemas/ig_automation.py).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.v1.deps import require_roles
from app.core.database import get_db, set_tenant_context
from app.models.automation import AutomationRule
from app.models.guest import Guest
from app.models.ig_automation import IgAutomationEvent, IgTrackedLink
from app.models.tenant import Tenant
from app.models.user import User, UserRole

router = APIRouter(tags=["instagram-automations"])

_MEDIA_FIELDS = "id,caption,media_type,media_product_type,thumbnail_url,media_url,permalink,timestamp,comments_count"


@router.get("/instagram/media")
def list_media(
    after: str | None = Query(default=None, max_length=500),
    limit: int = Query(default=24, ge=1, le=50),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    """The account's posts and reels, newest first, fetched live (Meta's image links expire, so nothing is stored)."""
    from app.services.ig_automation import _adapter

    adapter = _adapter(db, current_user.tenant_id)
    if adapter is None:
        raise HTTPException(status_code=409, detail="Connect Instagram first (Settings → Integrations).")
    params = {"fields": _MEDIA_FIELDS, "limit": limit}
    if after:
        params["after"] = after
    try:
        data = adapter._get(f"/{adapter._account_id}/media", params=params)
    except Exception:  # noqa: BLE001
        raise HTTPException(
            status_code=502, detail="Instagram did not return your posts. Try again in a minute."
        ) from None
    paging = data.get("paging") or {}
    items = [
        {
            "id": m.get("id"),
            "caption": (m.get("caption") or "")[:300],
            "type": "reel" if m.get("media_product_type") == "REELS" else (m.get("media_type") or "").lower(),
            "thumbnail": m.get("thumbnail_url") or m.get("media_url"),
            "permalink": m.get("permalink"),
            "timestamp": m.get("timestamp"),
            "comments": m.get("comments_count"),
        }
        for m in data.get("data", [])
    ]
    return {"items": items, "next": (paging.get("cursors") or {}).get("after") if paging.get("next") else None}


# Asked in separate calls: Meta refuses a whole call when one metric does not apply to the media type (profile visits
# and follows exist for feed posts, not reels), so one refused group never hides the others.
_INSIGHT_GROUPS = (("reach", "total_interactions", "likes", "comments", "saved", "shares"), ("views",),
                   ("profile_visits", "follows"))


@router.get("/instagram/media/{media_id}/insights")
def media_insights(
    media_id: str,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    """One post's Instagram insights, live (the Posts view's Insights). A metric Instagram does not give is null."""
    from app.services.ig_automation import _adapter

    if not media_id.isdigit() or len(media_id) > 40:  # goes into the Graph URL path
        raise HTTPException(status_code=422, detail="Unknown post")
    adapter = _adapter(db, current_user.tenant_id)
    if adapter is None:
        raise HTTPException(status_code=409, detail="Connect Instagram first (Settings → Integrations).")
    got: dict = {}
    for group in _INSIGHT_GROUPS:
        try:
            got.update(adapter.get_media_insights(media_id, list(group)))
        except Exception:  # noqa: BLE001 -- not offered for this media type, or Instagram busy: shown as "—"
            continue
    names = {"views": "views", "reach": "reach", "interactions": "total_interactions", "likes": "likes",
             "comments": "comments", "saves": "saved", "shares": "shares", "profile_visits": "profile_visits",
             "follows": "follows"}
    return {k: got.get(v) for k, v in names.items()}


@router.get("/instagram/automations/stats")
def automation_stats(
    days: int = Query(default=30, ge=1, le=365),
    period: str | None = Query(default=None, max_length=20),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    """Per automation over the last `days`: triggered, DMs sent, final messages / links sent, link clicks, follows,
    people reached, skipped, failed, and leads (people reached who shared a phone number after it)."""
    tenant_id = current_user.tenant_id
    since, until = datetime.now(UTC) - timedelta(days=days), datetime.now(UTC)
    if period:
        from app.services import ig_automation_overview

        try:
            (_, _, since, until), _ = ig_automation_overview.windows(period)
        except ValueError:
            raise HTTPException(status_code=422, detail="Unknown period") from None
    rows = (
        db.query(IgAutomationEvent.rule_id, IgAutomationEvent.kind, func.count())
        .filter(
            IgAutomationEvent.tenant_id == tenant_id,
            IgAutomationEvent.created_at >= since,
            IgAutomationEvent.created_at <= until,
        )
        .group_by(IgAutomationEvent.rule_id, IgAutomationEvent.kind)
        .all()
    )
    out: dict[str, dict] = {}
    for rule_id, kind, n in rows:
        out.setdefault(rule_id, {})[kind] = n

    people = (
        db.query(IgAutomationEvent.rule_id, IgAutomationEvent.guest_id, func.min(IgAutomationEvent.created_at))
        .filter(
            IgAutomationEvent.tenant_id == tenant_id,
            IgAutomationEvent.created_at >= since,
            IgAutomationEvent.created_at <= until,
            IgAutomationEvent.kind.in_(("dm_sent", "link_sent")),
            IgAutomationEvent.guest_id.isnot(None),
        )
        .group_by(IgAutomationEvent.rule_id, IgAutomationEvent.guest_id)
        .all()
    )
    identified = dict(
        db.query(Guest.id, Guest.lead_identified_at)
        .filter(
            Guest.tenant_id == tenant_id,
            Guest.id.in_({g for _, g, _ in people} or {""}),
            Guest.lead_identified_at.isnot(None),
        )
        .all()
    )
    for rule_id, guest_id, first_at in people:
        s = out.setdefault(rule_id, {})
        s["people"] = s.get("people", 0) + 1
        at = identified.get(guest_id)
        if at is not None:
            at = at if at.tzinfo else at.replace(tzinfo=UTC)
            first = first_at if first_at.tzinfo else first_at.replace(tzinfo=UTC)
            if at >= first:
                s["leads"] = s.get("leads", 0) + 1

    names = dict(db.query(AutomationRule.id, AutomationRule.name).filter(AutomationRule.tenant_id == tenant_id).all())
    return {
        "days": days,
        "automations": [
            {
                "rule_id": rid,
                "name": names.get(rid, "Deleted automation"),
                **{
                    k: s.get(k, 0)
                    for k in (
                        "triggered",
                        "dm_sent",
                        "link_sent",
                        "clicked",
                        "followed",
                        "gate_asked",
                        "people",
                        "leads",
                        "skipped",
                        "dm_failed",
                        "form_started",
                        "form_completed",
                        "form_dropped",
                        "sequence_sent",
                        "sequence_stopped",
                    )
                },
            }
            for rid, s in out.items()
        ],
    }


@router.get("/instagram/automations/overview")
def automation_overview(
    period: str = Query(default="this_month", max_length=20),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    """The automations dashboard for a period (today, yesterday, last_7d, this_month, last_month), with the period
    before for comparison. Booking amounts only with revenue.read; otherwise booked_amount is null and
    money_restricted is true (never a fake 0)."""
    from app.services import ig_automation_overview
    from app.services.authz_service import has_capability

    if period not in ig_automation_overview.PERIODS:
        raise HTTPException(status_code=422, detail="Unknown period")
    return ig_automation_overview.overview(
        db, current_user.tenant_id, period, money=has_capability(db, current_user, "revenue.read")
    )


@router.get("/instagram/welcome")
def get_welcome(
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    """Welcome questions (shown before someone's first message) and the chat menu, with what each one runs."""
    from app.services import ig_welcome

    tenant = db.query(Tenant).filter_by(id=current_user.tenant_id).first()
    return ig_welcome.get(tenant)


@router.put("/instagram/welcome")
def put_welcome(
    body: dict,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    """Save and push to Instagram. Saved even if Instagram refuses (pushed=false + Meta's reason), so it can be retried."""
    from pydantic import ValidationError

    from app.services import ig_welcome

    tenant = db.query(Tenant).filter_by(id=current_user.tenant_id).first()
    try:
        return ig_welcome.save(db, tenant, current_user.id, body)
    except ValidationError as exc:
        msg = str(exc.errors()[0].get("msg", "Invalid settings")).removeprefix("Value error, ")
        raise HTTPException(status_code=422, detail=msg) from None
    except ig_welcome.WelcomeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.get("/instagram/automations/posts")
def post_stats(
    ids: str = Query(..., max_length=2000, description="Comma-separated Instagram media ids (the posts on screen)"),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    """Per post, all time: which automations answer it and what they did (the Posts view). people = distinct people
    who triggered one there; sent = DMs; opened = people who opened one (Instagram "seen"); clicks = link clicks of the
    automations made for that post alone (an "any post" automation's clicks cannot be split by post)."""
    tid = current_user.tenant_id
    media_ids = [m.strip() for m in ids.split(",") if m.strip()][:50]
    rules = db.query(AutomationRule).filter(AutomationRule.tenant_id == tid, AutomationRule.trigger == "ig_comment_received",
                                            AutomationRule.action == "send_instagram_quick_reply").all()
    own = {m: [r.id for r in rules if (r.trigger_config or {}).get("media_id") == m] for m in media_ids}
    any_post = [r.id for r in rules if r.is_active and not (r.trigger_config or {}).get("media_id")
                and (r.trigger_config or {}).get("scope", "any") == "any" and not (r.trigger_config or {}).get("ad_id")]
    out = {m: {"rules": own[m], "covered_by_any": bool(any_post), "people": 0, "sent": 0, "public_replies": 0,
               "opened": 0, "clicks": 0} for m in media_ids}
    if not media_ids:
        return {"posts": out}
    rows = (db.query(IgAutomationEvent.media_id, IgAutomationEvent.kind, func.count())
            .filter(IgAutomationEvent.tenant_id == tid, IgAutomationEvent.media_id.in_(media_ids),
                    IgAutomationEvent.kind.in_(("dm_sent", "public_reply")))
            .group_by(IgAutomationEvent.media_id, IgAutomationEvent.kind).all())
    for media_id, kind, n in rows:
        out[media_id]["sent" if kind == "dm_sent" else "public_replies"] = n
    who = (db.query(IgAutomationEvent.media_id, IgAutomationEvent.rule_id, IgAutomationEvent.guest_id)
           .filter(IgAutomationEvent.tenant_id == tid, IgAutomationEvent.media_id.in_(media_ids),
                   IgAutomationEvent.kind == "triggered", IgAutomationEvent.guest_id.isnot(None)).distinct().all())
    by_pair: dict[tuple[str, str], set[str]] = {}
    for media_id, rule_id, guest_id in who:
        by_pair.setdefault((rule_id, guest_id), set()).add(media_id)
        out[media_id]["people"] += 1  # distinct (rule, person) pairs per post
    opened = (db.query(IgAutomationEvent.rule_id, IgAutomationEvent.guest_id)
              .filter(IgAutomationEvent.tenant_id == tid, IgAutomationEvent.kind == "opened",
                      IgAutomationEvent.rule_id.in_({r for r, _ in by_pair} or {""})).distinct().all())
    for pair in opened:
        for media_id in by_pair.get(tuple(pair), ()):
            out[media_id]["opened"] += 1
    rule_media = {rid: m for m, rids in own.items() for rid in rids}
    if rule_media:
        for rule_id, n in (db.query(IgAutomationEvent.rule_id, func.count())
                           .filter(IgAutomationEvent.tenant_id == tid, IgAutomationEvent.kind == "clicked",
                                   IgAutomationEvent.rule_id.in_(list(rule_media)))
                           .group_by(IgAutomationEvent.rule_id).all()):
            out[rule_media[rule_id]]["clicks"] += n
    return {"posts": out}


_IG_MEDIA_MB = {"image": 8, "video": 25}  # Instagram's limits for a DM attachment


def _ig_media_kind(head: bytes) -> tuple[str, str, str] | None:
    """(kind, content type, extension) from the file's first bytes: JPEG, PNG, or an MP4/MOV video."""
    if head.startswith(b"\xff\xd8\xff"):
        return "image", "image/jpeg", "jpg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image", "image/png", "png"
    if head[4:8] == b"ftyp":
        return ("video", "video/quicktime", "mov") if head[8:10] == b"qt" else ("video", "video/mp4", "mp4")
    return None


@router.post("/instagram/automations/media")
def upload_automation_media(
    file: UploadFile = File(...),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
):
    """The photo or video an automation sends after its message. Returns the ``attachment`` object for action_config
    (its key is checked to be this workspace's when the rule is saved)."""
    import os
    import re

    from app.services.media_storage import get_presigned_media_url, upload_ig_automation_media

    content = file.file.read(_IG_MEDIA_MB["video"] * 1024 * 1024 + 1)
    found = _ig_media_kind(content[:16])
    if not found:
        raise HTTPException(status_code=400, detail="Use a JPEG or PNG photo, or an MP4 video.")
    kind, content_type, ext = found
    if len(content) > _IG_MEDIA_MB[kind] * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"Instagram takes {'photos' if kind == 'image' else 'videos'} up to "
                                                    f"{_IG_MEDIA_MB[kind]} MB.")
    key = upload_ig_automation_media(current_user.tenant_id, content, content_type, ext)
    name = re.sub(r"[\x00-\x1f/\\]", "", os.path.basename(file.filename or "")).strip()[:120] or f"file.{ext}"
    return {"kind": kind, "key": key, "filename": name, "preview_url": get_presigned_media_url(key, expires_in=3600)}


@router.post("/instagram/automations/{rule_id}/send-existing", status_code=202)
def send_to_existing_comments(
    rule_id: str,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    """Answer the comments the rule's post(s) already have from the last 7 days (runs in the background)."""
    from app.core import cache
    from app.core.audit import append_audit
    from app.workers.tasks.ig_automation_tasks import send_existing

    rule = db.query(AutomationRule).filter_by(id=rule_id, tenant_id=current_user.tenant_id).first()
    if rule is None:
        raise HTTPException(status_code=404, detail="Automation not found")
    from app.services.ig_send_existing import is_comment_rule

    if not is_comment_rule(rule) or not rule.is_active:
        raise HTTPException(status_code=422, detail="Only a switched-on comment automation can answer existing comments.")
    if not cache.idem_check_and_set(f"igauto:send_existing:{rule.id}", ttl=600):
        raise HTTPException(status_code=409, detail="Already answering this post's comments. Try again in 10 minutes.")
    append_audit(db, tenant_id=current_user.tenant_id, actor_user_id=current_user.id, action="ig_automation.send_existing",
                 target_type="automation_rule", target_id=rule.id, payload={"name": rule.name})
    db.commit()
    send_existing.delay(current_user.tenant_id, rule.id)
    return {"queued": True}


PAUSE_HOURS = (1, 4, 24, 72, 168)


@router.get("/instagram/automations/pause")
def get_pause(
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    from app.services.ig_automation_extras import paused_until

    until = paused_until(db, current_user.tenant_id)
    return {"paused_until": until.isoformat() if until else None}


@router.put("/instagram/automations/pause")
def set_pause(
    body: dict,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    """Pause every Instagram automation for `hours` (1, 4, 24, 72 or 168), or resume with hours = null. Audited."""
    from sqlalchemy.orm.attributes import flag_modified

    from app.core.audit import append_audit

    hours = body.get("hours")
    if hours is not None and hours not in PAUSE_HOURS:
        raise HTTPException(status_code=422, detail="Pause for 1, 4, 24, 72 or 168 hours.")
    tenant = db.query(Tenant).filter_by(id=current_user.tenant_id).first()
    until = datetime.now(UTC) + timedelta(hours=hours) if hours else None
    bc = dict(tenant.brand_config or {})
    bc["ig_automations"] = {**(bc.get("ig_automations") or {}), "paused_until": until.isoformat() if until else None}
    tenant.brand_config = bc
    flag_modified(tenant, "brand_config")
    append_audit(db, tenant_id=tenant.id, actor_user_id=current_user.id,
                 action="ig_automation.paused" if until else "ig_automation.resumed", target_type="tenant",
                 target_id=tenant.id, payload={"hours": hours})
    db.commit()
    return {"paused_until": until.isoformat() if until else None}


@router.get("/instagram/card-library")
def get_card_library(
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    """Saved sets of swipeable cards to reuse in automations (brand_config.ig_card_library)."""
    bc = db.query(Tenant.brand_config).filter(Tenant.id == current_user.tenant_id).scalar() or {}
    return {"items": bc.get("ig_card_library") or []}


@router.put("/instagram/card-library")
def put_card_library(
    body: dict,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    """Replace the saved card sets: items [{name, cards}] (at most 20; cards as in an automation)."""
    from pydantic import BaseModel, Field, ValidationError
    from sqlalchemy.orm.attributes import flag_modified

    from app.schemas.ig_automation import IgCard

    class Item(BaseModel):
        name: str = Field(min_length=1, max_length=60)
        cards: list[IgCard] = Field(min_length=1, max_length=10)

    try:
        items = [Item(**i) for i in (body.get("items") or [])][:20]
    except (ValidationError, TypeError) as exc:
        raise HTTPException(status_code=422, detail="Each saved set needs a name and 1 to 10 cards with a headline.") from exc
    prefix = f"{current_user.tenant_id}/ig_automations/"
    if any(c.image_key and not c.image_key.startswith(prefix) for i in items for c in i.cards):
        raise HTTPException(status_code=422, detail="Upload the card images again.")
    tenant = db.query(Tenant).filter_by(id=current_user.tenant_id).first()
    tenant.brand_config = {**(tenant.brand_config or {}), "ig_card_library": [i.model_dump(exclude_none=True) for i in items]}
    flag_modified(tenant, "brand_config")
    db.commit()
    return {"items": tenant.brand_config["ig_card_library"]}


@router.get("/l/{slug}/{code}", include_in_schema=False)
def follow_link(slug: str, code: str, db: Session = Depends(get_db)):
    """A DM button's tracked link: count the click, then send the person on. Only stored codes resolve (no open
    redirect)."""
    tenant = db.query(Tenant).filter(Tenant.slug == slug[:100]).first()
    if tenant is None:
        raise HTTPException(status_code=404, detail="Link not found")
    set_tenant_context(db, tenant.id)
    link = db.query(IgTrackedLink).filter_by(tenant_id=tenant.id, code=code[:16]).first()
    if link is None:
        raise HTTPException(status_code=404, detail="Link not found")
    db.add(IgAutomationEvent(tenant_id=tenant.id, rule_id=link.rule_id, kind="clicked"))
    db.commit()
    return RedirectResponse(link.target_url, status_code=302)
