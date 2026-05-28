"""
Server-Sent Events endpoint.
Subscribes to Redis pub/sub channel `sse:<tenant_id>` and streams events to the browser.
"""
import asyncio
import json
import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from app.core.config import settings
from app.api.v1.deps import get_current_user_flexible
from app.models.user import User
import structlog

log = structlog.get_logger()
router = APIRouter(prefix="/sse", tags=["sse"])


@router.get("/inbox")
async def inbox_stream(
    request: Request,
    current_user: User = Depends(get_current_user_flexible),
):
    tenant_id = current_user.tenant_id

    async def event_generator():
        # Send connected event immediately
        yield f"data: {json.dumps({'event': 'connected', 'tenant_id': tenant_id})}\n\n"

        # Try to connect to Redis for real-time events; if unavailable, fall back to heartbeat
        try:
            r = aioredis.from_url(settings.REDIS_URL, socket_connect_timeout=5)
            pubsub = r.pubsub()
            await pubsub.subscribe(f"sse:{tenant_id}")
            try:
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
        except Exception as e:
            # Redis unavailable — stream heartbeats so the browser connection stays alive
            log.warning("sse_redis_unavailable", error=str(e))
            try:
                while True:
                    await asyncio.sleep(30)
                    yield f"data: {json.dumps({'event': 'heartbeat'})}\n\n"
            except asyncio.CancelledError:
                pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
