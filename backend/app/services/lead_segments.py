"""Lead segments (GET /leads/segments): the groups a sales team acts on, counted, in one place.

Two kinds, both built from what HAIP already computes, never a new definition:
  * "Ready-made" segments = the WhatsApp campaign presets (wa_lead_audience.PRESETS: hot, quoted not booked, travelling
    soon, went quiet, new this week, past guests), resolved by the same wa_lead_audience.resolve a campaign uses, so the
    count here is the count a campaign would reach (people, how many have a usable phone, how many opted out).
  * "AI tag" segments = open leads per tag the lead summary wrote (services/lead_tags.py), grouped as the vocabulary is.
    Open = the lead's stage is not closed won / closed lost.
Cached per workspace for CACHE_SECONDS: resolving six audiences reads every lead.
"""

from __future__ import annotations

from collections import Counter

from sqlalchemy.orm import Session

from app.core import cache

CACHE_SECONDS = 600


def overview(db: Session, tenant_id: str, use_cache: bool = True) -> dict:
    key = f"haip:lead_segments:{tenant_id}"
    if use_cache:
        hit = cache.get_cached(key)
        if isinstance(hit, dict):
            return hit
    out = {"presets": _presets(db, tenant_id), "tags": _tags(db, tenant_id)}
    cache.set_cached(key, out, ttl=CACHE_SECONDS)
    return out


def _presets(db: Session, tenant_id: str) -> list[dict]:
    from app.services import wa_lead_audience as aud

    rows = []
    for p in aud.PRESETS:
        res = aud.resolve(db, tenant_id, {"type": "leads", **p["filter"]})
        b = res.breakdown()
        rows.append({"id": p["id"], "label": p["label"], "description": p["description"], "filter": p["filter"],
                     "people": b["matched"], "reachable": b["will_receive"], "opted_out": b["opted_out"]})
    return rows


def _tags(db: Session, tenant_id: str) -> list[dict]:
    from app.models.inquiry import Inquiry
    from app.models.pipeline_stage import PipelineStage
    from app.services.lead_tags import VOCABULARY

    closed = {sid for (sid,) in db.query(PipelineStage.id).filter(
        PipelineStage.tenant_id == tenant_id,
        (PipelineStage.is_closed_won.is_(True)) | (PipelineStage.is_closed_lost.is_(True)))}
    counts: Counter = Counter()
    for stage_id, tags in db.query(Inquiry.stage_id, Inquiry.tags).filter(Inquiry.tenant_id == tenant_id):
        if stage_id in closed or not isinstance(tags, list):
            continue
        counts.update({t for t in tags if isinstance(t, str)})
    return [{"label": group, "tags": [{"tag": t, "open_leads": counts.get(t, 0)} for t in tags]}
            for group, tags in VOCABULARY.items()]
