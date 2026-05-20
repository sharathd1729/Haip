---
date: 2025-05-10
title: "DPDP Compliance & Meta Policy"
summary: "Opt-out keyword detection, consent proof storage, retention auto-purge, 24h service window, breach templates."
version: "2.3.0"
tags: [compliance, dpdp, meta]
---

## What's new

**Opt-out detection** — Guests can now reply `STOP`, `UNSUBSCRIBE`, `बंद करो`, or any of 15+ opt-out keywords to instantly unsubscribe from marketing. Confirmation sent automatically.

**24-hour service window indicator** — WhatsApp threads now show a countdown timer: "Service window: 18h 22m left." When closed, the composer blocks free-form messages and prompts you to send an approved template.

**DPDP deletion queue** — Guest deletion now has a 30-day grace period. Admin can restore from the Compliance → DPDP Deletions queue before hard delete.

**Breach notification template** — Pre-drafted 72-hour DPDP breach notification template available under Compliance → Incidents.

**Grievance officer page** — Public page at `/grievance` lets guests submit privacy concerns. Admin queue in Compliance → Audit.

**PII redaction in logs** — Phone numbers, emails, Aadhaar, PAN, and CC numbers are now masked in all application logs.
