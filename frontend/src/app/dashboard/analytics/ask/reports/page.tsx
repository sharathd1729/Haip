"use client";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, Sparkles, Mail, Loader2, Clock, X } from "lucide-react";
import { useRouter } from "next/navigation";
import api from "@/lib/api";
import { cn } from "@/lib/utils";

const REPORT_TYPES: { value: string; label: string; description: string }[] = [
  { value: "executive", label: "Executive Summary", description: "Cross-domain headline metrics and top signals" },
  { value: "weekly",    label: "Weekly Recap",       description: "Last 7 days across revenue, occupancy, inquiries" },
  { value: "monthly",   label: "Monthly Recap",      description: "Month-to-date performance and trend" },
  { value: "property",  label: "Property Performance", description: "Per-property occupancy and revenue breakdown" },
  { value: "guest",     label: "Guest Insights",     description: "Guest value, repeat rate, satisfaction signals" },
  { value: "revenue",   label: "Revenue Deep-Dive",  description: "Revenue trend, forecast, and property split" },
  { value: "inquiry",   label: "Inquiry & Funnel",   description: "Pipeline health, conversion, lost reasons" },
];

interface ReportSummary {
  id: string;
  report_type: string;
  title: string;
  period_start: string;
  period_end: string;
  created_at: string;
}

interface GeneratedReport {
  id: string;
  title: string;
  report_type: string;
  html: string;
  created_at: string | null;
}

