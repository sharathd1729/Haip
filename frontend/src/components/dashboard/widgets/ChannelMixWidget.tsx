import { BarChart, Bar, XAxis, Tooltip, ResponsiveContainer } from "recharts";

interface Props {
  data: { channels: { source: string; count: number; pct: number }[] };
}

export function ChannelMixWidget({ data }: Props) {
  return (
    <div style={{ height: "100%" }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data.channels} layout="vertical" margin={{ left: 0, right: 8, top: 4, bottom: 4 }}>
          <XAxis type="number" tick={{ fontSize: 9 }} hide />
          <Tooltip formatter={(v) => [v, "inquiries"]} />
          <Bar dataKey="count" fill="var(--primary)" radius={[0, 2, 2, 0]}
               label={{ position: "right", fontSize: 9, fill: "var(--haip-fg-subtle)" }} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
