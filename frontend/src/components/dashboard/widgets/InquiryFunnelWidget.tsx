interface Stage { stage: string; count: number; pct: number }
interface Props { data: { stages: Stage[]; conversion_rate: number } }

const STAGE_LABELS: Record<string, string> = {
  new: "New", responding: "Responding", quoted: "Quoted",
  site_visit_scheduled: "Site Visit", booked: "Booked",
};

export function InquiryFunnelWidget({ data }: Props) {
  return (
    <div className="flex flex-col gap-1 h-full">
      {data.stages.map((s) => (
        <div key={s.stage} className="flex items-center gap-2">
          <span className="text-[10px] w-20 flex-shrink-0 truncate" style={{ color: "var(--haip-fg-subtle)" }}>
            {STAGE_LABELS[s.stage] ?? s.stage}
          </span>
          <div className="flex-1 h-3 rounded-sm overflow-hidden" style={{ background: "var(--haip-border)" }}>
            <div
              className="h-full rounded-sm"
              style={{ width: `${s.pct}%`, background: "var(--primary)", opacity: 0.8 }}
            />
          </div>
          <span className="text-[10px] w-6 text-right tabular-nums flex-shrink-0" style={{ color: "var(--haip-fg)" }}>
            {s.count}
          </span>
        </div>
      ))}
      <p className="text-[10px] mt-1 font-semibold" style={{ color: "var(--haip-fg-subtle)" }}>
        {data.conversion_rate}% conversion rate
      </p>
    </div>
  );
}
