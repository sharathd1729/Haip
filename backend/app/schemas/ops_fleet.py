"""Ops phase 2, readiness and fleet (migration 180): request bodies and the single definitions of paper kinds, defect
severities and the guest form's ID types, consent text, nationalities and visa types."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# kind -> (plain label, critical for a vehicle: expired or expiring before the trip ends blocks dispatch)
PAPER_KINDS: dict[str, tuple[str, bool]] = {
    "insurance": ("Insurance", True),
    "permit": ("Permit", True),
    "fc": ("Fitness certificate (FC)", True),
    "puc": ("Pollution certificate (PUC)", True),
    "ais140": ("AIS-140 tracker certificate", True),
    "hmv_licence": ("HMV driving licence", True),
    "other": ("Other paper", False),
}
VEHICLE_PAPER_KINDS = ("insurance", "permit", "fc", "puc", "ais140", "other")
STAFF_PAPER_KINDS = ("hmv_licence", "other")

ID_TYPES = {
    "aadhaar": "Aadhaar",
    "passport": "Passport",
    "driving_licence": "Driving licence",
    "voter_id": "Voter ID",
    "other": "Other government ID",
}
# A wording change = a new version; the version and the exact text the guest saw are what they agreed to. v2 (Nov 2026):
# one text per file word (trip / stay) and the Form C use for guests who are not Indian citizens.
CONSENT_VERSION = "ops-guest-form-v2"
CONSENT_TEXTS = {
    "trip": (
        "I confirm these details are correct for everyone travelling, and I accept the booking terms. The details are kept "
        "private and used only to register this trip, for safety on the road and, for guests who are not Indian citizens, "
        "to file Form C with the Bureau of Immigration as Indian law requires."
    ),
    "stay": (
        "I confirm these details are correct for everyone staying, and I accept the booking terms. The details are kept "
        "private and used only to register this stay, for safety and, for guests who are not Indian citizens, to file "
        "Form C with the Bureau of Immigration as Indian law requires."
    ),
}
CONSENT_TEXT = CONSENT_TEXTS["trip"]

# Guests who are not Indian citizens (ops_guest_form + ops_form_c). Nationality = ISO 3166 alpha-2 code; screens name it.
COUNTRIES = frozenset(
    "AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR BS BT BV BW BY BZ CA CC "
    "CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR GA GB GD "
    "GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM JO JP KE KG KH "
    "KI KM KN KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW "
    "MX MY MZ NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY QA RE RO RS RU RW SA SB SC "
    "SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG UM US UY "
    "UZ VA VC VE VG VI VN VU WF WS YE YT ZA ZM ZW".split()
)
# Citizens of Nepal and Bhutan need no visa for India (and may travel without a passport): those fields are optional.
NO_VISA_NEEDED = frozenset({"NP", "BT"})
VISA_TYPES = {
    "tourist": "Tourist",
    "e_tourist": "e-Tourist visa",
    "business": "Business",
    "e_business": "e-Business visa",
    "employment": "Employment",
    "student": "Student",
    "medical": "Medical / e-Medical",
    "conference": "Conference / e-Conference",
    "transit": "Transit",
    "entry": "Entry (X)",
    "oci": "OCI card (no visa)",
    "other": "Other",
}
GUEST_DOC_KINDS = ("passport", "visa")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PaperIn(_Strict):
    property_id: str | None = None
    staff_id: str | None = None
    kind: Literal["insurance", "permit", "fc", "puc", "ais140", "hmv_licence", "other"]
    name: str | None = Field(default=None, max_length=120)  # empty = the kind's label
    number: str | None = Field(default=None, max_length=60)
    expires_on: date | None = None


class DefectIn(_Strict):
    property_id: str
    title: str = Field(min_length=1, max_length=200)
    detail: str | None = Field(default=None, max_length=2000)
    severity: Literal["critical", "normal"] = "normal"


class DefectCloseIn(_Strict):
    note: str | None = Field(default=None, max_length=1000)


class ServiceIn(_Strict):
    property_id: str
    name: str = Field(min_length=1, max_length=120)
    due_on: date | None = None
    due_km: int | None = Field(default=None, gt=0, lt=10_000_000)
    note: str | None = Field(default=None, max_length=500)


class ServiceDoneIn(_Strict):
    done_km: int | None = Field(default=None, gt=0, lt=10_000_000)
    note: str | None = Field(default=None, max_length=500)


class InventoryIn(_Strict):
    property_id: str
    name: str = Field(min_length=1, max_length=80)
    par: int = Field(ge=0, le=10_000)
    count: int | None = Field(default=None, ge=0, le=10_000)


class InventoryCountIn(_Strict):
    count: int | None = Field(default=None, ge=0, le=10_000)
    par: int | None = Field(default=None, ge=0, le=10_000)


class GuestEntryIn(_Strict):
    name: str = Field(default="", max_length=200)
    age: str = Field(default="", max_length=5)
    nationality: str = Field(default="IN", max_length=2)  # ISO alpha-2; "" = Indian (forms sent before v2)
    id_type: str = Field(default="", max_length=30)
    id_number: str = Field(default="", max_length=60)
    # Only read when nationality is not IN (dates as YYYY-MM-DD, checked in ops_guest_form.build so every problem is listed)
    passport_number: str = Field(default="", max_length=30)
    passport_expires_on: str = Field(default="", max_length=10)
    visa_type: str = Field(default="", max_length=20)
    visa_number: str = Field(default="", max_length=30)
    visa_expires_on: str = Field(default="", max_length=10)
    arrived_india_on: str = Field(default="", max_length=10)
    arrived_from: str = Field(default="", max_length=120)
    onward_to: str = Field(default="", max_length=120)
    passport_photo_id: str = Field(default="", max_length=40)
    visa_photo_id: str = Field(default="", max_length=40)


class GuestFormIn(_Strict):
    guests: list[GuestEntryIn] = Field(min_length=1, max_length=12)
    emergency_name: str = Field(default="", max_length=200)
    emergency_phone: str = Field(default="", max_length=40)
    food: str = Field(default="", max_length=1000)
    requests: str = Field(default="", max_length=2000)
    signed_name: str = Field(default="", max_length=200)
    agreed: bool = False
    consent_version: str = Field(default="", max_length=40)

    @field_validator("consent_version")
    @classmethod
    def _current(cls, v: str) -> str:
        if v and v != CONSENT_VERSION:
            raise ValueError("The form has changed. Please reload the page.")
        return v


class FormCSubmittedIn(_Strict):
    """The manager filed this guest's Form C on the Bureau of Immigration portal (HAIP never files it itself)."""

    note: str | None = Field(default=None, max_length=300)  # e.g. the portal's acknowledgement number
