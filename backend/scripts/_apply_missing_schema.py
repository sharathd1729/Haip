"""
Apply schema changes from migrations 022 and 023 that are missing from the DB.
Run once to bring the DB in sync with the models.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from app.core.database import engine
from sqlalchemy import text

steps = [
    # ── Migration 022 missing columns ───────────────────────────────────────
    ("ADD tenants.llm_provider_override",
     "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS llm_provider_override VARCHAR(50)"),

    ("ADD transcripts.script_type",
     "ALTER TABLE transcripts ADD COLUMN IF NOT EXISTS script_type VARCHAR(20)"),

    ("DROP guests phone unique constraint",
     "ALTER TABLE guests DROP CONSTRAINT IF EXISTS uq_guests_tenant_phone"),

    # ── Migration 023: InquirySource new values ──────────────────────────────
    ("ADD inquirysource inbound_call",
     "ALTER TYPE inquirysource ADD VALUE IF NOT EXISTS 'inbound_call'"),
    ("ADD inquirysource outbound_call",
     "ALTER TYPE inquirysource ADD VALUE IF NOT EXISTS 'outbound_call'"),
    ("ADD inquirysource ota_mmt",
     "ALTER TYPE inquirysource ADD VALUE IF NOT EXISTS 'ota_mmt'"),
    ("ADD inquirysource ota_goibibo",
     "ALTER TYPE inquirysource ADD VALUE IF NOT EXISTS 'ota_goibibo'"),
    ("ADD inquirysource channel_manager",
     "ALTER TYPE inquirysource ADD VALUE IF NOT EXISTS 'channel_manager'"),
    ("ADD inquirysource web_chat",
     "ALTER TYPE inquirysource ADD VALUE IF NOT EXISTS 'web_chat'"),

    # ── Migration 023: InquiryStage new values ────────────────────────────────
    ("ADD inquirystage site_visit_scheduled",
     "ALTER TYPE inquirystage ADD VALUE IF NOT EXISTS 'site_visit_scheduled'"),
    ("ADD inquirystage site_visit_done",
     "ALTER TYPE inquirystage ADD VALUE IF NOT EXISTS 'site_visit_done'"),

    # ── Migration 023: Indexes ────────────────────────────────────────────────
    ("CREATE INDEX ix_inquiries_tenant_id_stage",
     "CREATE INDEX IF NOT EXISTS ix_inquiries_tenant_id_stage ON inquiries(tenant_id, stage)"),
    ("CREATE INDEX ix_inquiries_tenant_id_source",
     "CREATE INDEX IF NOT EXISTS ix_inquiries_tenant_id_source ON inquiries(tenant_id, source)"),
    ("CREATE INDEX ix_inquiries_tenant_id_assigned_to",
     "CREATE INDEX IF NOT EXISTS ix_inquiries_tenant_id_assigned_to ON inquiries(tenant_id, assigned_to)"),
    ("CREATE INDEX ix_inquiries_tenant_id_updated_at",
     "CREATE INDEX IF NOT EXISTS ix_inquiries_tenant_id_updated_at ON inquiries(tenant_id, updated_at)"),
    ("CREATE INDEX ix_guest_identities_tenant_id_guest_id",
     "CREATE INDEX IF NOT EXISTS ix_guest_identities_tenant_id_guest_id ON guest_identities(tenant_id, guest_id)"),
]

# ALTER TYPE ADD VALUE cannot run inside a transaction on PostgreSQL
# Connect in autocommit mode for those statements
raw_conn = engine.raw_connection()
raw_conn.set_isolation_level(0)  # AUTOCOMMIT
cursor = raw_conn.cursor()

for label, sql in steps:
    try:
        cursor.execute(sql)
        print(f"OK  {label}")
    except Exception as e:
        print(f"ERR {label}: {e}")

cursor.close()
raw_conn.close()

# Update alembic version to 023
with engine.connect() as conn:
    conn.execute(text("UPDATE alembic_version SET version_num = '023'"))
    conn.commit()
    row = conn.execute(text("SELECT version_num FROM alembic_version")).fetchone()
    print(f"\nAlembic version updated to: {row[0]}")

print("\nDone.")
