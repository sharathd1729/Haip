"""scripts/import_properties.py: creates only missing properties, never touches existing or other workspaces."""
import json
import uuid
from pathlib import Path

from app.models.property import Property
from app.models.tenant import Tenant
from scripts.import_properties import import_properties

DATA = Path(__file__).resolve().parent.parent / "scripts" / "data" / "jade_properties.json"


def _tenant(db, slug):
    t = Tenant(id=str(uuid.uuid4()), name=slug, slug=f"{slug}-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.flush()
    return t


def test_jade_file_is_complete():
    rows = json.loads(DATA.read_text(encoding="utf-8"))["properties"]
    assert len(rows) == 14
    for r in rows:
        assert r["name"] and r["slug"] and r["bedrooms"] >= 1 and r["max_adults"] >= 2 and len(r["description"]) > 200


def test_dry_run_writes_nothing_and_apply_skips_existing(db):
    jade, other = _tenant(db, "jade"), _tenant(db, "other")
    db.add(Property(tenant_id=jade.id, name="Emerald by Jade", slug="emerald"))
    db.add(Property(tenant_id=other.id, name="Haven by Jade", slug="haven"))
    db.commit()
    rows = json.loads(DATA.read_text(encoding="utf-8"))["properties"]

    dry = import_properties(db, jade.id, rows, apply=False)
    assert len(dry["created"]) == 13 and dry["skipped"] == ["Emerald by Jade"]
    assert db.query(Property).filter_by(tenant_id=jade.id).count() == 1

    import_properties(db, jade.id, rows, apply=True)
    db.commit()
    assert db.query(Property).filter_by(tenant_id=jade.id).count() == 14
    haven = db.query(Property).filter_by(tenant_id=jade.id, slug="haven").one()
    assert haven.bedrooms == 5 and haven.max_adults == 25 and haven.amenities
    assert db.query(Property).filter_by(tenant_id=other.id).count() == 1          # other workspace untouched
    assert import_properties(db, jade.id, rows, apply=True)["created"] == []        # re-run creates nothing
