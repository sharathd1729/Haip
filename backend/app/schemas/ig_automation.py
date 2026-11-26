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
    "ig_global",  # one keyword automation on several places at once (trigger_config.surfaces)
    "ig_dm_default",  # a DM nothing else answers, when the AI would not reply either
)


class IgTriggerConfig(BaseModel):
    keywords: list[str] = Field(default_factory=list, max_length=50)
    exclude_keywords: list[str] = Field(default_factory=list, max_length=50)
    reply_all: bool = False  # any comment / story reply / mention, no keyword needed
    mention_only: bool = False  # comments only: the comment must tag someone (@name), e.g. "tag a friend" posts
    scope: Literal["post", "any", "next_post", "caption_code"] = "any"
    caption_code: str | None = Field(default=None, max_length=30)  # scope caption_code: posts whose caption has it
    surfaces: list[Literal["comment", "live", "story", "dm", "ad"]] = Field(default_factory=list)  # ig_global only
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
        if self.scope == "caption_code":
            code = (self.caption_code or "").strip().lstrip("#")
            if not (3 <= len(code) <= 30 and code.replace("_", "").isalnum()):
                raise ValueError("The caption code needs 3 to 30 letters or numbers, e.g. JADE1.")
            self.caption_code = code.upper()
            return self
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
            if not self.questions:
                raise ValueError("Add at least one question.")
            # The WhatsApp number is what makes the person a lead; a form without it (e.g. email only) collects details
            # but leaves them a contact.
            if len([q for q in self.questions if q.key == "phone"]) > 1:
                raise ValueError("Ask for the WhatsApp number only once.")
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


class IgAttachment(BaseModel):
    """A photo or video sent after the final message (uploaded through POST /automations/ig-media; Instagram fetches it
    from a short-lived link made at send time). Instagram: png/jpeg up to 8 MB, mp4/mov up to 25 MB."""

    kind: Literal["image", "video"]
    key: str = Field(min_length=1, max_length=300)
    filename: str = Field(default="", max_length=120)


class IgSharePost(BaseModel):
    """Send one of our own posts or reels in the DM after the final message (Instagram only shares the account's own posts).
    No media_id = the post they commented on."""

    enabled: bool = False
    media_id: str | None = Field(default=None, max_length=64)
    media_thumb: str | None = Field(default=None, max_length=2000)  # display only


DELAY_MAX_SECONDS = 3600


class IgQuickReply(BaseModel):
    """A tap button on the final message and the text sent back when it is tapped."""

    title: str = Field(min_length=1, max_length=20)
    reply: str = Field(min_length=1, max_length=640)


class IgCard(BaseModel):
    """One swipeable card (Instagram generic template): image, headline, text, up to 3 link buttons."""

    image_key: str | None = Field(default=None, max_length=300)
    title: str = Field(min_length=1, max_length=80)
    subtitle: str = Field(default="", max_length=80)
    buttons: list[IgButton] = Field(default_factory=list, max_length=3)


class IgActionConfig(BaseModel):
    message: str = Field(default="", max_length=900)
    send_dm: bool = True  # False = comments only: post the public reply and send no DM
    button: IgButton | None = None
    opener: str = Field(default="Hi {first_name}! Tap below and I'll send it over 👇", max_length=640)
    opener_button: str = Field(default="Send it", max_length=20)
    opener_always: bool = False  # start with the opener + tap even when nothing else needs it ("engagement starter")
    public_ack_pool: list[str] = Field(default_factory=list, max_length=10)
    follow_gate: IgFollowGate = Field(default_factory=IgFollowGate)
    once_per_person: bool = True
    once_per_post: bool = False  # with once_per_person: once per person per post, not once per automation
    delay_seconds: int = Field(default=0, ge=0, le=DELAY_MAX_SECONDS)  # wait before replying
    attachment: IgAttachment | None = None
    share_post: IgSharePost = Field(default_factory=IgSharePost)
    message_variants: list[str] = Field(default_factory=list, max_length=5)  # one of message + these, at random
    quick_replies: list[IgQuickReply] = Field(default_factory=list, max_length=5)
    cards: list[IgCard] = Field(default_factory=list, max_length=10)

    @field_validator("message_variants", mode="before")
    @classmethod
    def _variants(cls, v):
        return [str(x).strip()[:900] for x in (v or []) if str(x or "").strip()]
    follow_up: str = Field(default="", max_length=500)  # DM-keyword rules only (endpoints/automations.py)
    follow_up_after_hours: int | None = Field(default=None, ge=1, le=23)
    form: IgForm = Field(default_factory=IgForm)
    sequence: list[IgSequenceStep] = Field(default_factory=list, max_length=3)
    suggest_more: IgSuggestMore = Field(default_factory=IgSuggestMore)

    @model_validator(mode="after")
    def _message_when_dm(self):
        if self.send_dm and not self.message.strip():
            raise ValueError("Write the message people get in their DMs.")
        return self

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


