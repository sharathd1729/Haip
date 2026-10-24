"""The strategist's documents (studio plan phase 3): the shoot & collab brief and the monthly strategy deck.

Facts (theme score + evidence from marketing_radar, last month's numbers from marketing_reports, the Insights next plan,
the swipe file's proven hooks, research signals) are computed in code and stored on the doc; the AI writes the text
(router tasks `marketing_brief` / `marketing_deck`, prompts marketing-shoot-brief-v2 / marketing-strategy-deck-v1).
The deck's prose goes through the analyst number grounding; the brief's creative numbers (shot length, lens) are
directions, not facts, and every text passes the workspace's price policy + banned words. The tracking code and the
ASCI label come from code, never from the AI. Celery only (`marketing_strategy.write_doc`).
"""
import json
from datetime import date, timedelta
from typing import Literal, Optional

import structlog
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from app.core.prompt_versions import get_version
from app.models.marketing_research import MarketingStrategyDoc
from app.models.tenant import Tenant
from app.services import marketing_ai_service as ai
from app.services import marketing_content_service as content_svc
from app.services import usage_service
from app.services.marketing_content_service import MarketingError
from app.services.marketing_prompts import _schema

log = structlog.get_logger()

ASCI_LABELS = ("#Ad", "#Collaboration")       # India's ASCI influencer guidelines: one of these, upfront


class Shot(BaseModel):
    n: int = Field(ge=1, le=40)
    use: Literal["hook", "story", "detail", "cta", "broll"]
    scene: str = Field(max_length=160)
    shot_size: Literal["wide", "medium", "close", "extreme_close"]
    angle: Literal["eye", "low", "high", "pov", "overhead", "drone"]
    movement: Literal["static", "pan", "tilt", "push_in", "pull_out", "handheld", "gimbal", "drone"]
    lens: str = Field(max_length=20)
    duration_s: int = Field(ge=1, le=30)
    time_of_day: Literal["sunrise", "morning", "midday", "golden_hour", "dusk", "night"]
    talent: list[str] = Field(default_factory=list, max_length=6)
    props: list[str] = Field(default_factory=list, max_length=6)
    audio: str = Field(default="", max_length=80)
    on_screen_text: str = Field(default="", max_length=80)
    why: str = Field(max_length=200)
    priority: Literal["must", "nice"]


class Hook(BaseModel):
    text: str = Field(max_length=120)
    type: Literal["question", "number", "pov", "offer", "moment", "reveal", "statement"]


class ReelScript(BaseModel):
    title: str = Field(max_length=80)
    shots: list[int] = Field(min_length=2, max_length=12)
    length_s: int = Field(ge=6, le=60)
    cta: str = Field(max_length=80)


class PlanSlot(BaseModel):
    week: int = Field(ge=1, le=4)
    kind: Literal["reel", "carousel", "story", "post"]
    what: str = Field(max_length=160)


class Collab(BaseModel):
    creator_brief: str = Field(max_length=800)
    deliverables: list[str] = Field(max_length=8)
    usage_rights: str = Field(max_length=300)


class ShootBrief(BaseModel):
    focus: str = Field(max_length=240)
    must_get: list[str] = Field(max_length=8)
    shots: list[Shot] = Field(min_length=3, max_length=20)
    broll: list[str] = Field(default_factory=list, max_length=12)
    hooks: list[Hook] = Field(min_length=5, max_length=5)
    reels: list[ReelScript] = Field(min_length=2, max_length=3)
    captions: list[str] = Field(min_length=1, max_length=4)
    posting_plan: list[PlanSlot] = Field(min_length=2, max_length=16)
    collab: Optional[Collab] = None


