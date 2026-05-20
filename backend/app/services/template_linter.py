"""
T4 — WhatsApp template pre-submit linter.

Checks the most common reasons Meta rejects templates before submission.
Each rule returns a LintFinding with level "error" or "warn".
"""
from dataclasses import dataclass
import re


@dataclass
class LintFinding:
    level: str        # "error" | "warn"
    message: str
    field_path: str   # e.g. "body", "header", "components[0].text"


# URL shorteners that Meta flags
_URL_SHORTENERS = {
    "bit.ly", "tinyurl.com", "t.co", "goo.gl", "ow.ly",
    "buff.ly", "rebrand.ly", "short.io", "trib.al",
}

# Promotional keywords that don't belong in UTILITY templates
_PROMO_KEYWORDS = re.compile(
    r"\b(buy|offer|discount|sale|%\s*off|deal|free\s*gift|cashback|coupon|promo)\b",
    re.IGNORECASE,
)

# OTP / auth patterns for authentication category
_OTP_PATTERNS = re.compile(
    r"\b(otp|passcode|verification code|one.time|2fa|two.factor|auth)\b",
    re.IGNORECASE,
)

# Variable placeholder
_VAR_PATTERN = re.compile(r"\{\{(\d+)\}\}")


def lint_template(
    body: str,
    header: str | None = None,
    category: str = "UTILITY",
    sample_values: dict | None = None,
) -> list[LintFinding]:
    """
    Run all lint rules and return a list of findings (empty = clean).

    Args:
        body:          Template body text.
        header:        Optional header text.
        category:      UTILITY | MARKETING | AUTHENTICATION
        sample_values: Dict mapping variable index (str) to sample value,
                       e.g. {"1": "Ratha Signature", "2": "June 15"}
    """
    findings: list[LintFinding] = []
    sample_values = sample_values or {}

    # ── Rule 1: URL shorteners ────────────────────────────────────────────────
    full_text = f"{header or ''} {body}"
    for shortener in _URL_SHORTENERS:
        if shortener in full_text.lower():
            findings.append(LintFinding(
                level="error",
                message=f"URL shortener '{shortener}' detected. Meta rejects templates containing shortened links.",
                field_path="body",
            ))

    # ── Rule 2: More than 4 variables ────────────────────────────────────────
    vars_in_body = _VAR_PATTERN.findall(body)
    if len(vars_in_body) > 4:
        findings.append(LintFinding(
            level="warn",
            message=f"Template has {len(vars_in_body)} variables. Meta recommends ≤ 4 to reduce rejection risk.",
            field_path="body",
        ))

    # ── Rule 3: Variables without sample values ───────────────────────────────
    for var_idx in vars_in_body:
        if var_idx not in sample_values:
            findings.append(LintFinding(
                level="warn",
                message=f"Variable {{{{{{var_idx}}}}}}} has no sample value. Meta requires samples for all variables.",
                field_path=f"body.variable_{var_idx}",
            ))

    # ── Rule 4: Promotional language in UTILITY category ────────────────────
    if category.upper() == "UTILITY":
        promo_match = _PROMO_KEYWORDS.search(body)
        if promo_match:
            findings.append(LintFinding(
                level="warn",
                message=f"Promotional keyword '{promo_match.group()}' found in a UTILITY template. "
                        "Switch to MARKETING category or remove promotional language.",
                field_path="body",
            ))

    # ── Rule 5: Header with variable + URL ───────────────────────────────────
    if header:
        header_has_var = bool(_VAR_PATTERN.search(header))
        header_has_url = bool(re.search(r"https?://", header))
        if header_has_var and header_has_url:
            findings.append(LintFinding(
                level="error",
                message="Header cannot contain both a variable and a URL. Meta rejects this combination.",
                field_path="header",
            ))

    # ── Rule 6: Body too long ────────────────────────────────────────────────
    if len(body) > 1024:
        findings.append(LintFinding(
            level="warn",
            message=f"Body is {len(body)} characters. Maximum recommended is 1024 characters.",
            field_path="body",
        ))

    # ── Rule 7: Authentication category mismatch ─────────────────────────────
    if category.upper() == "AUTHENTICATION":
        if not _OTP_PATTERNS.search(body):
            findings.append(LintFinding(
                level="warn",
                message="AUTHENTICATION category but no OTP/passcode pattern found in body. "
                        "Meta expects authentication templates to clearly reference a code.",
                field_path="body",
            ))

    return findings


def lint_to_dict(findings: list[LintFinding]) -> list[dict]:
    return [{"level": f.level, "message": f.message, "field_path": f.field_path} for f in findings]
