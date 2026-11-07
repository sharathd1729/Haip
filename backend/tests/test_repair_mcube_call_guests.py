"""scripts/repair_mcube_call_guests.py: moves calls saved on the landing number to the real caller; nothing else."""
import uuid

from app.models.call import Call, CallDirection
from app.models.guest import Guest
from app.models.tenant import Tenant
from scripts.repair_mcube_call_guests import number_from_filename, repair

LANDING = "+918970663366"


def _call(db, tenant_id, call_id, url, from_number=LANDING, guest_id=None):
    c = Call(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest_id, ivr_provider="mcube", ivr_call_id=call_id,
             direction=CallDirection.INBOUND, from_number=from_number, to_number=LANDING, duration_seconds=40,
             recording_url_ivr=url)
    db.add(c)
    db.flush()
    return c


def test_number_from_filename():
    assert number_from_filename("https://recordings.mcube.com/r/2026/11/98765030531762523456.wav",
                                "1762523456") == "9876503053"
    assert number_from_filename("https://recordings.mcube.com/r/other.wav", "1762523456") is None
    assert number_from_filename("https://recordings.mcube.com/r/ab1762523456.wav", "1762523456") is None
    assert number_from_filename(None, "1762523456") is None


def test_dry_run_writes_nothing_then_apply_relinks_only_landing_number_calls(db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    other = Tenant(id=str(uuid.uuid4()), name="o", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    bogus = Guest(id=str(uuid.uuid4()), tenant_id=tid, name="Jade landing")
    db.add(bogus)
    db.flush()
    cid = uuid.uuid4().hex[:10]
    bad = _call(db, tid, cid, f"https://recordings.mcube.com/r/9876503053{cid}.wav", guest_id=bogus.id)
    unknown = _call(db, tid, "nofile", "https://recordings.mcube.com/r/x.wav", guest_id=bogus.id)
    fine = _call(db, tid, "ok1", "https://recordings.mcube.com/r/y.wav", from_number="+917249066854")
    elsewhere = _call(db, other.id, "o1", f"https://recordings.mcube.com/r/9876503053o1.wav")

    dry = repair(db, tid, apply=False)
    assert (dry["found"], dry["fixed"], dry["no_number"]) == (2, 1, 1)
    assert dry["bogus_guest_ids"] == [bogus.id] and dry["last4"] == ["3053"]
    db.refresh(bad)
    assert bad.guest_id == bogus.id and bad.from_number == LANDING

    done = repair(db, tid, apply=True)
    assert done["fixed"] == 1
    db.refresh(bad)
    assert bad.from_number == "+919876503053" and bad.guest_id != bogus.id and bad.inquiry_id
    assert db.query(Guest).filter_by(id=bad.guest_id).one().tenant_id == tid
    db.refresh(unknown), db.refresh(fine), db.refresh(elsewhere)
    assert unknown.guest_id == bogus.id                                   # no number found: left alone
    assert fine.from_number == "+917249066854"                            # normal call untouched
    assert elsewhere.from_number == LANDING                               # other workspace untouched
    assert repair(db, tid, apply=True)["fixed"] == 0                      # re-run: nothing to do


def test_csv_number_wins_over_filename(db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    c = _call(db, tid, "csv1", "https://recordings.mcube.com/r/x.wav")
    assert repair(db, tid, apply=True, numbers={"csv1": "9123404321"})["fixed"] == 1
    db.refresh(c)
    assert c.from_number == "+919123404321"
