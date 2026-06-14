interface Props {
  data: { sources: { source: string; booked: number; pct: number }[] };
}

export function AttributionWidget({ data }: Props) {
  return (
    <div className="flex flex-col gap-1.5 h-full">
      {data.sources.length === 0 ? (
        <p className="text-[11px] text-center mt-4" style={{ color: "var(--haip-fg-subtle)" }}>No booking data.</p>
      ) : (
        data.sources.slice(0, 5).map((s) => (
          <div key={s.source} className="flex items-center gap-2">
            <span className="text-[10px] flex-1 truncate" style={{ color: "var(--haip-fg)" }}>{s.source}</span>
            <div className="w-20 h-2 rounded-full overflow-hidden" style={{ background: "var(--haip-border)" }}>
              <div className="h-full rounded-full" style={{ width: `${s.pct}%`, background: "#22c55e" }} />
            </div>
            <span className="text-[10px] w-6 text-right tabular-nums flex-shrink-0" style={{ color: "var(--haip-fg-subtle)" }}>
              {s.pct}%
            </span>
          </div>
        ))
      )}
    </div>
  );
}
