# Security Audit — HAIP
**Date**: 2026-06-14 | **Auditor**: Security Engineer | **Score: 6.5 / 10**

---

## 1. Authentication & Authorization

### Strengths
- JWT HS256 with 15-minute access tokens and 30-day refresh tokens
- `get_current_user` dependency on all protected routes
- Role check (`owner` only) on module activate/deactivate
- Per-tenant RLS via `set_config('app.tenant_id', ...)` — parameterized, not string-formatted (SQL injection safe)

### Issues

#### CRITICAL — Instagram Webhook Uses `==` Instead of `secrets.compare_digest`
**File**: `backend/app/adapters/whatsapp/webhooks_instagram.py` line ~34
**Problem**: `token == expected` is vulnerable to timing attacks. An attacker can brute-force the verify token by measuring response time differences character by character.
**CLAUDE.md mandates**: "WhatsApp verify token uses `secrets.compare_digest` not `==`"
**Fix**:
```python
import secrets
if not secrets.compare_digest(token, expected):
    raise HTTPException(status_code=403)
```
**Risk**: CRITICAL — token brute-forceable; attacker can subscribe their own endpoint to your webhook feed.

#### HIGH — Dev/Staging Webhook Signature Bypass
**File**: `backend/app/core/webhook_security.py` lines 58–60
**Problem**: A conditional bypasses webhook HMAC signature verification for dev/staging environments. If `settings.ENVIRONMENT != "production"` skips verification, any request to the staging webhook URL can inject arbitrary call/message events.
**Fix**: Remove the bypass entirely. Use test fixtures and recorded webhook payloads in CI instead of disabling verification.
**Risk**: HIGH — staging data poisoning; if staging DB is seeded from prod, real guest data exposed.

#### HIGH — MFA Secret Stored Unencrypted in DB
**Problem**: MFA TOTP secrets stored as plaintext in `users` table. If DB is compromised, all MFA secrets are exposed — attacker can generate valid TOTP codes for all users.
**Fix**: Encrypt with Fernet (same mechanism used for integration credentials) before storing. Decrypt only during TOTP verification.
**Risk**: HIGH — defeats purpose of MFA.

#### MEDIUM — CallerDesk 404 Reveals Tenant Enumeration
**File**: `backend/app/adapters/ivr/` CallerDesk webhook handler
**Problem**: `GET /webhooks/callerdesk/{tenant_slug}` returns 404 for unknown slugs. Attacker can enumerate valid tenant slugs by probing the endpoint and checking 404 vs 403.
**Fix**: Return 403 for all invalid webhook requests (unknown slug or invalid signature) — same response code regardless of reason.
**Risk**: MEDIUM — information disclosure; attacker learns which hotel brands are on HAIP.

---

## 2. Input Validation

### Issues

#### HIGH — 10+ Schema Fields Use `List[Any]` or `Optional[Any]`
**Problem**: Pydantic schemas with `Any` type skip validation entirely. Malicious data can pass through to the ORM and DB.
**Examples found**: Analytics endpoint schemas, report field lists, widget configuration payloads.
**Fix**: Replace `Any` with typed models. At minimum use `Union[str, int, float, bool]` for fields that accept multiple primitives.
**Risk**: HIGH — potential for stored XSS via widget config, SQL injection edge cases, data corruption.

#### MEDIUM — No SSRF Protection on User-Supplied Recording URLs (Acefone/CallerDesk)
**CLAUDE.md defines allowed domains per provider**:
- CallerDesk: `cdn.callerdesk.io`, `recordings.callerdesk.io`
- Acefone: `cdn.acefone.com`
- Dograh: `cdn.dograh.com`, `recordings.dograh.com`, `storage.dograh.com`

**Verify** that all recording URL fetches validate scheme (`https`) and domain against this allowlist before making HTTP requests. Any `recording_url` field that accepts arbitrary user input without domain validation is an SSRF vector.
**Risk**: MEDIUM — attacker can exfiltrate internal metadata (AWS instance metadata, Redis, DB) via a crafted recording URL.

