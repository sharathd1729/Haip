from pydantic_settings import BaseSettings
from pydantic import model_validator
from typing import List
import logging

_log = logging.getLogger("haip.config")

_INSECURE_KEY_DEFAULTS = {
    "change-me-in-production",
    "secret",
    "your-secret-key",
    "changeme",
    "",
}


class Settings(BaseSettings):
    # App
    ENVIRONMENT: str = "development"
    SECRET_KEY: str = "change-me-in-production"
    ALLOWED_ORIGINS: str = "http://localhost:3000"
    FRONTEND_URL: str = "http://localhost:3000"
    # Public API base URL used in webhook-info responses (no trailing slash)
    API_BASE_URL: str = ""
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # Database
    DATABASE_URL: str = ""
    # Read-only connection for the Ask HAIP free-form analyst
    # (ask_haip_freeform_service.py), bound to the haip_analyst_ro Postgres
    # role (migration 052). Deliberately separate from DATABASE_URL -- the
    # feature must fail closed (not silently fall back to the privileged
    # connection) if this isn't set. Set once an operator has run
    # `ALTER ROLE haip_analyst_ro WITH LOGIN PASSWORD '...'` (see migration
    # 052's docstring); never generated or defaulted here.
    ANALYST_RO_DATABASE_URL: str = ""
    # Per-process pool sizing — override per process type (e.g. api vs
    # celery beat/flower, which rarely need concurrent connections) via env
    # vars in each service's docker-compose command/environment block.
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    REDIS_URL: str = "redis://localhost:6379/0"

    # ── Object storage (AWS S3 or Cloudflare R2) ─────────────────────────────
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_REGION: str = "ap-south-1"
    S3_BUCKET_NAME: str = "haip-recordings"
    KMS_KEY_ID: str = ""
    AWS_S3_ENDPOINT_URL: str = ""

    # ── AI provider selection ─────────────────────────────────────────────────
    LLM_PROVIDER: str = ""
    TRANSCRIPTION_PROVIDER: str = ""

    # NVIDIA NIM — one key per workload group for rate-limit isolation
    NVIDIA_API_KEY: str = ""          # global fallback (any group missing → uses this)
    NVIDIA_API_KEY_HEAVY: str = ""    # Ultra 550B: deep_reason, ask_haip_rca, report_gen
    NVIDIA_API_KEY_MID: str = ""      # Nemotron 70B / Super 49B: call_analysis, call_scoring
    NVIDIA_API_KEY_FAST: str = ""     # Llama 8B: quick_classify, bulk_batch, ask_haip_intent
    NVIDIA_API_KEY_FALLBACK: str = "" # Mistral Medium 3.5: fallback task
    ANTHROPIC_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    OPENAI_API_KEY: str = ""   # M5: OpenAI fallback provider
    GROQ_API_KEY: str = ""
    DEEPGRAM_API_KEY: str = ""
    SARVAM_API_KEY: str = ""   # Sarvam AI — best for Hindi/Indic/code-switched calls
    # Speech-to-text model for call transcription: "saaras:v3" (the translate batch job, proven in production) or "saaras:v4" (Sarvam's
    # newest: plain STT job in "translate" mode). Default stays v3 until v4 has been compared on real calls
    # (scripts/compare_sarvam_models.py). SARVAM_KEYTERMS = comma-separated names/brands to bias v4 toward (max 50; v4 only).
    SARVAM_STT_MODEL: str = "saaras:v3"
    SARVAM_KEYTERMS: str = ""
    # Operational kill switch: when true, new call recordings are stored but
    # NOT enqueued for transcription. Existing in-flight jobs are unaffected.
    TRANSCRIPTION_PAUSED: bool = False
    # DPDP right-to-erasure job (workers/tasks/dpdp_purge.py). Off = the nightly job only reports which deletion requests
    # are past their 30-day grace period. On = it erases them (dpdp_erasure_service). Check
    # scripts/dpdp_erasure_report.py on production before switching it on.
    DPDP_ERASURE_ENABLED: bool = False

    # CallerDesk
    CALLERDESK_API_KEY: str = ""
    CALLERDESK_API_SECRET: str = ""
    CALLERDESK_ACCOUNT_SID: str = ""
    CALLERDESK_WEBHOOK_SECRET: str = ""

    # Acefone
    ACEFONE_API_KEY: str = ""
    ACEFONE_API_SECRET: str = ""
    ACEFONE_WEBHOOK_SECRET: str = ""

    MCUBE_API_KEY: str = ""

    # Vobiz — SIP/voice trunk, Plivo-compatible REST API
    VOBIZ_AUTH_ID: str = ""
    VOBIZ_AUTH_TOKEN: str = ""
    # Agent's personal mobile the inbound call is bridged to (E.164). No DTMF
    # menu for this pass — every inbound call rings this one number while the
    # whole session records. Per-tenant routing is future work.
    VOBIZ_FORWARD_NUMBER: str = ""

    # WhatsApp / Instagram (Meta)
    META_WHATSAPP_PHONE_NUMBER_ID: str = ""
    META_WHATSAPP_ACCESS_TOKEN: str = ""
    META_WHATSAPP_WEBHOOK_VERIFY_TOKEN: str = ""
    # The single shared verify token above is still accepted so existing Meta setups keep verifying while
    # each workspace re-saves its callback with its own per-channel token. Set false once that is done.
    ALLOW_LEGACY_WEBHOOK_VERIFY_TOKEN: bool = True
    META_APP_SECRET: str = ""
    # Optional: the Meta app id, used to upload template header media. When
    # empty it is looked up from the WhatsApp access token (debug_token).
    META_APP_ID: str = ""
    META_INSTAGRAM_ACCESS_TOKEN: str = ""
    META_INSTAGRAM_PAGE_ID: str = ""
    INSTAGRAM_APP_ID: str = ""

    # Personal/Business-app WhatsApp bridge (whatsmeow, unofficial -- Phase 1
    # read-only capture only; see whatsapp_personal_service.py). Internal
    # network address of the bridge microservice.
    WHATSAPP_BRIDGE_URL: str = "http://whatsapp-bridge:8085"
    # This API's own public base URL, so the bridge can call back into it
    # (webhooks_whatsapp_personal.py). No existing setting covers this --
    # every other webhook is inbound-only (a third party calls us), this is
    # the first case of HAIP needing to hand its own address to a callee.
    PUBLIC_API_BASE_URL: str = "http://api:8000"

    # Email
    RESEND_API_KEY: str = ""
    # Resend only accepts a sender on a domain verified in the account.
    # onboarding@resend.dev is Resend's own test sender: it works with no DNS
    # setup, but ONLY delivers to the address that owns the Resend account.
    # Switch this to a verified domain (e.g. reports@genhaip.com) before any
    # real recipient is expected to receive mail.
    EMAIL_FROM: str = "onboarding@resend.dev"

    # Sentry
    SENTRY_DSN: str = ""
    SENTRY_RELEASE: str = ""

    # Hostaway
    HOSTAWAY_ACCOUNT_ID: str = ""
    HOSTAWAY_API_KEY: str = ""

    # Web Push (PWA notifications) — VAPID keys
    # Generate: python -c "from py_vapid import Vapid; v=Vapid(); v.generate_keys(); print(v.private_pem().decode())"
    VAPID_PRIVATE_KEY: str = ""
    VAPID_PUBLIC_KEY: str = ""
    VAPID_EMAIL: str = "notifications@haip.app"

    # HAIP's own website leads (book-demo, contact, property assessment). Every lead is stored in the platform-level
    # platform_leads table; when this names a workspace (tenant slug), the lead also becomes a Leads360 inquiry there
    # and that workspace's owners are notified. Empty = stored only (logged as platform_lead_unrouted).
    PLATFORM_LEADS_TENANT_SLUG: str = ""

    # Website builder (docs/website-builder/README.md). Every site gets "{slug}.{SITES_BASE_DOMAIN}"; custom domains
    # CNAME to SITES_CNAME_TARGET. The renderer (sites/ app) is told to refresh a site after a publish via
    # SITES_RENDERER_URL + SITES_REVALIDATE_SECRET. Cloudflare for SaaS is used for custom-domain TLS only when both
    # CLOUDFLARE_* values are set; otherwise domains are verified by DNS and TLS is handled at the proxy.
    SITES_BASE_DOMAIN: str = "genhaip.site"
    SITES_CNAME_TARGET: str = ""
    SITES_RENDERER_URL: str = ""
    SITES_REVALIDATE_SECRET: str = ""
    CLOUDFLARE_API_TOKEN: str = ""
    CLOUDFLARE_ZONE_ID: str = ""
    # Optional AI write-up of a property assessment (Celery, router task "assessment_narrative").
    ASSESSMENT_NARRATIVE_ENABLED: bool = True

    # Dograh Voice AI
    DOGRAH_WEBHOOK_SECRET: str = ""     # Global fallback — always prefer per-tenant secret
    DOGRAH_SERVER_URL: str = ""
    DOGRAH_AGENT_ID_DEFAULT: str = ""

    # SIP / Telephony (Twilio for dev, VoIP.ms or Plivo for production)
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_PHONE_NUMBER: str = ""

    @model_validator(mode="after")
    def _validate_and_warn(self) -> "Settings":
        """
        Hard-fail ONLY on the two things that make the whole app non-functional:
          1. No DATABASE_URL  — nothing can be persisted
          2. Weak SECRET_KEY  — all JWT tokens are compromised

        Every other missing key is a WARN — it disables that specific feature
        but must never crash the platform for all tenants.
        """
        is_prod = self.ENVIRONMENT == "production"

        # ── Hard failures (always, any environment) ───────────────────────────
        if not self.DATABASE_URL:
            raise ValueError(
                "DATABASE_URL is required. Set it to your PostgreSQL connection string."
            )
        if self.DATABASE_URL.startswith("sqlite") and is_prod:
            raise ValueError(
                "DATABASE_URL must be a PostgreSQL URL in production. "
                "SQLite does not support the multi-tenant row-level security used by HAIP."
            )
        if is_prod and (self.SECRET_KEY in _INSECURE_KEY_DEFAULTS or len(self.SECRET_KEY) < 32):
            raise ValueError(
                "SECRET_KEY must be a random 32+ character string in production.\n"
                "Generate one: python -c \"import secrets; print(secrets.token_hex(32))\""
            )

        # ── Soft warnings (feature-level degradation, never crash) ────────────
        if is_prod:
            _localhost = {"http://localhost:3000", "http://localhost:3001", ""}
            origins = {o.strip() for o in self.ALLOWED_ORIGINS.split(",")}
            if origins <= _localhost:
                _log.warning(
                    "ALLOWED_ORIGINS is still set to localhost. "
                    "Browser requests from your production frontend will be blocked by CORS. "
                    "Set ALLOWED_ORIGINS=https://your-app.vercel.app in Railway."
                )

            if not (self.GEMINI_API_KEY or self.ANTHROPIC_API_KEY):
                _log.warning(
                    "No AI provider key found (GEMINI_API_KEY or ANTHROPIC_API_KEY). "
                    "Call transcription, QA scoring and AI drafts will be unavailable."
                )

            if not self.META_APP_SECRET:
                _log.warning(
                    "META_APP_SECRET not set. "
                    "Inbound WhatsApp/Instagram webhooks will be rejected (signature check fails). "
                    "Core call-intelligence and CRM features are unaffected."
                )

            if not self.SARVAM_API_KEY and not self.GROQ_API_KEY and not self.DEEPGRAM_API_KEY:
                _log.warning(
                    "No transcription key set (SARVAM_API_KEY / GROQ_API_KEY / DEEPGRAM_API_KEY). "
                    "Call transcription will be unavailable."
                )

            if not self.RESEND_API_KEY:
                _log.warning(
                    "RESEND_API_KEY not set. Invitation emails will be silently dropped."
                )

        # Independent of environment: a free-mail EMAIL_FROM cannot work with
        # Resend, which requires a domain verified in the account. This was
        # set to a gmail.com address in production, so every outbound email --
        # invitations, password resets, reports -- failed with a 403 that only
        # showed up as an `email_send_failed` log line nobody was watching.
        _sender_domain = (self.EMAIL_FROM or "").split("@")[-1].lower()
        if self.RESEND_API_KEY and _sender_domain in {
            "gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com",
        }:
            _log.error(
                "EMAIL_FROM=%s uses a free-mail domain. Resend will reject every send "
                "(403) because the sender domain cannot be verified. Use a verified "
                "domain, or onboarding@resend.dev for testing.",
                self.EMAIL_FROM,
            )

        return self

    # ── Feature-flag helpers (use these in feature code instead of key checks) ─

    @property
    def ai_enabled(self) -> bool:
        return bool(self.GEMINI_API_KEY or self.ANTHROPIC_API_KEY)

    @property
    def transcription_enabled(self) -> bool:
        return bool(self.SARVAM_API_KEY or self.GROQ_API_KEY or self.DEEPGRAM_API_KEY)

    @property
    def whatsapp_enabled(self) -> bool:
        return bool(self.META_APP_SECRET and self.META_WHATSAPP_ACCESS_TOKEN)

    @property
    def email_enabled(self) -> bool:
        return bool(self.RESEND_API_KEY)

    @property
    def allowed_origins_list(self) -> List[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"


settings = Settings()
