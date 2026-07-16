"""Leads360: rework default pipeline taxonomy for existing tenants

Replaces the legacy 7-key stage set (new/responding/quoted/
site_visit_scheduled/site_visit_done/booked/closed) with the new
Valid/Invalid/Marketing taxonomy (general_enquiry, rnr, active,
unsuitable, lost, sold, collaboration_engagement) for every tenant that
still has the old set. Existing inquiries are remapped onto the
corresponding new stage before the old rows are dropped. Idempotent and
re-runnable: tenants already on the new taxonomy (e.g. seeded by
register() after this migration lands) are skipped.

Revision ID: 049
Revises: 048
Create Date: 2026-07-16
"""
from alembic import op
import sqlalchemy as sa
import uuid

revision = "049"
down_revision = "048"
branch_labels = None
depends_on = None

_NEW_TAXONOMY = [
    # key, label, color, order, category, is_default_entry, is_valid_lead_entry, is_collab_entry, is_closed_won, is_closed_lost
    ("general_enquiry",          "General Enquiry",           "#6b7280", 0, "invalid",   True,  False, False, False, False),
    ("rnr",                      "RNR",                       "#f59e0b", 1, "invalid",   False, False, False, False, False),
    ("active",                   "Active",                    "#6366f1", 2, "valid",     False, True,  False, False, False),
    ("unsuitable",               "Unsuitable",                "#8b5cf6", 3, "valid",     False, False, False, False, False),
    ("lost",                     "Lost",                      "#ef4444", 4, "valid",     False, False, False, False, True),
    ("sold",                     "Sold",                      "#22c55e", 5, "valid",     False, False, False, True,  False),
    ("collaboration_engagement", "Collaboration Engagement",  "#06b6d4", 6, "marketing", False, False, True,  False, False),
]

_OLD_TO_NEW_KEY = {
    "new": "general_enquiry",
    "responding": "active",
    "quoted": "active",
    "site_visit_scheduled": "active",
    "site_visit_done": "active",
    "site_visit": "active",  # deprecated alias, in case any tenant still has it
    "booked": "sold",
    "closed": "lost",
}

_OLD_KEYS = set(_OLD_TO_NEW_KEY.keys())
_NEW_KEYS = {row[0] for row in _NEW_TAXONOMY}


def _tenant_ids(bind):
    return [r[0] for r in bind.execute(sa.text("SELECT id FROM tenants")).fetchall()]


def _stage_keys(bind, tenant_id):
    rows = bind.execute(
        sa.text("SELECT key, id FROM pipeline_stages WHERE tenant_id = :t"),
        {"t": tenant_id},
    ).fetchall()
    return {r[0]: r[1] for r in rows}


