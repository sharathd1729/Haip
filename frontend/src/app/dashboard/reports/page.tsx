"use client";

import { useState, useMemo } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { FilterControl, activeFilters, type FilterDef, type FilterValue } from "@/components/reports/ReportFilters";
import { Phone, Users, MessageSquare, BarChart2, Star, Zap, Download, CheckSquare, Square, Loader2, AlertCircle, ChevronRight, FileText, RefreshCw, Check, FileSpreadsheet } from "@/lib/icons";

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

interface FieldDef {
  key: string;
  label: string;
  default: boolean;
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

// Raw shape returned by GET /reports/catalog -- the backend is the single
// source of truth for report ids/fields/filters, and it only lists the
// reports this person's role may run. Deriving REPORTS from the API response
// (never a second hand-kept copy) keeps the two in sync by construction.
interface CatalogEntry {
  id: string;
  name: string;
  description: string;
  icon: string;
  fields: FieldDef[];
  filters: FilterDef[];
}

interface PreviewMeta {
  total: number | null;   // exact match count; null where a report can't give one cheaply
  scope: "own" | "workspace";
}

interface Payload {
  report_id: string;
  fields: string[];
  date_from: string;
  date_to: string;
  filters: Record<string, FilterValue>;
}

// A download stops here, and says so up front rather than after the fact.
const MAX_DOWNLOAD_ROWS = 50_000;

const ICON_MAP: Record<string, React.ReactNode> = {
  phone: <Phone size={22} />,
  zap: <Zap size={22} />,
  users: <Users size={22} />,
  star: <Star size={22} />,
  "bar-chart": <BarChart2 size={22} />,
  "message-square": <MessageSquare size={22} />,
};

const GRADIENT_MAP: Record<string, string> = {
  calls: "from-blue-500 to-blue-600",
  inquiries: "from-teal-500 to-teal-600",
  guests: "from-violet-500 to-violet-600",
  qa_scores: "from-amber-500 to-amber-600",
  revenue: "from-green-500 to-green-600",
  whatsapp: "from-emerald-500 to-emerald-600",
  team: "from-indigo-500 to-indigo-600",
};

const DATE_HINT: Record<string, string> = {
  inquiries: "Filters by the day the enquiry came in (India time).",
  calls: "Filters by the day of the call.",
};

function catalogToReportDef(entry: CatalogEntry): ReportDef {
  return {
    id: entry.id,
    name: entry.name,
    description: entry.description,
    icon: ICON_MAP[entry.icon] ?? <FileText size={22} />,
    gradient: GRADIENT_MAP[entry.id] ?? "from-gray-500 to-gray-600",
    fields: entry.fields,
    filters: entry.filters ?? [],
  };
}

// Dates are India calendar days. toISOString() is UTC, which is a day behind
// for the first five and a half hours of every Indian morning.
const IST_DAY = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata", year: "numeric", month: "2-digit", day: "2-digit" });
function isoToday() {
  return IST_DAY.format(new Date());
}
function isoMinus(days: number) {
  return IST_DAY.format(new Date(Date.now() - days * 86_400_000));
}
function monthRange(offset: 0 | -1) {
  const [y, m] = isoToday().split("-").map(Number);
  const first = new Date(Date.UTC(y, m - 1 + offset, 1));
  const last = new Date(Date.UTC(y, m + offset, 0));
  return { from: first.toISOString().slice(0, 10), to: offset === 0 ? isoToday() : last.toISOString().slice(0, 10) };
}

const QUICK_RANGES: { label: string; range: () => { from: string; to: string } }[] = [
  { label: "Today",        range: () => ({ from: isoToday(),    to: isoToday() }) },
  { label: "Last 7 days",  range: () => ({ from: isoMinus(7),   to: isoToday() }) },
  { label: "Last 30 days", range: () => ({ from: isoMinus(30),  to: isoToday() }) },
  { label: "This month",   range: () => monthRange(0) },
  { label: "Last month",   range: () => monthRange(-1) },
  { label: "Last 90 days", range: () => ({ from: isoMinus(90),  to: isoToday() }) },
];

// One-click reports. Each fills in the type, dates, columns and filters, then
// shows the preview -- so the common asks ("leads who gave a number") don't
// need the four steps. A preset only appears if this person's catalog has the
// report and every filter it uses (an agent has no "owner" filter, for one).
interface Preset {
  id: string; label: string; hint: string; report: string;
  filters: Record<string, FilterValue>;
  range: () => { from: string; to: string };
  fields?: string[];
}

const LEAD_COLUMNS = ["created_at", "guest_name", "guest_phone", "source", "stage", "owner", "ai_summary", "next_step"];

const PRESETS: Preset[] = [
  {
    id: "phone-leads", label: "Leads who shared a phone number", hint: "This month, with owner and AI note",
    report: "inquiries", filters: { has_phone: "true" }, range: () => monthRange(0), fields: LEAD_COLUMNS,
  },
  {
    id: "leads-month", label: "All leads this month", hint: "Every channel, spam left out",
    report: "inquiries", filters: {}, range: () => monthRange(0), fields: LEAD_COLUMNS,
  },
  {
    id: "no-owner", label: "Leads with no owner yet", hint: "Last 30 days",
    report: "inquiries", filters: { owner: "unassigned" }, range: () => ({ from: isoMinus(30), to: isoToday() }), fields: LEAD_COLUMNS,
  },
  {
    id: "calls-week", label: "Calls, last 7 days", hint: "With agent, outcome and QA score",
    report: "calls", filters: {}, range: () => ({ from: isoMinus(7), to: isoToday() }),
  },
];

function extractErrorMessage(err: unknown): string {
  const e = err as { response?: { status?: number; data?: { detail?: unknown } }; message?: string } | null;
  const detail = e?.response?.data?.detail;
  const text = typeof detail === "string" ? detail
    : Array.isArray(detail) ? detail.map(d => (d as { msg?: string })?.msg).filter(Boolean).join("; ") : "";
  return text
    || (e?.response?.status ? `Server returned ${e.response.status}` : undefined)
    || e?.message
    || "Unknown error — check your connection and try again.";
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
  const [filterVals, setFilterVals]     = useState<Record<string, FilterValue>>({});
  const [preview, setPreview]           = useState<Record<string, unknown>[] | null>(null);
  const [previewCols, setPreviewCols]   = useState<string[]>([]);
  const [previewMeta, setPreviewMeta]   = useState<PreviewMeta>({ total: null, scope: "workspace" });

  const {
    data: catalogData, isLoading: catalogLoading, isError: catalogIsError, error: catalogError, refetch: refetchCatalog,
  } = useQuery({
    queryKey: ["reports-catalog"],
    queryFn: () => api.get<CatalogEntry[]>("/reports/catalog").then(r => r.data),
    staleTime: 5 * 60 * 1000,
    // Default is 3 retries with exponential backoff -- against a 20s axios
    // timeout that's several minutes of a silent spinner with no way out
    // before the user ever sees an error. One retry, then show it.
    retry: 1,
  });
  const REPORTS = useMemo(() => (catalogData ?? []).map(catalogToReportDef), [catalogData]);
  const presets = useMemo(
    () => PRESETS.filter(p => {
      const report = REPORTS.find(r => r.id === p.report);
      return !!report && Object.keys(p.filters).every(k => report.filters.some(f => f.key === k));
    }),
    [REPORTS],
  );

  // Columns go out in the report's own order, not the order they were ticked.
  function orderedFields(report: ReportDef, chosen: Set<string>) {
    return report.fields.filter(f => chosen.has(f.key)).map(f => f.key);
  }

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
      if (n.has(key)) n.delete(key); else n.add(key);
      return n;
    });
  }

  function applyRange(range: { from: string; to: string }) {
    setDateFrom(range.from);
    setDateTo(range.to);
  }

  function currentPayload(): Payload {
    return {
      report_id: selectedReport!.id,
      fields: orderedFields(selectedReport!, activeFields),
      date_from: dateFrom,
      date_to: dateTo,
      filters: activeFilters(filterVals),
    };
  }

  // Preview -- no mock-data fallback. This used to silently swap in generated
  // rows on any error, rendering fabricated numbers indistinguishable from
  // real ones. Surface the failure instead.
  const previewMutation = useMutation({
    mutationFn: (p: Payload) => api.post("/reports/preview", { ...p, limit: 10 }),
    onSuccess: (res, p) => {
      setPreview(res.data?.rows ?? []);
      setPreviewCols(p.fields);
      setPreviewMeta({ total: res.data?.total ?? null, scope: res.data?.scope ?? "workspace" });
      setStep(4);
    },
  });

  // `format` goes on the query string: the backend reads it via Query(), not
  // from the JSON body.
  const downloadMutation = useMutation({
    mutationFn: (fmt: "csv" | "json" | "xlsx") =>
      api.post(`/reports/download?format=${fmt}`, currentPayload(), { responseType: "blob" }),
    onSuccess: (res, fmt) => {
      const url = window.URL.createObjectURL(new Blob([res.data]));
      const a = document.createElement("a");
      const slug = selectedReport!.name.toLowerCase().replace(/[^a-z0-9]+/g, "_");
      a.href = url;
      a.download = `haip_${slug}_${dateFrom}_${dateTo}.${fmt}`;
      a.click();
      window.URL.revokeObjectURL(url);
    },
  });

  function applyPreset(p: Preset) {
    const report = REPORTS.find(r => r.id === p.report);
    if (!report) return;
    const keys = p.fields
      ? report.fields.filter(f => p.fields!.includes(f.key)).map(f => f.key)
      : report.fields.filter(f => f.default).map(f => f.key);
    const range = p.range();
    setSelectedReport(report);
    setActiveFields(new Set(keys));
    setFilterVals(p.filters);
    applyRange(range);
    setPreview(null);
    previewMutation.mutate({
      report_id: report.id, fields: keys, date_from: range.from, date_to: range.to, filters: p.filters,
    });
  }

  const canPreview = !!selectedReport && activeFields.size > 0;
  const filterCount = Object.keys(activeFilters(filterVals)).length;
  const noun = selectedReport?.id === "inquiries" ? "leads" : "rows";
  const total = previewMeta.total;
  const overCap = (total ?? 0) > MAX_DOWNLOAD_ROWS;

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="px-6 py-5 bg-white border-b border-gray-100 flex-shrink-0">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="haip-page-title">Reports</h1>
            <p className="text-sm text-gray-400 mt-0.5">
              Pick what you need, filter it down to exactly the rows you want, and download it as Excel or CSV.
            </p>
          </div>
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

          {/* Quick reports */}
          {presets.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-gray-600 uppercase tracking-wider mb-2">Quick reports</p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {presets.map(p => (
                  <button
                    key={p.id}
                    onClick={() => applyPreset(p)}
                    disabled={previewMutation.isPending}
                    className="flex items-center justify-between gap-3 px-4 py-3 rounded-xl border border-gray-200 bg-white text-left hover:border-teal-400 hover:shadow-sm transition-all disabled:opacity-60 outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
                  >
                    <span className="min-w-0">
                      <span className="block text-sm font-semibold text-gray-900 truncate">{p.label}</span>
                      <span className="block text-[11px] text-gray-500 mt-0.5">{p.hint}</span>
                    </span>
                    {previewMutation.isPending && previewMutation.variables?.filters === p.filters
                      ? <Loader2 size={14} className="animate-spin text-teal-600 flex-shrink-0" />
                      : <ChevronRight size={14} className="text-gray-300 flex-shrink-0" />}
                  </button>
                ))}
              </div>
              {previewMutation.isError && step !== 3 && (
                <div className="flex items-start gap-2 mt-3 px-4 py-3 bg-red-50 border border-red-200 rounded-xl text-sm text-red-700">
                  <AlertCircle size={15} className="flex-shrink-0 mt-0.5" />
                  <div>
                    <p className="font-medium">Couldn&apos;t load that report.</p>
                    <p className="text-xs text-red-600/80 mt-0.5">{extractErrorMessage(previewMutation.error)}</p>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* STEP 1 — Report type */}
          <Section
            title="1. Choose report type"
            done={step > 1}
            open={step >= 1}
            onEdit={() => setStep(1)}
            summary={selectedReport?.name}
          >
            {catalogLoading ? (
              <div className="flex items-center gap-2 text-sm text-gray-400 py-6">
                <Loader2 size={14} className="animate-spin" /> Loading report types…
              </div>
            ) : catalogIsError ? (
              <div className="flex items-start gap-3 px-4 py-3.5 bg-red-50 border border-red-200 rounded-xl text-sm text-red-700">
                <AlertCircle size={16} className="flex-shrink-0 mt-0.5" />
                <div className="flex-1">
                  <p className="font-medium">Couldn&apos;t load report types.</p>
                  <p className="text-xs text-red-600/80 mt-0.5">{extractErrorMessage(catalogError)}</p>
                </div>
                <button
                  onClick={() => refetchCatalog()}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-white border border-red-300 text-red-700 rounded-lg text-xs font-semibold hover:bg-red-100 transition-colors flex-shrink-0"
                >
                  <RefreshCw size={12} /> Retry
                </button>
              </div>
            ) : REPORTS.length === 0 ? (
              <p className="text-sm text-gray-500 py-4">No reports are available for your role. Ask an owner or manager for access.</p>
            ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
              {REPORTS.map(r => (
                <button
                  key={r.id}
                  onClick={() => selectReport(r)}
                  className={cn(
                    "flex items-start gap-3 p-4 min-h-[64px] rounded-2xl border-2 text-left transition-all",
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
            )}
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
                    onClick={() => applyRange(r.range())}
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
              {selectedReport && DATE_HINT[selectedReport.id] && (
                <p className="text-[11px] text-gray-400">{DATE_HINT[selectedReport.id]} Both days are included.</p>
              )}
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
            summary={step > 3 ? `${activeFields.size} columns${filterCount ? ` · ${filterCount} filter${filterCount === 1 ? "" : "s"}` : ""}` : undefined}
          >
            {selectedReport && (
              <div className="space-y-5">
                {/* Filters first: they decide which rows you get. */}
                {selectedReport.filters.length > 0 && (
                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <p className="text-xs font-semibold text-gray-600 uppercase tracking-wider">Filters <span className="font-normal text-gray-400 normal-case">(optional)</span></p>
                      {filterCount > 0 && (
                        <button onClick={() => setFilterVals({})} className="text-[11px] text-gray-400 hover:text-gray-700 hover:underline">
                          Clear all
                        </button>
                      )}
                    </div>
                    <div className="space-y-3">
                      {selectedReport.filters.map(f => (
                        <div key={f.key} className={cn(f.type === "boolean" && "flex items-center justify-between gap-3")}>
                          <label className={cn("text-xs font-medium text-gray-600", f.type === "boolean" ? "" : "block mb-1.5")}>{f.label}</label>
                          <FilterControl
                            def={f}
                            value={filterVals[f.key]}
                            onChange={v => setFilterVals(prev => ({ ...prev, [f.key]: v }))}
                          />
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Columns */}
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
                            "flex items-center gap-2 px-3 min-h-11 sm:min-h-0 sm:py-2.5 rounded-xl border text-sm transition-all text-left",
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

                <button
                  onClick={() => previewMutation.mutate(currentPayload())}
                  disabled={!canPreview || previewMutation.isPending}
                  className="flex items-center gap-2 px-5 py-2.5 bg-teal-500 text-white rounded-xl text-sm font-semibold hover:bg-teal-600 transition-colors disabled:opacity-50"
                >
                  {previewMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
                  Preview & count
                </button>

                {previewMutation.isError && (
                  <div className="flex items-start gap-2 px-4 py-3 bg-red-50 border border-red-200 rounded-xl text-sm text-red-700">
                    <AlertCircle size={15} className="flex-shrink-0 mt-0.5" />
                    <div>
                      <p className="font-medium">Couldn&apos;t load preview.</p>
                      <p className="text-xs text-red-600/80 mt-0.5">
                        {extractErrorMessage(previewMutation.error)}
                      </p>
                    </div>
                  </div>
                )}
              </div>
            )}
          </Section>

          {/* STEP 4 — Preview & download */}
          {step >= 4 && preview && (
            <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
              <div className="px-5 py-4 border-b border-gray-100 flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="text-sm font-semibold text-gray-800">
                    {total != null
                      ? `${total.toLocaleString("en-IN")} ${total === 1 ? noun.replace(/s$/, "") : noun} match`
                      : "4. Preview & download"}
                    {previewMeta.scope === "own" && (
                      <span className="ml-2 text-[11px] font-medium text-teal-700 bg-teal-50 px-2 py-0.5 rounded-full">Yours only</span>
                    )}
                  </p>
                  <p className="text-xs text-gray-400 mt-0.5">
                    Showing the first {preview.length} · {previewCols.length} columns · {dateFrom} → {dateTo}
                    {filterCount > 0 && ` · ${filterCount} filter${filterCount === 1 ? "" : "s"}`}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => downloadMutation.mutate("xlsx")}
                    disabled={downloadMutation.isPending || preview.length === 0}
                    className="flex items-center gap-1.5 px-4 min-h-11 sm:min-h-0 sm:py-2 bg-green-600 text-white rounded-xl text-xs font-semibold hover:bg-green-700 transition-colors disabled:opacity-50"
                  >
                    {downloadMutation.isPending ? <Loader2 size={12} className="animate-spin" /> : <FileSpreadsheet size={12} />}
                    Excel
                  </button>
                  <button
                    onClick={() => downloadMutation.mutate("csv")}
                    disabled={downloadMutation.isPending || preview.length === 0}
                    className="flex items-center gap-1.5 px-4 min-h-11 sm:min-h-0 sm:py-2 bg-teal-500 text-white rounded-xl text-xs font-semibold hover:bg-teal-600 transition-colors disabled:opacity-50"
                  >
                    {downloadMutation.isPending ? <Loader2 size={12} className="animate-spin" /> : <Download size={12} />}
                    CSV
                  </button>
                  <button
                    onClick={() => downloadMutation.mutate("json")}
                    disabled={downloadMutation.isPending || preview.length === 0}
                    className="flex items-center gap-1.5 px-4 min-h-11 sm:min-h-0 sm:py-2 bg-white border border-gray-200 text-gray-600 rounded-xl text-xs font-semibold hover:border-gray-300 transition-colors disabled:opacity-50"
                  >
                    JSON
                  </button>
                </div>
              </div>

              {overCap && (
                <div className="flex items-start gap-2 mx-5 mt-4 px-4 py-3 bg-amber-50 border border-amber-200 rounded-xl text-sm text-amber-800">
                  <AlertCircle size={15} className="flex-shrink-0 mt-0.5" />
                  <p>
                    More than {MAX_DOWNLOAD_ROWS.toLocaleString("en-IN")} rows match. A download stops at {MAX_DOWNLOAD_ROWS.toLocaleString("en-IN")} — narrow the dates or add a filter to get the rest.
                  </p>
                </div>
              )}

              {downloadMutation.isError && (
                <div className="flex items-start gap-2 mx-5 mt-4 px-4 py-3 bg-red-50 border border-red-200 rounded-xl text-sm text-red-700">
                  <AlertCircle size={15} className="flex-shrink-0 mt-0.5" />
                  <div>
                    <p className="font-medium">Download failed.</p>
                    <p className="text-xs text-red-600/80 mt-0.5">{extractErrorMessage(downloadMutation.error)}</p>
                  </div>
                </div>
              )}

              {preview.length === 0 && (
                <div className="mx-5 my-4 px-4 py-6 text-center text-sm text-gray-400 bg-gray-50 rounded-xl">
                  Nothing matches these dates and filters — try a wider date range or clear a filter.
                </div>
              )}

              {/* Table */}
              {preview.length > 0 && (
              <>
              {/* Phones and tablets: each row as a card (first column as the title), so nothing scrolls sideways; the table from lg up */}
              <ul className="divide-y divide-gray-100 lg:hidden">
                {preview.map((row, i) => (
                  <li key={i} className="px-4 py-3">
                    <p className="text-sm font-semibold text-gray-900 break-words">{String(row[previewCols[0]] ?? "—")}</p>
                    <dl className="mt-1.5 grid grid-cols-2 gap-x-3 gap-y-1.5 text-xs md:grid-cols-4">
                      {previewCols.slice(1).filter(c => row[c] != null && row[c] !== "").map(c => (
                        <div key={c} className="min-w-0">
                          <dt className="text-[10px] uppercase tracking-wide text-gray-400">{selectedReport?.fields.find(f => f.key === c)?.label ?? c}</dt>
                          <dd className="text-gray-700 break-words">{String(row[c] ?? "—")}</dd>
                        </div>
                      ))}
                    </dl>
                  </li>
                ))}
              </ul>
              <div className="hidden lg:block overflow-x-auto">
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
              </>
              )}

              <div className="px-5 py-3 bg-gray-50 border-t border-gray-100 flex items-center justify-between">
                <p className="text-[11px] text-gray-400">The preview shows a few rows. The download has every matching row.</p>
                <button
                  onClick={() => { setStep(1); setSelectedReport(null); setPreview(null); setFilterVals({}); }}
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
