"""scripts/move_calls_between_tenants.py: Jade's Mcube calls that landed in Ratha's workspace move to Jade;
guests Ratha also knows stay in Ratha; nothing else in either tenant is touched."""
import uuid

from app.models.call import Call, CallDirection
from app.models.conversation import ChannelType, Conversation
from app.models.guest_identity import GuestIdentity
from app.models.inquiry import Inquiry
from app.models.tenant import Tenant
from app.services import identity_service
from scripts.move_calls_between_tenants import plan_and_move

JADE_DID = "+918970663366"


def _tenant(db, slug):
    t = Tenant(id=str(uuid.uuid4()), name=slug, slug=f"{slug}-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.flush()
    return t


def _guest(db, tenant, phone):
    gid, _ = identity_service.resolve_gid(db, tenant.id, signal_type="phone", value=phone, source="test")
    return gid


def _call(db, tenant, guest_id, phone, to=JADE_DID, provider="mcube"):
    c = Call(id=str(uuid.uuid4()), tenant_id=tenant.id, ivr_provider=provider, ivr_call_id=uuid.uuid4().hex,
             direction=CallDirection.INBOUND, from_number=phone, to_number=to, guest_id=guest_id)
    db.add(c)
    db.flush()
    return c


def _setup(db):
    ratha, jade = _tenant(db, "rathaa"), _tenant(db, "jade")
    only_mcube = _guest(db, ratha, "+919000000001")
    inq = Inquiry(id=str(uuid.uuid4()), tenant_id=ratha.id, guest_id=only_mcube)
    db.add(inq)
    c1 = _call(db, ratha, only_mcube, "+919000000001")
    c1.inquiry_id = inq.id

    chatted = _guest(db, ratha, "+919000000002")                       # also wrote to Ratha on WhatsApp
    db.add(Conversation(id=str(uuid.uuid4()), tenant_id=ratha.id, guest_id=chatted, channel=ChannelType.WHATSAPP))
    c2 = _call(db, ratha, chatted, "+919000000002")

    test_call = _call(db, ratha, only_mcube, "+919000000001", to="+918035053336")   # Mcube's sample DID: stays
    vobiz = _call(db, ratha, chatted, "+919000000002", to="+918000000000", provider="vobiz")
    db.commit()
    return ratha, jade, dict(only_mcube=only_mcube, chatted=chatted, inq=inq.id, c1=c1.id, c2=c2.id,
                             test_call=test_call.id, vobiz=vobiz.id)


def _run(db, ratha, jade, apply):
    return plan_and_move(db, src=ratha.id, dst=jade.id, provider="mcube", to_number=JADE_DID, apply=apply)


def test_dry_run_counts_and_writes_nothing(db):
    ratha, jade, ids = _setup(db)
    report = _run(db, ratha, jade, apply=False)
    assert report["calls"] == 2
    # only_mcube also has the sample-DID test call (not moving), so it is NOT exclusive and stays.
    assert report["guests_moved"] == 0 and report["guests_kept"] == 2
    assert db.query(Call).filter_by(tenant_id=jade.id).count() == 0


def test_apply_moves_calls_keeps_known_guests_and_is_idempotent(db):
    ratha, jade, ids = _setup(db)
    db.query(Call).filter_by(id=ids["test_call"]).delete()   # now only_mcube's sole activity is the Jade call
    db.commit()

    report = _run(db, ratha, jade, apply=True)
    db.commit()
    assert report["calls"] == 2 and report["guests_moved"] == 1 and report["guests_kept"] == 1

    c1, c2 = db.get(Call, ids["c1"]), db.get(Call, ids["c2"])
    assert c1.tenant_id == jade.id and c1.guest_id == ids["only_mcube"]       # guest moved with its call
    assert db.get(Inquiry, ids["inq"]).tenant_id == jade.id
    assert db.query(GuestIdentity).filter_by(guest_id=ids["only_mcube"], tenant_id=jade.id).count() >= 1

    assert c2.tenant_id == jade.id and c2.guest_id != ids["chatted"]          # re-attached to a Jade guest
    assert db.query(GuestIdentity).filter_by(guest_id=c2.guest_id, tenant_id=jade.id).count() >= 1
    assert db.query(Conversation).filter_by(guest_id=ids["chatted"], tenant_id=ratha.id).count() == 1

    assert db.get(Call, ids["vobiz"]).tenant_id == ratha.id                    # other providers untouched
    assert _run(db, ratha, jade, apply=True)["calls"] == 0                     # second run: nothing left


def test_other_tenants_untouched(db):
    ratha, jade, ids = _setup(db)
    other = _tenant(db, "other")
    og = _guest(db, other, "+919000000009")
    oc = _call(db, other, og, "+919000000009")
    db.commit()
    _run(db, ratha, jade, apply=True)
    db.commit()
    assert db.get(Call, oc.id).tenant_id == other.id
