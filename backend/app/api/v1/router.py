from fastapi import APIRouter
from app.api.v1.endpoints import (
    auth, calls, dashboard, workspace_context,
    tenants, users, guests, inquiries, conversations, properties,
    qa, integrations, analytics, analytics_executive, analytics_sections, analytics_intelligence, analytics_forecasting, instagram_insights, ask_haip, audit, sse, messaging, reports, saved_replies, saved_views,
    webhooks_callerdesk, webhooks_acefone, webhooks_mcube, webhooks_whatsapp, webhooks_instagram,
    webhooks_dograh, webhooks_vobiz,
    voice_settings,
    mcp_tokens,
    capabilities,
    grievance, incidents, health, changelog, sample_data, admin_dlq,
    calculator, calendar, bookings,
    leads,
    pipeline_stages,
    lead_fields,
    automations,
    tasks,
    ivr,
    push,
    dashboards, metrics, widgets_api, goals,
    dashboard_overview,
    knowledge,
    worklist,
    lead_activity,
)

api_router = APIRouter(prefix="/api/v1")

# Auth
api_router.include_router(auth.router)

# Dashboard
api_router.include_router(dashboard.router)
api_router.include_router(dashboard_overview.router)
api_router.include_router(workspace_context.router)
api_router.include_router(dashboards.router)
api_router.include_router(goals.router)

# Metrics & Widgets catalogue
api_router.include_router(metrics.router)
api_router.include_router(widgets_api.router)

# Core app
api_router.include_router(tenants.router)
api_router.include_router(users.router)
api_router.include_router(guests.router)
api_router.include_router(inquiries.router)
api_router.include_router(pipeline_stages.router)
api_router.include_router(lead_fields.router)
api_router.include_router(conversations.router)
api_router.include_router(knowledge.router)
api_router.include_router(worklist.router)
api_router.include_router(lead_activity.router)
api_router.include_router(saved_replies.router)
api_router.include_router(saved_views.router)
api_router.include_router(properties.router)
api_router.include_router(calculator.router)
api_router.include_router(calendar.router)
api_router.include_router(bookings.router)
api_router.include_router(calls.router)

# Leads360 — unified sales pipeline
api_router.include_router(leads.router)

# Intelligence
api_router.include_router(qa.router)
api_router.include_router(analytics.router)
api_router.include_router(reports.router)
api_router.include_router(analytics_executive.router)
api_router.include_router(analytics_sections.router)
api_router.include_router(analytics_intelligence.router)
api_router.include_router(analytics_forecasting.router)
api_router.include_router(instagram_insights.router)
api_router.include_router(ask_haip.router)

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
api_router.include_router(mcp_tokens.router)
api_router.include_router(capabilities.router)
api_router.include_router(voice_settings.router)
