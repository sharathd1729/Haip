"""The placeholder property is named for the business: "Unassigned (villa not chosen yet)" in a villa workspace.

Revision ID: 201
Revises: 200

Data only. The placeholder was created with the caravan wording in every workspace. Code finds it by the "Unassigned"
prefix (vehicle_pool.is_placeholder_name), so the rename changes nothing but the label. Idempotent.
"""

from alembic import op

revision = "201"
down_revision = "200"
branch_labels = None
depends_on = None

OLD = "Unassigned (vehicle not chosen yet)"
# unit word -> tenants.business_type values (ops_pack_catalog.unit_word_for)
UNITS = {"villa": ("villa", "villa_resort"), "farmhouse": ("farmhouse",)}


def _rename(source: str, target: str, types: tuple) -> None:
    quoted = ", ".join(f"'{t}'" for t in types)
    op.execute(
        f"UPDATE properties SET name = '{target}' WHERE name = '{source}' "
        f"AND tenant_id IN (SELECT id FROM tenants WHERE lower(business_type) IN ({quoted}))"
    )


def upgrade():
    for unit, types in UNITS.items():
        _rename(OLD, f"Unassigned ({unit} not chosen yet)", types)


def downgrade():
    for unit, types in UNITS.items():
        _rename(f"Unassigned ({unit} not chosen yet)", OLD, types)
