"""
WhatsApp message-template helpers: structure validation, variable handling,
send-payload construction, and header-media upload to Meta.

Kept separate from api/v1/endpoints/messaging.py so the rules can be tested
without HTTP and reused by the campaign runner.

Scope: TEXT / IMAGE / VIDEO / DOCUMENT headers, a body with {{n}} variables, a
footer, and up to 10 buttons of type QUICK_REPLY, URL and PHONE_NUMBER. A URL
button may end in one {{1}} (a dynamic suffix, e.g. "https://rzp.io/{{1}}" for
a Razorpay link) with an example URL; the suffix is passed per send. A send may
also override a DOCUMENT header with its own file (e.g. this guest's invoice).
Carousel, COPY_CODE and LTO/catalog templates are not supported yet.
"""

from __future__ import annotations

import re
from typing import Any, Optional

import httpx
import structlog

from app.core.config import settings

log = structlog.get_logger()

_GRAPH = "https://graph.facebook.com/v18.0"
_VAR_RE = re.compile(r"\{\{(\d+)\}\}")

MEDIA_FORMATS = ("IMAGE", "VIDEO", "DOCUMENT")

# Meta's template-sample limits. Images/videos/documents used as the header
# sample and as the sent header both have to respect these.
MEDIA_RULES: dict[str, dict[str, Any]] = {
    "IMAGE":    {"types": {"image/jpeg": "jpg", "image/png": "png"},         "max_bytes": 5 * 1024 * 1024},
    "VIDEO":    {"types": {"video/mp4": "mp4"},                              "max_bytes": 16 * 1024 * 1024},
    "DOCUMENT": {"types": {"application/pdf": "pdf"},                        "max_bytes": 16 * 1024 * 1024},
}

MAX_BODY = 1024
MAX_HEADER_TEXT = 60
MAX_FOOTER = 60
MAX_BUTTON_TEXT = 25
MAX_BUTTONS = 10
MAX_URL_BUTTONS = 2
MAX_PHONE_BUTTONS = 1

VARIABLE_SOURCES = ("name", "first_name", "phone", "static")


class TemplateError(ValueError):
    """A template or upload the user has to fix; message is safe to show."""


# ─── Variables ───────────────────────────────────────────────────────────────

def variable_indices(text: Optional[str]) -> list[int]:
    return sorted({int(m) for m in _VAR_RE.findall(text or "")})


def template_variables(components: list) -> dict[str, list[int]]:
    """{"header": [1], "body": [1, 2]} -- only sections that have variables."""
    found: dict[str, list[int]] = {}
    for comp in components or []:
        ctype = (comp.get("type") or "").upper()
        if ctype in ("HEADER", "BODY"):
            idx = variable_indices(comp.get("text"))
            if idx:
                found[ctype.lower()] = idx
    return found


def unmapped_variables(components: list, variable_map: Optional[dict]) -> list[str]:
    """Names like 'body {{2}}' for every template variable with no usable mapping."""
    variable_map = variable_map or {}
    missing: list[str] = []
    for section, indices in template_variables(components).items():
        section_map = variable_map.get(section) or {}
        for i in indices:
            spec = section_map.get(str(i)) or {}
            source = spec.get("source")
            if source not in VARIABLE_SOURCES:
                missing.append(f"{section} {{{{{i}}}}}")
            elif source == "static" and not str(spec.get("value") or "").strip():
                missing.append(f"{section} {{{{{i}}}}}")
    return missing


# ─── Structure validation ────────────────────────────────────────────────────

def _button_group(button_type: str) -> str:
    return "quick_reply" if button_type == "QUICK_REPLY" else "cta"


