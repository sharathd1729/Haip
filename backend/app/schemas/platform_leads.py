"""Public lead intake for HAIP's own website (book-demo, contact, property assessment).

Every field is bounded: these bodies come from anonymous visitors. Unknown keys (a ``tenant_id`` for example) are
ignored, never honoured: where a lead goes is decided by server config (``PLATFORM_LEADS_TENANT_SLUG``) only.
"""
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.schemas.assessment import AssessmentInput

LeadKind = Literal["demo", "contact", "assessment"]


class LeadDetails(BaseModel):
    """Small form extras shown to the sales team. Free text, so each one is short."""
    model_config = ConfigDict(extra="ignore")

    segment: Optional[str] = Field(None, max_length=60)      # demo: what they operate
    properties: Optional[str] = Field(None, max_length=20)   # demo: how many properties
    source: Optional[str] = Field(None, max_length=120)      # how they heard about HAIP
    topic: Optional[str] = Field(None, max_length=40)        # contact: sales | support | ...


class PlatformLeadSubmit(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    kind: LeadKind
    # Generated once per form fill by the browser and re-sent on retry: the same id never makes a second lead.
    submission_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=120)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(None, max_length=30)
    company: Optional[str] = Field(None, max_length=160)
    message: Optional[str] = Field(None, max_length=2000)
    details: LeadDetails = Field(default_factory=LeadDetails)
    # DPDP: the visitor ticked the notice; the server stores which notice text (by version) they saw.
    consent: bool
    marketing_opt_in: bool = False
    notice_version: str = Field("web-v1", max_length=20)
    # Honeypot: a field people never see. A filled one is stored as spam and never becomes a lead.
    website: Optional[str] = Field(None, max_length=300)
    # kind=assessment only: the answers. The server recomputes the result itself (never trusts one sent by the page).
    assessment: Optional[AssessmentInput] = None

    @model_validator(mode="after")
    def _rules_per_kind(self):
        if self.consent is not True:
            raise ValueError("Please accept the privacy notice so we can contact you.")
        if self.phone:
            from app.services.phone_identity import normalize
            e164 = normalize(self.phone, "IN")   # HAIP sells in India: a 10-digit number is read as +91
            if e164 is None:
                raise ValueError("Please enter a valid phone number.")
            self.phone = e164
        else:
            self.phone = None
        if self.kind == "demo" and not (self.email and self.phone and self.company):
            raise ValueError("A demo request needs an email, a phone number and a company name.")
        if self.kind == "contact" and not (self.email and self.message):
            raise ValueError("A message needs an email address and some text.")
        if self.kind == "assessment":
            if not self.phone:
                raise ValueError("The full report needs a phone number.")
            if self.assessment is None:
                raise ValueError("The assessment answers are missing.")
        elif self.assessment is not None:
            raise ValueError("Only an assessment lead carries assessment answers.")
        return self


class PlatformLeadAccepted(BaseModel):
    id: str
    kind: LeadKind
    status: Literal["received"] = "received"
    duplicate: bool = False
    # kind=assessment only: the full report and the token that opens it again (JSON + PDF).
    report: Optional[dict] = None
    report_token: Optional[str] = None


class PlatformLeadRow(BaseModel):
    """One row of the owner-only list (HAIP's own sales workspace)."""
    id: str
    kind: str
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    message: Optional[str] = None
    details: dict = {}
    is_spam: bool
    routing_status: str
    workspace_inquiry_id: Optional[str] = None
    assessment_summary: Optional[dict] = None
    marketing_opt_in: bool
    created_at: str
