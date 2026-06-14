import { fmtTime } from "@/lib/fmt";

interface Props {
  data: { p95_seconds: number; p95_formatted: string };
}

export function ResponseTimeWidget({ data }: Props) {
  const secs = data.p95_seconds;
  const color = secs <= 120 ? "#22c55e" : secs <= 300 ? "#f59e0b" : "#ef4444";
  return (
    <div className="flex flex-col justify-center h-full">
      <p className="text-3xl font-bold tabular-nums" style={{ color }}>
        {fmtTime(secs)}
      </p>
      <p className="text-[10px] mt-1" style={{ color: "var(--haip-fg-subtle)" }}>
        p95 first-reply latency
      </p>
      <p className="text-[10px] mt-2" style={{ color: "var(--haip-fg-subtle)" }}>
        {secs <= 120 ? "Excellent" : secs <= 300 ? "Acceptable" : "Needs improvement"}
      </p>
    </div>
  );
}
