"""WhatsApp template rules: validation, variable mapping, send payload, media checks."""

from types import SimpleNamespace

import pytest

from app.services import wa_template_service as wts

BODY = {"type": "BODY", "text": "Hi {{1}}, your stay at {{2}} is confirmed.",
        "example": {"body_text": [["Priya", "Ratha"]]}}


def _image_header():
    return {"type": "HEADER", "format": "IMAGE", "example": {"header_handle": ["4::abc"]}}


# ─── validate_components ─────────────────────────────────────────────────────

def test_a_plain_body_is_valid():
    assert wts.validate_components([{"type": "BODY", "text": "Hello"}]) == []


def test_a_body_is_required():
    assert any("body is required" in e.lower() for e in wts.validate_components([{"type": "FOOTER", "text": "x"}]))


def test_media_header_needs_an_uploaded_sample():
    errors = wts.validate_components([{"type": "HEADER", "format": "IMAGE"}, BODY])
    assert any("sample image" in e for e in errors)
    assert wts.validate_components([_image_header(), BODY]) == []


def test_text_limits():
    long = "x" * 1025
    assert any("Body is over" in e for e in wts.validate_components([{"type": "BODY", "text": long}]))
    assert any("Footer is over" in e for e in wts.validate_components([BODY, {"type": "FOOTER", "text": "y" * 61}]))
    assert any("Header text is over" in e for e in wts.validate_components(
        [{"type": "HEADER", "format": "TEXT", "text": "h" * 61}, BODY]))


def test_a_footer_cannot_have_variables():
    assert any("footer" in e.lower() for e in wts.validate_components([BODY, {"type": "FOOTER", "text": "{{1}}"}]))


def _buttons(*specs):
    return {"type": "BUTTONS", "buttons": list(specs)}


def test_several_buttons_are_allowed():
    comps = [BODY, _buttons(
        {"type": "QUICK_REPLY", "text": "Yes"},
        {"type": "QUICK_REPLY", "text": "No"},
        {"type": "QUICK_REPLY", "text": "Later"},
    )]
    assert wts.validate_components(comps) == []


def test_button_rules():
    url = {"type": "URL", "text": "Open", "url": "https://ratha.example/book"}
    phone = {"type": "PHONE_NUMBER", "text": "Call", "phone_number": "+919876543210"}
    assert wts.validate_components([BODY, _buttons(url, phone)]) == []

    too_many_urls = [BODY, _buttons(url, url, url)]
    assert any("link buttons" in e for e in wts.validate_components(too_many_urls))

    assert any("https://" in e for e in wts.validate_components(
        [BODY, _buttons({"type": "URL", "text": "Open", "url": "http://x.com"})]))
    assert any("phone number" in e for e in wts.validate_components(
        [BODY, _buttons({"type": "PHONE_NUMBER", "text": "Call", "phone_number": "98765"})]))
    assert any("label" in e for e in wts.validate_components(
        [BODY, _buttons({"type": "QUICK_REPLY", "text": ""})]))
    assert any("25" in e for e in wts.validate_components(
        [BODY, _buttons({"type": "QUICK_REPLY", "text": "z" * 26})]))
    assert any("not supported" in e for e in wts.validate_components(
        [BODY, _buttons({"type": "COPY_CODE", "text": "Copy"})]))


def test_more_than_ten_buttons_is_rejected():
    qr = [{"type": "QUICK_REPLY", "text": f"b{i}"} for i in range(11)]
    assert any("At most 10" in e for e in wts.validate_components([BODY, _buttons(*qr)]))


def test_quick_replies_and_call_to_action_buttons_must_not_interleave():
    qr = {"type": "QUICK_REPLY", "text": "Yes"}
    url = {"type": "URL", "text": "Open", "url": "https://a.example"}
    assert wts.validate_components([BODY, _buttons(qr, qr, url)]) == []
    assert any("together" in e for e in wts.validate_components([BODY, _buttons(qr, url, qr)]))


# ─── variables ───────────────────────────────────────────────────────────────

def test_template_variables_by_section():
    comps = [{"type": "HEADER", "format": "TEXT", "text": "Hello {{1}}"}, BODY]
    assert wts.template_variables(comps) == {"header": [1], "body": [1, 2]}
    assert wts.template_variables([{"type": "BODY", "text": "No variables"}]) == {}


def test_unmapped_variables_lists_what_is_missing():
    comps = [BODY]
    assert wts.unmapped_variables(comps, {}) == ["body {{1}}", "body {{2}}"]
    partial = {"body": {"1": {"source": "first_name"}}}
    assert wts.unmapped_variables(comps, partial) == ["body {{2}}"]
    full = {"body": {"1": {"source": "first_name"}, "2": {"source": "static", "value": "Ratha"}}}
    assert wts.unmapped_variables(comps, full) == []


def test_a_static_variable_needs_a_value_and_an_unknown_source_is_unmapped():
    comps = [{"type": "BODY", "text": "Hi {{1}}"}]
    assert wts.unmapped_variables(comps, {"body": {"1": {"source": "static", "value": "  "}}}) == ["body {{1}}"]
    assert wts.unmapped_variables(comps, {"body": {"1": {"source": "email"}}}) == ["body {{1}}"]


