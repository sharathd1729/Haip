"""
Copy a Facebook (System User, "EAA...") token that was saved on a workspace's Instagram connection into its Meta
Business connection, so Ads and lead forms can use it and it survives an Instagram Login reconnect (which replaces
the Instagram connection's token).

    python scripts/copy_meta_token_to_business.py --tenant-slug jade-hospitainment          # dry run
    python scripts/copy_meta_token_to_business.py --tenant-slug jade-hospitainment --apply

The token is checked with Meta before it is saved. It is never printed. Safe to re-run.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.models  # noqa: E402,F401
from app.core.audit import append_audit  # noqa: E402
from app.core.database import SessionLocal, set_tenant_context  # noqa: E402
from app.core.encryption import decrypt_credentials  # noqa: E402
from app.models.integration import Integration  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.services import meta_business_service  # noqa: E402


def copy_token(db, tenant_id: str, apply: bool) -> str:
    if meta_business_service.get_token(db, tenant_id):
        return "already_connected"
    row = db.query(Integration).filter_by(tenant_id=tenant_id, kind="instagram").first()
    token = ""
    if row and row.credentials_kms_blob:
        try:
            token = decrypt_credentials(row.credentials_kms_blob).get("access_token", "") or ""
        except Exception:
            token = ""
    if not token.startswith("EAA"):
        return "no_facebook_token"
    if not apply:
        return "would_copy"
    saved = meta_business_service.connect(db, tenant_id, token)
    append_audit(
        db,
        tenant_id=tenant_id,
        action="meta_business.connected",
        target_type="integration",
        target_id=meta_business_service.KIND,
        payload={
            "token_name": (saved.config or {}).get("token_name"),
            "actor": "system",
            "source": "copy_meta_token_to_business.py",
        },
    )
    return "copied"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant-slug", required=True)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter_by(slug=a.tenant_slug).one_or_none()
        if not tenant:
            print("ERROR: unknown tenant slug")
            return 2
        set_tenant_context(db, tenant.id)
        result = copy_token(db, tenant.id, a.apply)
        print(
            {
                "already_connected": "Meta Business is already connected; nothing to do.",
                "no_facebook_token": "The Instagram connection holds no Facebook (EAA) token; nothing to copy.",
                "would_copy": "DRY RUN: would copy the Facebook token from the Instagram connection (add --apply).",
                "copied": "Copied. Meta Business is connected.",
            }[result]
        )
        if result == "copied":
            db.commit()
            st = meta_business_service.status(db, tenant.id)
            print(f"  token belongs to: {st['token_name']}")
            for name, cap in (st["capabilities"] or {}).items():
                print(f"  {name}: {'ok' if cap['ok'] else 'missing ' + '; '.join(cap['missing'])}")
            print(f"  ad accounts: {[a_['id'] for a_ in st['ad_accounts']]}  page: {st['page']}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
