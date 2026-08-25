"""Service-level test for media_storage.upload_user_avatar
(Round 2 avatar-photos plan) -- mirrors upload_ivr_greeting's own fixed-key,
overwrite-on-reupload convention."""
from unittest.mock import MagicMock, patch

from app.services import media_storage


class TestUploadUserAvatar:
    def test_writes_fixed_key_per_tenant_and_user(self):
        mock_s3 = MagicMock()
        with patch.object(media_storage, "_s3_client", return_value=mock_s3):
            key = media_storage.upload_user_avatar(
                "tenant-1", "user-1", b"fake-jpeg-bytes", "image/jpeg", "jpg",
            )

        assert key == "tenant-1/users/user-1/avatar.jpg"
        mock_s3.put_object.assert_called_once()
        kwargs = mock_s3.put_object.call_args.kwargs
        assert kwargs["Key"] == "tenant-1/users/user-1/avatar.jpg"
        assert kwargs["Body"] == b"fake-jpeg-bytes"
        assert kwargs["ContentType"] == "image/jpeg"

    def test_reupload_with_same_extension_overwrites_same_key(self):
        mock_s3 = MagicMock()
        with patch.object(media_storage, "_s3_client", return_value=mock_s3):
            key1 = media_storage.upload_user_avatar("tenant-1", "user-1", b"v1", "image/jpeg", "jpg")
            key2 = media_storage.upload_user_avatar("tenant-1", "user-1", b"v2", "image/jpeg", "jpg")

        # Same tenant/user/extension -> identical S3 key both times, so a
        # re-upload overwrites rather than accumulating orphaned files --
        # matching upload_ivr_greeting's "one file per identity" contract.
        assert key1 == key2 == "tenant-1/users/user-1/avatar.jpg"
