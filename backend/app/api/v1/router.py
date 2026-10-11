from fastapi import APIRouter
from app.api.v1.endpoints import (
    auth, calls, workspace_context,
    tenants, users, guests, inquiries, conversations, properties,
    qa, integrations, ical_feeds, api_keys, meta_ads, webhook_endpoints, booking_detail, booking_extras, payments_razorpay, analytics, analytics_executive, instagram_insights, audit, sse, messaging, messaging_campaign_reports, reports, saved_replies, saved_views,
    webhooks_callerdesk, webhooks_acefone, webhooks_mcube, webhooks_whatsapp, webhooks_instagram,
    webhooks_dograh, webhooks_vobiz, webhooks_whatsapp_personal,
    whatsapp_personal,
    voice_settings,
    mcp_tokens,
    capabilities,
    oauth_consent,
    grievance, incidents, health, changelog, sample_data, admin_dlq,
    calculator, calendar, bookings,
    leads,
    pipeline_stages,
    lead_fields,
    automations,
    tasks,
    ivr,
    push,
    dashboard_overview,
    knowledge,
    targets,
    work_queue,
    lead_activity,
)

api_router = APIRouter(prefix="/api/v1")

# Auth
api_router.include_router(auth.router)

# Dashboard
api_router.include_router(dashboard_overview.router)
api_router.include_router(workspace_context.router)

# Metrics & Widgets catalogue

# Core app
api_router.include_router(tenants.router)
api_router.include_router(users.router)
api_router.include_router(guests.router)
api_router.include_router(inquiries.router)
api_router.include_router(pipeline_stages.router)
api_router.include_router(lead_fields.router)
api_router.include_router(conversations.router)
api_router.include_router(knowledge.router)
api_router.include_router(targets.router)
api_router.include_router(work_queue.router)
api_router.include_router(lead_activity.router)
api_router.include_router(saved_replies.router)
api_router.include_router(saved_views.router)
api_router.include_router(properties.router)
api_router.include_router(calculator.router)
api_router.include_router(calendar.router)
api_router.include_router(bookings.router)
api_router.include_router(booking_detail.router)
api_router.include_router(booking_extras.router)
api_router.include_router(calls.router)

# Leads360 — unified sales pipeline
api_router.include_router(leads.router)

# Intelligence
api_router.include_router(qa.router)
api_router.include_router(analytics.router)
api_router.include_router(reports.router)
api_router.include_router(analytics_executive.router)
api_router.include_router(instagram_insights.router)

# Integrations & compliance
api_router.include_router(api_keys.router)
api_router.include_router(meta_ads.router)
api_router.include_router(webhook_endpoints.router)
api_router.include_router(payments_razorpay.router)
api_router.include_router(payments_razorpay.webhook_router)
api_router.include_router(integrations.router)
api_router.include_router(ical_feeds.router)
api_router.include_router(ical_feeds.public_router)
api_router.include_router(messaging.router)
api_router.include_router(messaging_campaign_reports.router)
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

# Automations
api_router.include_router(automations.router)

# Follow-up tasks
api_router.include_router(tasks.router)

# IVR call routing
api_router.include_router(ivr.router)

# PWA push notifications
api_router.include_router(push.router)

# Webhooks (no JWT required — use shared-secret auth)
api_router.include_router(webhooks_callerdesk.router)
api_router.include_router(webhooks_acefone.router)
api_router.include_router(webhooks_mcube.router)
api_router.include_router(webhooks_whatsapp.router)
api_router.include_router(webhooks_instagram.router)
api_router.include_router(webhooks_dograh.router)
api_router.include_router(webhooks_vobiz.router)
api_router.include_router(webhooks_whatsapp_personal.router)
api_router.include_router(whatsapp_personal.router)
api_router.include_router(mcp_tokens.router)
api_router.include_router(capabilities.router)
api_router.include_router(oauth_consent.router)
api_router.include_router(voice_settings.router)
