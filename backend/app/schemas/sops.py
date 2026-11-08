"""Dynamic SOPs (docs/sops/DYNAMIC_SOPS_PLAN.md): request bodies, the platform-rules file format and the AI's text slots.

Platform rules live in app/data/sop_rules/<platform>.json and are edited by the HAIP team by pull request. Every entry
says when it was true and where it came from; an `unverified` entry is shown as "Not confirmed" and never stated as fact.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

PLATFORMS = (
    "google_business",
    "instagram",
    "whatsapp",
    "facebook_page",
    "airbnb",
    "booking",
    "makemytrip",
    "agoda",
    "tripadvisor",
)
PLATFORM = Literal[
    "google_business",
    "instagram",
    "whatsapp",
    "facebook_page",
    "airbnb",
    "booking",
    "makemytrip",
    "agoda",
    "tripadvisor",
]
RULE_KINDS = ("category", "text_limit", "photo_spec", "advice", "programme")
# business_kind() values (website_seo.KINDS): the one segment rule
KIND = Literal[
    "boutique_hotel", "resort", "service_apartments", "homestay", "villa", "farmhouse", "caravan", "travel_agency"
]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RuleEntry(_Strict):
    key: str = Field(min_length=3, max_length=80, pattern=r"^[a-z0-9_.]+$")
    platform: PLATFORM
    kind: Literal["category", "text_limit", "photo_spec", "advice", "programme"]
    value: str | int | list[str]
    ranks: dict[KIND, int] = Field(default_factory=dict)  # category: which kinds it fits, 1 = best
    status: Literal["verified", "unverified", "haip_advice"]
    as_of: date
    source_url: HttpUrl | None = None
    source_note: str = Field(min_length=3, max_length=300)

    @model_validator(mode="after")
    def _sourced(self):
        if self.status == "verified" and self.source_url is None:
            raise ValueError(f"{self.key}: a verified rule needs a source_url")
        return self


class StartIn(_Strict):
    template_key: str = Field(min_length=1, max_length=60)
    property_id: str | None = Field(default=None, max_length=64)
    assignee_id: str | None = Field(default=None, max_length=64)


class ExtraStep(_Strict):
    key: str = Field(min_length=1, max_length=40, pattern=r"^custom_[a-z0-9_]+$")
    title: str = Field(min_length=1, max_length=120)
    how: str = Field(default="", max_length=1000)


class PatchIn(_Strict):
    assignee_id: str | None = Field(default=None, max_length=64)
    status: Literal["active", "paused", "archived"] | None = None
    hidden_steps: list[str] | None = Field(default=None, max_length=40)
    extra_steps: list[ExtraStep] | None = Field(default=None, max_length=20)


class EvidenceLinkIn(_Strict):
    url: HttpUrl

    @model_validator(mode="after")
    def _https(self):
        if self.url.scheme != "https":
            raise ValueError("The link must start with https://")
        return self


class QA(_Strict):
    q: str = Field(min_length=3, max_length=200)
    a: str = Field(min_length=3, max_length=600)


class SopText(_Strict):
    """What the model may write (prompt key sop_generate). Every field optional; code checks lengths against the rules."""

    description: str | None = Field(default=None, max_length=2000)
    short_bio: str | None = Field(default=None, max_length=300)
    wa_about: str | None = Field(default=None, max_length=300)
    offer_text: str | None = Field(default=None, max_length=200)  # an OTA promotion's name/line: never a figure
    qa: list[QA] = Field(default_factory=list, max_length=8)
