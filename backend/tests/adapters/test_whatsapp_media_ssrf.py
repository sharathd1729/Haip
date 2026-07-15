"""WhatsApp module Phase 1, T1.2 — SSRF allowlist on inbound media downloads."""
import pytest
from app.adapters.whatsapp.meta_cloud import validate_whatsapp_media_url


@pytest.mark.parametrize("url", [
    "https://lookaside.fbsbx.com/whatsapp_business/attachments/?mid=123",
    "https://scontent-bom2-1.fbcdn.net/v/some/path.jpg",
    "https://cdninstagram.com/foo",
])
def test_allowed_meta_hosts_pass(url):
    assert validate_whatsapp_media_url(url) is True


@pytest.mark.parametrize("url", [
    "https://evil.com/steal-metadata",
    "http://lookaside.fbsbx.com/whatsapp_business/attachments/",  # http, not https
    "https://lookaside.fbsbx.com.evil.com/attachments/",           # suffix-spoofing attempt
    "https://169.254.169.254/latest/meta-data/",                   # cloud metadata SSRF target
    "",
    "not-a-url",
])
def test_malicious_or_non_meta_hosts_rejected(url):
    assert validate_whatsapp_media_url(url) is False
