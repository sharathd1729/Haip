"""Instagram automation rule config (automation_rules.trigger_config / action_config for the ig_* triggers).

Validated when a rule is saved (endpoints/automations.py); the engine (services/ig_automation.py) reads the stored dicts
with the same defaults, so older rules written before these fields existed keep working.
"""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator

IG_TRIGGERS = (
    "ig_comment_received",  # comment on a post / reel / ad
    "ig_live_comment_received",  # comment during an Instagram Live
    "ig_story_reply_received",  # reply to one of our stories
    "ig_story_mention_received",  # someone mentions us in their story
    "ig_dm_received",  # DM keyword
    "ig_ad_chat_started",  # a chat opened from an ad
)


class IgTriggerConfig(BaseModel):
    keywords: list[str] = Field(default_factory=list, max_length=50)
    exclude_keywords: list[str] = Field(default_factory=list, max_length=50)
    reply_all: bool = False  # any comment / story reply / mention, no keyword needed
    scope: Literal["post", "any", "next_post"] = "any"
    media_id: str | None = Field(default=None, max_length=64)
    media_thumb: str | None = Field(default=None, max_length=2000)  # display only
    media_caption: str | None = Field(default=None, max_length=300)  # display only
    media_bound_at: str | None = None  # set by the engine when a next_post rule binds
    ad_id: str | None = Field(default=None, max_length=64)

    @field_validator("keywords", "exclude_keywords", mode="before")
    @classmethod
    def _split(cls, v):
        if isinstance(v, str):
            v = v.split(",")
        return [k.strip()[:60] for k in (v or []) if k and str(k).strip()]

    @model_validator(mode="after")
    def _media(self):
        if self.scope == "any" and self.media_id:
            self.scope = "post"  # older rules: a media_id alone meant "this post"
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
    send_anyway: bool = True  # after the last ask: send the message anyway, or stop


FORM_KEYS = ("dates", "guests", "phone", "email", "budget", "occasion", "custom")


class IgFormQuestion(BaseModel):
    key: Literal["dates", "guests", "phone", "email", "budget", "occasion", "custom"]
    text: str = Field(min_length=1, max_length=300)
    options: list[str] = Field(default_factory=list, max_length=10)  # tap-to-answer chips; typing works too

    @field_validator("options", mode="before")
    @classmethod
    def _options(cls, v):
        out = [str(o).strip() for o in (v or []) if str(o or "").strip()]
        too_long = [o for o in out if len(o) > 20]
        if too_long:  # Instagram cuts quick-reply titles at 20 characters
            raise ValueError(f"Keep each answer option to 20 characters: '{too_long[0]}'")
        return out


class IgForm(BaseModel):
    """Collect details inside the DM (services/ig_dm_form.py): questions asked one at a time after the tap; the rule's
    `message` (and button) is sent once the last answer arrives."""

    enabled: bool = False
    questions: list[IgFormQuestion] = Field(default_factory=list, max_length=6)

    @model_validator(mode="after")
    def _phone_once(self):
        if self.enabled:
            phones = [q for q in self.questions if q.key == "phone"]
            if len(phones) != 1:
                raise ValueError("The form must ask for the WhatsApp number once: that is what makes the person a lead.")
            keys = [q.key for q in self.questions if q.key != "custom"]
            if len(keys) != len(set(keys)):
                raise ValueError("Each question type can be asked only once (add more as 'your own question').")
        return self


SEQUENCE_WINDOW_MINUTES = 23 * 60  # Instagram allows messages for 24 h after the person's last message


class IgSequenceStep(BaseModel):
    """One follow-up after the automation's final message (services/ig_sequence.py)."""

    text: str = Field(min_length=1, max_length=640)
    after_minutes: int = Field(ge=5, le=SEQUENCE_WINDOW_MINUTES)  # wait after the previous message
    button: IgButton | None = None


class IgSuggestMore(BaseModel):
    """After the final message: a "More stays" button that shows the workspace's stays or packages as swipeable cards
    (services/ig_suggest.py). Cards never show prices; "I'm interested" hands the chat to the team."""

    enabled: bool = False
    source: Literal["stays", "packages"] = "stays"
    prompt: str = Field(default="Want to see our other stays?", max_length=300)
    button_title: str = Field(default="More stays", min_length=1, max_length=20)


class IgActionConfig(BaseModel):
    message: str = Field(min_length=1, max_length=900)
    button: IgButton | None = None
    opener: str = Field(default="Hi {first_name}! Tap below and I'll send it over 👇", max_length=640)
    opener_button: str = Field(default="Send it", max_length=20)
    public_ack_pool: list[str] = Field(default_factory=list, max_length=10)
    follow_gate: IgFollowGate = Field(default_factory=IgFollowGate)
    once_per_person: bool = True
    follow_up: str = Field(default="", max_length=500)  # DM-keyword rules only (endpoints/automations.py)
    follow_up_after_hours: int | None = Field(default=None, ge=1, le=23)
    form: IgForm = Field(default_factory=IgForm)
    sequence: list[IgSequenceStep] = Field(default_factory=list, max_length=3)
    suggest_more: IgSuggestMore = Field(default_factory=IgSuggestMore)

    @model_validator(mode="after")
    def _sequence_fits_the_window(self):
        total = sum(step.after_minutes for step in self.sequence)
        if total > SEQUENCE_WINDOW_MINUTES:
            raise ValueError("The follow-ups must all go out within 23 hours: Instagram stops allowing messages 24 hours "
                             "after the person's last message.")
        return self

    @field_validator("public_ack_pool", mode="before")
    @classmethod
    def _acks(cls, v):
        return [a.strip()[:300] for a in (v or []) if a and str(a).strip()]


def validate_ig_rule(trigger: str, trigger_config: dict, action_config: dict) -> tuple[dict, dict]:
    """Validated + normalised copies of both configs for an ig_* rule. Raises pydantic.ValidationError."""
    t = IgTriggerConfig(**(trigger_config or {}))
    if (
        trigger in ("ig_comment_received", "ig_live_comment_received", "ig_dm_received", "ig_story_reply_received")
        and not t.reply_all
        and not t.keywords
    ):
        raise ValueError("Add at least one keyword, or choose 'any comment'.")
    a = IgActionConfig(**(action_config or {}))
    return t.model_dump(exclude_none=True), a.model_dump(exclude_none=True)
