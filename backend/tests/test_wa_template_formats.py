"""WhatsApp step 2e: offer-code (COPY_CODE) buttons, limited-time offers and carousels: validation, send payload,
Meta's copy without HAIP's keys, and sync keeping the card files."""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.services import wa_template_service as wts

GUEST = SimpleNamespace(name="Priya Sharma", phone="+919800000001")
BODY = {"type": "BODY", "text": "Diwali at Ratha"}
URL_BTN = {"type": "URL", "text": "Book now", "url": "https://ratha.example/book"}
CODE_BTN = {"type": "COPY_CODE", "example": "DIWALI20"}


def _card(n, fmt="IMAGE", buttons=None):
    return {"components": [
        {"type": "HEADER", "format": fmt, "example": {"header_handle": [f"h{n}"]}, "media_key": f"t1/wa_templates/c{n}.jpg"},
        {"type": "BODY", "text": f"Route {n}"},
        {"type": "BUTTONS", "buttons": buttons or [dict(URL_BTN)]},
    ]}


def _lto(has_expiration=True):
    return [{"type": "HEADER", "format": "IMAGE", "example": {"header_handle": ["h"]}}, BODY,
            {"type": "LIMITED_TIME_OFFER", "limited_time_offer": {"text": "Ends soon", "has_expiration": has_expiration}},
            {"type": "BUTTONS", "buttons": [CODE_BTN, URL_BTN]}]


def test_copy_code_button_is_valid_and_sends_the_code():
    comps = [BODY, {"type": "BUTTONS", "buttons": [CODE_BTN, URL_BTN]}]
    assert wts.validate_components(comps) == []
    out = wts.build_send_components(comps, {"coupon": {"1": {"source": "static", "value": "RATHA15"}}}, GUEST)
    assert out == [{"type": "button", "sub_type": "copy_code", "index": "0",
                    "parameters": [{"type": "coupon_code", "coupon_code": "RATHA15"}]}]
    with pytest.raises(wts.TemplateError):
        wts.build_send_components(comps, {}, GUEST)


def test_copy_code_needs_a_plain_short_sample():
    bad = [BODY, {"type": "BUTTONS", "buttons": [{"type": "COPY_CODE", "example": "has space"}]}]
    assert any("offer code" in e for e in wts.validate_components(bad))
    two = [BODY, {"type": "BUTTONS", "buttons": [CODE_BTN, CODE_BTN]}]
    assert "Only one offer code button is allowed." in wts.validate_components(two)


def test_limited_time_offer_rules():
    assert wts.validate_components(_lto()) == []
    no_code = [c if c.get("type") != "BUTTONS" else {"type": "BUTTONS", "buttons": [URL_BTN]} for c in _lto()]
    assert any("countdown" in e for e in wts.validate_components(no_code))
    assert wts.validate_components([c if c.get("type") != "BUTTONS" else {"type": "BUTTONS", "buttons": [URL_BTN]}
                                    for c in _lto(has_expiration=False)]) == []
    with_footer = _lto() + [{"type": "FOOTER", "text": "T&C"}]
    assert any("footer" in e for e in wts.validate_components(with_footer))


def test_limited_time_offer_sends_its_expiry():
    ends = datetime.now(UTC) + timedelta(days=2)
    vm = {"coupon": {"1": {"source": "static", "value": "DIWALI20"}}, "offer": {"expires_at": ends.isoformat()}}
    out = wts.build_send_components(_lto(), vm, GUEST, header_media_link="https://cdn.example/x.jpg")
    lto = next(c for c in out if c["type"] == "limited_time_offer")
    assert lto["parameters"][0]["limited_time_offer"]["expiration_time_ms"] == int(ends.timestamp() * 1000)
    past = {**vm, "offer": {"expires_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat()}}
    with pytest.raises(wts.TemplateError, match="passed"):
        wts.build_send_components(_lto(), past, GUEST, header_media_link="https://cdn.example/x.jpg")


def test_carousel_rules():
    good = [BODY, {"type": "CAROUSEL", "cards": [_card(1), _card(2)]}]
    assert wts.validate_components(good) == []
    one = [BODY, {"type": "CAROUSEL", "cards": [_card(1)]}]
    assert any("2 to 10 cards" in e for e in wts.validate_components(one))
    mixed = [BODY, {"type": "CAROUSEL", "cards": [_card(1), _card(2, fmt="VIDEO")]}]
    assert any("same kind of file" in e for e in wts.validate_components(mixed))
    shapes = [BODY, {"type": "CAROUSEL", "cards": [_card(1), _card(2, buttons=[URL_BTN, {"type": "QUICK_REPLY", "text": "More"}])]}]
    assert any("same buttons" in e for e in wts.validate_components(shapes))
    with_buttons = good + [{"type": "BUTTONS", "buttons": [URL_BTN]}]
    assert any("carousel has only" in e for e in wts.validate_components(with_buttons))


def test_carousel_send_attaches_each_cards_file():
    comps = [BODY, {"type": "CAROUSEL", "cards": [_card(1), _card(2)]}]
    with patch("app.services.media_storage.get_presigned_media_url", side_effect=lambda k, expires_in: f"https://r2/{k}"):
        out = wts.build_send_components(comps, {}, GUEST)
    cards = out[0]["cards"]
    assert out[0]["type"] == "carousel" and [c["card_index"] for c in cards] == [0, 1]
    assert cards[1]["components"][0]["parameters"][0]["image"]["link"] == "https://r2/t1/wa_templates/c2.jpg"


def test_meta_never_sees_haip_keys_and_sync_keeps_them():
    comps = [BODY, {"type": "CAROUSEL", "cards": [_card(1), _card(2)]}]
    clean = wts.meta_components(comps)
    assert "media_key" not in str(clean) and clean[1]["cards"][0]["components"][0]["example"] == {"header_handle": ["h1"]}
    merged = wts.keep_card_media(comps, clean)
    assert wts.card_media_keys(merged) == ["t1/wa_templates/c1.jpg", "t1/wa_templates/c2.jpg"]


def test_saving_a_card_file_from_another_workspace_is_refused(client, tenant_and_user):
    comps = [BODY, {"type": "CAROUSEL", "cards": [_card(1), _card(2)]}]
    r = client.post("/api/v1/messaging/templates", json={"name": "routes", "language": "en", "category": "MARKETING",
                                                         "components": comps},
                    headers={"Authorization": f"Bearer {tenant_and_user['access_token']}"})
    assert r.status_code == 400 and "card's file" in r.json()["detail"]


def test_launch_check_asks_for_the_code_and_the_end_time():
    assert wts.unmapped_variables(_lto(), {}) == ["the offer code", "when the offer ends"]
    ends = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    assert wts.unmapped_variables(_lto(), {"coupon": {"1": {"source": "static", "value": "X1"}}, "offer": {"expires_at": ends}}) == []
