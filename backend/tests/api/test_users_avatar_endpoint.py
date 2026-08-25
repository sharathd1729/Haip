"""Tests for POST /users/me/avatar -- staff avatar photo upload
(Round 2 avatar-photos plan)."""
import io
import uuid
from unittest.mock import patch

import pytest

from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.core.security import create_access_token, get_password_hash


def _make_tenant(db, name="T"):
    t = Tenant(id=str(uuid.uuid4()), name=name, slug=f"slug-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t); db.flush(); return t


def _make_user(db, tenant_id, role=UserRole.CONCIERGE, name="Agent"):
    u = User(
        id=str(uuid.uuid4()), tenant_id=tenant_id, name=name,
        email=f"{uuid.uuid4().hex[:8]}@test.com",
        hashed_password=get_password_hash("pw"), role=role, is_active=True,
    )
    db.add(u); db.flush(); return u


def _token(user):
    return create_access_token({"sub": user.id, "tenant_id": user.tenant_id, "role": user.role.value})


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


class TestUploadAvatar:
    def test_happy_path_sets_key_and_returns_presigned_url(self, client, db):
        tenant = _make_tenant(db)
        user = _make_user(db, tenant.id)
        db.commit()

        with patch(
            "app.services.media_storage.upload_user_avatar",
            return_value=f"{tenant.id}/users/{user.id}/avatar.jpg",
        ) as mock_upload, patch(
            "app.services.media_storage.get_presigned_media_url",
            return_value="https://example-bucket.s3.amazonaws.com/signed-avatar-url",
        ):
            resp = client.post(
                "/api/v1/users/me/avatar",
                headers=_auth(_token(user)),
                files={"file": ("photo.jpg", io.BytesIO(b"fake-jpeg-bytes"), "image/jpeg")},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["avatar_url"] == "https://example-bucket.s3.amazonaws.com/signed-avatar-url"
        mock_upload.assert_called_once()
        db.refresh(user)
        assert user.avatar_s3_key == f"{tenant.id}/users/{user.id}/avatar.jpg"

    def test_rejects_unsupported_content_type(self, client, db):
        tenant = _make_tenant(db)
        user = _make_user(db, tenant.id)
        db.commit()

        resp = client.post(
            "/api/v1/users/me/avatar",
            headers=_auth(_token(user)),
            files={"file": ("notes.txt", io.BytesIO(b"not an image"), "text/plain")},
        )
        assert resp.status_code == 400

    def test_rejects_oversized_file(self, client, db):
        tenant = _make_tenant(db)
        user = _make_user(db, tenant.id)
        db.commit()

        oversized = b"0" * (6 * 1024 * 1024)  # over the 5MB cap
        resp = client.post(
            "/api/v1/users/me/avatar",
            headers=_auth(_token(user)),
            files={"file": ("photo.jpg", io.BytesIO(oversized), "image/jpeg")},
        )
        assert resp.status_code == 400