class DeckText(BaseModel):
    headline: str = Field(max_length=300)
    last_month: str = Field(max_length=1200)
    learnings: list[str] = Field(max_length=6)
    market_notes: list[str] = Field(max_length=6)
    themes: list[str] = Field(max_length=4)
    shoot_plan: list[str] = Field(max_length=6)
    hooks_to_test: list[str] = Field(max_length=6)
    collab_plan: list[str] = Field(max_length=4)
    ad_concepts: list[str] = Field(max_length=5)


BRIEF_SYSTEM = """You plan a photo/video shoot (and optionally a creator collab) for a hospitality brand's Instagram.
Use the THEME, its EVIDENCE, the shoot details and the PROVEN HOOKS given. Write: a one-sentence focus that names the
evidence, must-get shots, a numbered shot list (size, angle, movement, lens, seconds, time of day, people, props, audio,
on-screen text, why, priority), a B-roll list, exactly 5 hooks, 2-3 Reel scripts (shot numbers in order), 1-4 captions,
and a 2-4 week posting plan. Vertical 9:16: keep faces and text inside the middle safe zone. Never invent prices,
offers, reviews or facts about the property; if asked for a collab, write the creator brief, deliverables and usage
rights (the disclosure label and tracking code are added by the system)."""

DECK_SYSTEM = """You write a monthly marketing strategy deck for a hospitality brand's owner, in plain English, from the
FACTS (JSON) computed by code: last month vs goal, learnings, market and competitor notes, 2-4 themes for next month
with reasons, the shoot plan, hooks to test, the collab plan and ad concepts. Use only numbers that appear in the
facts, written the same way. Say "not enough data" when the facts are thin. No hype, no emojis."""


def brief_tool() -> dict:
    return {"name": "submit_brief", "description": "Return the shoot brief.", "input_schema": _schema(ShootBrief)}


def deck_tool() -> dict:
    return {"name": "submit_deck", "description": "Return the deck text.", "input_schema": _schema(DeckText)}


# ── Requests ────────────────────────────────────────────────────────────────────────────────────────────────────────

def request_brief(db: Session, tenant: Tenant, data: dict, actor_id: str) -> MarketingStrategyDoc:
    from app.services import marketing_radar as radar
    theme = str(data.get("theme") or "").strip()[:120]
    if not theme:
        raise MarketingError(422, "bad_brief", "Name the theme (pick one from the radar).")
    found = next((t for t in radar.radar(db, tenant)["all"] if t["theme"].lower() == theme.lower()), None)
    shoot = {k: str(data.get(k) or "").strip()[:200] or None for k in ("date", "vehicle", "route", "people")}
    if shoot["date"]:
        try:
            date.fromisoformat(shoot["date"])
        except ValueError:
            raise MarketingError(422, "bad_brief", "The shoot date must be YYYY-MM-DD.")
    collab = bool(data.get("collab"))
    doc = MarketingStrategyDoc(tenant_id=tenant.id, kind="brief", title=f"Shoot brief: {theme}"[:200], status="pending",
                               input={**shoot, "theme": theme, "collab": collab, "creator": (str(data.get("creator") or "")[:80] or None)},
                               facts={"theme": found, "tracking": _tracking(db, tenant, theme),
                                      "asci_label": ASCI_LABELS[0] if collab else None}, created_by=actor_id)
    db.add(doc)
    db.flush()
    return doc


def _tracking(db: Session, tenant: Tenant, theme: str) -> dict:
    """A WhatsApp code for the shoot's posts: same form as a post's code, keyed by the theme."""
    import hashlib
    from urllib.parse import quote
    from app.services.bio_packages import whatsapp_number
    code = "c-" + hashlib.sha256(f"{tenant.id}:{theme.lower()}".encode()).hexdigest()[:8]
    wa = whatsapp_number(None, tenant)
    return {"code": code, "whatsapp": f"https://wa.me/{wa}?text={quote(f'Hi! I saw your post ({code})')}" if wa else None}


