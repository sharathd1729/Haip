"""
Tests for sync_tenant_templates -- WhatsApp template approval status sync.

Real bug: access_token was read from Integration.config, which never held
it (access_token only ever lives in the encrypted credentials_kms_blob --
same class of bug already fixed once in send_whatsapp.py/
automation_engine.py/run_campaign.py, just never propagated here). Every
run silently no-op'd, so a template submitted to Meta and genuinely
approved there stayed PENDING in HAIP forever, invisible to the "approved
templates only" filter the Inbox's template picker applies.
"""
import uuid
from unittest.mock import patch

from sqlalchemy import text

from app.api.v1.endpoints.messaging import WATemplate, TemplateStatus
from app.models.integration import Integration
from app.core.encryption import encrypt_credentials
from app.workers.tasks.sync_wa_templates import sync_tenant_templates


def _status_and_reason(db, tmpl_id: str) -> tuple[str, "str | None"]:
    """sync_tenant_templates closes its own SessionLocal() in a finally
    block -- since SessionLocal is patched to the shared test `db`, that
    close() (after committing, which expires all attributes) detaches
    every identity-mapped instance. Raw SQL keyed on an id string captured
    *before* the task ran avoids ever touching a detached ORM object."""
    row = db.execute(
        text("SELECT status, rejection_reason FROM wa_templates WHERE id = :id"),
        {"id": tmpl_id},
    ).first()
    return row[0], row[1]


def _tenant_id(tenant_and_user):
    t = tenant_and_user["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


def _make_integration(db, tenant_id, waba_id="waba123", access_token="real-token"):
    integ = Integration(
        id=str(uuid.uuid4()), tenant_id=tenant_id, kind="whatsapp_meta", status="active",
        config={"waba_id": waba_id},
        credentials_kms_blob=encrypt_credentials({"access_token": access_token}),
    )
    db.add(integ); db.commit()
    return integ


def _make_pending_template(db, tenant_id, name="booking_confirmation"):
    tmpl = WATemplate(
        id=str(uuid.uuid4()), tenant_id=tenant_id, name=name,
        status=TemplateStatus.PENDING, components=[{"type": "BODY", "text": "Hi"}],
        meta_template_id="meta-123",
    )
    db.add(tmpl); db.commit()
    return tmpl


class _FakeMetaResponse:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return {"data": self._data}


class TestSyncTenantTemplates:
    def test_reads_access_token_from_encrypted_blob_not_config(self, db, tenant_and_user):
        """The actual fix: credentials only exist in credentials_kms_blob,
        never in Integration.config -- confirmed by never populating
        config with an access_token here at all."""
        tenant_id = _tenant_id(tenant_and_user)
        _make_integration(db, tenant_id)
        tmpl = _make_pending_template(db, tenant_id, name="booking_confirmation")
        # Captured before the task runs: it commits (expiring all attrs,
        # SQLAlchemy default) then closes its session (detaching them), so
        # `tmpl.id` itself becomes unreadable afterward.
        tmpl_id = tmpl.id

        with patch("app.workers.tasks.sync_wa_templates.SessionLocal", return_value=db), \
             patch("httpx.get", return_value=_FakeMetaResponse(
                 [{"name": "booking_confirmation", "status": "APPROVED"}]
             )) as mock_get:
            sync_tenant_templates.run(tenant_id=tenant_id)

        assert mock_get.called  # actually reached Meta this time
        status, _ = _status_and_reason(db, tmpl_id)
        assert status == TemplateStatus.APPROVED.name

    def test_marks_rejected_with_reason(self, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        _make_integration(db, tenant_id)
        tmpl = _make_pending_template(db, tenant_id, name="promo_blast")
        tmpl_id = tmpl.id

        with patch("app.workers.tasks.sync_wa_templates.SessionLocal", return_value=db), \
             patch("httpx.get", return_value=_FakeMetaResponse(
                 [{"name": "promo_blast", "status": "REJECTED", "rejected_reason": "Tag content policy"}]
             )):
            sync_tenant_templates.run(tenant_id=tenant_id)

        status, reason = _status_and_reason(db, tmpl_id)
        assert status == TemplateStatus.REJECTED.name
        assert reason == "Tag content policy"

    def test_no_pending_templates_never_calls_meta(self, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        _make_integration(db, tenant_id)

        with patch("app.workers.tasks.sync_wa_templates.SessionLocal", return_value=db), \
             patch("httpx.get") as mock_get:
            sync_tenant_templates.run(tenant_id=tenant_id)

        assert not mock_get.called

    def test_missing_credentials_blob_never_calls_meta(self, db, tenant_and_user):
        """No credentials_kms_blob at all (never connected properly) --
        must still no-op safely, not raise, and must not call Meta."""
        tenant_id = _tenant_id(tenant_and_user)
        integ = Integration(
            id=str(uuid.uuid4()), tenant_id=tenant_id, kind="whatsapp_meta", status="active",
            config={"waba_id": "waba123"},
        )
        db.add(integ); db.commit()
        _make_pending_template(db, tenant_id)

        with patch("app.workers.tasks.sync_wa_templates.SessionLocal", return_value=db), \
             patch("httpx.get") as mock_get:
            sync_tenant_templates.run(tenant_id=tenant_id)

        assert not mock_get.called

    def test_template_not_known_to_meta_yet_is_left_pending(self, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        _make_integration(db, tenant_id)
        tmpl = _make_pending_template(db, tenant_id, name="not_submitted_yet")
        tmpl_id = tmpl.id

        with patch("app.workers.tasks.sync_wa_templates.SessionLocal", return_value=db), \
             patch("httpx.get", return_value=_FakeMetaResponse([])):
            sync_tenant_templates.run(tenant_id=tenant_id)

        status, _ = _status_and_reason(db, tmpl_id)
        assert status == TemplateStatus.PENDING.name
