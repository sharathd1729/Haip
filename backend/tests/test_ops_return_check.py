"""Return vs handover photos (Ops phase 2): the return job opens on return, "return <zone>" photos are compared with that
zone's handover photo in one side-by-side JPEG, a difference flags possible damage, and the settle step shows the result."""

import io
import uuid

import pytest
from PIL import Image

from app.models.ops import OpsItem
from app.models.ops_files import OpsJob
from app.services import ops_return_check as rc
from app.services import ops_trip_service as trips
from tests.ops_helpers import prop, staff
from tests.test_ops_files import _actor_u1, _green_all_critical, _pay, _ready_file, _stay, _tenant  # noqa: F401
from tests.test_ops_photo_intake import RAW, _Model, _store


def _jpeg(w, h, colour=(10, 200, 30)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (w, h), colour).save(out, format="JPEG")
    return out.getvalue()


@pytest.fixture()
def w(db):
    t = _tenant(db)
    p = prop(db, t.id, "Ratha 1")
    w = type(
        "W",
        (),
        {
            "t": t,
            "p": p,
            "stay": _stay(db, t, p),
            "driver": staff(db, t.id, "Suresh", "driver"),
            "helper": staff(db, t.id, "Raju", "driver"),
        },
    )()
    w.f = _ready_file(db, w)
    _green_all_critical(db, w.f)
    next(i for i in trips.readiness_items(db, w.f) if i.key == "ac").photo_key = "t/ops/f/handover-ac.jpg"
    _pay(db, w.stay, "126732")
    trips.refresh(db, w.f)
    trips.dispatch(db, w.f, 87396, "u1")
    trips.end_trip(db, w.f, 88000, actor_id="u1")
    return w


def _send(db, w, caption, answer):
    m = _Model(answer)
    out = rc.handle(
        db,
        w.t.id,
        w.helper,
        raw=RAW,
        caption=caption,
        message_id=f"wamid.{uuid.uuid4().hex[:6]}",
        describe=m,
        store=_store,
        fetch=lambda key: _jpeg(30, 60),
    )
    return out, m


def test_compose_puts_both_photos_side_by_side_at_one_height():
    with Image.open(io.BytesIO(rc.compose(_jpeg(40, 30), _jpeg(30, 60)))) as im:
        assert im.format == "JPEG" and im.height == rc.HEIGHT and im.width == 1024 + 12 + 384


def test_return_opens_a_job_with_the_photo_zones(db, w):
    assert db.query(OpsJob).filter_by(file_id=w.f.id, kind="return").count() == 1
    keys = {i.key for i in rc.return_items(db, w.f)}
    assert keys == {"tyres", "electrical", "ac", "water", "interior", "safety", "inventory"}
    assert trips.stage(db, w.f)["tasks"][0]["hint"] == "0 of 7 return photos checked"


def test_a_matching_photo_is_green(db, w):
    out, m = _send(
        db, w, "return ac", {"same_zone": True, "differences": [], "damage_likely": False, "confidence": 0.9}
    )
    assert "matches" in out.reply and "HANDOVER" not in m.prompts[0] and "AC and cooling" in m.prompts[0]
    assert next(i for i in rc.return_items(db, w.f) if i.key == "ac").status == "green"
    assert "no differences found" in rc.summary(db, w.f)["words"]


def test_damage_turns_the_zone_red_and_flags_the_manager(db, w):
    out, _ = _send(
        db,
        w,
        "Return AC",
        {"same_zone": True, "differences": ["vent cover cracked"], "damage_likely": True, "confidence": 0.8},
    )
    item = next(i for i in rc.return_items(db, w.f) if i.key == "ac")
    assert item.status == "red" and "vent cover cracked" in item.note
    flag = db.query(OpsItem).filter_by(tenant_id=w.t.id, stay_id=w.stay.id).one()
    assert "possible damage: AC and cooling" in flag.title and flag.severity == "high"
    assert "possible damage: AC and cooling" in rc.summary(db, w.f)["words"]
    assert "manager has been told" in out.reply


def test_no_handover_photo_or_unclear_photo_changes_nothing_silently(db, w):
    out, m = _send(db, w, "return water", {"same_zone": True, "differences": [], "confidence": 0.9})
    assert m.prompts == [] and "no handover photo" in out.reply
    assert next(i for i in rc.return_items(db, w.f) if i.key == "water").note.startswith("No handover photo")
    out, _ = _send(db, w, "return ac", {"same_zone": False, "confidence": 0.9})
    assert (
        "send it again" in out.reply and next(i for i in rc.return_items(db, w.f) if i.key == "ac").status == "pending"
    )
    out, m = _send(db, w, "return", {})
    assert m.prompts == [] and "return ac" in out.reply


def test_the_intake_routes_return_captions_and_other_tenants_get_nothing(db, w):
    from app.services import ops_photo_intake as intake

    out = intake.handle_photo(
        db, w.t.id, w.helper, raw=RAW, caption="return tyres", message_id="wamid.x", describe=_Model({}), store=_store
    )
    assert "no handover photo" in out.reply
    other = _tenant(db)
    stranger = staff(db, other.id, "Other", "driver")
    assert "No returned trip" in rc.handle(db, other.id, stranger, raw=RAW, caption="return ac", message_id="m").reply
