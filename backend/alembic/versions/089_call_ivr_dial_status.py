"""Real Dial-leg answer/no-answer signal from the IVR provider.

Confirmed live: call_status_service.is_missed_call() falls back to
duration_seconds == 0 whenever no disposition has run yet (the common
case). Vobiz's session recording starts before the greeting even plays, so
any call with a greeting configured gets nonzero duration from the
greeting/voicemail audio alone, regardless of whether an agent ever
answered -- misclassifying real missed calls as answered. Vobiz's own
Dial callbackUrl supplies a real DialStatus (completed/busy/failed/
cancel/timeout/no-answer) that settles this definitively instead of
guessing from duration. Provider-agnostic column name (not
vobiz_dial_status) so a future CallerDesk/Acefone equivalent signal could
reuse it.

Revision ID: 089
Revises: 088
Create Date: 2026-08-24
"""
from alembic import op
import sqlalchemy as sa

revision = "089"
down_revision = "088"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("calls", sa.Column("ivr_dial_status", sa.String(20), nullable=True))


def downgrade():
    op.drop_column("calls", "ivr_dial_status")
