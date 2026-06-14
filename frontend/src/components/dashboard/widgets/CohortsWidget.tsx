interface Props { data: { total_stays: number; repeat_stays: number; repeat_pct: number } }

export function CohortsWidget({ data }: Props) {
  return (
    <div className="flex flex-col justify-center h-full gap-3">
      <div>
        <p className="text-2xl font-bold tabular-nums" style={{ color: "var(--primary)" }}>
          {data.repeat_pct}%
        </p>
        <p className="text-[10px]" style={{ color: "var(--haip-fg-subtle)" }}>returning guests</p>
      </div>
      <div className="w-full h-2 rounded-full overflow-hidden" style={{ background: "var(--haip-border)" }}>
        <div className="h-full rounded-full" style={{ width: `${data.repeat_pct}%`, background: "var(--primary)" }} />
      </div>
      <p className="text-[10px]" style={{ color: "var(--haip-fg-subtle)" }}>
        {data.repeat_stays} repeat / {data.total_stays} total stays
      </p>
    </div>
  );
}
