"""
One-off backfill for Guest rows created by the pre-fix call_ingest.py
_dedup_guest() (see call_ingest.py commit "route call guest dedup through
identity_service") -- that code hardcoded name="Unknown Guest" and did a
raw phone= lookup, bypassing identity_service.py entirely. Two consequences
this backfill fixes:

  1. Those guests never got a guest_identities "phone" signal written, so
     if the same phone later comes in via WhatsApp/Instagram/another call,
     identity_service can't find them and creates a SEPARATE duplicate
     guest instead of resolving to the existing one.
  2. If a duplicate with a real name already exists for the same phone
     (created via the correct identity_service path on another channel),
     the "Unknown Guest" call-only row and the real one never got merged.

For each tenant (or all tenants if --tenant-slug omitted):
  - For every non-deleted Guest named exactly "Unknown Guest" with a
    non-empty phone:
      - If another *different*, non-deleted guest already owns a "phone"
        signal for the same number:
          - If that other guest has a real name (not "Unknown Guest",
            not empty): merge the placeholder INTO the real one (real
            guest survives, keeps its name) -- merge_guests() only ever
            preserves the survivor's own fields, so direction matters.
          - Otherwise (both sides are placeholders): merge the newer
            row into the older one, arbitrarily, just to consolidate.
      - If no signal exists for this phone at all: write it via
        identity_service.add_signal() so future channels resolve
        correctly to this guest.

Usage (inside the API container, against production):
    docker compose -f docker-compose.prod.yml exec api \
        python3 scripts/backfill_unknown_guest_identity.py --tenant-slug ratha --dry-run
    docker compose -f docker-compose.prod.yml exec api \
        python3 scripts/backfill_unknown_guest_identity.py --tenant-slug ratha
"""
import argparse
import sys

import phonenumbers

from app.core.database import SessionLocal
from app.models.guest import Guest
from app.models.guest_identity import GuestIdentity
from app.models.tenant import Tenant
from app.services import identity_service
from app.services.identity_resolution import merge_guests

PLACEHOLDER_NAME = "Unknown Guest"


def _e164(phone: str) -> str:
    try:
        parsed = phonenumbers.parse(phone, "IN")
        return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except Exception:
        return phone


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-slug", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        q = db.query(Guest).filter(
            Guest.name == PLACEHOLDER_NAME,
            Guest.is_deleted.is_(False),
            Guest.phone != "",
        )
        if args.tenant_slug:
            tenant = db.query(Tenant).filter_by(slug=args.tenant_slug).first()
            if not tenant:
                print(f"No tenant with slug={args.tenant_slug!r}", file=sys.stderr)
                sys.exit(1)
            q = q.filter(Guest.tenant_id == tenant.id)

        placeholders = q.all()
        print(f"Found {len(placeholders)} '{PLACEHOLDER_NAME}' guest(s) with a phone.")

        merged = 0
        signals_written = 0
        already_ok = 0

        for guest in placeholders:
            e164 = _e164(guest.phone)
            existing = (
                db.query(GuestIdentity)
                .filter_by(tenant_id=guest.tenant_id, identity_type="phone", identity_value=e164)
                .first()
            )

            if existing and existing.guest_id != guest.id:
                other = db.query(Guest).filter_by(id=existing.guest_id, tenant_id=guest.tenant_id).first()
                if not other or other.is_deleted:
                    # Signal points at a guest that's already gone -- just
                    # re-attach the signal to this guest below.
                    existing = None
                else:
                    other_has_real_name = bool(other.name) and other.name != PLACEHOLDER_NAME
                    if other_has_real_name:
                        survivor, deprecated = other, guest
                    else:
                        # Both placeholders -- keep whichever was created first.
                        survivor, deprecated = (guest, other) if guest.created_at <= other.created_at else (other, guest)
                    print(f"  merge: survivor={survivor.id} ({survivor.name!r}) "
                          f"<- deprecated={deprecated.id} ({deprecated.name!r})")
                    if not args.dry_run:
                        merge_guests(db, guest.tenant_id, survivor_id=survivor.id, deprecated_id=deprecated.id)
                    merged += 1
                    continue

            if existing and existing.guest_id == guest.id:
                already_ok += 1
                continue

            # No signal at all for this phone -- backfill it.
            print(f"  add_signal: guest={guest.id} phone={e164[-4:]!r}")
            if not args.dry_run:
                identity_service.add_signal(
                    db, guest.tenant_id, guest_id=guest.id,
                    signal_type="phone", value=e164, source="backfill_migration",
                )
                db.commit()
            signals_written += 1

        if args.dry_run:
            print(f"Dry run -- would merge {merged}, write {signals_written} signals, "
                  f"{already_ok} already correct.")
        else:
            print(f"Merged {merged}, wrote {signals_written} signals, {already_ok} already correct.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
