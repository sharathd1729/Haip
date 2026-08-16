"use client";

import { useState, useMemo } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  Phone, Users, MessageSquare, BarChart2, Star, Zap,
  Download, Calendar, Filter, CheckSquare, Square,
  Loader2, AlertCircle, ChevronRight, FileText, RefreshCw,
  Check, FileSpreadsheet,
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
  type: "select" | "text" | "number" | "boolean";
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

// Raw shape returned by GET /reports/catalog -- the backend is the single
// source of truth for report ids/fields/filters. We used to keep a second,
// hand-maintained copy of this catalog here with different field keys than
// the backend's fetch_* functions actually produce, so every preview/download
// silently dropped almost every column. Deriving REPORTS from the API
// response instead of duplicating it keeps the two in sync by construction.
interface CatalogEntry {
  id: string;
  name: string;
  description: string;
  icon: string;
  fields: FieldDef[];
  filters: { key: string; label: string; type: string; options?: string[] }[];
}

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

function catalogToReportDef(entry: CatalogEntry): ReportDef {
  return {
    id: entry.id,
    name: entry.name,
    description: entry.description,
    icon: ICON_MAP[entry.icon] ?? <FileText size={22} />,
    gradient: GRADIENT_MAP[entry.id] ?? "from-gray-500 to-gray-600",
    fields: entry.fields,
    filters: (entry.filters as FilterDef[]) ?? [],
  };
}

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

function extractErrorMessage(err: unknown): string {
  const e = err as { response?: { status?: number; data?: { detail?: string } }; message?: string } | null;
  return e?.response?.data?.detail
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
  const [filterVals, setFilterVals]     = useState<Record<string, string>>({});
  const [preview, setPreview]           = useState<Record<string, unknown>[] | null>(null);
  const [previewCols, setPreviewCols]   = useState<string[]>([]);

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

  // Preview mutation — no mock-data fallback. This used to silently swap in
  // generateMockRows() on any error (including a plain network blip), which
  // rendered fabricated numbers indistinguishable from real ones with zero
  // indication anything was wrong. An owner could easily read fake revenue/
  // guest data as real. Surface the failure instead.
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
      const rows: Record<string, unknown>[] = res.data?.rows ?? [];
      setPreview(rows);
      setPreviewCols(Array.from(activeFields));
      setStep(4);
    },
  });

  // Download mutation — `format` must go on the query string: the backend
  // endpoint reads it via FastAPI's Query(), not from the JSON body, so
  // passing it inside the POST body was silently dropped and every download
  // came back as CSV regardless of which button was clicked.
  const downloadMutation = useMutation({
    mutationFn: (fmt: "csv" | "json" | "xlsx") =>
      api.post(`/reports/download?format=${fmt}`, {
        report_id: selectedReport!.id,
        fields: Array.from(activeFields),
        date_from: dateFrom,
        date_to: dateTo,
        filters: filterVals,
      }, { responseType: "blob" }),
    onSuccess: (res, fmt) => {
      const url = window.URL.createObjectURL(new Blob([res.data]));
      const a = document.createElement("a");
      a.href = url;
      a.download = `haip_${selectedReport!.id}_${dateFrom}_${dateTo}.${fmt}`;
      a.click();
      window.URL.revokeObjectURL(url);
    },
    // No onSuccess-only feedback before this meant a failed download just
    // sat there silently — button re-enables, nothing downloads, no
    // indication why. isError below surfaces it instead.
  });

  const canPreview = !!selectedReport && activeFields.size > 0;

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="px-6 py-5 bg-white border-b border-gray-100 flex-shrink-0">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="haip-page-title">Reports</h1>
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
            {catalogLoading ? (
              <div className="flex items-center gap-2 text-sm text-gray-400 py-6">
                <Loader2 size={14} className="animate-spin" /> Loading report types…
              </div>
            ) : catalogIsError ? (
              <div className="flex items-start gap-3 px-4 py-3.5 bg-red-50 border border-red-200 rounded-xl text-sm text-red-700">
                <AlertCircle size={16} className="flex-shrink-0 mt-0.5" />
                <div className="flex-1">
                  <p className="font-medium">Couldn't load report types.</p>
                  <p className="text-xs text-red-600/80 mt-0.5">{extractErrorMessage(catalogError)}</p>
                </div>
                <button
                  onClick={() => refetchCatalog()}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-white border border-red-300 text-red-700 rounded-lg text-xs font-semibold hover:bg-red-100 transition-colors flex-shrink-0"
                >
                  <RefreshCw size={12} /> Retry
                </button>
              </div>
            ) : (
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
                              <option value="">All</option>
                              {f.options?.filter(o => o !== "All").map(o => <option key={o} value={o}>{o}</option>)}
                            </select>
                          ) : f.type === "boolean" ? (
                            <select
                              value={filterVals[f.key] ?? ""}
                              onChange={e => setFilterVals(v => ({...v, [f.key]: e.target.value}))}
                              className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-teal-500/30"
                            >
                              <option value="">All</option>
                              <option value="true">Yes</option>
                              <option value="false">No</option>
                            </select>
                          ) : (
                            <input
                              type={f.type === "number" ? "number" : "text"}
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

                {previewMutation.isError && (
                  <div className="flex items-start gap-2 px-4 py-3 bg-red-50 border border-red-200 rounded-xl text-sm text-red-700">
                    <AlertCircle size={15} className="flex-shrink-0 mt-0.5" />
                    <div>
                      <p className="font-medium">Couldn't load preview.</p>
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
                    onClick={() => downloadMutation.mutate("xlsx")}
                    disabled={downloadMutation.isPending}
                    className="flex items-center gap-1.5 px-4 py-2 bg-green-600 text-white rounded-xl text-xs font-semibold hover:bg-green-700 transition-colors disabled:opacity-50"
                  >
                    {downloadMutation.isPending ? <Loader2 size={12} className="animate-spin" /> : <FileSpreadsheet size={12} />}
                    Excel
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
                <div className="mx-5 mt-4 px-4 py-6 text-center text-sm text-gray-400 bg-gray-50 rounded-xl">
                  No records match this date range and filters — nothing to download.
                </div>
              )}

              {/* Table */}
              {preview.length > 0 && (
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
              )}

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