def upgrade():
    bind = op.get_bind()

    for tenant_id in _tenant_ids(bind):
        stage_ids_by_key = _stage_keys(bind, tenant_id)
        has_old = bool(_OLD_KEYS & set(stage_ids_by_key.keys()))

        # 1. Create any missing new-taxonomy stages, and force-correct the
        # category/flags/color/order on any that already exist with a
        # canonical key -- a tenant may already have a stage keyed exactly
        # "active"/"general_enquiry"/etc. (e.g. hand-created via the
        # Pipeline Settings UI before this migration ever ran) with none of
        # the routing flags set. Treating "key present" as "correctly
        # configured" left those silently wrong (confirmed against Ratha's
        # production DB: `active` existed pre-migration but without
        # is_valid_lead_entry=true) -- always reassert the canonical shape
        # instead, on every run, not just on first creation.
        for key, label, color, order, category, is_default_entry, is_valid_lead_entry, is_collab_entry, is_closed_won, is_closed_lost in _NEW_TAXONOMY:
            if key in stage_ids_by_key:
                bind.execute(
                    sa.text(
                        """
                        UPDATE pipeline_stages
                        SET category = :category, is_default_entry = :is_default_entry,
                            is_valid_lead_entry = :is_valid_lead_entry, is_collab_entry = :is_collab_entry,
                            is_closed_won = :is_closed_won, is_closed_lost = :is_closed_lost,
                            "order" = :order, updated_at = now()
                        WHERE id = :id
                        """
                    ),
                    {
                        "id": stage_ids_by_key[key], "category": category, "order": order,
                        "is_default_entry": is_default_entry,
                        "is_valid_lead_entry": is_valid_lead_entry,
                        "is_collab_entry": is_collab_entry,
                        "is_closed_won": is_closed_won, "is_closed_lost": is_closed_lost,
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
                         :is_default_entry, :is_valid_lead_entry, :is_collab_entry,
                         :is_closed_won, :is_closed_lost, now(), now())
                    """
                ),
                {
                    "id": new_id, "tenant_id": tenant_id, "key": key, "label": label,
                    "color": color, "order": order, "category": category,
                    "is_default_entry": is_default_entry,
                    "is_valid_lead_entry": is_valid_lead_entry,
                    "is_collab_entry": is_collab_entry,
                    "is_closed_won": is_closed_won, "is_closed_lost": is_closed_lost,
                },
            )
            stage_ids_by_key[key] = new_id

        if not has_old:
            continue  # nothing further to remap/delete for this tenant

        # 2. Remap inquiries off any old stage onto the corresponding new one.
        for old_key, new_key in _OLD_TO_NEW_KEY.items():
            old_id = stage_ids_by_key.get(old_key)
            new_id = stage_ids_by_key.get(new_key)
            if not old_id or not new_id:
                continue
            bind.execute(
                sa.text("UPDATE inquiries SET stage_id = :new_id WHERE tenant_id = :t AND stage_id = :old_id"),
                {"new_id": new_id, "t": tenant_id, "old_id": old_id},
            )

        # 3. Drop the old stage rows now that nothing references them.
        old_ids_present = [stage_ids_by_key[k] for k in _OLD_KEYS if k in stage_ids_by_key]
        if old_ids_present:
            bind.execute(
                sa.text("DELETE FROM pipeline_stages WHERE id = ANY(:ids)"),
                {"ids": old_ids_present},
            )


def downgrade():
    # Best-effort inverse: recreate the legacy 7-key set and reverse-map
    # inquiries back onto them. Not perfectly reversible if new stages were
    # manually edited (renamed/merged) between upgrade and downgrade -- any
    # inquiry left on a still-existing new stage with no old-stage mapping
    # (e.g. "unsuitable", "rnr", "collaboration_engagement" -- stages that
    # didn't exist pre-upgrade) is left as-is rather than guessed at.
    bind = op.get_bind()

    _LEGACY = [
        ("new", "New", "#6366f1", 0),
        ("responding", "Responding", "#f59e0b", 1),
        ("quoted", "Quoted", "#8b5cf6", 2),
        ("site_visit_scheduled", "Site Visit", "#06b6d4", 3),
        ("site_visit_done", "Visit Done", "#10b981", 4),
        ("booked", "Booked", "#22c55e", 5),
        ("closed", "Closed", "#6b7280", 6),
    ]
    _NEW_TO_OLD_KEY = {"general_enquiry": "new", "active": "responding", "sold": "booked", "lost": "closed"}

    for tenant_id in _tenant_ids(bind):
        stage_ids_by_key = _stage_keys(bind, tenant_id)
        if not (_NEW_KEYS & set(stage_ids_by_key.keys())):
            continue  # not on the new taxonomy -- nothing to revert

        for key, label, color, order in _LEGACY:
            if key in stage_ids_by_key:
                continue
            new_id = str(uuid.uuid4())
            bind.execute(
                sa.text(
                    """
                    INSERT INTO pipeline_stages
                        (id, tenant_id, key, label, color, "order",
                         is_default_entry, is_valid_lead_entry, is_collab_entry,
                         is_closed_won, is_closed_lost, created_at, updated_at)
                    VALUES
                        (:id, :tenant_id, :key, :label, :color, :order,
                         :is_default_entry, false, false,
                         :is_closed_won, :is_closed_lost, now(), now())
                    """
                ),
                {
                    "id": new_id, "tenant_id": tenant_id, "key": key, "label": label,
                    "color": color, "order": order,
                    "is_default_entry": key == "new",
                    "is_closed_won": key == "booked", "is_closed_lost": key == "closed",
                },
            )
            stage_ids_by_key[key] = new_id

        for new_key, old_key in _NEW_TO_OLD_KEY.items():
            new_id = stage_ids_by_key.get(new_key)
            old_id = stage_ids_by_key.get(old_key)
            if not new_id or not old_id:
                continue
            bind.execute(
                sa.text("UPDATE inquiries SET stage_id = :old_id WHERE tenant_id = :t AND stage_id = :new_id"),
                {"old_id": old_id, "t": tenant_id, "new_id": new_id},
            )

        new_ids_present = [stage_ids_by_key[k] for k in _NEW_KEYS if k in stage_ids_by_key]
        if new_ids_present:
            bind.execute(
                sa.text("DELETE FROM pipeline_stages WHERE id = ANY(:ids)"),
                {"ids": new_ids_present},
            )
