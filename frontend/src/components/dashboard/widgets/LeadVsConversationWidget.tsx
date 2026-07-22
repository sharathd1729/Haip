import { LineChart, Line, XAxis, Tooltip, ResponsiveContainer } from "recharts";

interface Props {
  data: {
    series: { date: string; leads: number; conversations: number }[];
    total_leads: number;
    total_conversations: number;
  };
}

export function LeadVsConversationWidget({ data }: Props) {
  return (
    <div style={{ height: "100%" }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data.series} margin={{ left: 0, right: 8, top: 4, bottom: 4 }}>
          <XAxis dataKey="date" tick={{ fontSize: 9 }} hide />
          <Tooltip
            formatter={(v, name) => [v, name === "leads" ? "Leads" : "Conversations"]}
            labelFormatter={(d) => d}
          />
          <Line type="monotone" dataKey="leads" stroke="var(--primary)" strokeWidth={2} dot={false} />
          <Line type="monotone" dataKey="conversations" stroke="var(--haip-fg-subtle)" strokeWidth={2} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