def validate_components(components: list) -> list[str]:
    """Problems with a template's structure, in plain words. [] means valid.

    Catches what Meta would otherwise reject after submission with an opaque
    message: missing body, over-length text, bad button mixes, and media
    headers that have no uploaded sample."""
    errors: list[str] = []
    types = [(c.get("type") or "").upper() for c in components or []]

    for single in ("HEADER", "BODY", "FOOTER", "BUTTONS"):
        if types.count(single) > 1:
            errors.append(f"Only one {single.lower()} is allowed.")
    if "BODY" not in types:
        errors.append("A body is required.")

    for comp in components or []:
        ctype = (comp.get("type") or "").upper()
        text = comp.get("text") or ""

        if ctype == "HEADER":
            fmt = (comp.get("format") or "TEXT").upper()
            if fmt == "TEXT":
                if not text.strip():
                    errors.append("Header text is empty.")
                if len(text) > MAX_HEADER_TEXT:
                    errors.append(f"Header text is over {MAX_HEADER_TEXT} characters.")
                if len(variable_indices(text)) > 1:
                    errors.append("A text header can have at most one variable.")
            elif fmt in MEDIA_FORMATS:
                handle = ((comp.get("example") or {}).get("header_handle") or [])
                if not handle or not str(handle[0]).strip():
                    errors.append(f"Upload a sample {fmt.lower()} for the header.")
            else:
                errors.append(f"Header type {fmt} is not supported.")

        elif ctype == "BODY":
            if not text.strip():
                errors.append("Body text is empty.")
            if len(text) > MAX_BODY:
                errors.append(f"Body is over {MAX_BODY} characters.")

        elif ctype == "FOOTER":
            if len(text) > MAX_FOOTER:
                errors.append(f"Footer is over {MAX_FOOTER} characters.")
            if variable_indices(text):
                errors.append("A footer cannot contain variables.")

        elif ctype == "BUTTONS":
            buttons = comp.get("buttons") or []
            if not buttons:
                errors.append("Buttons section is empty.")
            if len(buttons) > MAX_BUTTONS:
                errors.append(f"At most {MAX_BUTTONS} buttons are allowed.")
            counts = {"URL": 0, "PHONE_NUMBER": 0}
            groups: list[str] = []
            for b in buttons:
                btype = (b.get("type") or "").upper()
                label = (b.get("text") or "").strip()
                if btype not in ("QUICK_REPLY", "URL", "PHONE_NUMBER"):
                    errors.append(f"Button type {btype or '(none)'} is not supported.")
                    continue
                if not label:
                    errors.append("Every button needs a label.")
                elif len(label) > MAX_BUTTON_TEXT:
                    errors.append(f"Button '{label[:12]}…' is over {MAX_BUTTON_TEXT} characters.")
                if btype == "URL":
                    counts["URL"] += 1
                    url = (b.get("url") or "").strip()
                    if not url.lower().startswith("https://"):
                        errors.append("A URL button needs a link starting with https://.")
                    if variable_indices(url):
                        if not url.endswith("{{1}}") or variable_indices(url) != [1] or url.count("{{") != 1:
                            errors.append("A link can only have one variable, {{1}}, at the very end.")
                        else:
                            example = b.get("example") or []
                            sample = str(example[0] if isinstance(example, list) and example else example or "")
                            if not sample.lower().startswith(url[:-5].lower()) or len(sample) <= len(url) - 5:
                                errors.append("A link with {{1}} needs an example: the full link with a sample ending.")
                elif btype == "PHONE_NUMBER":
                    counts["PHONE_NUMBER"] += 1
                    phone = (b.get("phone_number") or "").strip()
                    if not re.fullmatch(r"\+\d{8,15}", phone):
                        errors.append("A call button needs a phone number like +919876543210.")
                groups.append(_button_group(btype))
            if counts["URL"] > MAX_URL_BUTTONS:
                errors.append(f"At most {MAX_URL_BUTTONS} link buttons are allowed.")
            if counts["PHONE_NUMBER"] > MAX_PHONE_BUTTONS:
                errors.append("Only one call button is allowed.")
            # Meta wants quick replies together and call-to-action buttons together.
            changes = sum(1 for a, b in zip(groups, groups[1:]) if a != b)
            if changes > 1:
                errors.append("Keep quick-reply buttons together and link/call buttons together.")

    return errors


# ─── Send payload ────────────────────────────────────────────────────────────

def _first_name(name: Optional[str]) -> str:
    return (name or "").strip().split(" ")[0] if (name or "").strip() else ""


