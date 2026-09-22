HAIP-specific security rules. Treat a change that breaks any of these as a finding.

Multi-tenancy (highest priority)
- Every tenant-scoped query must filter by the caller's tenant_id (current_user.tenant_id). A lookup by id alone (filter_by(id=...), db.get(...)) in an endpoint or service is an IDOR, even when the id is a UUID.
- New tables need a tenant_id column, an Alembic migration and an RLS policy using current_setting('app.tenant_id').
- Agent roles must stay scoped to their own data (scope_user_id); only owner/manager may pass agent_id for someone else.

Webhooks
- Every inbound webhook must verify a per-tenant signature or per-tenant URL secret with hmac/secrets.compare_digest, and reject (401) when the secret is missing. A global shared secret, a skipped check, or a plain == comparison is a finding.

Outbound requests (SSRF)
- Any URL a tenant or guest can influence must be fetched via app/core/url_safety.py (assert_public_url / safe_get). Call-recording downloads must check the provider's host allowlist and https.

Secrets and PII
- API keys and tokens must never appear in URLs or log lines (httpx errors include the full URL). Phone numbers must be hashed in logs (_phone_token()).
- Credentials are stored encrypted (encrypt_credentials); never plaintext in the DB, the repo or responses.

HTML and the frontend
- /api/v1 is served from the app's own origin (Next.js rewrite), and /api/auth/session exposes the access token. Any backend HTMLResponse must html.escape interpolated values; any dangerouslySetInnerHTML with non-constant data is a finding.

LLM-generated SQL (Ask HAIP free-form)
- The validator in ask_haip_freeform_service.py must keep rejecting nested SELECTs and unknown (Anonymous) functions and must keep force-injecting the tenant predicate.

Auth
- Access tokens are HS256 JWTs checked in get_current_user; MFA challenge tokens must never be accepted as access tokens. Owner-only actions use require_roles / require_capability.
