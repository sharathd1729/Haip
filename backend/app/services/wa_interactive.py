"""WhatsApp interactive messages (reply buttons, a link button, a list, a location request, a WhatsApp Flow form).

A message carries its interactive part in ``message.channel_metadata["interactive"]`` as a small spec; the
send_whatsapp task turns it into Meta's ``interactive`` object with ``payload()``. Interactive messages are
session messages: like free text they reach the guest only inside WhatsApp's 24-hour window.

Meta's limits (enforced by ``InteractiveSpec``): up to 3 reply buttons of 20 characters, body 1024, a CTA URL button
title of 20 and an https link, list button 20, up to 10 rows in total, row title 24, row description 72.
"""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator


class ListRow(BaseModel):
    id: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=24)
    description: str | None = Field(default=None, max_length=72)


class ListSection(BaseModel):
    title: str | None = Field(default=None, max_length=24)
    rows: list[ListRow] = Field(min_length=1, max_length=10)


class InteractiveSpec(BaseModel):
    kind: Literal["buttons", "cta_url", "list", "location_request", "flow"]
    buttons: list[str] = Field(default_factory=list, max_length=3)  # reply buttons: the tapped title comes back as text
    button_ids: list[str] = Field(default_factory=list, max_length=3)  # optional ids sent back on a tap (else btn_0..)
    flow_id: str | None = Field(default=None, max_length=64)        # flow: the published Flow (wa_booking_form)
    flow_token: str | None = Field(default=None, max_length=200)    # flow: comes back with the answers
    flow_screen: str | None = Field(default=None, max_length=64)
    title: str | None = Field(default=None, max_length=20)  # cta_url button text
    url: str | None = Field(default=None, max_length=2000)
    button: str | None = Field(default=None, max_length=20)  # list: the button that opens it
    sections: list[ListSection] = Field(default_factory=list, max_length=10)
    footer: str | None = Field(default=None, max_length=60)

    @field_validator("buttons", mode="before")
    @classmethod
    def _buttons(cls, v):
        out = [str(b).strip() for b in (v or []) if str(b or "").strip()]
        if any(len(b) > 20 for b in out):
            raise ValueError("Keep each button to 20 characters.")
        if len(set(b.lower() for b in out)) != len(out):
            raise ValueError("Each button needs different text.")
        return out

    @model_validator(mode="after")
    def _shape(self):
        if self.kind == "buttons" and not self.buttons:
            raise ValueError("Add at least one button.")
        if self.button_ids and (len(self.button_ids) != len(self.buttons) or any(not 0 < len(i) <= 200 for i in self.button_ids)):
            raise ValueError("Each button needs one id.")
        if self.kind == "flow" and not (self.flow_id and self.title and self.flow_token and self.flow_screen):
            raise ValueError("A form needs its id, button text, token and first screen.")
        if self.kind == "cta_url":
            p = urlparse((self.url or "").strip())
            if not self.title or p.scheme != "https" or not p.netloc:
                raise ValueError("A link button needs its text and an https:// link.")
            self.url = self.url.strip()
        if self.kind == "list":
            if not self.button or not self.sections:
                raise ValueError("A list needs its button text and at least one row.")
            if sum(len(s.rows) for s in self.sections) > 10:
                raise ValueError("A list can hold at most 10 rows.")
        return self


def validate(spec: dict | None) -> dict | None:
    """A cleaned spec dict, or None. Raises pydantic.ValidationError (callers turn it into a 422)."""
    if not spec:
        return None
    return InteractiveSpec(**spec).model_dump(exclude_none=True)


def payload(spec: dict, body: str) -> dict:
    """Meta's ``interactive`` object for a validated spec and the message text."""
    s = InteractiveSpec(**spec)
    text = (body or "").strip()[:1024] or " "
    if s.kind == "buttons":
        out = {"type": "button", "body": {"text": text}, "action": {"buttons": [
            {"type": "reply", "reply": {"id": s.button_ids[i] if s.button_ids else f"btn_{i}", "title": b}}
            for i, b in enumerate(s.buttons)
        ]}}
    elif s.kind == "flow":
        out = {"type": "flow", "body": {"text": text}, "action": {"name": "flow", "parameters": {
            "flow_message_version": "3", "flow_token": s.flow_token, "flow_id": s.flow_id, "flow_cta": s.title,
            "flow_action": "navigate", "flow_action_payload": {"screen": s.flow_screen}}}}
    elif s.kind == "cta_url":
        out = {"type": "cta_url", "body": {"text": text},
               "action": {"name": "cta_url", "parameters": {"display_text": s.title, "url": s.url}}}
    elif s.kind == "list":
        out = {"type": "list", "body": {"text": text}, "action": {"button": s.button, "sections": [
            {**({"title": sec.title} if sec.title else {}),
             "rows": [r.model_dump(exclude_none=True) for r in sec.rows]} for sec in s.sections
        ]}}
    else:
        out = {"type": "location_request_message", "body": {"text": text}, "action": {"name": "send_location"}}
    if s.footer and s.kind != "location_request":
        out["footer"] = {"text": s.footer}
    return out
