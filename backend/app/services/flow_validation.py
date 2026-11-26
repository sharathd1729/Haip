"""Save-time checks for a WhatsApp flow canvas (docs/whatsapp/FLOW_CANVAS_SPEC.md "Validation on save").

``validate_flow`` raises ValueError with a plain sentence (the endpoint returns it as a 422) and returns the trigger
node's trigger value, which the ``wa_flows.trigger`` column mirrors. An empty flow (a fresh draft) passes.
"""
from __future__ import annotations

from urllib.parse import urlparse

KNOWN_TYPES = {"trigger", "message", "media", "location", "buttons", "list", "cta_url", "template", "question",
               "condition", "delay", "action", "http", "end"}
_OPTION_ID_MAX = 100   # the reply id is "wfl:<36-char id>:<option id>" and Meta allows 200 characters


def _https(url) -> bool:
    p = urlparse(str(url or "").strip())
    return p.scheme == "https" and bool(p.netloc)


def _text(node: dict, key: str) -> str:
    return str(node.get(key) or "").strip()


def _options(node: dict, key: str, what: str, most: int, title_max: int) -> None:
    items = node.get(key) or []
    if not isinstance(items, list) or not 1 <= len(items) <= most:
        raise ValueError(f"A {what} step needs 1 to {most} options.")
    ids, titles = set(), set()
    for item in items:
        oid, title = str((item or {}).get("id") or "").strip(), str((item or {}).get("title") or "").strip()
        if not oid or len(oid) > _OPTION_ID_MAX:
            raise ValueError(f"Each option on a {what} step needs a short id.")
        if not title or len(title) > title_max:
            raise ValueError(f"Keep each {what} option title between 1 and {title_max} characters.")
        if oid in ids or title.lower() in titles:
            raise ValueError(f"Each option on a {what} step needs its own id and title.")
        ids.add(oid)
        titles.add(title.lower())
        if len(str(item.get("description") or "")) > 72:
            raise ValueError("Keep each list row description to 72 characters.")


def _check_node(node: dict, tenant_id: str) -> None:
    ntype = node.get("type")
    if ntype not in KNOWN_TYPES:
        raise ValueError(f"Unknown step type '{ntype}'.")
    if ntype in ("buttons", "list", "cta_url", "question"):
        if not _text(node, "content") or len(_text(node, "content")) > 1024:
            raise ValueError("Write the message for each buttons, list, link and question step (up to 1024 characters).")
    if ntype in ("list", "cta_url") and not 1 <= len(_text(node, "button_label")) <= 20:
        raise ValueError("Keep the button text on list and link steps between 1 and 20 characters.")
    if ntype == "buttons":
        _options(node, "buttons", "buttons", 3, 20)
    elif ntype == "list":
        _options(node, "rows", "list", 10, 24)
    elif ntype == "cta_url" and not _https(node.get("url")):
        raise ValueError("A link button needs an https:// link.")
    elif ntype == "http":
        if str(node.get("method") or "").upper() not in ("GET", "POST"):
            raise ValueError("A web request step must use GET or POST.")
        if not _https(node.get("url")):
            raise ValueError("A web request step needs an https:// link.")
    elif ntype == "media":
        if node.get("media_kind") not in ("image", "video", "audio", "document"):
            raise ValueError("Pick the kind of file for each media step.")
        if not _text(node, "file_key").startswith(f"{tenant_id}/wa_flows/"):
            raise ValueError("Upload the file again: it does not belong to this workspace.")
    elif ntype == "location":
        try:
            lat, lng = float(node.get("latitude")), float(node.get("longitude"))
        except (TypeError, ValueError):
            raise ValueError("A location step needs a latitude and a longitude.") from None
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            raise ValueError("That location's latitude or longitude is out of range.")
    elif ntype == "question":
        save_as = _text(node, "save_as")
        if save_as not in ("name", "email", "notes") and not (save_as.startswith("custom:") and save_as[7:].strip()):
            raise ValueError("Choose where each question's answer is saved.")
    elif ntype == "action" and (node.get("action") or node.get("content")) == "add_label":
        if not (_text(node, "tag") or _text(node, "label")):
            raise ValueError("Type the label an add-label step adds.")


def validate_flow(nodes: list, edges: list, tenant_id: str) -> str | None:
    if not nodes:
        return None
    if not all(isinstance(n, dict) for n in nodes) or not all(isinstance(e, dict) for e in edges or []):
        raise ValueError("The flow could not be read. Reload the page and try again.")
    ids = [str(n.get("id") or "") for n in nodes]
    if not all(ids):
        raise ValueError("Every step needs an id.")
    if len(set(ids)) != len(ids):
        raise ValueError("Two steps share the same id.")
    triggers = [n for n in nodes if n.get("type") == "trigger"]
    if len(triggers) != 1:
        raise ValueError("A flow needs exactly one trigger step.")
    trigger = triggers[0]
    value = trigger.get("trigger") or trigger.get("content") or None
    if value == "keyword" and not [k for k in (trigger.get("keywords") or []) if str(k).strip()]:
        raise ValueError("A keyword trigger needs at least one keyword.")
    if trigger.get("match") not in (None, "", "exact", "contains"):
        raise ValueError("A keyword trigger matches either the exact message or a word in it.")
    for node in nodes:
        _check_node(node, tenant_id)
    known, edge_ids = set(ids), [e.get("id") for e in edges or [] if e.get("id")]
    if len(set(edge_ids)) != len(edge_ids):
        raise ValueError("Two connections share the same id.")
    for edge in edges or []:
        if edge.get("from") not in known or edge.get("to") not in known:
            raise ValueError("A connection points at a step that no longer exists.")
    return value
