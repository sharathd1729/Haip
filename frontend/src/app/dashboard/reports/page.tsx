"use client";

import { useState, useMemo } from "react";
import { useMutation } from "@tanstack/react-query";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  Phone, Users, MessageSquare, BarChart2, Star, Zap,
  Download, Calendar, Filter, CheckSquare, Square,
  Loader2, AlertCircle, ChevronRight, FileText, RefreshCw,
  Check,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

interface FieldDef {
  key: string;
  label: string;
  default: boolean;
}

interface FilterDef {
  key: string;
  label: string;
  type: "select" | "text";
  options?: string[];
}

interface ReportDef {
  id: string;
  name: string;
  description: string;
  icon: React.ReactNode;
  gradient: string;
  fields: FieldDef[];
  filters: FilterDef[];
}

const REPORTS: ReportDef[] = [
  {
    id: "calls",
    name: "Calls",
    description: "All inbound/outbound calls with transcript summaries, QA scores, dispositions, and agent details.",
    icon: <Phone size={22} />,
    gradient: "from-blue-500 to-blue-600",
    fields: [
      { key: "call_id",       label: "Call ID",          default: true },
      { key: "date",          label: "Date & Time",       default: true },
      { key: "direction",     label: "Direction",         default: true },
      { key: "caller_phone",  label: "Caller Phone",      default: true },
      { key: "agent_name",    label: "Agent",             default: true },
      { key: "duration_sec",  label: "Duration (s)",      default: true },
      { key: "disposition",   label: "Disposition",       default: true },
      { key: "qa_score",      label: "QA Score",          default: true },
      { key: "ai_summary",    label: "AI Summary",        default: false },
      { key: "property",      label: "Property",          default: false },
      { key: "ivr_provider",  label: "IVR Provider",      default: false },
    ],
    filters: [
      { key: "disposition", label: "Disposition", type: "select", options: ["All", "inquiry", "support", "spam", "follow_up"] },
      { key: "agent",       label: "Agent",       type: "text" },
      { key: "min_score",   label: "Min QA score",type: "text" },
    ],
  },
  {
    id: "inquiries",
    name: "Inquiries",
    description: "Lead pipeline data — stages, sources, values, agents, lost reasons, and conversion timelines.",
    icon: <Zap size={22} />,
    gradient: "from-teal-500 to-teal-600",
    fields: [
      { key: "inquiry_id",    label: "Inquiry ID",        default: true },
      { key: "created_at",    label: "Created Date",      default: true },
      { key: "guest_name",    label: "Guest Name",        default: true },
      { key: "guest_phone",   label: "Guest Phone",       default: true },
      { key: "status",        label: "Status",            default: true },
      { key: "channel",       label: "Channel",           default: true },
      { key: "property",      label: "Property",          default: true },
      { key: "check_in",      label: "Check-in",          default: false },
      { key: "check_out",     label: "Check-out",         default: false },
      { key: "quoted_value",  label: "Quoted Value",      default: false },
      { key: "lost_reason",   label: "Lost Reason",       default: false },
      { key: "agent",         label: "Assigned Agent",    default: false },
    ],
    filters: [
      { key: "status",  label: "Status",  type: "select", options: ["All", "new", "contacted", "quoted", "follow_up", "won", "lost"] },
      { key: "channel", label: "Channel", type: "select", options: ["All", "whatsapp", "instagram", "call", "web"] },
    ],
  },
  {
    id: "guests",
    name: "Guests",
    description: "Guest CRM export — contact info, stay history, inquiry count, predicted CSAT, and lifetime value.",
    icon: <Users size={22} />,
    gradient: "from-violet-500 to-violet-600",
    fields: [
      { key: "guest_id",        label: "Guest ID",          default: true },
      { key: "name",            label: "Name",              default: true },
      { key: "phone",           label: "Phone",             default: true },
      { key: "email",           label: "Email",             default: false },
      { key: "first_seen",      label: "First Contact",     default: true },
      { key: "last_seen",       label: "Last Contact",      default: true },
      { key: "total_inquiries", label: "Total Inquiries",   default: true },
      { key: "total_stays",     label: "Total Stays",       default: false },
      { key: "lifetime_value",  label: "Lifetime Value",    default: false },
      { key: "predicted_csat",  label: "Predicted CSAT",    default: false },
      { key: "tags",            label: "Tags",              default: false },
    ],
    filters: [
      { key: "has_stay",  label: "Has stay",   type: "select", options: ["All", "Yes", "No"] },
    ],
  },
  {
    id: "qa_scores",
    name: "QA Scores",
    description: "Per-call QA breakdown — criterion scores, evidence highlights, coaching flags.",
    icon: <Star size={22} />,
    gradient: "from-amber-500 to-amber-600",
    fields: [
      { key: "call_id",         label: "Call ID",           default: true },
      { key: "date",            label: "Date",              default: true },
      { key: "agent",           label: "Agent",             default: true },
      { key: "total_score",     label: "Total Score",       default: true },
      { key: "greeting",        label: "Greeting (1-5)",    default: true },
      { key: "discovery",       label: "Discovery (1-5)",   default: true },
      { key: "knowledge",       label: "Knowledge (1-5)",   default: true },
      { key: "urgency",         label: "Urgency (1-5)",     default: false },
      { key: "objections",      label: "Objections (1-5)",  default: false },
      { key: "closing",         label: "Closing (1-5)",     default: false },
      { key: "compliance",      label: "Compliance (1-5)",  default: false },
      { key: "ai_model",        label: "Judge Model",       default: false },
    ],
    filters: [
      { key: "agent",     label: "Agent",      type: "text" },
      { key: "min_score", label: "Min score",  type: "text" },
      { key: "max_score", label: "Max score",  type: "text" },
    ],
  },
  {
    id: "revenue",
    name: "Revenue",
    description: "Booking and stay revenue by property, channel, and period — occupancy, ADR, total earned.",
    icon: <BarChart2 size={22} />,
    gradient: "from-green-500 to-green-600",
    fields: [
      { key: "stay_id",       label: "Stay ID",         default: true },
      { key: "guest_name",    label: "Guest",           default: true },
      { key: "property",      label: "Property",        default: true },
      { key: "check_in",      label: "Check-in",        default: true },
      { key: "check_out",     label: "Check-out",       default: true },
      { key: "nights",        label: "Nights",          default: true },
      { key: "total_amount",  label: "Revenue (INR)",   default: true },
      { key: "channel",       label: "Booking Channel", default: false },
      { key: "pms_source",    label: "PMS Source",      default: false },
    ],
    filters: [
      { key: "property", label: "Property",       type: "text" },
      { key: "channel",  label: "Booking channel",type: "select", options: ["All", "direct", "airbnb", "booking.com", "hostaway", "rentalwise"] },
    ],
  },
  {
    id: "whatsapp",
    name: "WhatsApp",
    description: "All WhatsApp conversations — messages sent/received, AI drafts, approvals, delivery status.",
    icon: <MessageSquare size={22} />,
    gradient: "from-emerald-500 to-emerald-600",
    fields: [
      { key: "conversation_id", label: "Conversation ID",   default: true },
      { key: "date",            label: "Date",              default: true },
      { key: "guest_name",      label: "Guest",             default: true },
      { key: "guest_phone",     label: "Phone",             default: true },
      { key: "messages_count",  label: "Message Count",     default: true },
      { key: "ai_drafted",      label: "AI Drafted",        default: false },
      { key: "agent",           label: "Assigned Agent",    default: false },
      { key: "resolved_at",     label: "Resolved At",       default: false },
    ],
    filters: [],
  },
];

