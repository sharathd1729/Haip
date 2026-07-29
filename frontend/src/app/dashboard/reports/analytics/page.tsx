"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  LineChart, Line, Legend,
} from "recharts";
import api from "@/lib/api";
import { Skeleton } from "@/components/ui/skeleton";

function isoToday() { return new Date().toISOString().slice(0, 10); }
function isoMinus(days: number) {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString().slice(0, 10);
}

interface SourceRow {
  source: string;
  total_leads: number;
  converted: number;
  conversion_rate: number;
}

interface FunnelRow {
  date: string;
  total_leads: number;
  valid: number;
  invalid: number;
  converted: number;
}

interface OccupancyDay {
  date: string;
  occupied_properties: number;
  total_properties: number;
  occupancy_pct: number;
}

function ChartCard({ title, subtitle, children }: { title: string; subtitle: string; children: React.ReactNode }) {
  return (
    <div className="bg-white border border-gray-100 rounded-xl p-5">
      <h2 className="text-sm font-semibold text-gray-900">{title}</h2>
      <p className="text-xs text-gray-400 mt-0.5 mb-4">{subtitle}</p>
      <div style={{ height: 280 }}>{children}</div>
    </div>
  );
}

export default function ReportsAnalyticsPage() {
  const [dateFrom, setDateFrom] = useState(isoMinus(30));
  const [dateTo, setDateTo] = useState(isoToday());

  const sourceQ = useQuery({
    queryKey: ["reports", "lead-source-breakdown", dateFrom, dateTo],
    queryFn: async () => {
      const res = await api.get("/reports/lead-source-breakdown", { params: { date_from: dateFrom, date_to: dateTo } });
      return res.data.sources as SourceRow[];
    },
  });

  const funnelQ = useQuery({
    queryKey: ["reports", "lead-funnel-daily", dateFrom, dateTo],
    queryFn: async () => {
      const res = await api.get("/reports/lead-funnel-daily", { params: { date_from: dateFrom, date_to: dateTo } });
      return res.data.daily as FunnelRow[];
    },
  });

  const occupancyQ = useQuery({
    queryKey: ["reports", "occupancy-summary", dateFrom, dateTo],
    queryFn: async () => {
      const res = await api.get("/reports/occupancy-summary", { params: { date_from: dateFrom, date_to: dateTo } });
      return res.data.daily as OccupancyDay[];
    },
  });

  return (
    <div className="h-full flex flex-col">
      <div className="px-6 py-5 bg-white border-b border-gray-100 flex-shrink-0">
        <h1 className="haip-page-title">Analytics</h1>
        <p className="text-sm text-gray-400 mt-0.5">
          Lead source, daily funnel, and occupancy trends. For row-level exports, use{" "}
          <a href="/dashboard/reports" className="text-teal-600 hover:underline">Reports</a>.
        </p>
        <div className="flex items-center gap-2 mt-4">
          <label className="text-xs text-gray-500">From</label>
          <input
            type="date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
            className="text-xs border border-gray-200 rounded-lg px-2 py-1.5"
          />
          <label className="text-xs text-gray-500">To</label>
          <input
            type="date"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
            className="text-xs border border-gray-200 rounded-lg px-2 py-1.5"
          />
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-6 space-y-5">
        <ChartCard title="Lead source" subtitle="Lead volume and conversion rate by source">
          {sourceQ.isLoading ? (
            <Skeleton className="h-full w-full" />
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={sourceQ.data ?? []} margin={{ left: 0, right: 16, top: 8, bottom: 40 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="source" tick={{ fontSize: 10 }} angle={-35} textAnchor="end" interval={0} />
                <YAxis tick={{ fontSize: 10 }} />
                <Tooltip
                  formatter={(v, name) =>
                    name === "total_leads" ? [v, "Leads"] : [v, "Converted"]
                  }
                />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Bar dataKey="total_leads" name="Leads" fill="#14b8a6" radius={[3, 3, 0, 0]} />
                <Bar dataKey="converted" name="Converted" fill="#0f766e" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </ChartCard>

        <ChartCard title="Day-wise lead funnel" subtitle="Leads / valid / invalid / conversion, per day">
          {funnelQ.isLoading ? (
            <Skeleton className="h-full w-full" />
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={funnelQ.data ?? []} margin={{ left: 0, right: 16, top: 8, bottom: 8 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="date" tick={{ fontSize: 9 }} />
                <YAxis tick={{ fontSize: 10 }} />
                <Tooltip />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Line type="monotone" dataKey="total_leads" name="Total leads" stroke="#6366f1" strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="valid" name="Valid" stroke="#14b8a6" strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="invalid" name="Invalid" stroke="#f87171" strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="converted" name="Converted" stroke="#0f766e" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          )}
        </ChartCard>

        <ChartCard title="Occupancy" subtitle="Daily occupancy % across active properties">
          {occupancyQ.isLoading ? (
            <Skeleton className="h-full w-full" />
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={occupancyQ.data ?? []} margin={{ left: 0, right: 16, top: 8, bottom: 8 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="date" tick={{ fontSize: 9 }} />
                <YAxis tick={{ fontSize: 10 }} unit="%" domain={[0, 100]} />
                <Tooltip formatter={(v) => [`${v}%`, "Occupancy"]} />
                <Line type="monotone" dataKey="occupancy_pct" name="Occupancy %" stroke="#14b8a6" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          )}
        </ChartCard>
      </div>
    </div>
  );
}
