"use client";

/**
 * A1 — KPI card drill-down side panel.
 *
 * Renders a right-side panel with 4 breakdown views when a KPI card is clicked:
 *   By Property | By Agent | By Hour of Day | By Channel
 */

import { useState } from "react";
import { X, Download, ChevronDown } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { cn } from "@/lib/utils";

// ─── Types ────────────────────────────────────────────────────────────────────

interface DrillPoint {
  label: string;
  value: number;
  count: number;
}

interface MetricDrillData {
  metric_key: string;
  metric_label: string;
  unit: string;
  by_property: DrillPoint[];
  by_agent: DrillPoint[];
  by_hour: DrillPoint[];
  by_channel: DrillPoint[];
}

type BreakdownKey = "by_property" | "by_agent" | "by_hour" | "by_channel";

const BREAKDOWN_LABELS: Record<BreakdownKey, string> = {
  by_property: "Property",
  by_agent: "Agent",
  by_hour: "Hour of day",
  by_channel: "Channel",
};

const RANGE_OPTIONS = [
  { value: "7", label: "Last 7 days" },
  { value: "14", label: "Last 14 days" },
  { value: "30", label: "Last 30 days" },
  { value: "90", label: "Last 90 days" },
];

// ─── Bar chart (pure CSS, no recharts dep) ────────────────────────────────────

function HorizontalBarChart({ data, unit }: { data: DrillPoint[]; unit: string }) {
  if (!data.length) {
    return <p className="text-sm text-gray-400 py-6 text-center">No data for this breakdown</p>;
  }
  const max = Math.max(...data.map(d => d.value), 1);
  return (
    <div className="space-y-2.5">
      {data.map((d, i) => (
        <div key={i} className="flex items-center gap-3">
          <span className="w-28 text-xs text-gray-600 truncate text-right flex-shrink-0">{d.label}</span>
          <div className="flex-1 h-5 bg-gray-100 rounded-full overflow-hidden">
            <div
              className="h-full rounded-full bg-indigo-500 transition-all duration-500"
              style={{ width: `${(d.value / max) * 100}%` }}
            />
          </div>
          <span className="w-16 text-xs text-gray-500 font-mono text-right flex-shrink-0">
            {unit === "s"
              ? `${Math.round(d.value)}s`
              : unit === "%"
              ? `${d.value.toFixed(1)}%`
              : unit === "₹"
              ? `₹${(d.value / 1000).toFixed(0)}k`
              : d.value.toFixed(1)}
          </span>
        </div>
      ))}
    </div>
  );
}

// ─── CSV export helper ────────────────────────────────────────────────────────

function exportCSV(data: MetricDrillData, breakdown: BreakdownKey, rangeDays: string) {
  const rows = data[breakdown];
  if (!rows.length) return;

  const header = `# Metric: ${data.metric_label}\n# Breakdown: ${BREAKDOWN_LABELS[breakdown]}\n# Range: Last ${rangeDays} days\n# Generated: ${new Date().toISOString()}\n`;
  const cols = "Label,Value,Count\n";
  const body = rows.map(r => `"${r.label}",${r.value},${r.count}`).join("\n");
  const csv = header + cols + body;

  const blob = new Blob([csv], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `haip_${data.metric_key}_${breakdown}_${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

// ─── Panel ────────────────────────────────────────────────────────────────────

interface MetricDrillDownProps {
  metricKey: string;
  metricLabel: string;
  onClose: () => void;
}

export function MetricDrillDown({ metricKey, metricLabel, onClose }: MetricDrillDownProps) {
  const [breakdown, setBreakdown] = useState<BreakdownKey>("by_property");
  const [rangeDays, setRangeDays] = useState("7");

  const { data, isLoading } = useQuery<MetricDrillData>({
    queryKey: ["metric-drill", metricKey, rangeDays],
    queryFn: () =>
      api.get(`/analytics/metrics/${metricKey}/drill?range_days=${rangeDays}`).then(r => r.data),
    staleTime: 60_000,
  });

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40 bg-black/20 backdrop-blur-[1px]"
        onClick={onClose}
      />

      {/* Side panel */}
      <div className="fixed right-0 top-0 bottom-0 z-50 w-[480px] max-w-[95vw] bg-white shadow-2xl flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100 flex-shrink-0">
          <div>
            <h2 className="text-base font-bold text-gray-900">{metricLabel}</h2>
            <p className="text-xs text-gray-400 mt-0.5">Drill-down breakdown</p>
          </div>
          <div className="flex items-center gap-2">
            {/* Range selector */}
            <div className="relative">
              <select
                value={rangeDays}
                onChange={e => setRangeDays(e.target.value)}
                className="appearance-none text-xs bg-gray-100 text-gray-700 px-3 py-1.5 pr-6 rounded-lg font-medium cursor-pointer focus:outline-none focus:ring-2 focus:ring-indigo-500"
              >
                {RANGE_OPTIONS.map(o => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
              <ChevronDown size={10} className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
            </div>
            {/* Export */}
            {data && (
              <button
                onClick={() => exportCSV(data, breakdown, rangeDays)}
                title="Export breakdown CSV"
                className="w-8 h-8 flex items-center justify-center rounded-lg text-gray-400 hover:text-gray-700 hover:bg-gray-100 transition-colors"
              >
                <Download size={14} />
              </button>
            )}
            {/* Close */}
            <button
              onClick={onClose}
              className="w-8 h-8 flex items-center justify-center rounded-lg text-gray-400 hover:text-gray-700 hover:bg-gray-100 transition-colors"
            >
              <X size={16} />
            </button>
          </div>
        </div>

        {/* Breakdown tabs */}
        <div className="flex items-center gap-1 px-5 py-3 border-b border-gray-100 flex-shrink-0">
          {(Object.keys(BREAKDOWN_LABELS) as BreakdownKey[]).map(key => (
            <button
              key={key}
              onClick={() => setBreakdown(key)}
              className={cn(
                "text-xs font-medium px-3 py-1.5 rounded-lg transition-colors",
                breakdown === key
                  ? "bg-indigo-100 text-indigo-700"
                  : "text-gray-500 hover:bg-gray-100"
              )}
            >
              {BREAKDOWN_LABELS[key]}
            </button>
          ))}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-5">
          {isLoading ? (
            <div className="space-y-3">
              {Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="flex items-center gap-3">
                  <div className="w-28 h-4 bg-gray-100 rounded animate-pulse" />
                  <div className="flex-1 h-5 bg-gray-100 rounded-full animate-pulse" />
                  <div className="w-16 h-4 bg-gray-100 rounded animate-pulse" />
                </div>
              ))}
            </div>
          ) : data ? (
            <HorizontalBarChart data={data[breakdown]} unit={data.unit} />
          ) : (
            <p className="text-sm text-gray-400 py-6 text-center">Failed to load data</p>
          )}
        </div>

        {/* Footer */}
        <div className="px-5 py-3 border-t border-gray-100 flex-shrink-0">
          <p className="text-[11px] text-gray-400">
            Data aggregated across all agents and properties unless filtered.
          </p>
        </div>
      </div>
    </>
  );
}
