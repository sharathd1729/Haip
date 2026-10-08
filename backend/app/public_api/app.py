"""HAIP public API: a separate FastAPI app mounted at /api/public/v1.

Being its own app gives it its own OpenAPI file and docs pages that list only the public
endpoints (never the internal ones), and its own error format.
"""
from __future__ import annotations

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.public_api import routes_bookings, routes_messaging
from app.public_api import schemas as sc
from app.public_api.deps import ApiError

log = structlog.get_logger()

DESCRIPTION = """
Connect your own systems to HAIP: read your bookings, and send WhatsApp and Instagram messages from your own software.

## Getting started

1. In HAIP open **Settings > Developers** and create an API key. Give it only the scopes you need. The key is shown **once**, so store it securely.
2. Send it on every request:

```
Authorization: Bearer haip_live_xxxxxxxxxxxxxxxx
```

3. Call the API. Base URL: `https://api.genhaip.com/api/public/v1`

```bash
curl https://api.genhaip.com/api/public/v1/bookings?status=confirmed \\
  -H "Authorization: Bearer $HAIP_API_KEY"
```

An API key belongs to one HAIP account and can only see that account's data. Keep it on your server; never put it in a mobile app or web page.

## Scopes

| Scope | Allows |
|---|---|
| `properties:read` | List properties |
| `bookings:read` | Read bookings, including guest name, phone and email, add-ons, payments and service requests |
| `messages:read` | Read WhatsApp templates, find conversations, read messages and delivery status |
| `messages:send` | Send WhatsApp and Instagram messages |

A missing scope returns `403 insufficient_scope`.

## Errors

Every error has the same shape:

```json
{ "error": { "code": "template_not_found", "message": "No approved template named 'arrival_alert'." } }
```

Use `code` in your program and show `message` to people. Validation errors (`422 validation_error`) also carry a `details` list naming each field.

| Status | Meaning |
|---|---|
| 200 / 202 | Success. **202 means accepted and queued, not delivered.** |
| 401 | Missing, invalid, expired or revoked API key |
| 403 | The key lacks the scope this endpoint needs |
| 404 | Not found (or belongs to another account) |
| 422 | The request is invalid or can't be done (for example `session_window_closed`) |
| 429 | Too many requests. Wait for the `Retry-After` header (seconds) |
| 5xx | A problem on HAIP's side. Retry with the same `local_message_id` so nothing is sent twice |

## Rate limits

300 requests per minute per API key for reads, and 60 per minute per key for sending messages. Every 429 response includes `Retry-After`.

## Pagination

List endpoints take `page` and `per_page` (up to 100) and return `meta` with `total` and `total_pages`.

## Sending messages safely

Add your own `local_message_id` (or an `Idempotency-Key` header) to every send. If you send the same id again, HAIP returns the original message with `idempotent_replay: true` instead of sending a second one, so retrying after a timeout is safe.

**WhatsApp rules.** Free-text messages are only allowed within 24 hours of the guest's last message. For alerts and reminders to guests who haven't just written to you, use an **approved template** (they work at any time). Instagram allows only replies within 24 hours, and a guest must message you first.

## Keeping in sync

For bookings, store the time of your last successful sync and call `GET /bookings?updated_since=<that time>`. The filter also catches changes to add-ons, payments and requests. Webhooks (below) tell you the moment something changes, so use them to stay current and `updated_since` to catch up after downtime.

## Webhooks

Instead of polling, give HAIP a URL and it calls you when something happens. Create endpoints in **Settings > Developers** (HTTPS only). Each endpoint chooses its events and gets its own signing secret, shown once.

| Event | When |
|---|---|
| `booking.created` | A booking is created |
| `booking.updated` | Dates, guests, add-ons, payments, schedule, notes or requests change |
| `booking.cancelled` | A booking is cancelled |
| `payment.received` | A payment is recorded, including online payments |
| `message.received` | A guest sends a WhatsApp or Instagram message |
| `message.status` | An outbound message becomes sent, delivered, read or failed |

Every delivery is a `POST` with a JSON body `{ "id", "type", "created_at", "data" }`. The shape of `data` for each event is listed under **Webhooks** in the reference below.

**Respond quickly with any 2xx status** (within 10 seconds) and do your work afterwards. Anything else counts as a failure.

**Retries.** A failed delivery is retried up to 8 more times over about 22 hours (after 30 seconds, 2 minutes, 10 minutes, 30 minutes, 1 hour, 3 hours, 6 hours, 12 hours). An endpoint that fails 100 times in a row is switched off; fix it and enable it again in Settings. Events can arrive more than once and out of order: **use the event `id` to ignore repeats**, and `updated_at` on bookings to ignore stale ones.

**Verify every request.** HAIP signs the exact body it sends. Headers:

```
X-HAIP-Event: booking.updated
X-HAIP-Delivery: <delivery id>
X-HAIP-Timestamp: 1760000000
X-HAIP-Signature: v1=<hex>
```

`<hex>` is the HMAC-SHA256, keyed with your endpoint secret, of the string `"<timestamp>." + <raw request body>`. Reject requests whose timestamp is more than 5 minutes old, and compare signatures in constant time.

```python
import hmac, hashlib, time

def is_valid(secret: str, raw_body: bytes, timestamp: str, signature: str) -> bool:
    if abs(time.time() - int(timestamp)) > 300:
        return False
    expected = "v1=" + hmac.new(secret.encode(), timestamp.encode() + b"." + raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
```

```javascript
const crypto = require("crypto");

function isValid(secret, rawBody, timestamp, signature) {
  if (Math.abs(Date.now() / 1000 - Number(timestamp)) > 300) return false;
  const expected = "v1=" + crypto.createHmac("sha256", secret).update(`${timestamp}.`).update(rawBody).digest("hex");
  const a = Buffer.from(expected), b = Buffer.from(signature);
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}
```

Use **Send test event** in Settings to send a `ping` and see what your server answers.
"""

