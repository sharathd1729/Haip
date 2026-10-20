"""Invoice details (seller profile) and invoice API shapes.

The seller profile lives in ``tenants.brand_config["invoice_profile"]``; booking payment automation switches live in
``brand_config["payments"]``. Both are validated here so the settings page and the invoice code read one shape.
"""
from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

# GST state codes (first two digits of a GSTIN, and the "place of supply" code on an invoice).
GST_STATES: dict[str, str] = {
    "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh", "05": "Uttarakhand",
    "06": "Haryana", "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh", "10": "Bihar", "11": "Sikkim",
    "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur", "15": "Mizoram", "16": "Tripura", "17": "Meghalaya",
    "18": "Assam", "19": "West Bengal", "20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh", "23": "Madhya Pradesh",
    "24": "Gujarat", "26": "Dadra and Nagar Haveli and Daman and Diu", "27": "Maharashtra", "29": "Karnataka",
    "30": "Goa", "31": "Lakshadweep", "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry",
    "35": "Andaman and Nicobar Islands", "36": "Telangana", "37": "Andhra Pradesh", "38": "Ladakh",
    "97": "Other Territory",
}

_GSTIN_RE = re.compile(r"^(\d{2})([A-Z]{5}\d{4}[A-Z])([1-9A-Z])Z([0-9A-Z])$")
_GSTIN_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_PREFIX_RE = re.compile(r"^[A-Z0-9][A-Z0-9-]{0,9}$")
_SAC_RE = re.compile(r"^\d{4,8}$")


def gstin_check_char(first14: str) -> str:
    """The GSTIN check character (mod-36 weighted sum over the first 14 characters)."""
    total = 0
    for i, ch in enumerate(first14):
        product = _GSTIN_CHARS.index(ch) * (2 if i % 2 else 1)
        total += product // 36 + product % 36
    return _GSTIN_CHARS[(36 - total % 36) % 36]


def gstin_problem(value: str) -> Optional[str]:
    """Why a GSTIN is not valid, in plain words, or None when it is."""
    v = (value or "").strip().upper()
    if len(v) != 15:
        return "A GSTIN has exactly 15 characters."
    m = _GSTIN_RE.match(v)
    if not m:
        return "That is not the GSTIN format (2-digit state code, 10-character PAN, entity number, Z, check character)."
    if m.group(1) not in GST_STATES:
        return f"{m.group(1)} is not a GST state code."
    if gstin_check_char(v[:14]) != v[14]:
        return "The last character of this GSTIN does not match the rest. Check it for a typing mistake."
    return None


class InvoiceProfile(BaseModel):
    """What the business prints on its invoices. Everything is optional so a half-filled profile can be saved;
    ``missing_for_invoice()`` says what an invoice still needs."""
    legal_name: Optional[str] = Field(None, max_length=200)
    gstin: Optional[str] = Field(None, max_length=15)
    address: Optional[str] = Field(None, max_length=500)
    state_code: Optional[str] = Field(None, max_length=2)       # seller state = default place of supply
    sac_code: Optional[str] = Field(None, max_length=8)
    gst_rate: float = Field(12.0, ge=0, le=28)                  # percent; booking amounts include it
    invoice_prefix: str = Field("INV", max_length=10)
    receipt_prefix: str = Field("RCPT", max_length=10)
    logo_key: Optional[str] = Field(None, max_length=300)       # uploaded via POST /settings/invoice-profile/logo
    use_branding_logo: bool = True                              # fall back to Branding's logo when no logo_key

    @field_validator("legal_name", "address", "gstin", "sac_code", "state_code", mode="before")
    @classmethod
    def _strip(cls, v):
        if v is None:
            return None
        v = str(v).strip()
        return v or None

    @field_validator("gstin")
    @classmethod
    def _gstin(cls, v):
        if v is None:
            return None
        v = v.upper()
        problem = gstin_problem(v)
        if problem:
            raise ValueError(problem)
        return v

    @field_validator("state_code")
    @classmethod
    def _state(cls, v):
        if v is None:
            return None
        v = v.zfill(2)
        if v not in GST_STATES:
            raise ValueError("Pick a state from the list.")
        return v

    @field_validator("sac_code")
    @classmethod
    def _sac(cls, v):
        if v is not None and not _SAC_RE.match(v):
            raise ValueError("A SAC code is 4 to 8 digits, e.g. 9964.")
        return v

    @field_validator("invoice_prefix", "receipt_prefix")
    @classmethod
    def _prefix(cls, v):
        v = (v or "").strip().upper()
        if not _PREFIX_RE.match(v):
            raise ValueError("Use 1 to 10 letters, digits or dashes, e.g. INV or RATHA-INV.")
        return v

    @model_validator(mode="after")
    def _gstin_matches_state(self):
        if self.gstin and self.state_code and self.gstin[:2] != self.state_code:
            raise ValueError(f"This GSTIN is registered in {GST_STATES.get(self.gstin[:2], self.gstin[:2])}, "
                             f"but the state chosen is {GST_STATES[self.state_code]}.")
        if self.gstin and not self.state_code:
            self.state_code = self.gstin[:2]
        if self.invoice_prefix == self.receipt_prefix:
            raise ValueError("Invoices and receipts need different prefixes so their numbers never clash.")
        return self

    def missing_for_invoice(self) -> list[str]:
        out = []
        if not self.legal_name:
            out.append("legal name")
        if not self.address:
            out.append("address")
        if not self.state_code:
            out.append("state")
        return out


class PaymentAutomation(BaseModel):
    """``brand_config["payments"]``: switches for what HAIP does around booking payments."""
    auto_balance_reminder: bool = False     # daily: balance due in 3 days -> link + ratha_balance_due_v1, once per instalment


class InvoiceSettingsIn(BaseModel):
    profile: InvoiceProfile
    payments: Optional[PaymentAutomation] = None


class ReissueRequest(BaseModel):
    """Issue a fresh invoice for the booking as it stands now; the current one (if any) becomes superseded."""
    place_of_supply: Optional[str] = Field(None, max_length=2)     # GST state code of the guest; default: seller state
    buyer_gstin: Optional[str] = Field(None, max_length=15)
    reason: Optional[str] = Field(None, max_length=300)

    @field_validator("place_of_supply")
    @classmethod
    def _pos(cls, v):
        if not v:
            return None
        v = v.strip().zfill(2)
        if v not in GST_STATES:
            raise ValueError("Pick a state from the list.")
        return v

    @field_validator("buyer_gstin")
    @classmethod
    def _buyer(cls, v):
        if not v or not v.strip():
            return None
        v = v.strip().upper()
        problem = gstin_problem(v)
        if problem:
            raise ValueError(problem)
        return v
