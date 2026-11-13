"""Android in-app update: endpoints/app_releases.py + scripts/publish_android_release.py."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.core.config import settings

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "publish_android_release.py"


@pytest.fixture()
def downloads(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "APP_DOWNLOADS_DIR", str(tmp_path))
    return tmp_path


def _publish(folder, *args):
    return subprocess.run([sys.executable, str(SCRIPT), "--dir", str(folder), *args], capture_output=True, text=True)


def test_nothing_published_says_so(client, downloads):
    assert client.get("/api/v1/app/android/version?flavor=yaad").json() == {"available": False}
    assert client.get("/api/v1/app/android/download/yaad").status_code == 404


def test_published_version_is_offered_and_downloads(client, downloads, tmp_path):
    apk = tmp_path / "yaad-0.1.9-release.apk"
    apk.write_bytes(b"PK\x03\x04" + b"\x00" * 64)
    r = _publish(downloads, "--flavor", "yaad", "--apk", str(apk), "--version-code", "9", "--notes", "Ask Yaad")
    assert r.returncode == 0, r.stdout + r.stderr
    v = client.get("/api/v1/app/android/version?flavor=yaad").json()
    assert v["available"] and v["version_code"] == 9 and v["version_name"] == "0.1.9" and v["notes"] == "Ask Yaad"
    assert v["url"] == "/api/v1/app/android/download/yaad" and len(v["sha256"]) == 64
    d = client.get(v["url"])
    assert d.status_code == 200 and d.content.startswith(b"PK")
    assert d.headers["content-type"] == "application/vnd.android.package-archive"
    assert client.get("/api/v1/app/android/version?flavor=calls").json() == {"available": False}  # the other app


def test_publish_refuses_an_older_or_non_apk_file(downloads, tmp_path):
    apk = tmp_path / "a.apk"
    apk.write_bytes(b"PK\x03\x04")
    assert _publish(downloads, "--flavor", "calls", "--apk", str(apk), "--version-code", "5").returncode == 0
    assert _publish(downloads, "--flavor", "calls", "--apk", str(apk), "--version-code", "5").returncode == 1
    junk = tmp_path / "x.apk"
    junk.write_bytes(b"not an apk")
    assert _publish(downloads, "--flavor", "calls", "--apk", str(junk), "--version-code", "6").returncode == 1
    assert json.loads((downloads / "calls.json").read_text())["version_code"] == 5


def test_only_known_apps(client, downloads):
    assert client.get("/api/v1/app/android/version?flavor=../etc").status_code == 422
    assert client.get("/api/v1/app/android/download/..%2Fsecret").status_code in (404, 422)