COMMENT_TRIGGERS = ("ig_comment_received", "ig_live_comment_received")


def validate_ig_rule(
    trigger: str, trigger_config: dict, action_config: dict, tenant_id: str | None = None
) -> tuple[dict, dict]:
    """Validated + normalised copies of both configs for an ig_* rule. Raises pydantic.ValidationError / ValueError."""
    t = IgTriggerConfig(**(trigger_config or {}))
    if trigger not in COMMENT_TRIGGERS:
        t.mention_only = False
    if (
        trigger in ("ig_comment_received", "ig_live_comment_received", "ig_dm_received", "ig_story_reply_received")
        and not t.reply_all
        and not t.mention_only
        and not t.keywords
    ):
        raise ValueError("Add at least one keyword, or choose 'any comment'.")
    a = IgActionConfig(**(action_config or {}))
    if not a.send_dm:
        if trigger not in COMMENT_TRIGGERS:
            raise ValueError("'Public reply only' works for comments; other automations always answer in the DM.")
        if not a.public_ack_pool:
            raise ValueError("Add at least one public reply: with 'Public reply only' it is the whole answer.")
    if a.attachment and tenant_id and not a.attachment.key.startswith(f"{tenant_id}/ig_automations/"):
        raise ValueError("Upload the photo or video again.")
    keys = [c.image_key for c in a.cards if c.image_key]
    if tenant_id and any(not k.startswith(f"{tenant_id}/ig_automations/") for k in keys):
        raise ValueError("Upload the card images again.")
    if trigger == "ig_global" and not t.surfaces:
        raise ValueError("Pick where this automation works: comments, Live, stories, DMs or ads.")
    if trigger == "ig_global" and not t.reply_all and not t.keywords:
        raise ValueError("Add at least one keyword, or choose 'any message'.")
    if a.share_post.enabled and not a.share_post.media_id and trigger not in COMMENT_TRIGGERS:
        raise ValueError("Pick the post or reel to share.")
    return t.model_dump(exclude_none=True), a.model_dump(exclude_none=True)


class IgWelcomeQuestion(BaseModel):
    """A ready-made question Instagram shows before someone's first message (an "ice breaker")."""

    question: str = Field(min_length=1, max_length=80)
    rule_id: str | None = Field(default=None, max_length=36)  # run this automation; empty = a normal message


class IgMenuItem(BaseModel):
    """One item of the menu Instagram shows in every chat (the "persistent menu")."""

    title: str = Field(min_length=1, max_length=30)
    kind: Literal["automation", "link", "message"] = "message"
    rule_id: str | None = Field(default=None, max_length=36)
    url: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _target(self):
        if self.kind == "automation" and not self.rule_id:
            raise ValueError(f"Pick the automation for “{self.title}”.")
        if self.kind == "link":
            p = urlparse((self.url or "").strip())
            if p.scheme != "https" or not p.netloc:
                raise ValueError(f"The link for “{self.title}” must start with https://")
            self.url = self.url.strip()
        return self


class IgWelcome(BaseModel):
    """Workspace-level: brand_config.instagram_welcome (services/ig_welcome.py)."""

    questions: list[IgWelcomeQuestion] = Field(default_factory=list, max_length=4)
    menu: list[IgMenuItem] = Field(default_factory=list, max_length=5)
