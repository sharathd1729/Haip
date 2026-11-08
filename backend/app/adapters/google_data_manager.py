"""Google Data Manager API: conversion uploads to Google Ads (website growth #5).

Docs read 8 Nov 2026 (developers.google.com/data-manager/api): POST https://datamanager.googleapis.com/v1/events:ingest,
OAuth scope https://www.googleapis.com/auth/datamanager (offline access = refresh token). Body: destinations
[{operatingAccount {accountType GOOGLE_ADS, accountId = 10-digit customer id without hyphens}, loginAccount (the account
the Google user signs in to), productDestinationId = the conversion action id}], encoding HEX, consent
{adUserData, adPersonalization: CONSENT_GRANTED|CONSENT_DENIED}, events (<= 2,000) [{transactionId, eventTimestamp RFC 3339,
conversionValue, currency, eventSource WEB|APP|IN_STORE|PHONE|MESSAGE|OTHER, adIdentifiers {gclid|gbraid|wbraid},
userData {userIdentifiers [{emailAddress}|{phoneNumber}]} (SHA-256, hex)}]. The conversion action must be of type
"Import from clicks" (UPLOAD_CLICKS). Google moved click-conversion uploads here from the Google Ads API (15 June 2026).
Every host is fixed (nothing a person types reaches a URL), no redirects; 429 / 5xx / timeouts are transient.
"""

from urllib.parse import urlencode

import httpx

from app.adapters import google_business as gbp

INGEST = "https://datamanager.googleapis.com/v1/events:ingest"
SCOPE = "https://www.googleapis.com/auth/datamanager"
TIMEOUT = 30


class DataManagerError(Exception):
    def __init__(self, message: str, *, transient: bool, auth: bool = False):
        super().__init__(message)
        self.transient, self.auth = transient, auth


def authorize_url(client_id: str, redirect_uri: str, state: str) -> str:
    return (
        gbp.AUTH
        + "?"
        + urlencode(
            {
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": SCOPE,
                "access_type": "offline",
                "prompt": "consent",
                "state": state,
            }
        )
    )


# The token exchange and refresh are the same Google OAuth calls Business Profile uses (scope-agnostic).
exchange_code = gbp.exchange_code
refresh = gbp.refresh


def ingest(access_token: str, body: dict, client: httpx.Client | None = None) -> dict:
    """One events:ingest call. The error text carries Google's status only (never the body we sent)."""
    c = client or httpx.Client(timeout=TIMEOUT, follow_redirects=False)
    try:
        r = c.post(INGEST, json=body, headers={"Authorization": f"Bearer {access_token}"})
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        raise DataManagerError(f"Google did not answer ({type(exc).__name__})", transient=True) from exc
    finally:
        if client is None:
            c.close()
    if r.status_code in (401, 403):
        raise DataManagerError(f"Google refused HAIP's access ({r.status_code})", transient=False, auth=True)
    if r.status_code >= 300:
        status = ""
        try:
            status = (r.json().get("error") or {}).get("status") or ""
        except ValueError:
            pass
        raise DataManagerError(
            f"Google answered {r.status_code} {status}".strip(), transient=r.status_code == 429 or r.status_code >= 500
        )
    return r.json() if r.content else {}
