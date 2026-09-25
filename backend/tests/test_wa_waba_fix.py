"""Template submission failing with "Object with ID ... does not exist".

Real incident (Ratha, Sep 2026): the saved WhatsApp Business Account ID was
wrong for the token. Meta answered code 100 / subcode 33 and the template was
labelled "Rejected" although Meta never reviewed it.
"""
import os
import uuid
from unittest.mock import patch

from cryptography.fernet import Fernet

os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())

import pytest

from app.core.encryption import decrypt_credentials, encrypt_credentials
from app.models.integration import Integration
from app.services import wa_health_service as svc
from app.services import wa_template_service as wts

NOT_FOUND = {"code": 100, "error_subcode": 33, "message": "Unsupported post request. Object with ID '1' does not exist"}


def test_object_not_found_is_a_connection_problem():
    reason, connection = wts.explain_meta_error(NOT_FOUND, "1")
    assert connection is True
    assert "WhatsApp Business Account ID" in reason and "(1)" in reason
    assert "Unsupported post request" not in reason


@pytest.mark.parametrize("code", [190, 102, 10, 200])
def test_token_errors_are_connection_problems(code):
    assert wts.explain_meta_error({"code": code, "message": "x"})[1] is True


def test_content_errors_stay_rejections():
    reason, connection = wts.explain_meta_error({"code": 100, "error_subcode": 2388042, "error_user_msg": "Body too long"})
    assert connection is False
    assert reason == "Body too long"


def test_token_access_reads_scopes_and_accounts():
    body = {"data": {"scopes": ["whatsapp_business_management"], "granular_scopes": [
        {"scope": "whatsapp_business_management", "target_ids": [111, 222]}]}}
    with patch.object(svc, "_meta_get", return_value=(body, None)):
        assert svc.token_access("t") == (["whatsapp_business_management"], ["111", "222"], None)


def test_token_access_passes_meta_error_through():
    with patch.object(svc, "_meta_get", return_value=(None, "bad token")):
        assert svc.token_access("t") == ([], [], "bad token")


def _tid(tu):
    t = tu["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


def _connect(db, tid):
    row = Integration(
        id=str(uuid.uuid4()), tenant_id=tid, kind="whatsapp_meta", status="active",
        config={"phone_number_id": "pn1", "waba_id": "old"},
        credentials_kms_blob=encrypt_credentials({"access_token": "tok", "app_secret": "s", "phone_number_id": "pn1", "waba_id": "old"}),
    )
    db.add(row)
    db.commit()
    return row


def test_apply_waba_saves_an_id_meta_confirms(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    row = _connect(db, tid)
    with patch.object(svc, "candidate_wabas", return_value=([], ["999"], None)):
        assert svc.apply_waba(db, tid, "999") == "999"
    db.refresh(row)
    assert row.config["waba_id"] == "999"
    creds = decrypt_credentials(row.credentials_kms_blob)
    assert creds["waba_id"] == "999" and creds["app_secret"] == "s"       # nothing else disturbed


def test_apply_waba_refuses_an_id_meta_does_not_confirm(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    row = _connect(db, tid)
    with patch.object(svc, "candidate_wabas", return_value=([], ["999"], None)):
        with pytest.raises(ValueError):
            svc.apply_waba(db, tid, "555")
    db.refresh(row)
    assert row.config["waba_id"] == "old"


def test_apply_waba_is_tenant_scoped(db, tenant_and_user):
    _connect(db, "some-other-tenant")
    with patch.object(svc, "candidate_wabas", return_value=([], ["999"], None)):
        with pytest.raises(ValueError):
            svc.apply_waba(db, _tid(tenant_and_user), "999")
