"""Local test mode (EXTERNAL_SERVICES=fake): production can never load it, and when on nothing but AI leaves the machine."""
import json

import httpx
import pytest

from app.core import fake_services
from app.core.config import Settings, settings


def test_production_refuses_fake_mode():
    with pytest.raises(ValueError, match="never allowed in production"):
        Settings(ENVIRONMENT="production", DATABASE_URL="postgresql://x/y", SECRET_KEY="k" * 40,
                 EXTERNAL_SERVICES="fake")


def test_default_is_real_and_unknown_value_rejected():
    assert Settings(DATABASE_URL="postgresql://x/y").EXTERNAL_SERVICES == "real"
    with pytest.raises(ValueError):
        Settings(DATABASE_URL="postgresql://x/y", EXTERNAL_SERVICES="maybe")


def test_install_refuses_production(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "EXTERNAL_SERVICES", "fake")
    assert fake_services.enabled() is False
    with pytest.raises(RuntimeError):
        fake_services.install()


def test_dev_routes_absent_when_not_faked(client):
    # The test app runs with the default (real) setting, like production: the outbox does not exist.
    assert settings.EXTERNAL_SERVICES == "real"
    assert client.get("/dev/outbox").status_code == 404
    assert client.get("/dev/media/x/y.jpg").status_code == 404


def test_hosts_that_pass_through():
    assert fake_services.passes_through("integrate.api.nvidia.com")
    assert fake_services.passes_through("generativelanguage.googleapis.com")
    assert fake_services.passes_through("127.0.0.1")
    for host in ("graph.facebook.com", "graph.instagram.com", "api.razorpay.com", "api.resend.com", "api.vobiz.ai",
                 "whatsapp-bridge", "fcm.googleapis.com"):
        assert not fake_services.passes_through(host)


@pytest.fixture
def faked(monkeypatch, tmp_path):
    """Install the patches for one test and undo them afterwards."""
    import boto3
    from requests.adapters import HTTPAdapter
    saved = (httpx.HTTPTransport.handle_request, httpx.AsyncHTTPTransport.handle_async_request, HTTPAdapter.send,
             boto3.client)
    monkeypatch.setattr(settings, "EXTERNAL_SERVICES", "fake")
    monkeypatch.setattr(settings, "LOCAL_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(fake_services, "_installed", False)
    real_calls = []
    # Anything that reaches the real network layer is recorded here instead of going out.
    httpx.HTTPTransport.handle_request = lambda self, req: real_calls.append(str(req.url)) or httpx.Response(200, json={"ok": 1})
    fake_services.install()
    yield real_calls
    (httpx.HTTPTransport.handle_request, httpx.AsyncHTTPTransport.handle_async_request, HTTPAdapter.send,
     boto3.client) = saved


def test_whatsapp_send_is_recorded_not_sent(faked):
    resp = httpx.post("https://graph.facebook.com/v20.0/1001/messages?access_token=SECRET",
                      json={"messaging_product": "whatsapp", "to": "919000000001", "type": "text",
                            "text": {"body": "Hello from the demo"}})
    assert resp.status_code == 200
    assert resp.json()["messages"][0]["id"].startswith("wamid.FAKE")
    assert faked == []  # nothing reached the network
    entry = fake_services.read_outbox()[0]
    assert (entry["service"], entry["to"], entry["text"]) == ("whatsapp", "919000000001", "Hello from the demo")
    assert "SECRET" not in entry["url"]


def test_ai_host_passes_through(faked):
    httpx.post("https://integrate.api.nvidia.com/v1/chat/completions", json={"model": "m"})
    assert faked == ["https://integrate.api.nvidia.com/v1/chat/completions"]
    assert fake_services.read_outbox() == []


def test_razorpay_link_and_requests_and_s3(faked):
    import boto3
    import requests
    link = httpx.post("https://api.razorpay.com/v1/payment_links", auth=("k", "s"),
                      json={"amount": 1250000, "description": "Deposit", "customer": {"contact": "+919000000002"}}).json()
    assert link["id"].startswith("plink_FAKE") and link["status"] == "created"
    assert requests.post("https://fcm.googleapis.com/fcm/send/abc", data=b"x").status_code == 201
    s3 = boto3.client("s3", endpoint_url="https://example.r2.cloudflarestorage.com")
    s3.put_object(Bucket="b", Key="t1/marketing/a.jpg", Body=b"jpeg")
    assert s3.get_object(Bucket="b", Key="t1/marketing/a.jpg")["Body"].read() == b"jpeg"
    assert s3.generate_presigned_url("get_object", Params={"Key": "t1/marketing/a.jpg"}).endswith("/dev/media/t1/marketing/a.jpg")
    with pytest.raises(ValueError):
        s3.put_object(Bucket="b", Key="../../escape.txt", Body=b"x")
    services = [e["service"] for e in fake_services.read_outbox()]
    assert services == ["web_push", "razorpay"]
    assert json.loads(fake_services.read_outbox()[1]["body"])["amount"] == 1250000
