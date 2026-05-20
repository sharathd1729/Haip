"""
D13 — PII redaction for application logs and Sentry.

Apply at log-formatter level so every log call is covered automatically.
Does NOT modify the original data — only masks log output strings.

Patterns:
- Indian mobile: +91XXXXXXXXXX or 10-digit → +91XXXX******1234 shape
- International phone: generic E.164 + local patterns → mask middle
- Email: a***@example.com
- Aadhaar: 4-4-4 digit groups (separated by space or hyphen) → XXXX XXXX XXXX
- PAN: [A-Z]{5}[0-9]{4}[A-Z] → fully mask
- Credit card: 16-digit groups → mask middle 8
"""
import re

# ── Compiled patterns ─────────────────────────────────────────────────────────

# Indian mobile: +91 followed by 10 digits, or bare 10-digit starting 6-9
_INDIAN_MOBILE_RE = re.compile(
    r'(?<!\d)(\+91[\s\-]?)?([6-9]\d{9})(?!\d)',
    re.ASCII,
)

# Generic E.164 international phone not caught above
_INTL_PHONE_RE = re.compile(
    r'(?<!\d)\+(?!91)\d{7,14}(?!\d)',
    re.ASCII,
)

# Email
_EMAIL_RE = re.compile(
    r'\b([a-zA-Z0-9][a-zA-Z0-9._%+\-]*)@([a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})\b',
)

# Aadhaar: XXXX XXXX XXXX or XXXX-XXXX-XXXX (12 digits in 3 groups of 4)
_AADHAAR_RE = re.compile(
    r'(?<!\d)\d{4}[\s\-]\d{4}[\s\-]\d{4}(?!\d)',
)

# PAN: AAAAA0000A (5 uppercase letters, 4 digits, 1 uppercase letter)
_PAN_RE = re.compile(
    r'\b[A-Z]{5}[0-9]{4}[A-Z]\b',
)

# Credit card: 16 digits optionally grouped by spaces/dashes
_CC_RE = re.compile(
    r'(?<!\d)\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}(?!\d)',
)


def _redact_phones(text: str) -> str:
    def _mask_indian(m: re.Match) -> str:
        prefix = m.group(1) or ""
        number = m.group(2)
        # Keep last 4 digits: +91XXXX******1234
        masked = "X" * 6 + number[-4:]
        return f"{prefix}{masked}"

    text = _INDIAN_MOBILE_RE.sub(_mask_indian, text)

    def _mask_intl(m: re.Match) -> str:
        raw = m.group(0)
        # Keep country code (+XX) and last 4 digits
        if len(raw) > 8:
            return raw[:3] + "X" * (len(raw) - 7) + raw[-4:]
        return "XXXXXXXX"

    text = _INTL_PHONE_RE.sub(_mask_intl, text)
    return text


def _redact_email(text: str) -> str:
    def _mask(m: re.Match) -> str:
        local = m.group(1)
        domain = m.group(2)
        masked_local = local[0] + "***" if len(local) > 1 else "***"
        return f"{masked_local}@{domain}"
    return _EMAIL_RE.sub(_mask, text)


def _redact_aadhaar(text: str) -> str:
    return _AADHAAR_RE.sub("XXXX XXXX XXXX", text)


def _redact_pan(text: str) -> str:
    return _PAN_RE.sub("[PAN REDACTED]", text)


def _redact_cc(text: str) -> str:
    def _mask(m: re.Match) -> str:
        raw = m.group(0)
        digits = re.sub(r'[\s\-]', '', raw)
        if len(digits) == 16:
            return digits[:4] + " **** **** " + digits[-4:]
        return "[CARD REDACTED]"
    return _CC_RE.sub(_mask, text)


def redact(text: str) -> str:
    """Run all PII redaction passes on a log string."""
    if not isinstance(text, str):
        return text
    text = _redact_aadhaar(text)   # do Aadhaar before phone (avoids partial overlap)
    text = _redact_cc(text)        # CC before phone
    text = _redact_pan(text)
    text = _redact_phones(text)
    text = _redact_email(text)
    return text


def redact_dict(data: dict) -> dict:
    """Recursively redact PII from a dict (for log event dicts)."""
    result = {}
    for k, v in data.items():
        if isinstance(v, str):
            result[k] = redact(v)
        elif isinstance(v, dict):
            result[k] = redact_dict(v)
        elif isinstance(v, list):
            result[k] = [redact(i) if isinstance(i, str) else i for i in v]
        else:
            result[k] = v
    return result


# ── Structlog processor ───────────────────────────────────────────────────────

def pii_redaction_processor(logger, method, event_dict: dict) -> dict:
    """
    Structlog processor — called for every log event.
    Redacts PII from the 'event' string and all string values.
    """
    if "event" in event_dict and isinstance(event_dict["event"], str):
        event_dict["event"] = redact(event_dict["event"])
    return redact_dict(event_dict)
