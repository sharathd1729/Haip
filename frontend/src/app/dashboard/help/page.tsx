"use client";

import { useState } from "react";
import { HelpCircle, ChevronDown, ChevronUp, Phone, MessageSquare, Users, BarChart2, Shield, Star, Search, Mail, ExternalLink, FileText, Zap, Home, FileDown, Bot } from "@/lib/icons";
import { Plug2 } from "lucide-react";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// FAQ data per module
// ---------------------------------------------------------------------------

const MODULES = [
  {
    id: "calls",
    label: "Calls & IVR",
    icon: <Phone size={16} />,
    color: "from-blue-500 to-blue-600",
    faqs: [
      {
        q: "How does HAIP receive inbound calls?",
        a: "HAIP integrates with your CallerDesk or Acefone account via webhooks. When a call ends, the IVR provider sends a webhook to HAIP with the recording URL, duration, and caller details. HAIP then fetches the recording, transcribes it, and triggers AI scoring — all within 90 seconds."
      },
      {
        q: "How do I connect my IVR provider?",
        a: "Go to Settings → Integrations, find CallerDesk or Acefone, click Connect, and paste your API key. Then copy the HAIP webhook URL and paste it in your IVR dashboard under webhook settings. Ensure your HAIP server IP is whitelisted in CallerDesk."
      },
      {
        q: "What is a 'wrap-up' and when is it generated?",
        a: "A wrap-up is the AI-generated summary for a call — it includes the disposition (inquiry / support / spam), a 2–3 sentence summary, the suggested next action, and a QA score. It appears in the call detail page within 90 seconds of the call ending."
      },
      {
        q: "Can I override the AI disposition?",
        a: "Yes. On any call detail page, use the Disposition dropdown to override the AI's classification. Your override is logged in the audit trail and does not affect the AI model — it's purely a manual correction."
      },
      {
        q: "Why do some calls show 'transcription failed'?",
        a: "This usually means the recording URL returned by the IVR was empty, the audio was shorter than 3 seconds, or the Deepgram API key is missing. Check Settings → Environment keys for DEEPGRAM_API_KEY status."
      },
    ],
  },
  {
    id: "inbox",
    label: "Inbox & Messaging",
    icon: <MessageSquare size={16} />,
    color: "from-green-500 to-green-600",
    faqs: [
      {
        q: "What channels appear in the Inbox?",
        a: "The Inbox shows WhatsApp Business (Cloud API), Instagram DMs, and future channels (web chat, email). Each conversation is tagged with a channel badge. You can filter by channel using the pills in the left pane."
      },
      {
        q: "How do I approve an AI-drafted reply?",
        a: "When the AI Concierge drafts a reply, it appears as a teal pill below the conversation. Click Approve to send, Edit to modify before sending, or Reject to discard it and reply manually. Only Shadow mode requires approval — Autonomous mode sends directly."
      },
      {
        q: "Why is the AI not drafting replies for new WhatsApp messages?",
        a: "Check three things: (1) the WhatsApp integration is connected and shows 'Active' in Integrations, (2) the AI Concierge mode in Settings → AI Concierge is not set to 'Off', (3) Celery workers are running (the concierge_draft task is queue-based)."
      },
      {
        q: "Can I send a bulk WhatsApp message to all guests?",
        a: "Yes — go to Messaging → Campaigns. You can select a template, choose a guest segment, schedule the send, and track delivery and reply rates. Bulk messaging requires a pre-approved WhatsApp message template."
      },
      {
        q: "How does HAIP connect to Instagram DMs?",
        a: "Go to Integrations → Instagram DMs → Connect. Paste your Instagram Business Account ID, access token (with instagram_manage_messages permission), and optional App Secret. After connecting, configure the webhook URL shown in the info panel inside your Meta App's Webhooks settings."
      },
    ],
  },
  {
    id: "crm",
    label: "Guests & Inquiries",
    icon: <Users size={16} />,
    color: "from-violet-500 to-violet-600",
    faqs: [
      {
        q: "How are guests created?",
        a: "Guests are created automatically when HAIP receives an inbound call, WhatsApp message, or Instagram DM from a new number/account. Phone number is the primary identity. Guests can also be created manually on the Guests page."
      },
      {
        q: "What is an Inquiry and how does it differ from a Conversation?",
        a: "An Inquiry is a sales opportunity — a guest expressing interest in booking a property. A Conversation is the communication thread (WhatsApp, call, etc.) attached to that inquiry. One inquiry can have multiple conversations across channels."
      },
      {
        q: "How does the Inquiry Kanban work?",
        a: "The Kanban shows inquiries across pipeline stages: New → Contacted → Quoted → Follow-up → Won / Lost. Drag a card to move it between stages. When dragging to 'Lost', a modal prompts you to select a lost reason — this data feeds the weekly lost-reason cluster report."
      },
      {
        q: "Can I import existing guests from a spreadsheet?",
        a: "CSV import is on the roadmap (Q3 2026). Currently, guests are synced from Hostaway and RentalWise (via the PMS integration) or created from inbound interactions."
      },
      {
        q: "What is Guest 360?",
        a: "The Guest 360 page (click any guest name) shows their full timeline: all calls, WhatsApp conversations, Instagram DMs, bookings, and stays. It also shows predicted CSAT, lifetime value, and any tags. It's the single source of truth for each guest relationship."
      },
    ],
  },
  {
    id: "qa",
    label: "QA & Scoring",
    icon: <Star size={16} />,
    color: "from-amber-500 to-amber-600",
    faqs: [
      {
        q: "How is the QA score calculated?",
        a: "HAIP uses a 7-criterion hospitality rubric: greeting & personalisation, needs discovery, product knowledge, urgency creation, objection handling, closing technique, and compliance. Each criterion is scored 1–5. The total is normalised to 100. Claude Haiku scores first; if confidence < 0.78, Claude Sonnet re-judges."
      },
      {
        q: "Can I customise the QA rubric?",
        a: "Yes. Go to QA → Rubric Editor to add, remove, or reweight criteria. Changes apply to new calls immediately — historical scores are not retroactively updated."
      },
      {
        q: "What are 'coaching nudges'?",
        a: "After a QA score is generated, the AI produces 1–2 actionable coaching suggestions for the agent based on their lowest-scoring criteria. These appear on the agent's scorecard in QA → Scorecards."
      },
      {
        q: "Why does the leaderboard show 'N/A' for some agents?",
        a: "An agent shows N/A if they have fewer than 3 scored calls in the selected period. This prevents misleading rankings from single-call samples."
      },
    ],
  },
  {
    id: "analytics",
    label: "Analytics & Reports",
    icon: <BarChart2 size={16} />,
    color: "from-primary to-[var(--haip-primary-hover)]",
    faqs: [
      {
        q: "What is the difference between Analytics and Reports?",
        a: "Analytics shows live dashboards — KPI cards, trend charts, and leaderboards that auto-refresh every 5 minutes. Reports lets you build custom flat-file exports (CSV or JSON) with any combination of fields, filters, and date ranges."
      },
      {
        q: "How do I download a report?",
        a: "Go to Reports, select a report type (Calls, Inquiries, Guests, etc.), set the date range, choose the columns you want, apply any filters, then click Preview to check the first 50 rows. When ready, click Download CSV or Download JSON."
      },
      {
        q: "How often is the Analytics dashboard updated?",
        a: "Most KPI cards update every 5 minutes via server-sent events (SSE). The 'Lost reason clusters' chart updates weekly (Monday 6 AM) via Celery Beat. The QA leaderboard refreshes every hour."
      },
      {
        q: "Can I schedule reports to be emailed automatically?",
        a: "Scheduled report delivery is on the roadmap (Q3 2026). For now, enable the 'Weekly performance report' notification in Settings → Notifications and HAIP will send a digest every Monday morning."
      },
    ],
  },
  {
    id: "integrations",
    label: "Integrations",
    icon: <Plug2 size={16} />,
    color: "from-indigo-500 to-indigo-600",
    faqs: [
      {
        q: "Do I need a Meta (Facebook) developer app to connect WhatsApp?",
        a: "Yes — but it's your own Meta App, not HAIP's. Create a free Meta App at developers.facebook.com, add the WhatsApp product, and paste the Phone Number ID, WABA ID, and a permanent System User token into HAIP's WhatsApp integration form."
      },
      {
        q: "How often does the Hostaway sync run?",
        a: "Automatically every hour at :10 (e.g. 9:10, 10:10). You can also trigger a manual sync anytime from Integrations → Hostaway → Sync now."
      },
      {
        q: "What data does the PMS sync pull?",
        a: "For Hostaway and RentalWise: property listings (name, type, city, address), reservations (check-in/out dates, status, channel source, revenue), and guest details (name, phone, email). Guest phone numbers are deduplicated against existing HAIP guests."
      },
      {
        q: "My RentalWise credentials are correct but the connection fails. What should I check?",
        a: "Ensure your RentalWise account has Partners API access enabled (contact your RentalWise account manager). The base URL defaults to https://partners-api.rentalwise.com — only change it if your account uses a different endpoint."
      },
    ],
  },
  {
    id: "compliance",
    label: "Compliance & Privacy",
    icon: <Shield size={16} />,
    color: "from-red-500 to-red-600",
    faqs: [
      {
        q: "Is HAIP compliant with India's DPDP Act 2023?",
        a: "HAIP is built with DPDP compliance as a first-class requirement. Guest data is stored in ap-south-1 (Mumbai), PII is redacted before LLM processing, audit logs are hash-chained and append-only for 5 years, and data-deletion requests are fulfilled within 30 days."
      },
      {
        q: "How do I process a guest's data-deletion request?",
        a: "Go to Compliance → Data Rights Queue. Find the guest's request, review it, and click 'Process deletion'. This triggers a hard-delete chain: guest record, messages, call transcripts, consent records, and any S3 recordings are purged and a tombstone audit event is logged."
      },
      {
        q: "Where are call recordings stored?",
        a: "Call recordings stay at your IVR provider (CallerDesk/Acefone) and are accessed via a signed URL. HAIP does not copy or store the raw audio — only the transcript and derived analytics are stored in HAIP's database."
      },
      {
        q: "Who can access the Audit Log?",
        a: "Only users with the Compliance or Owner role can view the audit log. It is read-only and cannot be edited or deleted. Each event is SHA-256 hash-chained to the previous event, making tampering detectable."
      },
    ],
  },
];