export default function AskHaipReportsPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [reportType, setReportType] = useState("executive");
  const [rangeDays, setRangeDays] = useState(30);
  const [sendEmail, setSendEmail] = useState(false);
  const [viewing, setViewing] = useState<GeneratedReport | null>(null);

  const { data: reportsData, isLoading: loadingList } = useQuery<{ reports: ReportSummary[] }>({
    queryKey: ["ask-haip-reports"],
    queryFn: () => api.get("/ask/reports").then(r => r.data),
  });
  const reports = reportsData?.reports ?? [];

  const generate = useMutation({
    mutationFn: () =>
      api.post<GeneratedReport>("/ask/reports/generate", {
        report_type: reportType,
        range_days: rangeDays,
        send_email: sendEmail,
      }).then(r => r.data),
    onSuccess: (report) => {
      queryClient.invalidateQueries({ queryKey: ["ask-haip-reports"] });
      setViewing(report);
    },
  });

  const viewReport = useMutation({
    mutationFn: (id: string) =>
      api.get(`/ask/reports/${id}/html`, { responseType: "text" }).then(r => r.data as string),
  });

  async function openReport(r: ReportSummary) {
    const html = await viewReport.mutateAsync(r.id);
    setViewing({ id: r.id, title: r.title, report_type: r.report_type, html, created_at: r.created_at });
  }

  return (
    <div className="flex flex-col h-full bg-[#F8FAFC]">
      <div className="flex-shrink-0 px-6 py-3 flex items-center justify-between" style={{ background: "#FFFFFF", borderBottom: "1px solid #E5E7EB" }}>
        <div>
          <h1 className="text-base font-bold" style={{ fontFamily: "var(--font-display), sans-serif", color: "#111827" }}>
            Ask HAIP Reports
          </h1>
          <p className="text-xs mt-0.5 text-gray-500">Generate and review AI-written business reports</p>
        </div>
        <button
          onClick={() => router.push("/dashboard/ask-haip")}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold"
          style={{ border: "1px solid #0F766E", color: "#0F766E" }}
        >
          <Sparkles size={12} /> Ask a question instead
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-6 grid grid-cols-1 lg:grid-cols-3 gap-5">
        {/* Generate panel */}
        <div className="lg:col-span-1 bg-white rounded-2xl border p-5 h-fit" style={{ borderColor: "#E5E7EB" }}>
          <p className="text-xs font-semibold text-gray-700 mb-3">Generate a new report</p>

          <div className="space-y-2 mb-4">
            {REPORT_TYPES.map(t => (
              <button
                key={t.value}
                onClick={() => setReportType(t.value)}
                className={cn(
                  "w-full text-left px-3 py-2.5 rounded-xl border transition-colors",
                  reportType === t.value ? "border-teal-600 bg-teal-50" : "border-gray-200 hover:bg-gray-50"
                )}
              >
                <p className="text-[12.5px] font-semibold text-gray-800">{t.label}</p>
                <p className="text-[10.5px] text-gray-500 mt-0.5">{t.description}</p>
              </button>
            ))}
          </div>

          <label className="block text-[11px] font-semibold text-gray-600 mb-1">Range</label>
          <select
            value={rangeDays}
            onChange={e => setRangeDays(Number(e.target.value))}
            className="w-full px-3 py-2 rounded-xl text-sm border mb-3"
            style={{ borderColor: "#E5E7EB" }}
          >
            <option value={7}>Last 7 days</option>
            <option value={30}>Last 30 days</option>
            <option value={90}>Last 90 days</option>
          </select>

          <label className="flex items-center gap-2 text-[11.5px] text-gray-600 mb-4">
            <input type="checkbox" checked={sendEmail} onChange={e => setSendEmail(e.target.checked)} />
            <Mail size={12} /> Email me a copy
          </label>

          {generate.isError && (
            <p className="text-xs text-red-600 mb-2">Failed to generate report. Please try again.</p>
          )}

          <button
            onClick={() => generate.mutate()}
            disabled={generate.isPending}
            className="w-full py-2.5 rounded-xl text-sm font-semibold text-white transition-colors disabled:opacity-40 flex items-center justify-center gap-2"
            style={{ background: "#0F766E" }}
          >
            {generate.isPending && <Loader2 size={14} className="animate-spin" />}
            Generate Report
          </button>
        </div>

        {/* Existing reports list */}
        <div className="lg:col-span-2 bg-white rounded-2xl border p-5" style={{ borderColor: "#E5E7EB" }}>
          <p className="text-xs font-semibold text-gray-700 mb-3">Recent reports</p>
          {loadingList ? (
            <div className="space-y-2">
              {[...Array(4)].map((_, i) => <div key={i} className="h-14 bg-gray-100 rounded-xl animate-pulse" />)}
            </div>
          ) : reports.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 gap-2 text-center">
              <FileText size={28} className="text-gray-300" />
              <p className="text-sm text-gray-400">No reports generated yet</p>
            </div>
          ) : (
            <div className="space-y-2">
              {reports.map(r => (
                <button
                  key={r.id}
                  onClick={() => openReport(r)}
                  className="w-full flex items-center justify-between px-4 py-3 rounded-xl border hover:bg-gray-50 transition-colors text-left"
                  style={{ borderColor: "#F3F4F6" }}
                >
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0" style={{ background: "rgba(15,118,110,0.08)" }}>
                      <FileText size={14} style={{ color: "#0F766E" }} />
                    </div>
                    <div>
                      <p className="text-[13px] font-semibold text-gray-800">{r.title}</p>
                      <p className="text-[10.5px] text-gray-400 flex items-center gap-1 mt-0.5">
                        <Clock size={10} /> {r.created_at ? new Date(r.created_at).toLocaleString("en-IN") : "—"}
                      </p>
                    </div>
                  </div>
                  <span className="text-[10px] font-medium px-2 py-1 rounded-full" style={{ background: "#F3F4F6", color: "#6B7280" }}>
                    {REPORT_TYPES.find(t => t.value === r.report_type)?.label ?? r.report_type}
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Report viewer modal */}
      {viewing && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-3xl h-[85vh] flex flex-col overflow-hidden" style={{ border: "1px solid #E5E7EB" }}>
            <div className="flex items-center justify-between px-5 py-3 flex-shrink-0" style={{ background: "#F9FAFB", borderBottom: "1px solid #E5E7EB" }}>
              <p className="text-sm font-bold text-gray-800">{viewing.title}</p>
              <button onClick={() => setViewing(null)} className="w-7 h-7 rounded-lg flex items-center justify-center text-gray-400 hover:text-gray-700">
                <X size={15} />
              </button>
            </div>
            <iframe
              srcDoc={viewing.html}
              sandbox=""
              className="flex-1 w-full"
              style={{ border: "none" }}
              title={viewing.title}
            />
          </div>
        </div>
      )}
    </div>
  );
}
