import { BarChart, Bar, XAxis, Tooltip, ResponsiveContainer } from "recharts";

interface Props {
  data: { series: { date: string; count: number }[]; total_calls: number; avg_qa_score: number };
}

export function CallVolumeWidget({ data }: Props) {
  return (
    <div className="flex flex-col gap-2 h-full">
      <div className="flex gap-4">
        <div>
          <p className="text-lg font-bold tabular-nums" style={{ color: "var(--haip-fg)" }}>
            {data.total_calls}
          </p>
          <p className="text-[10px]" style={{ color: "var(--haip-fg-subtle)" }}>total calls</p>
        </div>
        <div>
          <p className="text-lg font-bold tabular-nums" style={{ color: "var(--haip-fg)" }}>
            {data.avg_qa_score}/10
          </p>
          <p className="text-[10px]" style={{ color: "var(--haip-fg-subtle)" }}>avg QA</p>
        </div>
      </div>
      <div className="flex-1" style={{ minHeight: 80 }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data.series} margin={{ top: 0, right: 0, left: -20, bottom: 0 }}>
            <XAxis dataKey="date" tick={{ fontSize: 9 }} tickFormatter={(v) => v.slice(5)} />
            <Tooltip formatter={(v) => [v, "calls"]} labelStyle={{ fontSize: 10 }} />
            <Bar dataKey="count" fill="var(--primary)" radius={[2, 2, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
