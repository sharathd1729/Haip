"""Where the property assessment's numbers come from: ONE function, ``active()``.

Source order: the active ``roi_benchmarks`` row (set by the owner of HAIP's sales workspace), else the seed file
``app/data/roi_benchmarks/ka-2026-10-sample-v1.json`` (SAMPLE Karnataka values, every entry "sample — owner to
confirm"). A future market-data feed (AirDNA, PriceLabs, STR) plugs in here and nowhere else.

Versions are immutable: ``create_version`` stores a new validated set (inactive), ``activate`` switches to it; both are
audited in the sales workspace's chain. Activating the seed's version deactivates every stored row.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Optional

import structlog
from sqlalchemy.orm import Session

from app.models.roi_benchmark import RoiBenchmarkVersion
from app.schemas.assessment import BenchmarkSet

log = structlog.get_logger()

SEED_FILE = Path(__file__).resolve().parents[1] / "data" / "roi_benchmarks" / "ka-2026-10-sample-v1.json"


class VersionExists(ValueError):
    pass


@lru_cache(maxsize=1)
def _seed_json() -> str:
    data = json.loads(SEED_FILE.read_text(encoding="utf-8"))
    return json.dumps(BenchmarkSet.model_validate(data).model_dump())


def seed() -> dict:
    """A fresh copy every call: callers may not mutate the cached seed."""
    return json.loads(_seed_json())


def active(db: Session) -> dict:
    row = (db.query(RoiBenchmarkVersion).filter(RoiBenchmarkVersion.is_active.is_(True))
           .order_by(RoiBenchmarkVersion.activated_at.desc()).first())
    return dict(row.data) if row is not None else seed()


def get_version(db: Session, version: str) -> Optional[dict]:
    s = seed()
    if version == s["version"]:
        return s
    row = db.query(RoiBenchmarkVersion).filter_by(version=version).first()
    return dict(row.data) if row is not None else None


def list_versions(db: Session) -> list[dict]:
    rows = db.query(RoiBenchmarkVersion).order_by(RoiBenchmarkVersion.created_at.desc()).all()
    any_active = any(r.is_active for r in rows)
    s = seed()
    out = [{"version": r.version, "label": (r.data or {}).get("label"), "sample": bool((r.data or {}).get("sample")),
            "source": "stored", "is_active": bool(r.is_active), "notes": r.notes,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "activated_at": r.activated_at.isoformat() if r.activated_at else None} for r in rows]
    out.append({"version": s["version"], "label": s["label"], "sample": s["sample"], "source": "seed",
                "is_active": not any_active, "notes": "Seed file shipped with the code", "created_at": None,
                "activated_at": None})
    return out


def create_version(db: Session, data: BenchmarkSet, *, notes: Optional[str], actor_user_id: str, tenant_id: str) -> RoiBenchmarkVersion:
    version = data.version
    if version == seed()["version"] or db.query(RoiBenchmarkVersion).filter_by(version=version).first():
        raise VersionExists(f"Version {version} already exists. A changed set needs a new version name.")
    row = RoiBenchmarkVersion(version=version, data=data.model_dump(), notes=notes, is_active=False,
                              created_by_user_id=actor_user_id)
    db.add(row)
    db.flush()
    from app.core.audit import append_audit
    append_audit(db, tenant_id=tenant_id, action="roi_benchmarks.created", actor_user_id=actor_user_id,
                 target_type="roi_benchmarks", target_id=row.id, payload={"version": version, "notes": notes})
    db.commit()
    log.info("roi_benchmarks_created", version=version, actor=actor_user_id)
    return row


def activate(db: Session, version: str, *, actor_user_id: str, tenant_id: str) -> str:
    """Make ``version`` the one the public assessment uses. Raises LookupError for an unknown version."""
    is_seed = version == seed()["version"]
    row = None if is_seed else db.query(RoiBenchmarkVersion).filter_by(version=version).first()
    if not is_seed and row is None:
        raise LookupError(version)
    previous = active(db)["version"]
    db.query(RoiBenchmarkVersion).filter(RoiBenchmarkVersion.is_active.is_(True)).update(
        {RoiBenchmarkVersion.is_active: False}, synchronize_session=False)
    if row is not None:
        row.is_active = True
        row.activated_at = datetime.now(timezone.utc)
    from app.core.audit import append_audit
    append_audit(db, tenant_id=tenant_id, action="roi_benchmarks.activated", actor_user_id=actor_user_id,
                 target_type="roi_benchmarks", target_id=row.id if row else None,
                 payload={"version": version, "previous": previous})
    db.commit()
    log.info("roi_benchmarks_activated", version=version, previous=previous, actor=actor_user_id)
    return version
