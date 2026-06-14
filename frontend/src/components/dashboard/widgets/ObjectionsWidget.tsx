interface Props {
  data: { objections: { label: string; count: number }[] };
}

export function ObjectionsWidget({ data }: Props) {
  const max = data.objections[0]?.count || 1;
  return (
    <div className="flex flex-col gap-2 h-full">
      {data.objections.length === 0 ? (
        <p className="text-[11px] text-center mt-4" style={{ color: "var(--haip-fg-subtle)" }}>No objections recorded.</p>
      ) : (
        data.objections.map((obj) => (
          <div key={obj.label} className="flex items-center gap-2">
            <p className="text-[10px] w-28 truncate flex-shrink-0" style={{ color: "var(--haip-fg)" }}>{obj.label}</p>
            <div className="flex-1 h-2 rounded-full overflow-hidden" style={{ background: "var(--haip-border)" }}>
              <div
                className="h-full rounded-full"
                style={{ width: `${(obj.count / max) * 100}%`, background: "var(--primary)" }}
              />
            </div>
            <span className="text-[10px] w-5 text-right tabular-nums flex-shrink-0" style={{ color: "var(--haip-fg-subtle)" }}>
              {obj.count}
            </span>
          </div>
        ))
      )}
    </div>
  );
}