def request_deck(db: Session, tenant: Tenant, month: date, actor_id: Optional[str]) -> MarketingStrategyDoc:
    period = month.strftime("%Y-%m")
    doc = (db.query(MarketingStrategyDoc).filter_by(tenant_id=tenant.id, kind="deck", period=period)
           .order_by(MarketingStrategyDoc.created_at.desc()).first())
    if doc is None:
        doc = MarketingStrategyDoc(tenant_id=tenant.id, kind="deck", title=f"Strategy for {period}", period=period,
                                   created_by=actor_id)
        db.add(doc)
    doc.status, doc.error = "pending", None
    db.flush()
    return doc


# ── Writing (Celery) ────────────────────────────────────────────────────────────────────────────────────────────────

def _swipe_hooks(db: Session, tenant_id: str) -> list[str]:
    from app.services.marketing_video_read import swipe_file
    return [f"{i.get('hook_type')}: {i.get('hook_text')}" for i in swipe_file(db, tenant_id, 10) if i.get("hook_text")]


def write(db: Session, tenant_id: str, doc_id: str) -> MarketingStrategyDoc:
    doc = db.query(MarketingStrategyDoc).filter_by(id=doc_id, tenant_id=tenant_id).one()
    tenant = db.query(Tenant).filter_by(id=tenant_id).one()
    try:
        if doc.kind == "brief":
            _write_brief(db, tenant, doc)
        else:
            _write_deck(db, tenant, doc)
    except ValidationError as exc:
        doc.status, doc.error = "failed", f"The AI's answer did not fit the format: {ai._errors(exc)}"[:2000]
    except ValueError as exc:
        doc.status, doc.error = "failed", str(exc)[:2000]
    return doc


def _write_brief(db: Session, tenant: Tenant, doc: MarketingStrategyDoc) -> None:
    doc.prompt_version = get_version("marketing_brief")
    user = (f"THEME: {doc.input.get('theme')}\nEVIDENCE: {json.dumps((doc.facts or {}).get('theme'), default=str)}\n"
            f"SHOOT: {json.dumps({k: doc.input.get(k) for k in ('date', 'vehicle', 'route', 'people')})}\n"
            f"COLLAB: {'yes, creator ' + (doc.input.get('creator') or 'to be chosen') if doc.input.get('collab') else 'no'}\n"
            f"PROVEN HOOKS (swipe file): {_swipe_hooks(db, tenant.id) or '(none yet)'}\n"
            f"Business facts:\n{ai._facts(db, tenant)}")
    data, raw, provider = ai._call("marketing_brief", tenant.id, BRIEF_SYSTEM, user, brief_tool())
    usage_service.record_llm(db, tenant.id, ai.MODULE, raw, provider=provider, ref_type="marketing_strategy_doc", ref_id=doc.id)
    body = ShootBrief.model_validate(data).model_dump()
    problems = content_svc.check_text(db, tenant.id, {"brief": json.dumps(body)})
    if problems:
        raise ValueError("; ".join(problems))
    if not doc.input.get("collab"):
        body["collab"] = None
    elif body.get("collab"):
        body["collab"]["asci_label"] = ASCI_LABELS[0]
        body["collab"]["tracking_code"] = (doc.facts or {}).get("tracking", {}).get("code")
    doc.body, doc.model, doc.status, doc.error, doc.source = body, raw.get("model"), "ready", None, "llm"


