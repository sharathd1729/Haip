import { fmt_inr } from "@/lib/fmt";

interface Props { data: { forecast_30d: number } }

export function RevenueForecastWidget({ data }: Props) {
  return (
    <div className="flex flex-col justify-center h-full gap-2">
      <p className="text-3xl font-bold tabular-nums" style={{ color: "#22c55e" }}>
        {fmt_inr(data.forecast_30d)}
      </p>
      <p className="text-[10px]" style={{ color: "var(--haip-fg-subtle)" }}>
        forecasted revenue — next 30 days
      </p>
    </div>
  );
}