def resolve_variable(spec: dict, recipient: Any) -> str:
    """The text for one variable for one recipient, or "" if there is nothing
    to send (caller decides what an empty value means)."""
    source = spec.get("source")
    if source == "static":
        value = str(spec.get("value") or "")
    elif source == "name":
        value = (getattr(recipient, "name", None) or "").strip()
    elif source == "first_name":
        value = _first_name(getattr(recipient, "name", None))
    elif source == "phone":
        value = (getattr(recipient, "phone", None) or "").strip()
    else:
        value = ""
    if not value:
        value = str(spec.get("fallback") or "").strip()
    return value


def build_send_components(
    components: list,
    variable_map: Optional[dict],
    recipient: Any,
    header_media_link: Optional[str] = None,
    header_document_filename: Optional[str] = None,
    button_params: Optional[dict[int, str]] = None,
) -> list[dict]:
    """Components array for Meta's send-template call: header media and
    every {{n}} variable filled in for this recipient.

    ``header_document_filename`` names a DOCUMENT header file as the guest sees
    it ("Invoice INV-2026-27-0001.pdf"). ``button_params`` maps a button's
    position to the text that fills its URL's {{1}}.

    Raises TemplateError when a value cannot be resolved (Meta rejects an
    empty parameter), so the caller can count that recipient as failed with a
    reason instead of sending a broken message."""
    variable_map = variable_map or {}
    button_params = button_params or {}
    out: list[dict] = []

    for comp in components or []:
        ctype = (comp.get("type") or "").upper()

        if ctype == "HEADER":
            fmt = (comp.get("format") or "TEXT").upper()
            if fmt in MEDIA_FORMATS:
                if not header_media_link:
                    raise TemplateError(f"This template has a {fmt.lower()} header but no file is attached.")
                key = fmt.lower()
                media: dict = {"link": header_media_link}
                if fmt == "DOCUMENT" and header_document_filename:
                    media["filename"] = header_document_filename[:240]
                out.append({"type": "header", "parameters": [{"type": key, key: media}]})
            elif variable_indices(comp.get("text")):
                out.append({"type": "header", "parameters": _text_params(comp, "header", variable_map, recipient)})

        elif ctype == "BODY" and variable_indices(comp.get("text")):
            out.append({"type": "body", "parameters": _text_params(comp, "body", variable_map, recipient)})

        elif ctype == "BUTTONS":
            for index, b in enumerate(comp.get("buttons") or []):
                if (b.get("type") or "").upper() != "URL" or not variable_indices(b.get("url")):
                    continue
                suffix = str(button_params.get(index) or "").strip()
                if not suffix:
                    raise TemplateError(f"The '{b.get('text') or 'link'}' button needs the end of its link for this message.")
                out.append({"type": "button", "sub_type": "url", "index": str(index),
                            "parameters": [{"type": "text", "text": suffix}]})

    return out


def _text_params(comp: dict, section: str, variable_map: dict, recipient: Any) -> list[dict]:
    params = []
    section_map = variable_map.get(section) or {}
    for i in variable_indices(comp.get("text")):
        spec = section_map.get(str(i)) or {}
        value = resolve_variable(spec, recipient)
        if not value:
            raise TemplateError(f"No value for {section} {{{{{i}}}}} and no fallback set.")
        params.append({"type": "text", "text": value})
    return params


# ─── Meta's errors, in words ─────────────────────────────────────────────────

# Errors that say something is wrong with the WhatsApp connection, not with
# the template: retrying or editing the template cannot fix them.
_CONNECTION_CODES = {3, 10, 102, 190, 200}


