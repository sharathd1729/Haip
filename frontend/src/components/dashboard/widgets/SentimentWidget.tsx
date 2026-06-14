import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from "recharts";

interface Props {
  data: { positive: number; negative: number; neutral: number; total: number };
}

const COLORS = { positive: "#22c55e", negative: "#ef4444", neutral: "#94a3b8" };

export function SentimentWidget({ data }: Props) {
  const chartData = [
    { name: "Positive", value: data.positive },
    { name: "Negative", value: data.negative },
    { name: "Neutral",  value: data.neutral },
  ].filter((d) => d.value > 0);

  const pctPos = data.total ? Math.round((data.positive / data.total) * 100) : 0;

  return (
    <div className="flex items-center gap-3 h-full">
      <div style={{ width: 90, height: 90, flexShrink: 0 }}>
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie data={chartData} dataKey="value" innerRadius={26} outerRadius={40} paddingAngle={2}>
              {chartData.map((entry) => (
                <Cell key={entry.name} fill={COLORS[entry.name.toLowerCase() as keyof typeof COLORS] ?? "#94a3b8"} />
              ))}
            </Pie>
            <Tooltip formatter={(v) => [v, ""]} />
          </PieChart>
        </ResponsiveContainer>
      </div>
      <div className="flex flex-col gap-1.5 min-w-0">
        <p className="text-2xl font-bold tabular-nums" style={{ color: "#22c55e" }}>{pctPos}%</p>
        <p className="text-[10px]" style={{ color: "var(--haip-fg-subtle)" }}>positive out of {data.total} calls</p>
        <div className="flex gap-2 mt-1">
          {[["Neg", data.negative, "#ef4444"], ["Neu", data.neutral, "#94a3b8"]].map(([l, v, c]) => (
            <span key={l as string} className="text-[10px] tabular-nums" style={{ color: c as string }}>
              {l} {v}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
