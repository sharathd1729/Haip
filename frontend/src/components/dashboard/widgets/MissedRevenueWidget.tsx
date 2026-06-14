import { fmt_inr } from "@/lib/fmt";

interface Props {
  data: { revenue_at_risk: number; lost_inquiries: number };
}

export function MissedRevenueWidget({ data }: Props) {
  return (
    <div className="flex flex-col justify-center h-full gap-3">
      <div>
        <p className="text-2xl font-bold tabular-nums" style={{ color: "#ef4444" }}>
          {fmt_inr(data.revenue_at_risk)}
        </p>
        <p className="text-[10px]" style={{ color: "var(--haip-fg-subtle)" }}>revenue at risk</p>
      </div>
      <div>
        <p className="text-lg font-semibold tabular-nums" style={{ color: "var(--haip-fg)" }}>
          {data.lost_inquiries}
        </p>
        <p className="text-[10px]" style={{ color: "var(--haip-fg-subtle)" }}>inquiries closed lost</p>
      </div>
    </div>
  );
}
