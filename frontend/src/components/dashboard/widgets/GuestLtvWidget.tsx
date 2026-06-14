import { fmt_inr } from "@/lib/fmt";

interface Props { data: { stays: number; avg_ltv: number; total_rev: number } }

export function GuestLtvWidget({ data }: Props) {
  return (
    <div className="flex flex-col justify-center h-full gap-3">
      <div>
        <p className="text-2xl font-bold tabular-nums" style={{ color: "var(--haip-fg)" }}>
          {fmt_inr(data.avg_ltv)}
        </p>
        <p className="text-[10px]" style={{ color: "var(--haip-fg-subtle)" }}>average guest LTV</p>
      </div>
      <div>
        <p className="text-sm font-semibold tabular-nums" style={{ color: "var(--haip-fg)" }}>
          {fmt_inr(data.total_rev)} · {data.stays} stays
        </p>
        <p className="text-[10px]" style={{ color: "var(--haip-fg-subtle)" }}>total portfolio revenue</p>
      </div>
    </div>
  );
}
