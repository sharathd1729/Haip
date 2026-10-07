"""Razorpay client: payment links and webhook signature verification.

Each tenant uses their own Razorpay account (key id/secret stored encrypted on
their Integration row), so money goes straight to the client, never through HAIP.
Amounts cross the wire in paise.
"""
from __future__ import annotations

import hashlib
import hmac
from typing import Optional

import httpx

API_BASE = "https://api.razorpay.com/v1"
_TIMEOUT = 20


class RazorpayError(Exception):
    """Raised with a message that is safe to show to staff."""


def verify_signature(body: bytes, signature: Optional[str], secret: str) -> bool:
    """X-Razorpay-Signature is the hex HMAC-SHA256 of the raw request body."""
    if not signature or not secret:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _request(method: str, path: str, key_id: str, key_secret: str, json: Optional[dict] = None) -> dict:
    try:
        resp = httpx.request(method, f"{API_BASE}{path}", auth=(key_id, key_secret), json=json, timeout=_TIMEOUT)
    except httpx.HTTPError as exc:
        raise RazorpayError("Could not reach Razorpay. Try again in a moment.") from exc
    if resp.status_code == 401:
        raise RazorpayError("Razorpay rejected the API keys. Check the Key ID and Key Secret.")
    if resp.status_code >= 400:
        try:
            desc = resp.json().get("error", {}).get("description")
        except ValueError:
            desc = None
        raise RazorpayError(desc or f"Razorpay returned HTTP {resp.status_code}.")
    return resp.json()


def check_credentials(key_id: str, key_secret: str) -> None:
    """Cheap authenticated read; raises RazorpayError when the keys are wrong."""
    _request("GET", "/payment_links?count=1", key_id, key_secret)


def create_payment_link(
    key_id: str, key_secret: str, *, amount_inr: float, description: str, reference_id: str,
    customer_name: Optional[str], customer_phone: Optional[str], customer_email: Optional[str],
    expire_by: Optional[int], notes: dict,
) -> dict:
    customer = {k: v for k, v in {"name": customer_name, "contact": customer_phone, "email": customer_email}.items() if v}
    body = {
        "amount": int(round(amount_inr * 100)),
        "currency": "INR",
        "accept_partial": False,
        "description": description[:2000],
        "reference_id": reference_id[:40],
        "customer": customer,
        "notify": {"sms": False, "email": False},   # staff send it themselves (WhatsApp)
        "reminder_enable": False,
        "notes": notes,
    }
    if expire_by:
        body["expire_by"] = expire_by
    return _request("POST", "/payment_links", key_id, key_secret, json=body)


def cancel_payment_link(key_id: str, key_secret: str, link_id: str) -> None:
    _request("POST", f"/payment_links/{link_id}/cancel", key_id, key_secret)
