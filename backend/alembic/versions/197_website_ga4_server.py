"""Website GA4 purchase from the server (Measurement Protocol).

sites.ga4_secret_enc            the owner's GA4 Measurement Protocol API secret, Fernet-encrypted, never returned
booking_holds.analytics_consent the visitor's cookie-banner choice at checkout (TRUE = accepted, NULL/FALSE = no)
booking_holds.ga_client_id      the GA4 client id from the visitor's _ga cookie at checkout (only with consent)
website_events.ga_client_id     the client id a GA4 row is sent with (browser's, else one HAIP generated)

All three tables already have tenant_id + forced RLS (158, 183). ADD COLUMN IF NOT EXISTS: idempotent (prod also runs
create_all, which never adds a column to an existing table).

Revision ID: 197
Revises: 196
"""

from alembic import op

revision = "197"
down_revision = "196"
branch_labels = None
depends_on = None


COLUMNS = (
    ("sites", "ga4_secret_enc", "TEXT"),
    ("booking_holds", "analytics_consent", "BOOLEAN"),
    ("booking_holds", "ga_client_id", "VARCHAR(60)"),
    ("website_events", "ga_client_id", "VARCHAR(60)"),
)


def upgrade():
    bind = op.get_bind()
    postgres = bind.dialect.name == "postgresql"
    if postgres:
        op.execute("SET LOCAL lock_timeout = '10s'")
    for table, column, kind in COLUMNS:
        if postgres:
            op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {kind}")
        elif column not in {r[1] for r in bind.exec_driver_sql(f"PRAGMA table_info({table})")}:
            op.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")


def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        for table, column, _kind in COLUMNS:
            op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {column}")
