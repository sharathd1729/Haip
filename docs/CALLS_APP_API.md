# HAIP Calls app: device API

The contract between the Android Calls app and the HAIP backend. Written from the code on `feat/calls-app`
(`backend/app/api/v1/endpoints/mobile_devices.py`, `schemas/mobile_device.py`, `services/mobile_device_service.py`);
if this file and the code disagree, the code wins and this file is a bug.

The app only sends facts (call log entries, recording files). HAIP matches the guest, creates the call through the same
ingest path as IVR calls, and runs transcription, summary and QA itself.

## Base URL

`https://genhaip.com/api/v1` (the web app's origin; Next.js forwards `/api/v1/*` to the backend). Keep it a build
setting in the app (`HAIP_BASE_URL`), so a staging build can point elsewhere.

All bodies are JSON (UTF-8) except the recording upload (multipart). Times are ISO 8601 **with a zone offset**
(`2026-11-12T11:00:00+05:30`); a time without one is refused (422).

Errors use FastAPI's shape: `{"detail": "Plain sentence for a person"}`, or for 422 validation errors
`{"detail": [{"loc": [...], "msg": "...", "type": "..."}]}`.

## Two kinds of credentials

| Credential | Who has it | Used for | Lifetime |
|---|---|---|---|
| User access token (JWT) | the staff member's web session | `POST /devices/register` only | 15 minutes |
| Device token `haip_dev_...` | the app, after registering | everything else the app calls | until revoked or replaced |

Both go in the same header: `Authorization: Bearer <token>`.

The device token is returned **once**, at registration. HAIP stores only its SHA-256, so it cannot be shown again: keep
it in Android Keystore-backed storage (`EncryptedSharedPreferences`). Losing it means registering again.

### Getting the user token from the web login

The app shows the HAIP web app in a WebView and does not handle passwords itself. Once the WebView has signed in (it is
on a `/dashboard` page):

1. Read the WebView's cookies for the origin: `CookieManager.getInstance().getCookie("https://genhaip.com")`.
2. `GET https://genhaip.com/api/auth/session` with header `Cookie: <those cookies>`. The NextAuth session JSON contains
   `accessToken` (the backend JWT). No `accessToken` = not signed in yet.
3. Call `POST /devices/register` with `Authorization: Bearer <accessToken>` straight away (it expires in 15 minutes).

The app never stores the user token or the cookies. Only the device token is kept.

## Endpoints

### `POST /devices/register` (user token)

Registers this phone for the signed-in staff member and returns a new device token.

Request:

```json
{
  "device_id": "3f1c9a0e2b7d4e51",
  "model": "Galaxy A54",
  "android_version": "14",
  "app_version": "1.0.0",
  "settings": {"unknown_numbers": "working_hours", "working_hours": {"start": "09:00", "end": "19:00"}}
}
```

| Field | Rules |
|---|---|
| `device_id` | required, 1-100 chars. A stable id for this app install (e.g. a UUID made at first launch and kept). The same id again = the same device row |
| `model`, `android_version`, `app_version` | optional; max 100 / 20 / 20 chars |
| `settings` | optional; same shape as `PUT /devices/settings` |

Response `201`:

```json
{
  "id": "b2d0...",
  "device_id": "3f1c9a0e2b7d4e51",
  "user_id": "u-123",
  "user_name": "Asha",
  "model": "Galaxy A54",
  "android_version": "14",
  "app_version": "1.0.0",
  "last_seen_at": null,
  "created_at": "2026-11-12T10:00:00+00:00",
  "revoked": false,
  "settings": {"unknown_numbers": "working_hours", "working_hours": {"start": "09:00", "end": "19:00"}},
  "token": "haip_dev_..."
}
```

`id` is the device row id (needed for `DELETE /devices/{id}`). Registering the same `device_id` again by the same person
issues a **new** token and the old one stops working at once.

| Status | Meaning | App should |
|---|---|---|
| 201 | registered | store `token` and `id` |
| 401 | user token missing or expired | get a fresh one from the session and retry once |
| 403 | this phone was removed (revoked) by a manager | show the message; only an owner/manager can bring it back |
| 409 | this phone is registered to another staff member | show the message; a manager must move it |
| 422 | bad field | fix the request (a bug) |

### `PUT /devices/settings` (device token)

Request (both fields optional, any other key is refused with 422):

```json
{"unknown_numbers": "working_hours", "working_hours": {"start": "22:00", "end": "06:00"}}
```

| Field | Values |
|---|---|
| `unknown_numbers` | `working_hours` (default): calls with numbers that match no guest are kept only inside the working hours; `always`; `never` |
| `working_hours` | `{"start": "HH:MM", "end": "HH:MM"}`, 24-hour, in the **workspace's** timezone (IST for Ratha and Jade). `start` later than `end` = overnight shift. `null` = no hours set, which makes `working_hours` behave like `always` |

Response `200`: the saved settings, same shape.

**Personal numbers are never sent to HAIP**, not even hashed. A `personal_numbers` key is refused (422). The app keeps
that list on the phone and drops those calls before uploading (see "Privacy rules").

### `POST /device-calls` (device token)

Uploads call-log entries. Send at most 200 per request; send more in several requests.

Request:

```json
{
  "calls": [
    {
      "device_call_id": "1842",
      "number": "+919812345678",
      "direction": "in",
      "started_at": "2026-11-12T11:00:00+05:30",
      "duration_sec": 42,
      "answered": true,
      "sim_slot": 1
    }
  ]
}
```

| Field | Rules |
|---|---|
| `device_call_id` | required, 1-100 chars, unique on this phone. Use the call log's `CallLog.Calls._ID` |
| `number` | required, 1-40 chars, as the call log has it (local or international). HAIP normalises it with the workspace's country |
| `direction` | `in` or `out` |
| `started_at` | call start (`CallLog.Calls.DATE`), with zone |
| `duration_sec` | 0-86400 (`CallLog.Calls.DURATION`) |
| `answered` | incoming: false = missed / rejected. Outgoing: false = nobody picked up. Send `duration_sec` as logged; HAIP counts an unanswered call as 0 seconds |
| `sim_slot` | optional 0-9; accepted, not stored |

Response `200`, one result per call in the same order:

```json
{
  "results": [{"device_call_id": "1842", "status": "queued"}],
  "counts": {"queued": 1}
}
```

| Per-call `status` | Meaning | Upload its recording? |
|---|---|---|
| `queued` | accepted; HAIP creates the call within seconds | yes |
| `duplicate` | HAIP already has this call (a resend) | yes, if not sent yet (a repeat is ignored) |
| `skipped_unknown_number` | number matches no guest and the unknown-number rule was off at that time; nothing stored | **no** |
| `invalid_number` | withheld, private or malformed number; nothing stored | **no** |

Resending a call is always safe (idempotent on this phone + `device_call_id`). A `200` means every call in the batch has
a final status: move the sync cursor past them. On any other response, keep them and retry.

If HAIP's queue loses a `queued` call, HAIP queues it again by itself (15 minutes later, up to 5 times). The app does
not need to resend it.

### `POST /device-calls/{device_call_id}/recording` (device token)

Uploads the phone dialer's recording of one of **this phone's** calls. Multipart form, one field named `file`.

```
POST /api/v1/device-calls/1842/recording
Authorization: Bearer haip_dev_...
Content-Type: multipart/form-data; boundary=...
Content-Length: 812345

--...
Content-Disposition: form-data; name="file"; filename="Call_+919812345678_20261112.m4a"
Content-Type: audio/mp4

<bytes>
--...--
```

- Send `Content-Length` (411 without it). OkHttp sends it for a `File` or `ByteArray` body.
- Accepted: m4a/3gp, mp3, amr, aac, wav, ogg, decided from the file's **first bytes**, never the file name or
  `Content-Type`. Up to 50 MB.
- HAIP re-encodes every recording to MP3 before storing it, so the app sends the dialer's file as it is.

Response: `{"status": "attached" | "waiting" | "duplicate", "call_id": "c-789" | null}`

| Status | Meaning | App should |
|---|---|---|
| 201 `attached` | stored and attached to the call; transcription starts | mark done |
| 202 `waiting` | stored; the call is still being created and gets it when it is | mark done |
| 200 `duplicate` | this call already has a recording; ignored | mark done |
| 404 | HAIP has no such call from this phone: not uploaded yet, or the call was `skipped_unknown_number` / `invalid_number` | upload the call first; retry later only if the call came back `queued` or `duplicate` |
| 411 | no `Content-Length` | fix the request |
| 413 | over 50 MB | mark failed, do not retry |
| 415 | not an accepted audio type | mark failed, do not retry |
| 422 | empty file, missing `file` field, or HAIP could not read the audio | mark failed, do not retry |
| 503 | HAIP cannot process recordings right now | retry with backoff |

### `DELETE /devices/{id}` (user token)

Revokes a device: its token stops working at once (any further call = 401). Staff can revoke their own phone; owners
and managers can revoke anyone's. Response `204`. The app can use it for "Sign out of the Calls app" while it still has a
user session.

### `GET /devices` (user token, owner/manager)

Lists every staff device in the workspace (same fields as the register response, without `token`), plus the phone's
last 30 days: `calls_30d`, `recordings_30d`, `last_call_at`, `last_recording_at`. For the web app's "Calls app phones"
screen (Settings > Workspace), not the phone.

## Rate limit

Device-token requests (`/device-calls*`, `/devices/settings`) are limited **per device token**: 120 requests a minute.
Over that: `429` with header `Retry-After: <seconds>` and body `{"detail": "...", "retry_after": <seconds>}`. Wait that
long, then carry on. A first sync with a large backlog should upload calls first (200 per request), then recordings one
at a time.

## Retry rules

| Response | Retry? |
|---|---|
| network error, timeout, 5xx, 503 | yes, exponential backoff (WorkManager's default is fine) |
| 429 | yes, after `Retry-After` |
| 401 on a device-token call | no; the device was revoked or the staff member deactivated. Clear the device token and ask them to sign in again |
| other 4xx | no (it would fail the same way); log it |

## Privacy rules the app must follow

- Never upload a call whose number the staff member marked personal. The list stays on the phone.
- Never upload a recording for a call that came back `skipped_unknown_number` or `invalid_number`.
- Send only the fields above: no contact names, no SMS, no other files from the recordings folder.

## Not built yet

- `GET /app/android/version` (in-app update check, spec step 3): not built. The APK comes from the GitHub Actions build
  for now.
- Upload size through the web origin: the Next.js proxy in front of `/api/v1` may cap request bodies below 50 MB. Check
  with a long recording during the pilot. If it does, give the app the backend's own host as `HAIP_BASE_URL`.
