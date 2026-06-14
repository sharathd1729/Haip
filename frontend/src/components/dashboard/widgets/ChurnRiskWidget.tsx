interface Props { data: { at_risk_guests: number } }

export function ChurnRiskWidget({ data }: Props) {
  return (
    <div className="flex flex-col justify-center h-full gap-2">
      <p className="text-3xl font-bold tabular-nums" style={{ color: data.at_risk_guests > 0 ? "#ef4444" : "#22c55e" }}>
        {data.at_risk_guests}
      </p>
      <p className="text-[10px]" style={{ color: "var(--haip-fg-subtle)" }}>
        guests haven&apos;t returned in 6+ months
      </p>
    </div>
  );
}