app = FastAPI(
    title="HAIP Public API",
    version="1.0.0",
    description=DESCRIPTION,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    responses={
        401: {"model": sc.ErrorResponse, "description": "Missing, invalid, expired or revoked API key"},
        403: {"model": sc.ErrorResponse, "description": "The key lacks the required scope"},
        422: {"model": sc.ErrorResponse, "description": "Invalid request"},
        429: {"model": sc.ErrorResponse, "description": "Rate limit exceeded; see the Retry-After header"},
    },
)

# Webhook events appear under "Webhooks" in the generated reference (OpenAPI 3.1).
@app.webhooks.post("booking-event", summary="booking.created / booking.updated / booking.cancelled")
def _booking_event(event: sc.BookingEvent):
    """Sent when a booking is created, changes, or is cancelled. `data` is the full booking, the same shape as `GET /bookings/{id}`."""


@app.webhooks.post("payment-received", summary="payment.received")
def _payment_event(event: sc.PaymentEvent):
    """Sent when a payment is recorded on a booking, by staff or online."""


@app.webhooks.post("message-received", summary="message.received")
def _message_received_event(event: sc.MessageReceivedEvent):
    """Sent when a guest writes to you on WhatsApp or Instagram."""


@app.webhooks.post("message-status", summary="message.status")
def _message_status_event(event: sc.MessageStatusEvent):
    """Sent when an outbound message becomes sent, delivered, read, or failed."""


app.include_router(routes_bookings.router)
app.include_router(routes_messaging.router)


def _error(status: int, code: str, message: str, headers: dict | None = None, details=None) -> JSONResponse:
    body: dict = {"error": {"code": code, "message": message}}
    if details:
        body["error"]["details"] = details
    return JSONResponse(status_code=status, content=body, headers=headers)


@app.exception_handler(ApiError)
async def _api_error(_: Request, exc: ApiError):
    return _error(exc.status_code, exc.code, str(exc.detail), exc.headers)


@app.exception_handler(StarletteHTTPException)
async def _http_error(_: Request, exc: StarletteHTTPException):
    code = {404: "not_found", 405: "method_not_allowed", 401: "unauthorized", 403: "forbidden"}.get(exc.status_code, "error")
    return _error(exc.status_code, code, str(exc.detail), getattr(exc, "headers", None))


@app.exception_handler(RequestValidationError)
async def _validation_error(_: Request, exc: RequestValidationError):
    details = [{"field": ".".join(str(p) for p in e.get("loc", []) if p != "body"), "message": e.get("msg", "")} for e in exc.errors()]
    return _error(422, "validation_error", "The request is invalid.", details=details)


@app.exception_handler(Exception)
async def _unexpected(request: Request, exc: Exception):
    log.error("public_api_unhandled", path=request.url.path, error=str(exc), exc_info=True)
    return _error(500, "internal_error", "Something went wrong on HAIP's side. Please retry.")
