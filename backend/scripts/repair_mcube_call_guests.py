"""
Re-link Mcube calls that were saved against the business's own landing number.

Before the adapter fix, a Jade call whose Mcube post had `callfrom` == `landingnumber` was stored with
from_number == to_number == the landing number, so every such call sat on ONE bogus "guest" (Jade's own number) and
the real caller (Mcube's `callto`) was never stored on the call. This script finds the caller and moves each call to
the right guest and lead:

- From the recording file name: Mcube names it `<callto><callid>.wav`, so a name that ends with the call id gives
  the caller's number in front of it.
- Or from an Mcube call-log export: `--numbers-csv file.csv` with columns `callid,number` (wins over the file name).

    python scripts/repair_mcube_call_guests.py --tenant-slug jade-hospitainment                  # dry run, counts only
    python scripts/repair_mcube_call_guests.py --tenant-slug jade-hospitainment --apply
    python scripts/repair_mcube_call_guests.py --tenant-slug jade-hospitainment --numbers-csv mcube.csv --apply

Guest resolution goes through identity_service (via call_ingest._dedup_guest). Calls with no recoverable number are
left as they are and counted. The bogus landing-number guest is NOT deleted; it is reported so a person can close its
lead. Safe to re-run: a repaired call no longer has from_number == to_number. Output shows last 4 digits only.
"""
import argparse
import csv
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.models  # noqa: E402,F401
from app.core.audit import append_audit  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.models.call import Call  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402

_DIGITS = re.compile(r"\d{10,12}")


def number_from_filename(recording_url: str | None, call_id: str) -> str | None:
    """`.../<callto><callid>.wav` -> callto (10-12 digits), else None."""
    if not recording_url or not call_id:
        return None
    stem = Path(urlparse(recording_url).path).stem
    if not stem.endswith(call_id):
        return None
    prefix = stem[: -len(call_id)]
    return prefix if _DIGITS.fullmatch(prefix) else None


def load_numbers_csv(path: str) -> dict[str, str]:
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return {r["callid"].strip(): r["number"].strip() for r in csv.DictReader(fh)
                if r.get("callid") and r.get("number")}


def repair(db, tenant_id: str, apply: bool, numbers: dict[str, str] | None = None) -> dict:
    from app.adapters.ivr.mcube import McubeAdapter
    from app.services.inquiry_service import get_or_create_from_call
    from app.workers.tasks.call_ingest import _dedup_guest, _find_or_create_voice_conversation

    numbers = numbers or {}
    norm = McubeAdapter()._normalize_phone
    calls = db.query(Call).filter(
        Call.tenant_id == tenant_id, Call.ivr_provider == "mcube", Call.from_number == Call.to_number,
    ).order_by(Call.created_at).all()
    report = {"found": len(calls), "fixed": 0, "no_number": 0, "bogus_guest_ids": set(), "last4": []}
    for call in calls:
        raw = numbers.get(call.ivr_call_id) or number_from_filename(call.recording_url_ivr, call.ivr_call_id)
        guest_number = norm(raw) if raw else ""
        if not guest_number or guest_number == call.to_number:
            report["no_number"] += 1
            continue
        report["fixed"] += 1
        report["last4"].append(guest_number[-4:])
        if call.guest_id:
            report["bogus_guest_ids"].add(call.guest_id)
        if not apply:
            continue
        guest = _dedup_guest(db, tenant_id, guest_number)
        _find_or_create_voice_conversation(db, tenant_id, guest)
        inquiry = get_or_create_from_call(db, tenant_id, guest.id, direction=call.direction.value
                                          if hasattr(call.direction, "value") else str(call.direction),
                                          answered=(call.duration_seconds or 0) > 0)
        call.guest_id = guest.id
        call.inquiry_id = inquiry.id if inquiry else None
        call.from_number = guest_number
        db.flush()
    if apply and report["fixed"]:
        append_audit(db, tenant_id=tenant_id, action="call.guest_repaired", target_type="tenant", target_id=tenant_id,
                     payload={"calls": report["fixed"], "source": "repair_mcube_call_guests.py",
                              "actor": "system"})
    report["bogus_guest_ids"] = sorted(report["bogus_guest_ids"])
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant-slug", required=True)
    ap.add_argument("--numbers-csv")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter_by(slug=a.tenant_slug).one_or_none()
        if not tenant:
            print("ERROR: unknown tenant slug")
            return 2
        from app.core.database import set_tenant_context
        set_tenant_context(db, tenant.id)
        numbers = load_numbers_csv(a.numbers_csv) if a.numbers_csv else None
        r = repair(db, tenant.id, a.apply, numbers)
        print(("APPLYING" if a.apply else "DRY RUN (nothing written; add --apply)")
              + f": {r['found']} Mcube calls saved on the landing number; "
              f"{r['fixed']} {'re-linked' if a.apply else 'can be re-linked'}, {r['no_number']} with no number found")
        if r["last4"]:
            print("  callers (last 4 digits): " + ", ".join(sorted(set(r["last4"]))))
        for gid in r["bogus_guest_ids"]:
            print(f"  wrong guest these calls were on (not deleted; close its lead by hand): {gid}")
        if a.apply:
            db.commit()
            print("done")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
