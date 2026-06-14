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


@router.get("/workspace/stream")
async def workspace_stream(
    request: Request,
    current_user: User = Depends(get_current_user_flexible),
):
    """
    Workspace-scoped SSE channel per Scale + Migrate architecture.
    Events: metric_update | module_changed | goal_alert | insight_new
    Published via cache.publish_workspace_event(workspace_id, event_type, payload).
    No polling — pure Redis pub/sub.
    """
    workspace_id = current_user.tenant_id

    async def generator():
        yield f"data: {json.dumps({'event': 'connected', 'workspace_id': workspace_id})}\n\n"

        try:
            r = aioredis.from_url(settings.REDIS_URL, socket_connect_timeout=5)
            pubsub = r.pubsub()
            channel = f"ws_events:{workspace_id}"
            await pubsub.subscribe(channel)
            log.info("workspace_sse_connected", workspace_id=workspace_id)
            try:
                async for raw in pubsub.listen():
                    if await request.is_disconnected():
                        break
                    if raw["type"] == "message":
                        data = raw["data"]
                        if isinstance(data, bytes):
                            data = data.decode()
                        yield f"data: {data}\n\n"
            except asyncio.CancelledError:
                pass
            finally:
                await pubsub.unsubscribe(channel)
                await r.aclose()
                log.info("workspace_sse_disconnected", workspace_id=workspace_id)
        except Exception as exc:
            log.warning("workspace_sse_redis_unavailable", error=str(exc))
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    await asyncio.sleep(30)
                    yield f"data: {json.dumps({'event': 'heartbeat', 'workspace_id': workspace_id})}\n\n"
            except asyncio.CancelledError:
                pass

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
