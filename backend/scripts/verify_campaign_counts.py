"""Read-only check: do each campaign's stored counters (accepted / delivered / read / failed) match its recipient rows?

    python -m scripts.verify_campaign_counts            # every tenant, every campaign
    python -m scripts.verify_campaign_counts <tenant_id>

Reads only. It prints one line per campaign that disagrees (stored vs recomputed) and a summary; it never writes. A campaign whose
counters are behind its rows is repaired by re-running the report (any status callback recalculates them) -- this script does not do it.

Run it against a copy or a read replica unless you have been told to run it against production.
"""
import sys

from app.api.v1.endpoints.messaging import WACampaign
from app.core.database import SessionLocal
from app.services import wa_campaign_delivery as delivery


def main(tenant_id: str | None = None) -> int:
    db = SessionLocal()
    bad = checked = 0
    try:
        q = db.query(WACampaign)
        if tenant_id:
            q = q.filter(WACampaign.tenant_id == tenant_id)
        for c in q.all():
            checked += 1
            counts = delivery.cumulative(delivery.status_counts(db, c.id))
            stored = {"sent": c.sent_count, "delivered": c.delivered_count, "read": c.read_count, "failed": c.failed_count}
            actual = {k: str(counts[k]) for k in stored}
            ordered = counts["sent"] >= counts["delivered"] >= counts["read"]
            if {k: str(v or "0") for k, v in stored.items()} != actual or not ordered:
                bad += 1
                print(f"{c.tenant_id} {c.id} {c.name!r}: stored={stored} recomputed={actual} ordered={ordered}")
        print(f"checked {checked} campaign(s); {bad} disagree")
        return 1 if bad else 0
    finally:
        db.rollback()
        db.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else None))