// ---------------------------------------------------------------------------
// FAQ Item
// ---------------------------------------------------------------------------

function FAQItem({ q, a }: { q: string; a: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="border-b border-[var(--haip-border)] last:border-0">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-start justify-between gap-4 py-4 text-left group"
      >
        <span className="text-sm font-medium text-[var(--haip-fg)] group-hover:text-primary transition-colors">{q}</span>
        <span className="flex-shrink-0 mt-0.5">
          {open ? <ChevronUp size={15} className="text-primary" /> : <ChevronDown size={15} className="text-[var(--haip-fg-subtle)]" />}
        </span>
      </button>
      {open && (
        <p className="pb-4 text-sm text-[var(--haip-fg-muted)] leading-relaxed -mt-1">{a}</p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function HelpPage() {
  const [search, setSearch] = useState("");
  const [activeModule, setActiveModule] = useState<string | null>(null);

  const allFaqs = MODULES.flatMap(m => m.faqs.map(f => ({ ...f, module: m.label })));
  const searchResults = search.trim().length > 1
    ? allFaqs.filter(f => f.q.toLowerCase().includes(search.toLowerCase()) || f.a.toLowerCase().includes(search.toLowerCase()))
    : null;

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="px-6 py-6 bg-white border-b border-[var(--haip-border)]">
        <div className="max-w-2xl">
          <h1 className="haip-page-title">Help & Support</h1>
          <p className="text-sm text-[var(--haip-fg-subtle)] mt-0.5 mb-4">Find answers to common questions, or get in touch with our team</p>

          {/* Search */}
          <div className="relative">
            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--haip-fg-subtle)]" />
            <input
              type="text"
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Search FAQs… e.g. 'connect WhatsApp' or 'QA score'"
              className="w-full pl-10 pr-4 py-2.5 border border-[var(--haip-border)] rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 bg-white"
            />
            {search && (
              <button onClick={() => setSearch("")} className="absolute right-3 top-1/2 -translate-y-1/2 text-[var(--haip-fg-subtle)] hover:text-[var(--haip-fg-muted)]">
                ×
              </button>
            )}
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-3xl space-y-6">
          {/* Search results */}
          {searchResults !== null ? (
            <div className="bg-white rounded-2xl border border-[var(--haip-border)] shadow-sm p-5">
              <p className="text-xs font-bold text-[var(--haip-fg-subtle)] uppercase tracking-wider mb-1">
                {searchResults.length} result{searchResults.length !== 1 ? "s" : ""} for "{search}"
              </p>
              {searchResults.length === 0 ? (
                <div className="py-8 text-center text-[var(--haip-fg-subtle)]">
                  <HelpCircle size={32} className="mx-auto mb-3 opacity-30" />
                  <p className="text-sm">No FAQs match your search.</p>
                  <p className="text-xs mt-1">Try a different keyword or <a href="mailto:hello@haip.app" className="text-primary hover:underline">email support</a>.</p>
                </div>
              ) : (
                searchResults.map((f, i) => (
                  <div key={i}>
                    <p className="text-[10px] font-bold text-primary uppercase tracking-wider mt-3 mb-0.5">{f.module}</p>
                    <FAQItem q={f.q} a={f.a} />
                  </div>
                ))
              )}
            </div>
          ) : (
            <>
              {/* Module cards */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                {MODULES.map(m => (
                  <button
                    key={m.id}
                    onClick={() => setActiveModule(activeModule === m.id ? null : m.id)}
                    className={cn(
                      "flex flex-col items-center gap-2 p-4 rounded-2xl border transition-all text-center",
                      activeModule === m.id
                        ? "border-primary bg-[var(--haip-primary-tint)] shadow-sm"
                        : "bg-white border-[var(--haip-border)] hover:border-[color-mix(in_srgb,var(--primary)_25%,transparent)] hover:shadow-sm"
                    )}
                  >
                    <div className={cn("w-10 h-10 rounded-xl bg-gradient-to-br flex items-center justify-center text-white shadow-sm", m.color)}>
                      {m.icon}
                    </div>
                    <span className="text-xs font-semibold text-[var(--haip-fg-2)]">{m.label}</span>
                    <span className="text-[10px] text-[var(--haip-fg-subtle)]">{m.faqs.length} FAQs</span>
                  </button>
                ))}
              </div>

              {/* FAQ accordion for selected module, or all */}
              {MODULES.filter(m => !activeModule || m.id === activeModule).map(m => (
                <div key={m.id} className="bg-white rounded-2xl border border-[var(--haip-border)] shadow-sm overflow-hidden">
                  <div className={cn("px-5 py-4 bg-gradient-to-r text-white flex items-center gap-3", m.color)}>
                    {m.icon}
                    <span className="font-semibold text-sm">{m.label}</span>
                  </div>
                  <div className="px-5">
                    {m.faqs.map((faq, i) => (
                      <FAQItem key={i} q={faq.q} a={faq.a} />
                    ))}
                  </div>
                </div>
              ))}
            </>
          )}

          {/* Contact section */}
          <div className="rounded-2xl p-6 text-white" style={{ background: "linear-gradient(135deg, #0F766E, #0d9488)" }}>
            <div className="flex items-start gap-4">
              <div className="w-12 h-12 rounded-xl bg-primary/20 flex items-center justify-center flex-shrink-0">
                <Mail size={22} className="text-primary" />
              </div>
              <div className="flex-1">
                <h3 className="text-base font-bold mb-1">Still need help?</h3>
                <p className="text-sm text-slate-300 mb-4 leading-relaxed">
                  Our support team typically responds within 4 business hours. Include your workspace name and a brief description of the issue.
                </p>
                <div className="flex flex-wrap gap-3">
                  <a
                    href="mailto:hello@haip.app?subject=HAIP Support Request"
                    className="flex items-center gap-2 px-4 py-2.5 bg-primary hover:bg-primary text-white rounded-xl text-sm font-semibold transition-colors"
                  >
                    <Mail size={14} />
                    Email support
                  </a>
                  <a
                    href="https://wa.me/919999999999?text=Hi%20HAIP%20support"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-2 px-4 py-2.5 bg-white/10 hover:bg-white/20 text-white rounded-xl text-sm font-semibold transition-colors"
                  >
                    <MessageSquare size={14} />
                    WhatsApp support
                  </a>
                </div>
                <p className="text-xs text-slate-500 mt-4">
                  Support hours: Monday–Saturday, 9 AM – 7 PM IST
                  · hello@haip.app
                </p>
              </div>
            </div>
          </div>

          {/* Quick links */}
          <div className="grid grid-cols-2 gap-3">
            {[
              { label: "API Documentation",       href: "#", icon: <FileText size={14} /> },
              { label: "Changelog & releases",    href: "#", icon: <ExternalLink size={14} /> },
              { label: "Integrations guide",      href: "/dashboard/settings/integrations", icon: <Plug2 size={14} /> },
              { label: "Compliance centre",       href: "/dashboard/compliance", icon: <Shield size={14} /> },
            ].map(l => (
              <a
                key={l.label}
                href={l.href}
                className="flex items-center gap-2.5 bg-white rounded-xl border border-[var(--haip-border)] px-4 py-3 text-sm text-[var(--haip-fg-2)] hover:border-[color-mix(in_srgb,var(--primary)_25%,transparent)] hover:text-primary hover:shadow-sm transition-all group"
              >
                <span className="text-[var(--haip-fg-subtle)] group-hover:text-primary">{l.icon}</span>
                {l.label}
                <ChevronDown size={12} className="ml-auto rotate-[-90deg] text-[var(--haip-fg-subtle)]/70 group-hover:text-primary" />
              </a>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
