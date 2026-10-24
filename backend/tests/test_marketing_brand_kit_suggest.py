"""Brand kit "Fill from my website / logo" (POST /marketing/studio/brand-kit/suggest): the HAIP website's theme first,
else the logo's two dominant non-neutral colours (Pillow, no AI). A suggestion only: nothing is saved."""
import io
import uuid

import pytest
from PIL import Image

from app.models.media_asset import MediaAsset
from app.models.tenant import Tenant
from app.models.user import UserRole
from app.models.website import Site, SiteVersion
from app.services import marketing_brand_kit as kit_svc
from tests.test_marketing_studio_content import BASE, make_user, ws  # noqa: F401  (fixture)

BLUE, ORANGE = (20, 60, 160), (240, 120, 20)


def _logo() -> bytes:
    """Transparent background, a white box, a big blue block and a smaller orange one."""
    img = Image.new("RGBA", (400, 200), (0, 0, 0, 0))
    img.paste((255, 255, 255, 255), (0, 0, 400, 30))
    img.paste((*BLUE, 255), (0, 40, 250, 200))
    img.paste((*ORANGE, 255), (260, 40, 400, 140))
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


@pytest.fixture(autouse=True)
def _storage(monkeypatch):
    monkeypatch.setattr("app.services.media_library_service._read_object", lambda key: _logo())


def _asset(db, tid):
    a = MediaAsset(id=str(uuid.uuid4()), tenant_id=tid, storage_key=f"{tid}/marketing/{uuid.uuid4().hex}.png",
                   mime_type="image/png", bytes=10, sha256=uuid.uuid4().hex * 2, status="active")
    db.add(a)
    db.commit()
    return a


def _site(db, tid, pack):
    site = Site(id=str(uuid.uuid4()), tenant_id=tid, name="S", slug=f"s-{uuid.uuid4().hex[:8]}", status="live")
    db.add(site)
    db.flush()
    v = SiteVersion(id=str(uuid.uuid4()), tenant_id=tid, site_id=site.id, number=1, sha256="a" * 64, status="published",
                    doc={"theme": {"pack": pack, "personality": "calm"}, "pages": []})
    db.add(v)
    site.live_version_id = v.id
    db.commit()


def _close(hex_, rgb, tol=40):
    return all(abs(a - b) <= tol for a, b in zip(kit_svc._rgb(hex_), rgb))


def test_logo_palette_is_the_two_brand_colours_and_ignores_transparent_and_white():
    first, second = kit_svc.logo_palette(_logo())
    assert _close(first, BLUE) and _close(second, ORANGE)
    plain = io.BytesIO()
    Image.new("RGBA", (100, 100), (255, 255, 255, 255)).save(plain, format="PNG")
    assert kit_svc.logo_palette(plain.getvalue()) == []


def test_a_suggested_colour_is_readable_on_white():
    assert kit_svc.contrast_on_white("#A6D23C") < 3                     # the Goa pack's lime as it is
    fixed = kit_svc.readable("#A6D23C")
    assert kit_svc.contrast_on_white(fixed) >= 3 and kit_svc.readable("#1F6B45") == "#1F6B45"


def test_suggest_from_the_logo_saves_nothing_and_needs_edit(client, db, ws):  # noqa: F811
    logo = _asset(db, ws["tenant"].id)
    r = client.post(f"{BASE}/brand-kit/suggest", json={"logo_asset_id": logo.id}, headers=ws["mkt_h"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "logo" and body["font"] == "plain"
    assert _close(body["primary"], BLUE) and kit_svc.contrast_on_white(body["accent"]) >= 3
    assert client.get(f"{BASE}/brand-kit", headers=ws["mkt_h"]).json()["primary"] is None      # never auto-saved
    _, foh_h = make_user(db, ws["tenant"].id, UserRole.FOH)
    assert client.post(f"{BASE}/brand-kit/suggest", json={"logo_asset_id": logo.id}, headers=foh_h).status_code == 403


def test_the_website_theme_wins_over_the_logo(client, db, ws):  # noqa: F811
    logo = _asset(db, ws["tenant"].id)
    _site(db, ws["tenant"].id, "rajasthan")
    r = client.post(f"{BASE}/brand-kit/suggest", json={"logo_asset_id": logo.id}, headers=ws["owner_h"])
    assert r.json() == {"source": "website", "primary": "#B23A6B", "accent": "#2E4A9A", "font": "serif"}


def test_another_tenants_logo_or_website_is_never_read(client, db, ws):  # noqa: F811
    other = Tenant(id=str(uuid.uuid4()), name="O", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    theirs = _asset(db, other.id)
    _site(db, other.id, "goa")
    r = client.post(f"{BASE}/brand-kit/suggest", json={"logo_asset_id": theirs.id}, headers=ws["owner_h"])
    assert r.status_code == 422 and r.json()["detail"]["code"] == "nothing_to_read"
