import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend } from "recharts";

interface Props {
  data: { intents: { label: string; count: number; pct: number }[] };
}

const COLORS = ["var(--primary)", "#f59e0b", "#06b6d4", "#8b5cf6", "#10b981"];

export function IntentMixWidget({ data }: Props) {
  return (
    <div style={{ height: "100%" }}>
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie data={data.intents} dataKey="count" nameKey="label" innerRadius={24} outerRadius={42}>
            {data.intents.map((_, i) => (
              <Cell key={i} fill={COLORS[i % COLORS.length]} />
            ))}
          </Pie>
          <Tooltip formatter={(v, name) => [v, name]} />
          <Legend iconSize={8} wrapperStyle={{ fontSize: 9 }} />
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}