---

## 3. Secrets & Credentials

### Strengths
- Fernet encryption for integration credentials (WhatsApp, IVR)
- Per-tenant webhook secrets stored encrypted (`dograh_webhook_secret_enc`)
- No hardcoded secrets found in application code
- `.env` not committed (confirmed by gitignore)

### Issues

#### HIGH — Docker Compose Default Credentials
**File**: `docker-compose.yml`
**Problem**: Default PostgreSQL credentials `haip/haip` in docker-compose. If developer runs compose locally and exposes port 5432, anyone on the same network has DB access.
**Fix**: Use environment variable substitution in compose: `${POSTGRES_PASSWORD:-changeme}`. Add `POSTGRES_PASSWORD` to `.env.example` with a note to change before use.
**Risk**: MEDIUM in dev, HIGH if compose is used on a shared or cloud VM.

#### MEDIUM — No Secret Rotation Mechanism
Integration credentials encrypted with Fernet. No key rotation endpoint or CLI tool. If Fernet key is compromised, all stored credentials are exposed with no recovery path.
**Fix**: Store credential version with each encrypted blob. Add `POST /integrations/{id}/rotate-secret` endpoint that re-encrypts with new key material.

---

## 4. PII Handling

### Strengths
- CLAUDE.md mandates: "PII never logged in plaintext — hash phone numbers in logs via `_phone_token()`"
- DPDP consent tracked in `Consent` table with `consent_source`, `collected_by`, `collected_at`
- Agent-added signals auto-write Consent row (handled in `identity_service.add_signal()`)

### Issues

#### MEDIUM — Verify `_phone_token()` Is Used Everywhere
Confirm that all structlog calls that include phone numbers use `_phone_token()`. A grep for `phone` in log statements should return zero plaintext phone numbers.
**Check**: `grep -r "log.*phone\|structlog.*phone" backend/app --include="*.py"` should show only hashed forms.

---

## 5. Multi-Tenancy

### Strengths
- RLS on all tenant-scoped tables
- `set_config('app.tenant_id', ...)` called at start of every DB session
- Every query in service layer filters by `tenant_id`
- Weekly cross-tenant breach simulation test mandated in CLAUDE.md

### Issues

#### MEDIUM — Missing Cross-Tenant Test in New Endpoints
New endpoints added this sprint (metrics drill/series/compare, widget refresh/data, goals status, reports export) need explicit cross-tenant tests. Pattern: create resource as tenant A, attempt access as tenant B, expect 404 not 200.

---

## 6. Security Scores

| Domain | Score | Top Issue |
|--------|-------|-----------|
| Authentication | 7/10 | Instagram timing attack |
| Authorization | 8/10 | Role checks present; RLS enforced |
| Input validation | 5/10 | `List[Any]` schemas bypass Pydantic |
| Secrets management | 7/10 | Fernet good; no rotation; Docker defaults |
| PII handling | 7/10 | Consent tracked; verify no plaintext logs |
| Multi-tenancy | 8/10 | RLS solid; new endpoints need cross-tenant tests |
| Webhook security | 5/10 | `==` timing attack; dev bypass present |

**Overall: 6.5 / 10**

---

## 7. Priority Fixes (Ordered by Risk)

1. **`secrets.compare_digest`** in Instagram webhook — 5 min fix, CRITICAL
2. **Remove dev webhook bypass** in `webhook_security.py` lines 58–60 — HIGH
3. **Encrypt MFA secrets** with Fernet before DB storage — HIGH
4. **Replace `Any` schemas** with typed Pydantic models — HIGH (do in bulk)
5. **Tenant enumeration** — return 403 for all webhook failures — MEDIUM
6. **Docker compose** — parameterize default credentials — MEDIUM
7. **SSRF audit** — verify recording URL domain validation across all IVR adapters — MEDIUM
