"""Leads360: split default-entry stage into Unqualified vs General Enquiry

Every new DM (WhatsApp/Instagram) was landing in "General Enquiry" regardless
of whether the guest had shared a phone number -- General Enquiry was the
single is_default_entry stage, flooding it with everything. This splits the
landing zone in two:

  - No phone signal (the common IG-DM case)  -> "Unqualified" (new stage,
    is_default_entry, category="invalid" -- doesn't count as a lead in
    dashboards/metrics)
  - Phone signal present                     -> "General Enquiry"
    (is_valid_lead_entry, category flips invalid->valid -- now counts as a
    real lead). Agents move it into Active/Unsuitable/etc. manually from
    there, same as before.

For every tenant: create "Unqualified" if missing, reassert canonical
flags/category/order on "General Enquiry" and "Active" (same
force-correct-on-every-run approach as migration 049, since a tenant may
already have a same-keyed stage from before this migration existed), then
remap any inquiry currently sitting in General Enquiry whose guest has no
"phone" identity signal onto the new Unqualified stage.

Revision ID: 062
Revises: 061
Create Date: 2026-08-05
"""
from alembic import op
import sqlalchemy as sa
import uuid

revision = "062"
down_revision = "061"
branch_labels = None
depends_on = None

_CANONICAL = [
    # key, label, color, order, category, is_default_entry, is_valid_lead_entry
    ("unqualified",      "Unqualified",      "#94a3b8", 0, "invalid", True,  False),
    ("general_enquiry",  "General Enquiry",  "#6b7280", 1, "valid",   False, True),
    ("active",           "Active",           "#6366f1", 3, "valid",   False, False),
]


def _tenant_ids(bind):
    return [r[0] for r in bind.execute(sa.text("SELECT id FROM tenants")).fetchall()]


def _stage_ids_by_key(bind, tenant_id):
    rows = bind.execute(
        sa.text("SELECT key, id FROM pipeline_stages WHERE tenant_id = :t"),
        {"t": tenant_id},
    ).fetchall()
    return {r[0]: r[1] for r in rows}


def upgrade():
    bind = op.get_bind()

    for tenant_id in _tenant_ids(bind):
        stage_ids_by_key = _stage_ids_by_key(bind, tenant_id)
        had_general_enquiry_before = "general_enquiry" in stage_ids_by_key

        for key, label, color, order, category, is_default_entry, is_valid_lead_entry in _CANONICAL:
            if key in stage_ids_by_key:
                bind.execute(
                    sa.text(
                        """
                        UPDATE pipeline_stages
                        SET category = :category, is_default_entry = :is_default_entry,
                            is_valid_lead_entry = :is_valid_lead_entry, "order" = :order,
                            updated_at = now()
                        WHERE id = :id
                        """
                    ),
                    {
                        "id": stage_ids_by_key[key], "category": category, "order": order,
                        "is_default_entry": is_default_entry,
                        "is_valid_lead_entry": is_valid_lead_entry,
                    },
                )
                continue
            new_id = str(uuid.uuid4())
            bind.execute(
                sa.text(
                    """
                    INSERT INTO pipeline_stages
                        (id, tenant_id, key, label, color, "order", category,
                         is_default_entry, is_valid_lead_entry, is_collab_entry,
                         is_closed_won, is_closed_lost, created_at, updated_at)
                    VALUES
                        (:id, :tenant_id, :key, :label, :color, :order, :category,
                         :is_default_entry, :is_valid_lead_entry, false,
                         false, false, now(), now())
                    """
                ),
                {
                    "id": new_id, "tenant_id": tenant_id, "key": key, "label": label,
                    "color": color, "order": order, "category": category,
                    "is_default_entry": is_default_entry,
                    "is_valid_lead_entry": is_valid_lead_entry,
                },
            )
            stage_ids_by_key[key] = new_id

        if not had_general_enquiry_before:
            continue  # nothing was ever misrouted here for this tenant

        # Remap: any inquiry currently sitting in General Enquiry whose guest
        # has no phone signal on file was misrouted under the old single
        # default-entry rule -- move it to Unqualified. An inquiry whose
        # guest DOES have a phone signal stays put; General Enquiry is now
        # the correct home for it.
        bind.execute(
            sa.text(
                """
                UPDATE inquiries
                SET stage_id = :unqualified_id, updated_at = now()
                WHERE tenant_id = :t
                  AND stage_id = :general_enquiry_id
                  AND guest_id NOT IN (
                      SELECT guest_id FROM guest_identities
                      WHERE tenant_id = :t AND identity_type = 'phone'
                  )
                """
            ),
            {
                "t": tenant_id,
                "unqualified_id": stage_ids_by_key["unqualified"],
                "general_enquiry_id": stage_ids_by_key["general_enquiry"],
            },
        )


def downgrade():
    """Best-effort inverse: fold Unqualified back into General Enquiry
    (can't distinguish which inquiries were "really" general-enquiry-typed
    vs. auto-created-without-phone after the fact), restore General
    Enquiry as the sole default-entry stage, and drop Unqualified."""
    bind = op.get_bind()

    for tenant_id in _tenant_ids(bind):
        stage_ids_by_key = _stage_ids_by_key(bind, tenant_id)
        unqualified_id = stage_ids_by_key.get("unqualified")
        general_enquiry_id = stage_ids_by_key.get("general_enquiry")

        if general_enquiry_id:
            bind.execute(
                sa.text(
                    """
                    UPDATE pipeline_stages
                    SET category = 'invalid', is_default_entry = true,
                        is_valid_lead_entry = false, "order" = 0, updated_at = now()
                    WHERE id = :id
                    """
                ),
                {"id": general_enquiry_id},
            )
        if "active" in stage_ids_by_key:
            bind.execute(
                sa.text(
                    """
                    UPDATE pipeline_stages
                    SET is_valid_lead_entry = true, "order" = 2, updated_at = now()
                    WHERE id = :id
                    """
                ),
                {"id": stage_ids_by_key["active"]},
            )

        if unqualified_id and general_enquiry_id:
            bind.execute(
                sa.text("UPDATE inquiries SET stage_id = :ge_id WHERE tenant_id = :t AND stage_id = :uq_id"),
                {"ge_id": general_enquiry_id, "t": tenant_id, "uq_id": unqualified_id},
            )
        if unqualified_id:
            bind.execute(
                sa.text("DELETE FROM pipeline_stages WHERE id = :id"),
                {"id": unqualified_id},
            )