def explain_meta_error(err: dict, waba_id: Optional[str] = None) -> tuple[str, bool]:
    """(plain-language reason, is_connection_problem) for an error Meta
    returned when creating or editing a template.

    Real case (Ratha, Sep 2026): every submission came back "Rejected" with
    Meta's raw "Unsupported post request. Object with ID '1006816261945573'
    does not exist, cannot be loaded due to missing permissions..." The ID was
    the saved WhatsApp Business Account ID; Meta never reviewed the template."""
    code, sub = err.get("code"), err.get("error_subcode")
    if code == 100 and sub == 33:
        which = f" ({waba_id})" if waba_id else ""
        return (
            f"Meta doesn't recognise the WhatsApp Business Account ID saved here{which}, or the access token isn't allowed to manage it. "
            "Open Messaging → Overview and use the connection check, or correct the ID in Settings → Integrations → WhatsApp "
            "(WhatsApp Manager → Account tools shows it). The token also needs the whatsapp_business_management permission.",
            True,
        )
    if code in (102, 190):
        return ("The WhatsApp access token has expired or is invalid. Create a permanent System User token and reconnect WhatsApp.", True)
    if code in (10, 200):
        return ("The access token isn't allowed to manage message templates. It needs the whatsapp_business_management permission.", True)
    if sub == 2388023:
        return ("Meta remembers this template name from one that was deleted and won't let it be reused for a while. Use a different name.", False)
    text = err.get("error_user_msg") or err.get("error_user_title") or err.get("message") or "Meta refused the template."
    return (str(text)[:500], code in _CONNECTION_CODES)


# ─── Media upload ────────────────────────────────────────────────────────────

_MAGIC = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "application/pdf": (b"%PDF-",),
}


def check_media(fmt: str, content_type: str, content: bytes) -> str:
    """Validate an uploaded header sample, return its file extension.

    Trusts the file's bytes over the browser-supplied content type."""
    rules = MEDIA_RULES.get(fmt.upper())
    if not rules:
        raise TemplateError(f"Header type {fmt} is not supported.")
    if not content:
        raise TemplateError("The file is empty.")
    if len(content) > rules["max_bytes"]:
        raise TemplateError(f"File is too large ({len(content) / 1048576:.1f} MB). Max {rules['max_bytes'] // 1048576} MB for {fmt.lower()}.")
    ctype = (content_type or "").split(";")[0].strip().lower()
    if ctype not in rules["types"]:
        allowed = ", ".join(sorted(rules["types"].values())).upper()
        raise TemplateError(f"Unsupported file type. Use {allowed} for a {fmt.lower()} header.")
    magic = _MAGIC.get(ctype)
    if magic and not any(content.startswith(m) for m in magic):
        raise TemplateError("The file's contents don't match its type.")
    if ctype == "video/mp4" and b"ftyp" not in content[:32]:
        raise TemplateError("The file's contents don't match its type.")
    return rules["types"][ctype]


def _app_id(access_token: str) -> str:
    """The Meta app id that owns this token -- needed by the upload API."""
    if settings.META_APP_ID:
        return settings.META_APP_ID
    resp = httpx.get(
        f"{_GRAPH}/debug_token",
        params={"input_token": access_token, "access_token": access_token},
        timeout=15,
    )
    app_id = (resp.json().get("data") or {}).get("app_id")
    if not app_id:
        raise TemplateError("Couldn't work out the Meta app for this WhatsApp connection. Set META_APP_ID on the server.")
    return str(app_id)


def upload_sample_to_meta(access_token: str, content: bytes, content_type: str, file_name: str) -> str:
    """Meta's resumable upload: returns the header_handle that a template's
    media header must carry as its example."""
    try:
        app_id = _app_id(access_token)
        start = httpx.post(
            f"{_GRAPH}/{app_id}/uploads",
            params={
                "file_length": len(content), "file_type": content_type, "file_name": file_name,
                "access_token": access_token,
            },
            timeout=20,
        ).json()
        upload_id = start.get("id")
        if not upload_id:
            raise TemplateError(f"Meta refused the upload: {(start.get('error') or {}).get('message', 'unknown error')}")
        done = httpx.post(
            f"{_GRAPH}/{upload_id}",
            headers={"Authorization": f"OAuth {access_token}", "file_offset": "0"},
            content=content,
            timeout=60,
        ).json()
    except httpx.HTTPError as exc:
        log.error("wa_template_media_upload_failed", error=str(exc))
        raise TemplateError("Couldn't reach Meta to upload the file. Try again.") from exc
    handle = done.get("h")
    if not handle:
        raise TemplateError(f"Meta refused the upload: {(done.get('error') or {}).get('message', 'unknown error')}")
    return handle
