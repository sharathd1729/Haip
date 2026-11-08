"""Packs as data (Ops 2, gap 7): copy a segment's pack defaults into the business's own rows, read them back, edit them.

  checklists   ops_checklist_templates: one default row per pack + kind (property_id NULL); a property may have its own
               copy (property_id set), used for that property's jobs instead.
  pack data    ops_settings.pack_config[pack] = {flow, duties, issue_types, paperwork, addons, auto_messages}.

seed() is idempotent and INSERT-ONLY: a missing row or key is filled from ops_pack_catalog; anything already there (a
person's edit, or an older seed) is left exactly as it is. It runs at sign-up, when the business type changes in Settings,
and in the daily ops sync (so existing businesses get their pack without a migration).
"""

from __future__ import annotations

import copy

from sqlalchemy.orm import Session

from app.models.ops import OpsSettings
from app.models.ops_files import OpsChecklistTemplate
from app.models.tenant import Tenant
from app.services import ops_pack_catalog as packs

CONFIG_KEYS = ("flow", "duties", "issue_types", "paperwork", "addons", "auto_messages")


def business_pack(db: Session, tenant_id: str) -> str | None:
    tenant = db.query(Tenant).filter_by(id=tenant_id).first()
    return packs.pack_for_business_type(tenant.business_type if tenant else None)


def _defaults(pack: str) -> dict:
    spec = packs.get(pack)
    return {
        "flow": spec["flow"],
        "duties": list(spec["duties"]),
        "issue_types": copy.deepcopy(spec["issue_types"]),
        "paperwork": list(spec["paperwork"]),
        "addons": copy.deepcopy(spec["addons"]),
        "auto_messages": copy.deepcopy(spec["auto_messages"]),
    }


# ── Checklists ──────────────────────────────────────────────────────────────


def _row(db: Session, tenant_id: str, pack: str, kind: str, property_id: str | None) -> OpsChecklistTemplate | None:
    q = db.query(OpsChecklistTemplate).filter_by(tenant_id=tenant_id, pack=pack, kind=kind)
    q = (
        q.filter(OpsChecklistTemplate.property_id.is_(None))
        if property_id is None
        else q.filter_by(property_id=property_id)
    )
    return q.first()


def default_template(db: Session, tenant_id: str, pack: str, kind: str) -> OpsChecklistTemplate:
    """The business's checklist for pack + kind, created from the pack's defaults the first time."""
    t = _row(db, tenant_id, pack, kind, None)
    if t is None:
        spec = packs.get(pack)["checklists"][kind]
        t = OpsChecklistTemplate(
            tenant_id=tenant_id, pack=pack, kind=kind, name=spec["name"], items=copy.deepcopy(spec["items"])
        )
        db.add(t)
        db.flush()
    return t


def template(db: Session, tenant_id: str, pack: str, kind: str, property_id: str | None = None) -> OpsChecklistTemplate:
    """The checklist a job at this property uses: the property's own copy, else the business's default."""
    if property_id is not None:
        own = _row(db, tenant_id, pack, kind, property_id)
        if own is not None:
            return own
    return default_template(db, tenant_id, pack, kind)


def save_template(
    db: Session, tenant_id: str, pack: str, kind: str, name: str, items: list[dict], property_id: str | None = None
) -> OpsChecklistTemplate:
    """A person's edit: the business default, or the property's own copy (created on its first edit)."""
    if kind not in packs.get(pack)["checklists"]:
        raise KeyError(kind)
    t = (
        default_template(db, tenant_id, pack, kind)
        if property_id is None
        else _row(db, tenant_id, pack, kind, property_id)
    )
    if t is None:
        t = OpsChecklistTemplate(
            tenant_id=tenant_id, pack=pack, kind=kind, property_id=property_id, name=name, items=[]
        )
        db.add(t)
    t.name, t.items = name, [dict(i) for i in items]
    db.flush()
    return t


def reset_property_template(db: Session, tenant_id: str, pack: str, kind: str, property_id: str) -> bool:
    """The property goes back to the business's checklist. True when it had its own."""
    t = _row(db, tenant_id, pack, kind, property_id)
    if t is None:
        return False
    db.delete(t)
    db.flush()
    return True


