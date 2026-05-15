"""
Hostaway channel manager adapter.
OAuth2 client credentials grant + hourly polling for bookings, listings, guests.
"""
import httpx
from typing import Optional
from app.core.config import settings
import structlog

log = structlog.get_logger()

HOSTAWAY_BASE = "https://api.hostaway.com/v1"


class HostawayAdapter:
    def __init__(self):
        self._token: Optional[str] = None

    async def _get_token(self) -> str:
        if self._token:
            return self._token
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{HOSTAWAY_BASE}/accessTokens",
                data={
                    "grant_type": "client_credentials",
                    "client_id": settings.HOSTAWAY_ACCOUNT_ID,
                    "client_secret": settings.HOSTAWAY_API_KEY,
                    "scope": "general",
                },
            )
            resp.raise_for_status()
            self._token = resp.json()["access_token"]
        return self._token

    async def get_listings(self) -> list:
        return await self._get("/listings")

    async def get_reservations(self, limit: int = 100, offset: int = 0) -> list:
        return await self._get(f"/reservations?limit={limit}&offset={offset}")

    async def get_guest(self, guest_id: str) -> dict:
        return await self._get(f"/guests/{guest_id}")

    async def _get(self, path: str) -> list:
        token = await self._get_token()
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"{HOSTAWAY_BASE}{path}", headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return data.get("result", data)
