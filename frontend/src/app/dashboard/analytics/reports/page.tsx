"use client";

/**
 * /dashboard/analytics/reports — Report Generation & History
 * Phase 5: Generate, view, and email business intelligence reports.
 */

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  FileText, Download, Mail, Loader2, RefreshCw,
  BarChart2, Users, Building2, DollarSign, Search, Calendar,
  TrendingUp, CheckCircle2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import api from "@/lib/api";

// ─── Types ──────────────────────────────────────────────────────────────────

interface ReportListItem {
  id: string;
  report_type: string;
  title: string;
  period_start: string;
  period_end: string;
  has_pdf: boolean;
  email_sent_at: string | null;
  created_at: string;
}

// ─── Report type config ──────────────────────────────────────────────────────

const REPORT_CFG: Record<string, { label: string; desc: string; icon: React.ReactNode; color: string }> = {
  executive: {
    label: "Executive Report",
    desc: "6 KPIs, top finding, recommendations",
    icon: <BarChart2 size={18} />,
    color: "text-teal-600 bg-teal-50 border-teal-200",
  },
  weekly: {
    label: "Weekly Digest",
    desc: "7-day deltas, top win, top concern",
    icon: <Calendar size={18} />,
    color: "text-indigo-600 bg-indigo-50 border-indigo-200",
  },
  monthly: {
    label: "Monthly Report",
    desc: "Full portfolio analysis across 10 domains",
    icon: <TrendingUp size={18} />,
    color: "text-purple-600 bg-purple-50 border-purple-200",
  },
  revenue: {
    label: "Revenue Report",
    desc: "MTD vs forecast, channel mix, property breakdown",
    icon: <DollarSign size={18} />,
    color: "text-green-600 bg-green-50 border-green-200",
  },
  inquiry: {
    label: "Inquiry Report",
    desc: "Funnel, lost reasons, agent leaderboard",
    icon: <Search size={18} />,
    color: "text-amber-600 bg-amber-50 border-amber-200",
  },
  property: {
    label: "Property Report",
    desc: "RevPAR matrix, occupancy, dynamic pricing",
    icon: <Building2 size={18} />,
    color: "text-blue-600 bg-blue-50 border-blue-200",
  },
  guest: {
    label: "Guest Report",
    desc: "Top guests, churn risk, LTV cohorts",
    icon: <Users size={18} />,
    color: "text-rose-600 bg-rose-50 border-rose-200",
  },
};

const REPORT_TYPES = Object.keys(REPORT_CFG);

// ─── Page ────────────────────────────────────────────────────────────────────