def property_overrides(db: Session, tenant_id: str, pack: str) -> dict[str, list[str]]:
    """{kind: [property ids with their own copy]}."""
    out: dict[str, list[str]] = {}
    for kind, pid in db.query(OpsChecklistTemplate.kind, OpsChecklistTemplate.property_id).filter(
        OpsChecklistTemplate.tenant_id == tenant_id,
        OpsChecklistTemplate.pack == pack,
        OpsChecklistTemplate.property_id.isnot(None),
    ):
        out.setdefault(kind, []).append(pid)
    return out


# ── Pack data ───────────────────────────────────────────────────────────────


def _settings_row(db: Session, tenant_id: str) -> OpsSettings:
    row = db.query(OpsSettings).filter_by(tenant_id=tenant_id).first()
    if row is None:
        row = OpsSettings(tenant_id=tenant_id)
        db.add(row)
        db.flush()
    return row


def config(db: Session, tenant_id: str, pack: str | None = None) -> dict:
    """The business's pack data: what it saved, with the pack's defaults under anything missing."""
    pack = pack or business_pack(db, tenant_id)
    if pack is None:
        return {}
    out = _defaults(pack)
    row = db.query(OpsSettings).filter_by(tenant_id=tenant_id).first()
    saved = ((row.pack_config or {}) if row else {}).get(pack) or {}
    for key in CONFIG_KEYS:
        if key == "auto_messages" and isinstance(saved.get(key), dict):
            for kind, timing in saved[key].items():
                if kind in out[key] and isinstance(timing, dict):
                    out[key][kind] = {**out[key][kind], **timing}
        elif key in saved:
            out[key] = saved[key]
    return out


def save_config(db: Session, tenant_id: str, pack: str, patch: dict) -> dict:
    """A person's edit of the pack data (validated by the endpoint's schema). Only the keys given change."""
    row = _settings_row(db, tenant_id)
    allcfg = copy.deepcopy(row.pack_config or {})
    mine = dict(allcfg.get(pack) or {})
    for key, value in patch.items():
        if key == "auto_messages":
            merged = dict(mine.get(key) or {})
            for kind, timing in value.items():
                merged[kind] = {**(merged.get(kind) or {}), **timing}
            mine[key] = merged
        else:
            mine[key] = value
    allcfg[pack] = mine
    row.pack_config = allcfg  # a new dict: SQLAlchemy sees the change
    db.flush()
    return config(db, tenant_id, pack)


def message_hours(db: Session, tenant_id: str, pack: str, kind: str) -> int:
    """Hours before/after for one automatic message (the business's edit, else the pack default)."""
    timing = config(db, tenant_id, pack)["auto_messages"][kind]
    return int(timing["hours"])


def seed(db: Session, tenant_id: str, business_type: str | None = None) -> dict:
    """Fill the business's missing checklist rows and pack-data keys from its pack. Never changes what is there."""
    if business_type is None:
        pack = business_pack(db, tenant_id)
    else:
        pack = packs.pack_for_business_type(business_type)
    if pack is None:
        return {"pack": None, "templates_created": 0, "config_keys_added": 0}
    created = 0
    for kind in packs.get(pack)["checklists"]:
        if _row(db, tenant_id, pack, kind, None) is None:
            default_template(db, tenant_id, pack, kind)
            created += 1
    row = _settings_row(db, tenant_id)
    allcfg = copy.deepcopy(row.pack_config or {})
    mine = dict(allcfg.get(pack) or {})
    added = 0
    for key, value in _defaults(pack).items():
        if key not in mine:
            mine[key] = value
            added += 1
        elif key == "auto_messages" and isinstance(mine[key], dict):
            for kind, timing in value.items():  # a timing added to the pack later reaches older businesses too
                if kind not in mine[key]:
                    mine[key] = {**mine[key], kind: timing}
                    added += 1
    if added:
        allcfg[pack] = mine
        row.pack_config = allcfg
        db.flush()
    return {"pack": pack, "templates_created": created, "config_keys_added": added}