# ─── send payload ────────────────────────────────────────────────────────────

RECIPIENT = SimpleNamespace(name="Priya Sharma", phone="+919876543210")
NAMELESS = SimpleNamespace(name=None, phone="+919000000000")


def test_resolve_variable_sources_and_fallback():
    assert wts.resolve_variable({"source": "name"}, RECIPIENT) == "Priya Sharma"
    assert wts.resolve_variable({"source": "first_name"}, RECIPIENT) == "Priya"
    assert wts.resolve_variable({"source": "phone"}, RECIPIENT) == "+919876543210"
    assert wts.resolve_variable({"source": "static", "value": "Ratha"}, RECIPIENT) == "Ratha"
    assert wts.resolve_variable({"source": "first_name", "fallback": "Guest"}, NAMELESS) == "Guest"
    assert wts.resolve_variable({"source": "first_name"}, NAMELESS) == ""


def test_build_send_components_fills_header_media_and_body():
    comps = [_image_header(), BODY]
    vmap = {"body": {"1": {"source": "first_name"}, "2": {"source": "static", "value": "Ratha"}}}
    out = wts.build_send_components(comps, vmap, RECIPIENT, header_media_link="https://files.example/h.jpg")
    assert out == [
        {"type": "header", "parameters": [{"type": "image", "image": {"link": "https://files.example/h.jpg"}}]},
        {"type": "body", "parameters": [{"type": "text", "text": "Priya"}, {"type": "text", "text": "Ratha"}]},
    ]


def test_build_send_components_video_and_document_use_their_own_key():
    for fmt, key in (("VIDEO", "video"), ("DOCUMENT", "document")):
        out = wts.build_send_components(
            [{"type": "HEADER", "format": fmt, "example": {"header_handle": ["h"]}}, {"type": "BODY", "text": "Hi"}],
            {}, RECIPIENT, header_media_link="https://f.example/x",
        )
        assert out == [{"type": "header", "parameters": [{"type": key, key: {"link": "https://f.example/x"}}]}]


def test_a_template_without_variables_sends_no_body_component():
    assert wts.build_send_components([{"type": "BODY", "text": "Hello"}], {}, RECIPIENT) == []


def test_text_header_variable_is_filled():
    comps = [{"type": "HEADER", "format": "TEXT", "text": "Welcome {{1}}"}, {"type": "BODY", "text": "Hi"}]
    out = wts.build_send_components(comps, {"header": {"1": {"source": "first_name"}}}, RECIPIENT)
    assert out == [{"type": "header", "parameters": [{"type": "text", "text": "Priya"}]}]


def test_an_unresolvable_variable_raises_instead_of_sending_a_broken_message():
    vmap = {"body": {"1": {"source": "first_name"}, "2": {"source": "static", "value": "Ratha"}}}
    with pytest.raises(wts.TemplateError, match=r"body \{\{1\}\}"):
        wts.build_send_components([BODY], vmap, NAMELESS)


def test_a_media_header_with_no_file_raises():
    with pytest.raises(wts.TemplateError, match="image header"):
        wts.build_send_components([_image_header(), BODY], {}, RECIPIENT, header_media_link=None)


# ─── media checks ────────────────────────────────────────────────────────────

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 100
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 100
PDF = b"%PDF-1.7" + b"0" * 100
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"0" * 100


def test_check_media_accepts_the_right_types():
    assert wts.check_media("IMAGE", "image/jpeg", JPEG) == "jpg"
    assert wts.check_media("IMAGE", "image/png", PNG) == "png"
    assert wts.check_media("DOCUMENT", "application/pdf", PDF) == "pdf"
    assert wts.check_media("VIDEO", "video/mp4", MP4) == "mp4"


def test_check_media_rejects_bad_uploads():
    with pytest.raises(wts.TemplateError, match="empty"):
        wts.check_media("IMAGE", "image/jpeg", b"")
    with pytest.raises(wts.TemplateError, match="Unsupported"):
        wts.check_media("IMAGE", "image/gif", b"GIF89a" + b"0" * 50)
    with pytest.raises(wts.TemplateError, match="too large"):
        wts.check_media("IMAGE", "image/jpeg", JPEG + b"0" * (5 * 1024 * 1024))
    with pytest.raises(wts.TemplateError, match="don't match"):
        wts.check_media("IMAGE", "image/jpeg", b"<html>not an image</html>")     # wrong bytes
    with pytest.raises(wts.TemplateError, match="don't match"):
        wts.check_media("DOCUMENT", "application/pdf", JPEG)
    with pytest.raises(wts.TemplateError, match="not supported"):
        wts.check_media("AUDIO", "audio/mpeg", b"x")
    with pytest.raises(wts.TemplateError, match="Unsupported"):
        wts.check_media("VIDEO", "image/png", PNG)          # right bytes, wrong header type
