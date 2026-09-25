"""CRM template list mirrors the WhatsApp Business Account.

Real case (Ratha, Sep 2026): a template created in WhatsApp Manager never showed
up here, and one deleted there stayed here.
"""
import os
import uuid
from unittest.mock import patch

from cryptography.fernet import Fernet

os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())

import pytest

from app.api.v1.endpoints.messaging import TemplateCategory, TemplateStatus, WACampaign, WATemplate
from app.services import wa_template_sync as sync


def _tid(tu):
    t = tu["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


def _local(db, tid, name, meta_id=None, status=TemplateStatus.APPROVED, language="en"):
    row = WATemplate(id=str(uuid.uuid4()), tenant_id=tid, name=name, language=language, status=status,
                     components=[{"type": "BODY", "text": "old"}], meta_template_id=meta_id)
    db.add(row)
    db.commit()
    return row.id


def _meta(id_, name, status="APPROVED", **kw):
    return {"id": id_, "name": name, "language": "en", "status": status, "category": "MARKETING",
            "components": [{"type": "BODY", "text": "from meta"}], **kw}


def _rows(db, tid):
    db.expire_all()
    return {t.name: t for t in db.query(WATemplate).filter_by(tenant_id=tid).all()}


def test_template_created_on_meta_appears(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    out = sync.apply(db, tid, [_meta("m1", "made_on_meta", "PENDING")])
    row = _rows(db, tid)["made_on_meta"]
    assert out["added"] == 1
    assert row.status == TemplateStatus.PENDING and row.meta_template_id == "m1"
    assert row.components[0]["text"] == "from meta" and row.category == TemplateCategory.MARKETING


def test_second_sync_adds_nothing(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    sync.apply(db, tid, [_meta("m1", "made_on_meta")])
    out = sync.apply(db, tid, [_meta("m1", "made_on_meta")])
    assert (out["added"], out["updated"], out["removed"]) == (0, 0, 0)
    assert len(_rows(db, tid)) == 1


def test_template_deleted_on_meta_disappears(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _local(db, tid, "gone", meta_id="m9")
    _local(db, tid, "kept", meta_id="m1")
    out = sync.apply(db, tid, [_meta("m1", "kept")])
    assert out["removed"] == 1
    assert set(_rows(db, tid)) == {"kept"}


def test_local_drafts_and_failed_submissions_are_never_removed(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _local(db, tid, "my_draft", status=TemplateStatus.DRAFT)
    _local(db, tid, "never_sent", status=TemplateStatus.SUBMISSION_FAILED)
    sync.apply(db, tid, [])
    assert set(_rows(db, tid)) == {"my_draft", "never_sent"}


def test_deleted_template_used_by_a_campaign_is_kept_but_unusable(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    tmpl_id = _local(db, tid, "old_promo", meta_id="m9")
    db.add(WACampaign(id=str(uuid.uuid4()), tenant_id=tid, name="Aug blast", template_id=tmpl_id))
    db.commit()
    out = sync.apply(db, tid, [])
    row = _rows(db, tid)["old_promo"]
    assert out["removed"] == 0
    assert row.status == TemplateStatus.REJECTED and "Deleted on Meta" in row.rejection_reason


def test_status_and_rejection_reason_follow_meta(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _local(db, tid, "promo", meta_id="m1", status=TemplateStatus.PENDING)
    sync.apply(db, tid, [_meta("m1", "promo", "REJECTED", rejected_reason="INVALID_FORMAT")])
    row = _rows(db, tid)["promo"]
    assert row.status == TemplateStatus.REJECTED and row.rejection_reason == "INVALID_FORMAT"
    sync.apply(db, tid, [_meta("m1", "promo", "APPROVED")])
    row = _rows(db, tid)["promo"]
    assert row.status == TemplateStatus.APPROVED and row.rejection_reason is None


def test_unsent_local_template_is_linked_to_its_meta_twin_by_name(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _local(db, tid, "welcome", meta_id=None, status=TemplateStatus.PENDING)
    out = sync.apply(db, tid, [_meta("m5", "welcome")])
    assert out["added"] == 0
    row = _rows(db, tid)["welcome"]
    assert row.meta_template_id == "m5" and row.status == TemplateStatus.APPROVED


def test_other_tenants_templates_untouched(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    other = _local(db, "other-tenant", "theirs", meta_id="zz")
    sync.apply(db, tid, [])
    assert db.query(WATemplate).filter_by(id=other).first() is not None


def test_meta_failure_raises_and_changes_nothing(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _local(db, tid, "safe", meta_id="m1")

    class Resp:
        def json(self):
            return {"error": {"code": 190, "message": "expired"}}

    with patch("httpx.get", return_value=Resp()):
        with pytest.raises(sync.SyncError):
            sync.fetch_meta_templates("w", "t")
    assert set(_rows(db, tid)) == {"safe"}


def test_pagination_is_followed():
    pages = [
        {"data": [_meta("1", "a")], "paging": {"next": "https://graph.facebook.com/next"}},
        {"data": [_meta("2", "b")]},
    ]

    class Resp:
        def __init__(self, d):
            self.d = d

        def json(self):
            return self.d

    with patch("httpx.get", side_effect=[Resp(p) for p in pages]):
        assert [t["id"] for t in sync.fetch_meta_templates("w", "t")] == ["1", "2"]


def test_endpoint_requires_a_connection(client, db, tenant_and_user):
    headers = tenant_and_user["headers"] if isinstance(tenant_and_user, dict) and "headers" in tenant_and_user else None
    if headers is None:
        pytest.skip("fixture has no auth headers")
    r = client.post("/api/v1/messaging/templates/sync", headers=headers)
    assert r.status_code == 400
