interface Props {
  data: { agents: { name: string; calls: number; avg_score: number }[] };
}

export function AgentLeaderboardWidget({ data }: Props) {
  return (
    <div className="flex flex-col gap-1.5 h-full overflow-hidden">
      {data.agents.length === 0 ? (
        <p className="text-[11px] text-center mt-4" style={{ color: "var(--haip-fg-subtle)" }}>No agent scores yet.</p>
      ) : (
        data.agents.map((a, i) => (
          <div key={a.name} className="flex items-center gap-2">
            <span
              className="text-[10px] font-bold w-4 flex-shrink-0"
              style={{ color: i === 0 ? "#f59e0b" : "var(--haip-fg-subtle)" }}
            >
              {i + 1}
            </span>
            <span className="text-[11px] flex-1 truncate" style={{ color: "var(--haip-fg)" }}>{a.name}</span>
            <span className="text-[10px] tabular-nums" style={{ color: "var(--haip-fg-subtle)" }}>{a.calls} calls</span>
            <span
              className="text-[10px] tabular-nums font-semibold w-12 text-right flex-shrink-0"
              style={{ color: a.avg_score >= 8 ? "#22c55e" : a.avg_score >= 6 ? "#f59e0b" : "#ef4444" }}
            >
              {a.avg_score}/10
            </span>
          </div>
        ))
      )}
    </div>
  );
}
