"""Tests for the 2026-08-05 pipeline-stage fix: every DM (with or without a
phone number) used to land in "General Enquiry" -- the single is_default_entry
stage -- flooding it with unqualified leads. Now: no phone -> "Unqualified"
(is_default_entry, invalid), phone present -> "General Enquiry"
(is_valid_lead_entry, valid). See migration 062 for the existing-tenant
backfill (not exercised here -- tests run on SQLite, migrations don't)."""
import uuid

from app.models.pipeline_stage import PipelineStage
from app.services.pipeline_stage_service import seed_default_pipeline_stages
from app.services.lead_auto_create import resolve_entry_stage_id


def _tenant_id(tenant_and_user):
    t = tenant_and_user["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


class TestSeedDefaultTaxonomy:
    def test_unqualified_is_the_default_entry_stage(self, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        seed_default_pipeline_stages(db, tenant_id)

        unqualified = db.query(PipelineStage).filter_by(tenant_id=tenant_id, key="unqualified").first()
        general_enquiry = db.query(PipelineStage).filter_by(tenant_id=tenant_id, key="general_enquiry").first()
        active = db.query(PipelineStage).filter_by(tenant_id=tenant_id, key="active").first()

        assert unqualified is not None
        assert unqualified.is_default_entry is True
        assert unqualified.category == "invalid"

        assert general_enquiry is not None
        assert general_enquiry.is_default_entry is False
        assert general_enquiry.is_valid_lead_entry is True
        assert general_enquiry.category == "valid"

        assert active is not None
        assert active.is_valid_lead_entry is False  # no longer an auto-landing target

    def test_idempotent_on_second_call(self, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        seed_default_pipeline_stages(db, tenant_id)
        seed_default_pipeline_stages(db, tenant_id)

        stages = db.query(PipelineStage).filter_by(tenant_id=tenant_id).all()
        assert len(stages) == 8  # 7 original + unqualified, no duplicates


class TestResolveEntryStageRouting:
    def test_no_phone_routes_to_unqualified(self, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        seed_default_pipeline_stages(db, tenant_id)
        unqualified = db.query(PipelineStage).filter_by(tenant_id=tenant_id, key="unqualified").first()

        stage_id = resolve_entry_stage_id(db, tenant_id, is_collab=False, has_phone=False)
        assert stage_id == unqualified.id

    def test_phone_present_routes_to_general_enquiry(self, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        seed_default_pipeline_stages(db, tenant_id)
        general_enquiry = db.query(PipelineStage).filter_by(tenant_id=tenant_id, key="general_enquiry").first()

        stage_id = resolve_entry_stage_id(db, tenant_id, is_collab=False, has_phone=True)
        assert stage_id == general_enquiry.id

    def test_collab_wins_over_phone(self, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        seed_default_pipeline_stages(db, tenant_id)
        collab = db.query(PipelineStage).filter_by(tenant_id=tenant_id, key="collaboration_engagement").first()

        stage_id = resolve_entry_stage_id(db, tenant_id, is_collab=True, has_phone=True)
        assert stage_id == collab.id
