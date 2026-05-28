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

    ANTHROPIC_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    DEEPGRAM_API_KEY: str = ""
    SARVAM_API_KEY: str = ""   # Sarvam AI — best for Hindi/Indic/code-switched calls

    # CallerDesk
    CALLERDESK_API_KEY: str = ""
    CALLERDESK_API_SECRET: str = ""
    CALLERDESK_ACCOUNT_SID: str = ""
    CALLERDESK_WEBHOOK_SECRET: str = ""

    # Acefone
    ACEFONE_API_KEY: str = ""
    ACEFONE_API_SECRET: str = ""
    ACEFONE_WEBHOOK_SECRET: str = ""

    # WhatsApp / Instagram (Meta)
    META_WHATSAPP_PHONE_NUMBER_ID: str = ""
    META_WHATSAPP_ACCESS_TOKEN: str = ""
    META_WHATSAPP_WEBHOOK_VERIFY_TOKEN: str = ""
    META_APP_SECRET: str = ""
    META_INSTAGRAM_ACCESS_TOKEN: str = ""
    META_INSTAGRAM_PAGE_ID: str = ""

    # Email
    RESEND_API_KEY: str = ""
    EMAIL_FROM: str = "notifications@haip.app"

    # Sentry
    SENTRY_DSN: str = ""
    SENTRY_RELEASE: str = ""

    # Hostaway
    HOSTAWAY_ACCOUNT_ID: str = ""
    HOSTAWAY_API_KEY: str = ""

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