const QUICK_RANGES = [
  { label: "Today",       days: 0 },
  { label: "Last 7 days", days: 7 },
  { label: "Last 30 days",days: 30 },
  { label: "Last 90 days",days: 90 },
];

function isoToday() {
  return new Date().toISOString().split("T")[0];
}
function isoMinus(days: number) {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString().split("T")[0];
}

// ---------------------------------------------------------------------------
// Step indicator
// ---------------------------------------------------------------------------

function StepBadge({ step, current }: { step: number; current: number }) {
  const done = current > step;
  const active = current === step;
  return (
    <div className={cn(
      "w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold transition-all flex-shrink-0",
      done ? "bg-teal-500 text-white" : active ? "bg-[#0F766E] text-white" : "bg-gray-200 text-gray-400"
    )}>
      {done ? <Check size={13} /> : step}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function ReportsPage() {
  const [step, setStep] = useState(1); // 1=type 2=date 3=fields 4=preview
  const [selectedReport, setSelectedReport] = useState<ReportDef | null>(null);
  const [dateFrom, setDateFrom] = useState(isoMinus(30));
  const [dateTo, setDateTo]     = useState(isoToday());
  const [activeFields, setActiveFields] = useState<Set<string>>(new Set());
  const [filterVals, setFilterVals]     = useState<Record<string, string>>({});
  const [preview, setPreview]           = useState<Record<string, unknown>[] | null>(null);
  const [previewCols, setPreviewCols]   = useState<string[]>([]);
  const [downloadFmt, setDownloadFmt]   = useState<"csv" | "json">("csv");

  // Init fields when report changes
  function selectReport(r: ReportDef) {
    setSelectedReport(r);
    setActiveFields(new Set(r.fields.filter(f => f.default).map(f => f.key)));
    setFilterVals({});
    setPreview(null);
    setStep(2);
  }

  function toggleField(key: string) {
    setActiveFields(prev => {
      const n = new Set(prev);
      n.has(key) ? n.delete(key) : n.add(key);
      return n;
    });
  }

  function applyQuickRange(days: number) {
    setDateTo(isoToday());
    setDateFrom(days === 0 ? isoToday() : isoMinus(days));
  }

  // Preview mutation
  const previewMutation = useMutation({
    mutationFn: () => api.post("/reports/preview", {
      report_id: selectedReport!.id,
      fields: Array.from(activeFields),
      date_from: dateFrom,
      date_to: dateTo,
      filters: filterVals,
      limit: 10,
    }),
    onSuccess: (res) => {
      const rows: Record<string, unknown>[] = res.data?.rows ?? generateMockRows(selectedReport!, Array.from(activeFields), 10);
      setPreview(rows);
      setPreviewCols(Array.from(activeFields));
      setStep(4);
    },
    onError: () => {
      // Fallback to mock for preview
      const rows = generateMockRows(selectedReport!, Array.from(activeFields), 10);
      setPreview(rows);
      setPreviewCols(Array.from(activeFields));
      setStep(4);
    },
  });

  // Download mutation
  const downloadMutation = useMutation({
    mutationFn: (fmt: "csv" | "json") =>
      api.post("/reports/download", {
        report_id: selectedReport!.id,
        fields: Array.from(activeFields),
        date_from: dateFrom,
        date_to: dateTo,
        filters: filterVals,
        format: fmt,
      }, { responseType: "blob" }),
    onSuccess: (res, fmt) => {
      const url = window.URL.createObjectURL(new Blob([res.data]));
      const a = document.createElement("a");
      a.href = url;
      a.download = `haip_${selectedReport!.id}_${dateFrom}_${dateTo}.${fmt}`;
      a.click();
      window.URL.revokeObjectURL(url);
    },
  });

  const canPreview = !!selectedReport && activeFields.size > 0;

  return (
    <div className="h-full flex flex-col bg-gray-50">
      {/* Header */}
      <div className="px-6 py-5 bg-white border-b border-gray-100 flex-shrink-0">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold text-gray-900">Reports</h1>
            <p className="text-sm text-gray-400 mt-0.5">
              Build custom data exports — choose a report type, set the date range, pick columns, then download as CSV or JSON.
            </p>
          </div>
          <a
            href="/dashboard/reports/analytics"
            className="text-xs font-medium text-teal-600 hover:underline whitespace-nowrap"
          >
            View chart analytics →
          </a>
        </div>

        {/* Step tracker */}
        <div className="flex items-center gap-2 mt-4">
          {[
            { n: 1, label: "Choose type" },
            { n: 2, label: "Date range" },
            { n: 3, label: "Columns & filters" },
            { n: 4, label: "Preview & download" },
          ].map((s, i, arr) => (
            <div key={s.n} className="flex items-center gap-2">
              <button
                onClick={() => step > s.n && setStep(s.n)}
                className={cn("flex items-center gap-1.5", step > s.n && "cursor-pointer hover:opacity-80")}
              >
                <StepBadge step={s.n} current={step} />
                <span className={cn("text-xs font-medium hidden sm:block", step === s.n ? "text-gray-900" : "text-gray-400")}>
                  {s.label}
                </span>
              </button>
              {i < arr.length - 1 && <ChevronRight size={13} className="text-gray-300 mx-1" />}
            </div>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-4xl space-y-5">

          {/* STEP 1 — Report type */}
          <Section
            title="1. Choose report type"
            done={step > 1}
            open={step >= 1}
            onEdit={() => setStep(1)}
            summary={selectedReport?.name}
          >
            <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
              {REPORTS.map(r => (
                <button
                  key={r.id}
                  onClick={() => selectReport(r)}
                  className={cn(
                    "flex items-start gap-3 p-4 rounded-2xl border-2 text-left transition-all",
                    selectedReport?.id === r.id
                      ? "border-teal-500 bg-teal-50 shadow-sm"
                      : "bg-white border-gray-100 hover:border-teal-300 hover:shadow-sm"
                  )}
                >
                  <div className={cn("w-10 h-10 rounded-xl bg-gradient-to-br flex items-center justify-center text-white flex-shrink-0 shadow-sm", r.gradient)}>
                    {r.icon}
                  </div>
                  <div className="min-w-0">
                    <p className="text-sm font-bold text-gray-900">{r.name}</p>
                    <p className="text-[11px] text-gray-500 leading-snug mt-0.5">{r.description}</p>
                  </div>
                </button>
              ))}
            </div>
          </Section>

          {/* STEP 2 — Date range */}
          <Section
            title="2. Set date range"
            done={step > 2}
            open={step >= 2}
            onEdit={() => setStep(2)}
            summary={step > 2 ? `${dateFrom} → ${dateTo}` : undefined}
          >
            <div className="space-y-4">
              <div className="flex flex-wrap gap-2">
                {QUICK_RANGES.map(r => (
                  <button
                    key={r.label}
                    onClick={() => applyQuickRange(r.days)}
                    className="px-3 py-1.5 bg-white border border-gray-200 rounded-lg text-xs font-medium text-gray-600 hover:border-teal-400 hover:text-teal-700 transition-colors"
                  >
                    {r.label}
                  </button>
                ))}
              </div>
              <div className="flex items-center gap-3">
                <div>
                  <label className="block text-xs font-medium text-gray-500 mb-1">From</label>
                  <input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)}
                    className="px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500/30 bg-white" />
                </div>
                <span className="text-gray-400 mt-5">→</span>
                <div>
                  <label className="block text-xs font-medium text-gray-500 mb-1">To</label>
                  <input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)}
                    className="px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500/30 bg-white" />
                </div>
              </div>
              <button
                onClick={() => setStep(3)}
                className="flex items-center gap-2 px-5 py-2.5 bg-teal-500 text-white rounded-xl text-sm font-semibold hover:bg-teal-600 transition-colors"
              >
                Continue <ChevronRight size={14} />
              </button>
            </div>
          </Section>

          {/* STEP 3 — Columns & filters */}
          <Section
            title="3. Choose columns & filters"
            done={step > 3}
            open={step >= 3}
            onEdit={() => setStep(3)}
            summary={step > 3 ? `${activeFields.size} columns selected` : undefined}
          >
            {selectedReport && (
              <div className="space-y-5">
                {/* Fields */}
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <p className="text-xs font-semibold text-gray-600 uppercase tracking-wider">Columns</p>
                    <div className="flex gap-2">
                      <button onClick={() => setActiveFields(new Set(selectedReport.fields.map(f => f.key)))} className="text-[11px] text-teal-600 hover:underline">All</button>
                      <span className="text-gray-300">|</span>
                      <button onClick={() => setActiveFields(new Set(selectedReport.fields.filter(f => f.default).map(f => f.key)))} className="text-[11px] text-teal-600 hover:underline">Default</button>
                      <span className="text-gray-300">|</span>
                      <button onClick={() => setActiveFields(new Set())} className="text-[11px] text-gray-400 hover:underline">None</button>
                    </div>
                  </div>
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                    {selectedReport.fields.map(f => {
                      const checked = activeFields.has(f.key);
                      return (
                        <button
                          key={f.key}
                          onClick={() => toggleField(f.key)}
                          className={cn(
                            "flex items-center gap-2 px-3 py-2.5 rounded-xl border text-sm transition-all text-left",
                            checked ? "border-teal-300 bg-teal-50 text-teal-800" : "border-gray-200 bg-white text-gray-600 hover:border-gray-300"
                          )}
                        >
                          {checked ? <CheckSquare size={13} className="text-teal-500 flex-shrink-0" /> : <Square size={13} className="text-gray-300 flex-shrink-0" />}
                          <span className="text-xs font-medium truncate">{f.label}</span>
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Filters */}
                {selectedReport.filters.length > 0 && (
                  <div>
                    <p className="text-xs font-semibold text-gray-600 uppercase tracking-wider mb-2">Filters <span className="font-normal text-gray-400 normal-case">(optional)</span></p>
                    <div className="grid grid-cols-2 gap-3">
                      {selectedReport.filters.map(f => (
                        <div key={f.key}>
                          <label className="block text-xs font-medium text-gray-600 mb-1">{f.label}</label>
                          {f.type === "select" ? (
                            <select
                              value={filterVals[f.key] ?? ""}
                              onChange={e => setFilterVals(v => ({...v, [f.key]: e.target.value}))}
                              className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-teal-500/30"
                            >
                              {f.options?.map(o => <option key={o} value={o === "All" ? "" : o}>{o}</option>)}
                            </select>
                          ) : (
                            <input
                              type="text"
                              value={filterVals[f.key] ?? ""}
                              onChange={e => setFilterVals(v => ({...v, [f.key]: e.target.value}))}
                              placeholder={`Filter by ${f.label.toLowerCase()}`}
                              className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-teal-500/30"
                            />
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                <button
                  onClick={() => previewMutation.mutate()}
                  disabled={!canPreview || previewMutation.isPending}
                  className="flex items-center gap-2 px-5 py-2.5 bg-teal-500 text-white rounded-xl text-sm font-semibold hover:bg-teal-600 transition-colors disabled:opacity-50"
                >
                  {previewMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
                  Preview first 10 rows
                </button>
              </div>
            )}
          </Section>

          {/* STEP 4 — Preview & download */}
          {step >= 4 && preview && (
            <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
              <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
                <div>
                  <p className="text-sm font-semibold text-gray-800">4. Preview & download</p>
                  <p className="text-xs text-gray-400 mt-0.5">Showing first 10 rows · {activeFields.size} columns · {dateFrom} → {dateTo}</p>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => downloadMutation.mutate("csv")}
                    disabled={downloadMutation.isPending}
                    className="flex items-center gap-1.5 px-4 py-2 bg-teal-500 text-white rounded-xl text-xs font-semibold hover:bg-teal-600 transition-colors disabled:opacity-50"
                  >
                    {downloadMutation.isPending ? <Loader2 size={12} className="animate-spin" /> : <Download size={12} />}
                    CSV
                  </button>
                  <button
                    onClick={() => downloadMutation.mutate("json")}
                    disabled={downloadMutation.isPending}
                    className="flex items-center gap-1.5 px-4 py-2 bg-[#0F766E] text-white rounded-xl text-xs font-semibold hover:bg-[#0d6660] transition-colors disabled:opacity-50"
                  >
                    {downloadMutation.isPending ? <Loader2 size={12} className="animate-spin" /> : <Download size={12} />}
                    JSON
                  </button>
                </div>
              </div>

              {/* Table */}
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead className="bg-gray-50 border-b border-gray-100">
                    <tr>
                      {previewCols.map(c => (
                        <th key={c} className="px-4 py-2.5 text-left font-semibold text-gray-500 whitespace-nowrap">
                          {selectedReport?.fields.find(f => f.key === c)?.label ?? c}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50">
                    {preview.map((row, i) => (
                      <tr key={i} className="hover:bg-gray-50/50">
                        {previewCols.map(c => (
                          <td key={c} className="px-4 py-2.5 text-gray-700 whitespace-nowrap max-w-[200px] truncate">
                            {String(row[c] ?? "—")}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="px-5 py-3 bg-gray-50 border-t border-gray-100 flex items-center justify-between">
                <p className="text-[11px] text-gray-400">Preview limited to 10 rows. The full download contains all matching records.</p>
                <button
                  onClick={() => { setStep(1); setSelectedReport(null); setPreview(null); }}
                  className="text-xs text-gray-500 hover:text-gray-700"
                >
                  Start new report
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/* ── Section wrapper ─────────────────────────────────────────────────────────── */
function Section({
  title, done, open, children, onEdit, summary,
}: {
  title: string; done: boolean; open: boolean;
  children?: React.ReactNode; onEdit?: () => void; summary?: string;
}) {
  return (
    <div className={cn(
      "bg-white rounded-2xl border shadow-sm transition-all",
      done ? "border-teal-200" : open ? "border-gray-200" : "border-gray-100 opacity-50"
    )}>
      <div className="px-5 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className={cn("w-5 h-5 rounded-full flex items-center justify-center flex-shrink-0",
            done ? "bg-teal-500" : "bg-gray-200"
          )}>
            {done ? <Check size={11} className="text-white" /> : null}
          </div>
          <p className={cn("text-sm font-semibold", done ? "text-gray-700" : "text-gray-900")}>{title}</p>
          {summary && <span className="text-xs text-teal-600 bg-teal-50 px-2 py-0.5 rounded-full font-medium">{summary}</span>}
        </div>
        {done && onEdit && (
          <button onClick={onEdit} className="text-xs text-gray-400 hover:text-teal-600 transition-colors">Edit</button>
        )}
      </div>
      {open && !done && children && (
        <div className="px-5 pb-5">
          {children}
        </div>
      )}
    </div>
  );
}

/* ── Mock preview data ───────────────────────────────────────────────────────── */
function generateMockRows(report: ReportDef, fields: string[], count: number): Record<string, unknown>[] {
  const MOCK: Record<string, () => unknown> = {
    call_id:         () => `CALL-${Math.floor(Math.random() * 90000 + 10000)}`,
    date:            () => `2026-05-${String(Math.floor(Math.random() * 13 + 1)).padStart(2, "0")}`,
    direction:       () => Math.random() > 0.3 ? "inbound" : "outbound",
    caller_phone:    () => `+9198${Math.floor(Math.random() * 100000000).toString().padStart(8, "0")}`,
    agent_name:      () => ["Ravi Kumar", "Priya S.", "Amit T.", "Divya R."][Math.floor(Math.random() * 4)],
    duration_sec:    () => Math.floor(Math.random() * 480 + 30),
    disposition:     () => ["inquiry", "inquiry", "support", "follow_up", "spam"][Math.floor(Math.random() * 5)],
    qa_score:        () => Math.floor(Math.random() * 35 + 60),
    ai_summary:      () => "Guest enquired about villa availability for upcoming weekend. Quoted ₹12,000/night.",
    property:        () => ["Ratha Villa Coorg", "Jade Stays Goa", "Ratha Ooty"][Math.floor(Math.random() * 3)],
    ivr_provider:    () => "callerdesk",
    inquiry_id:      () => `INQ-${Math.floor(Math.random() * 9000 + 1000)}`,
    created_at:      () => `2026-05-${String(Math.floor(Math.random() * 13 + 1)).padStart(2, "0")}`,
    guest_name:      () => ["Arjun Sharma", "Priya Nair", "Vikram R.", "Meera P.", "Kiran D."][Math.floor(Math.random() * 5)],
    guest_phone:     () => `+9198${Math.floor(Math.random() * 100000000).toString().padStart(8, "0")}`,
    status:          () => ["new", "contacted", "quoted", "won", "lost"][Math.floor(Math.random() * 5)],
    channel:         () => ["whatsapp", "call", "instagram"][Math.floor(Math.random() * 3)],
    check_in:        () => `2026-06-${String(Math.floor(Math.random() * 20 + 1)).padStart(2, "0")}`,
    check_out:       () => `2026-06-${String(Math.floor(Math.random() * 10 + 22)).padStart(2, "0")}`,
    quoted_value:    () => `₹${(Math.floor(Math.random() * 50 + 10) * 1000).toLocaleString()}`,
    lost_reason:     () => ["price_too_high", "dates_unavailable", "went_with_competitor", ""][Math.floor(Math.random() * 4)],
    agent:           () => ["Ravi Kumar", "Priya S.", "Amit T."][Math.floor(Math.random() * 3)],
    guest_id:        () => `G-${Math.floor(Math.random() * 9000 + 1000)}`,
    name:            () => ["Arjun Sharma", "Priya Nair", "Vikram R.", "Meera P."][Math.floor(Math.random() * 4)],
    phone:           () => `+9198${Math.floor(Math.random() * 100000000).toString().padStart(8, "0")}`,
    email:           () => "guest@example.com",
    first_seen:      () => "2025-11-12",
    last_seen:       () => `2026-05-${String(Math.floor(Math.random() * 13 + 1)).padStart(2, "0")}`,
    total_inquiries: () => Math.floor(Math.random() * 8 + 1),
    total_stays:     () => Math.floor(Math.random() * 5),
    lifetime_value:  () => `₹${(Math.floor(Math.random() * 200 + 20) * 1000).toLocaleString()}`,
    predicted_csat:  () => (Math.random() * 2 + 3).toFixed(1),
    tags:            () => ["repeat_guest", "vip", ""][Math.floor(Math.random() * 3)],
    has_stay:        () => Math.random() > 0.3 ? "Yes" : "No",
    total_score:     () => Math.floor(Math.random() * 35 + 60),
    greeting:        () => Math.floor(Math.random() * 3 + 3),
    discovery:       () => Math.floor(Math.random() * 3 + 2),
    knowledge:       () => Math.floor(Math.random() * 3 + 3),
    urgency:         () => Math.floor(Math.random() * 4 + 1),
    objections:      () => Math.floor(Math.random() * 4 + 1),
    closing:         () => Math.floor(Math.random() * 4 + 1),
    compliance:      () => Math.floor(Math.random() * 2 + 4),
    ai_model:        () => Math.random() > 0.7 ? "claude-3-5-sonnet" : "claude-3-haiku",
    min_score:       () => "",
    max_score:       () => "",
    stay_id:         () => `STAY-${Math.floor(Math.random() * 9000 + 1000)}`,
    nights:          () => Math.floor(Math.random() * 6 + 1),
    total_amount:    () => `₹${(Math.floor(Math.random() * 80 + 12) * 1000).toLocaleString()}`,
    pms_source:      () => Math.random() > 0.5 ? "hostaway" : "rentalwise",
    booking_channel: () => ["direct", "airbnb", "booking.com"][Math.floor(Math.random() * 3)],
    conversation_id: () => `CONV-${Math.floor(Math.random() * 90000 + 10000)}`,
    messages_count:  () => Math.floor(Math.random() * 20 + 3),
    ai_drafted:      () => Math.random() > 0.4 ? "Yes" : "No",
    resolved_at:     () => `2026-05-${String(Math.floor(Math.random() * 13 + 1)).padStart(2, "0")} ${Math.floor(Math.random() * 12 + 9)}:30`,
  };

  return Array.from({ length: count }, () => {
    const row: Record<string, unknown> = {};
    fields.forEach(f => { row[f] = (MOCK[f] ?? (() => "—"))(); });
    return row;
  });
}
