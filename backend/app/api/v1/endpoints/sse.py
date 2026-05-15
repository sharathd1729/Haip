"""
Server-Sent Events endpoint.
Subscribes to Redis pub/sub channel `sse:<tenant_id>` and streams events to the browser.
"""
import asyncio
import json
import redis.asyncio as aioredis
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from app.core.config import settings
from app.api.v1.deps import get_current_user
from app.models.user import User
import structlog

log = structlog.get_logger()
router = APIRouter(prefix="/sse", tags=["sse"])


@router.get("/inbox")
async def inbox_stream(current_user: User = Depends(get_current_user)):
    tenant_id = current_user.tenant_id

    async def event_generator():
        r = aioredis.from_url(settings.REDIS_URL)
        pubsub = r.pubsub()
        await pubsub.subscribe(f"sse:{tenant_id}")
        try:
            yield f"data: {json.dumps({'event': 'connected', 'tenant_id': tenant_id})}\n\n"
            async for raw in pubsub.listen():
                if raw["type"] == "message":
                    data = raw["data"]
                    if isinstance(data, bytes):
                        data = data.decode()
                    yield f"data: {data}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            await pubsub.unsubscribe(f"sse:{tenant_id}")
            await r.aclose()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