def deck_facts(db: Session, tenant: Tenant, month: date) -> dict:
    from app.services import marketing_radar as radar
    from app.services import marketing_reports as reports
    from app.services.marketing_insights_report import latest
    prev = (month.replace(day=1) - timedelta(days=1)).replace(day=1)
    try:
        last = reports.monthly(db, tenant, prev)
    except Exception as exc:  # noqa: BLE001 -- the deck still lists what is known
        last = {"error": type(exc).__name__}
    ins = latest(db, tenant.id)
    from app.models.marketing_research import MarketingSignal
    signals = (db.query(MarketingSignal).filter(MarketingSignal.tenant_id == tenant.id,
                                                MarketingSignal.observed_on >= month - timedelta(days=30))
               .order_by(MarketingSignal.value.desc()).limit(15).all())
    briefs = (db.query(MarketingStrategyDoc).filter_by(tenant_id=tenant.id, kind="brief", status="ready")
              .order_by(MarketingStrategyDoc.created_at.desc()).limit(4).all())
    return {"month": month.strftime("%Y-%m"), "last_month": last,
            "insights_next_plan": ((ins.facts or {}).get("next_plan") if ins else None),
            "radar": radar.radar(db, tenant, month)["top"],
            "market": [{"source": s.source, "evidence": s.evidence, "title": s.title, "value": s.value} for s in signals],
            "hooks": _swipe_hooks(db, tenant.id), "briefs": [b.title for b in briefs]}


def deck_deterministic(f: dict) -> dict:
    return {"headline": f"Strategy for {f['month']}: focus on " + (", ".join(t["theme"] for t in f["radar"]) or "not enough data yet"),
            "last_month": "See the numbers below.", "learnings": [i["what"] for i in ((f.get("insights_next_plan") or {}).get("do_more") or [])],
            "market_notes": [s["title"] for s in f["market"][:5] if s.get("title")],
            "themes": [f"{t['theme']} (score {t['score']}, shoot by {t['shoot_by']})" for t in f["radar"]],
            "shoot_plan": f["briefs"], "hooks_to_test": f["hooks"][:5], "collab_plan": [], "ad_concepts": []}


def _write_deck(db: Session, tenant: Tenant, doc: MarketingStrategyDoc) -> None:
    from app.services.analyst import grounding
    month = date.fromisoformat(f"{doc.period}-01")
    facts = deck_facts(db, tenant, month)
    doc.facts, doc.prompt_version = facts, get_version("marketing_deck")
    body, source = deck_deterministic(facts), "deterministic"
    try:
        data, raw, provider = ai._call("marketing_deck", tenant.id, DECK_SYSTEM, f"FACTS:\n{json.dumps(facts, default=str)[:14000]}",
                                       deck_tool())
        usage_service.record_llm(db, tenant.id, ai.MODULE, raw, provider=provider, ref_type="marketing_strategy_doc", ref_id=doc.id)
        text = DeckText.model_validate(data).model_dump()
        allowed, dropped = grounding.allowed_numbers(facts), []
        for k, v in text.items():
            if isinstance(v, str):
                text[k] = grounding.clean_text(v, allowed, k, dropped) or body.get(k)
            else:
                text[k] = grounding.clean_list(v, allowed, k, dropped)
        body, source, doc.model = text, "llm", raw.get("model")
        facts["dropped_sentences"] = dropped[:20]
    except (ai.LLMTransientError, ValueError, ValidationError) as exc:
        log.warning("marketing_deck_llm_failed", tenant_id=tenant.id, error=type(exc).__name__)
    doc.body, doc.source, doc.status, doc.error = body, source, "ready", None


def as_dict(d: MarketingStrategyDoc) -> dict:
    return {"id": d.id, "kind": d.kind, "title": d.title, "period": d.period, "status": d.status, "input": d.input,
            "facts": d.facts, "body": d.body, "error": d.error, "source": d.source, "prompt_version": d.prompt_version,
            "created_at": d.created_at}


def due_decks(db: Session, now_for) -> list[tuple[str, date]]:
    """(tenant id, month) for workspaces whose deck for this month is due: the 1st from 08:00 local, none yet."""
    from app.workers.tasks.marketing_insights import _studio_tenants
    out = []
    for t in _studio_tenants(db):
        now = now_for(t)
        if now.day != 1 or now.hour < 8:
            continue
        period = now.strftime("%Y-%m")
        if not db.query(MarketingStrategyDoc.id).filter_by(tenant_id=t.id, kind="deck", period=period).first():
            out.append((t.id, now.date().replace(day=1)))
    return out
