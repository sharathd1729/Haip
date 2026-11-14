"""Instagram automation rule config (automation_rules.trigger_config / action_config for the ig_* triggers).

Validated when a rule is saved (endpoints/automations.py); the engine (services/ig_automation.py) reads the stored dicts
with the same defaults, so older rules written before these fields existed keep working.
"""
from __future__ import annotations

from typing import Literal, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator

IG_TRIGGERS = (
    "ig_comment_received",        # comment on a post / reel / ad
    "ig_live_comment_received",   # comment during an Instagram Live
    "ig_story_reply_received",    # reply to one of our stories
    "ig_story_mention_received",  # someone mentions us in their story
    "ig_dm_received",             # DM keyword
    "ig_ad_chat_started",         # a chat opened from an ad
)


class IgTriggerConfig(BaseModel):
    keywords: list[str] = Field(default_factory=list, max_length=50)
    exclude_keywords: list[str] = Field(default_factory=list, max_length=50)
    reply_all: bool = False                       # any comment / story reply / mention, no keyword needed
    scope: Literal["post", "any", "next_post"] = "any"
    media_id: Optional[str] = Field(default=None, max_length=64)
    media_thumb: Optional[str] = Field(default=None, max_length=2000)    # display only
    media_caption: Optional[str] = Field(default=None, max_length=300)   # display only
    media_bound_at: Optional[str] = None          # set by the engine when a next_post rule binds
    ad_id: Optional[str] = Field(default=None, max_length=64)

    @field_validator("keywords", "exclude_keywords", mode="before")
    @classmethod
    def _split(cls, v):
        if isinstance(v, str):
            v = v.split(",")
        return [k.strip()[:60] for k in (v or []) if k and str(k).strip()]

    @model_validator(mode="after")
    def _media(self):
        if self.scope == "any" and self.media_id:
            self.scope = "post"                       # older rules: a media_id alone meant "this post"
        if self.scope == "post" and not self.media_id:
            raise ValueError("Pick the post or reel this automation is for.")
        return self


class IgButton(BaseModel):
    title: str = Field(min_length=1, max_length=20)
    url: str = Field(max_length=1000)

    @field_validator("url")
    @classmethod
    def _https(cls, v: str) -> str:
        p = urlparse(v.strip())
        if p.scheme != "https" or not p.netloc:
            raise ValueError("The button link must start with https://")
        return v.strip()


class IgFollowGate(BaseModel):
    enabled: bool = False
    ask_text: str = Field(default="Please follow us first, then tap the button below 👇", max_length=640)
    button_title: str = Field(default="I'm following", max_length=20)
    max_asks: int = Field(default=3, ge=1, le=5)
    send_anyway: bool = True                      # after the last ask: send the message anyway, or stop


class IgActionConfig(BaseModel):
    message: str = Field(min_length=1, max_length=900)
    button: Optional[IgButton] = None
    opener: str = Field(default="Hi {first_name}! Tap below and I'll send it over 👇", max_length=640)
    opener_button: str = Field(default="Send it", max_length=20)
    public_ack_pool: list[str] = Field(default_factory=list, max_length=10)
    follow_gate: IgFollowGate = Field(default_factory=IgFollowGate)
    once_per_person: bool = True

    @field_validator("public_ack_pool", mode="before")
    @classmethod
    def _acks(cls, v):
        return [a.strip()[:300] for a in (v or []) if a and str(a).strip()]


def validate_ig_rule(trigger: str, trigger_config: dict, action_config: dict) -> tuple[dict, dict]:
    """Validated + normalised copies of both configs for an ig_* rule. Raises pydantic.ValidationError."""
    t = IgTriggerConfig(**(trigger_config or {}))
    if trigger in ("ig_comment_received", "ig_live_comment_received", "ig_dm_received", "ig_story_reply_received") \
            and not t.reply_all and not t.keywords:
        raise ValueError("Add at least one keyword, or choose 'any comment'.")
    a = IgActionConfig(**(action_config or {}))
    return t.model_dump(exclude_none=True), a.model_dump(exclude_none=True)
