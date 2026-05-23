from fastapi import APIRouter
from app.api.v1.endpoints import (
    auth, calls, dashboard,
    tenants, users, guests, inquiries, conversations, properties,
    qa, integrations, analytics, audit, sse, messaging, reports, saved_replies, saved_views,
    webhooks_callerdesk, webhooks_acefone, webhooks_whatsapp, webhooks_instagram,
    grievance, incidents, health, changelog, sample_data, admin_dlq,
    calculator, calendar,
)

api_router = APIRouter(prefix="/api/v1")

# Auth
api_router.include_router(auth.router)

# Dashboard
api_router.include_router(dashboard.router)

# Core app
api_router.include_router(tenants.router)
api_router.include_router(users.router)
api_router.include_router(guests.router)
api_router.include_router(inquiries.router)
api_router.include_router(conversations.router)
api_router.include_router(saved_replies.router)
api_router.include_router(saved_views.router)
api_router.include_router(properties.router)
api_router.include_router(calculator.router)
api_router.include_router(calendar.router)
api_router.include_router(calls.router)

# Intelligence
api_router.include_router(qa.router)
api_router.include_router(analytics.router)
api_router.include_router(reports.router)

# Integrations & compliance
api_router.include_router(integrations.router)
api_router.include_router(messaging.router)
api_router.include_router(audit.router)
api_router.include_router(sse.router)

# Compliance
api_router.include_router(grievance.router)
api_router.include_router(incidents.router)

# Health / status bar (X8)
api_router.include_router(health.router)

# Changelog (X9)
api_router.include_router(changelog.router)

# Sample data (O2 / O9)
api_router.include_router(sample_data.router)

# Admin: DLQ (B3)
api_router.include_router(admin_dlq.router)

# Webhooks (no JWT required — use shared-secret auth)
api_router.include_router(webhooks_callerdesk.router)
api_router.include_router(webhooks_acefone.router)
api_router.include_router(webhooks_whatsapp.router)
api_router.include_router(webhooks_instagram.router)
