from pydantic_settings import BaseSettings
from pydantic import model_validator
from typing import List

_INSECURE_DEFAULTS = {
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
    FRONTEND_URL: str = "http://localhost:3000"   # Used for invite links, password reset, etc.
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # Database
    DATABASE_URL: str
    REDIS_URL: str = "redis://localhost:6379/0"

    # ── Object storage (AWS S3 or Cloudflare R2 — R2 is free 10GB) ──────────
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_REGION: str = "ap-south-1"
    S3_BUCKET_NAME: str = "haip-recordings"
    KMS_KEY_ID: str = ""
    # Set for Cloudflare R2: https://<account-id>.r2.cloudflarestorage.com
    # Leave blank for real AWS S3
    AWS_S3_ENDPOINT_URL: str = ""

    # ── AI provider selection ─────────────────────────────────────────────────
    # LLM_PROVIDER: "gemini" | "claude"  (auto-detected from keys if blank)
    LLM_PROVIDER: str = ""
    # TRANSCRIPTION_PROVIDER: "groq" | "deepgram" | "whisper"  (auto if blank)
    TRANSCRIPTION_PROVIDER: str = ""

    # Anthropic Claude (paid — fallback when Gemini not configured)
    ANTHROPIC_API_KEY: str = ""

    # Google Gemini (FREE tier: 15 rpm, 1M tokens/day)
    GEMINI_API_KEY: str = ""

    # Groq  (FREE tier: 7200 sec audio/day, fast inference)
    GROQ_API_KEY: str = ""

    # Deepgram (paid — fallback when Groq not configured)
    DEEPGRAM_API_KEY: str = ""

    # CallerDesk
    CALLERDESK_API_KEY: str = ""
    CALLERDESK_API_SECRET: str = ""
    CALLERDESK_ACCOUNT_SID: str = ""
    CALLERDESK_WEBHOOK_SECRET: str = ""

    # Acefone
    ACEFONE_API_KEY: str = ""
    ACEFONE_API_SECRET: str = ""
    ACEFONE_WEBHOOK_SECRET: str = ""

    # WhatsApp
    META_WHATSAPP_PHONE_NUMBER_ID: str = ""
    META_WHATSAPP_ACCESS_TOKEN: str = ""
    META_WHATSAPP_WEBHOOK_VERIFY_TOKEN: str = ""
    META_APP_SECRET: str = ""

    # Instagram
    META_INSTAGRAM_ACCESS_TOKEN: str = ""
    META_INSTAGRAM_PAGE_ID: str = ""

    # Email
    RESEND_API_KEY: str = ""
    EMAIL_FROM: str = "notifications@haip.app"

    # Sentry
    SENTRY_DSN: str = ""
    # Set by CI to the git SHA / tag (e.g. "v1.2.3" or "abc1234").
    # Used for Sentry release tracking and source-map association.
    # In Railway / GitHub Actions: set SENTRY_RELEASE=${{ github.sha }}
    SENTRY_RELEASE: str = ""

    # Hostaway
    HOSTAWAY_ACCOUNT_ID: str = ""
    HOSTAWAY_API_KEY: str = ""

    @model_validator(mode="after")
    def _validate_secrets(self) -> "Settings":
        if self.ENVIRONMENT == "production":
            if self.SECRET_KEY in _INSECURE_DEFAULTS or len(self.SECRET_KEY) < 32:
                raise ValueError(
                    "SECRET_KEY must be a random 32+ character string in production. "
                    "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
                )
            if not self.DATABASE_URL or self.DATABASE_URL.startswith("sqlite"):
                raise ValueError("DATABASE_URL must be a real PostgreSQL URL in production.")
            if not (self.GEMINI_API_KEY or self.ANTHROPIC_API_KEY):
                raise ValueError("At least one AI provider key (GEMINI_API_KEY or ANTHROPIC_API_KEY) is required.")
            # B1: webhook security — warn (not crash) if Meta secret is absent.
            # WhatsApp/Instagram webhooks will be rejected until this is set,
            # but core call-intelligence features still function without it.
            if not self.META_APP_SECRET:
                import warnings
                warnings.warn(
                    "META_APP_SECRET is not set. All inbound Meta webhooks "
                    "(WhatsApp / Instagram) will be rejected until this is configured.",
                    stacklevel=2,
                )
            # B6: CORS — refuse to start with the localhost default in prod
            _localhost_defaults = {"http://localhost:3000", "http://localhost:3001", ""}
            origins = {o.strip() for o in self.ALLOWED_ORIGINS.split(",")}
            if origins <= _localhost_defaults or not self.ALLOWED_ORIGINS.strip():
                raise RuntimeError(
                    "ALLOWED_ORIGINS must be set explicitly in production "
                    "(e.g. 'https://yourdomain.com'). The localhost default is not valid."
                )
        return self

    @property
    def allowed_origins_list(self) -> List[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",")]

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