export default function ReportsPage() {
  const qc = useQueryClient();
  const [previewHtml, setPreviewHtml] = useState<string | null>(null);
  const [previewTitle, setPreviewTitle] = useState("");
  const [sendEmail, setSendEmail] = useState(false);
  const [generating, setGenerating] = useState<string | null>(null);

  const { data: reportsList, isLoading } = useQuery<{ reports: ReportListItem[] }>({
    queryKey: ["reports-list"],
    queryFn: () => api.get("/analytics/reports").then(r => r.data),
    staleTime: 60_000,
  });

  const generateMutation = useMutation({
    mutationFn: ({ report_type }: { report_type: string }) =>
      api.post("/analytics/reports/generate", {
        report_type,
        range_days: 30,
        send_email: sendEmail,
      }).then(r => r.data),
    onSuccess: (data) => {
      setPreviewHtml(data.html);
      setPreviewTitle(data.title);
      setGenerating(null);
      qc.invalidateQueries({ queryKey: ["reports-list"] });
    },
    onError: () => setGenerating(null),
  });

  async function handleGenerate(type: string) {
    setGenerating(type);
    generateMutation.mutate({ report_type: type });
  }

  async function handleViewReport(id: string, title: string) {
    try {
      const res = await api.get(`/analytics/reports/${id}/html`);
      setPreviewHtml(typeof res.data === "string" ? res.data : res.data.html || "");
      setPreviewTitle(title);
    } catch (e) {
      console.error("Failed to load report", e);
    }
  }

  function handleDownload() {
    if (!previewHtml) return;
    const blob = new Blob([previewHtml], { type: "text/html" });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement("a");
    a.href     = url;
    a.download = `${previewTitle.replace(/[^a-z0-9]/gi, "_").toLowerCase()}.html`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 tracking-tight">Reports</h1>
          <p className="text-[12px] mt-0.5 text-gray-400">
            Generate intelligence reports — weekly auto-delivery every Monday
          </p>
        </div>
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-1.5 text-xs text-gray-500 cursor-pointer">
            <input type="checkbox" checked={sendEmail} onChange={e => setSendEmail(e.target.checked)}
              className="rounded" />
            Email on generate
          </label>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">

        {/* Left: report generator + history */}
        <div className="lg:col-span-2 space-y-5">

          {/* Report type cards */}
          <div>
            <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide mb-2">Generate Report</p>
            <div className="space-y-2">
              {REPORT_TYPES.map(type => {
                const cfg = REPORT_CFG[type];
                const isGenerating = generating === type;
                return (
                  <div key={type}
                    className={cn("flex items-center gap-3 bg-white border rounded-xl px-4 py-3", cfg.color)}>
                    <span className="shrink-0">{cfg.icon}</span>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-semibold text-gray-800">{cfg.label}</p>
                      <p className="text-[11px] text-gray-400 truncate">{cfg.desc}</p>
                    </div>
                    <button
                      onClick={() => handleGenerate(type)}
                      disabled={generateMutation.isPending}
                      className={cn(
                        "shrink-0 text-xs font-medium px-3 py-1.5 rounded-lg border transition-all",
                        isGenerating
                          ? "bg-gray-100 text-gray-400 border-gray-100"
                          : "bg-white text-gray-700 border-gray-200 hover:border-teal-300 hover:text-teal-700",
                      )}
                    >
                      {isGenerating ? <Loader2 size={12} className="animate-spin" /> : "Generate"}
                    </button>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Report history */}
          <div>
            <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide mb-2">Report History</p>
            {isLoading ? (
              <div className="space-y-2">
                {[1,2,3].map(i => <div key={i} className="h-14 bg-gray-100 rounded-xl animate-pulse" />)}
              </div>
            ) : reportsList?.reports.length === 0 ? (
              <div className="bg-gray-50 border border-gray-100 rounded-xl p-6 text-center">
                <FileText size={20} className="text-gray-300 mx-auto mb-2" />
                <p className="text-xs text-gray-400">No reports yet. Generate your first report above.</p>
              </div>
            ) : (
              <div className="space-y-1.5">
                {reportsList?.reports.map(r => {
                  const cfg = REPORT_CFG[r.report_type] ?? REPORT_CFG.executive;
                  return (
                    <button key={r.id}
                      onClick={() => handleViewReport(r.id, r.title)}
                      className="w-full text-left bg-white border border-gray-100 rounded-xl px-4 py-2.5 hover:border-teal-200 transition-all group">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <span className={cn("text-xs", cfg.color.split(" ")[0])}>{cfg.icon}</span>
                          <p className="text-xs font-medium text-gray-700 group-hover:text-teal-700 truncate max-w-[160px]">
                            {r.title}
                          </p>
                        </div>
                        <div className="flex items-center gap-1.5 ml-2 shrink-0">
                          {r.email_sent_at && (
                            <span title="Emailed"><Mail size={10} className="text-teal-400" /></span>
                          )}
                          <span className="text-[9px] text-gray-400">
                            {r.created_at ? new Date(r.created_at).toLocaleDateString() : ""}
                          </span>
                        </div>
                      </div>
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        {/* Right: report preview */}
        <div className="lg:col-span-3">
          {previewHtml ? (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <p className="text-sm font-semibold text-gray-800 truncate flex-1">{previewTitle}</p>
                <div className="flex items-center gap-2 shrink-0 ml-2">
                  <button onClick={handleDownload}
                    className="flex items-center gap-1.5 text-xs font-medium text-gray-600 bg-white border border-gray-200 px-3 py-1.5 rounded-lg hover:border-teal-300 hover:text-teal-700 transition-all">
                    <Download size={12} /> Download
                  </button>
                  <button onClick={() => { setPreviewHtml(null); setPreviewTitle(""); }}
                    className="text-xs text-gray-400 hover:text-gray-600">
                    Close
                  </button>
                </div>
              </div>
              <iframe
                srcDoc={previewHtml}
                className="w-full rounded-2xl border border-gray-100 shadow-sm"
                style={{ height: "calc(100vh - 200px)", minHeight: 500 }}
                title={previewTitle}
              />
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center h-full min-h-[400px] bg-white border border-gray-100 rounded-2xl">
              <FileText size={32} className="text-gray-200 mb-3" />
              <p className="text-sm font-medium text-gray-500">Select or generate a report</p>
              <p className="text-xs text-gray-400 mt-1">Reports open in preview here</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
