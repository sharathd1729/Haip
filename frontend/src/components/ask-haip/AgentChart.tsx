"use client";
import {
  BarChart, Bar, LineChart, Line, AreaChart, Area,
  PieChart, Pie, Cell, FunnelChart, Funnel, LabelList,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts";

export interface ChartSpec {
  type: string;               // "bar" | "line" | "area" | "pie" | "funnel" | "heatmap" | ...
  label: string;
  series: Array<Record<string, unknown>>;
}

const COLORS = ["#0F766E", "#14B8A6", "#F59E0B", "#EF4444", "#6366F1", "#EC4899", "#84CC16", "#06B6D4"];

/**
 * Chart specs come from 10 different backend agent functions
 * (ask_haip_agents.py) with varying field names per domain (e.g.
 * {stage,count} for funnels, {name,pct} for occupancy, {name,value} for
 * pie) -- rather than a schema per chart type, infer the category/value
 * keys generically: first string-valued field becomes the label axis,
 * first numeric-valued field becomes the plotted value.
 */
function inferKeys(series: Array<Record<string, unknown>>): { labelKey: string; valueKey: string } {
  const sample = series[0] || {};
  let labelKey = "";
  let valueKey = "";
  for (const [k, v] of Object.entries(sample)) {
    if (!labelKey && typeof v === "string") labelKey = k;
    if (!valueKey && typeof v === "number") valueKey = k;
  }
  return { labelKey: labelKey || "name", valueKey: valueKey || "value" };
}

export function AgentChart({ spec }: { spec: ChartSpec }) {
  const { series, type, label } = spec;
  if (!series || series.length === 0) return null;
  const { labelKey, valueKey } = inferKeys(series);

  return (
    <div className="rounded-xl border p-3" style={{ borderColor: "#E5E7EB", background: "#fff" }}>
      <p className="text-[11px] font-semibold mb-2" style={{ color: "#6B7280" }}>{label}</p>
      <ResponsiveContainer width="100%" height={180}>
        {renderChart(type, series, labelKey, valueKey)}
      </ResponsiveContainer>
    </div>
  );
}

function renderChart(
  type: string,
  series: Array<Record<string, unknown>>,
  labelKey: string,
  valueKey: string,
) {
  switch (type) {
    case "line":
      return (
        <LineChart data={series}>
          <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" />
          <XAxis dataKey={labelKey} tick={{ fontSize: 10 }} />
          <YAxis tick={{ fontSize: 10 }} />
          <Tooltip />
          <Line type="monotone" dataKey={valueKey} stroke="#0F766E" strokeWidth={2} dot={false} />
        </LineChart>
      );
    case "area":
      return (
        <AreaChart data={series}>
          <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" />
          <XAxis dataKey={labelKey} tick={{ fontSize: 10 }} />
          <YAxis tick={{ fontSize: 10 }} />
          <Tooltip />
          <Area type="monotone" dataKey={valueKey} stroke="#0F766E" fill="#0F766E" fillOpacity={0.15} />
        </AreaChart>
      );
    case "pie":
      return (
        <PieChart>
          <Tooltip />
          <Pie data={series} dataKey={valueKey} nameKey={labelKey} outerRadius={70} label={{ fontSize: 10 }}>
            {series.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
          </Pie>
        </PieChart>
      );
    case "funnel":
      return (
        <FunnelChart>
          <Tooltip />
          <Funnel data={series} dataKey={valueKey} nameKey={labelKey}>
            <LabelList position="right" dataKey={labelKey} fill="#374151" stroke="none" fontSize={10} />
            {series.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
          </Funnel>
        </FunnelChart>
      );
    case "heatmap":
    case "bar":
    default:
      return (
        <BarChart data={series} layout={type === "heatmap" ? "vertical" : "horizontal"}>
          <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" />
          {type === "heatmap" ? (
            <>
              <XAxis type="number" tick={{ fontSize: 10 }} />
              <YAxis type="category" dataKey={labelKey} tick={{ fontSize: 10 }} width={90} />
            </>
          ) : (
            <>
              <XAxis dataKey={labelKey} tick={{ fontSize: 10 }} />
              <YAxis tick={{ fontSize: 10 }} />
            </>
          )}
          <Tooltip />
          <Bar dataKey={valueKey} fill="#0F766E" radius={[3, 3, 3, 3]} />
        </BarChart>
      );
  }
}
