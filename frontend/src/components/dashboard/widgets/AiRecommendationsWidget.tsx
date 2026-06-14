import api from "@/lib/api";
import { useState } from "react";

interface Rec { id: string; title: string; severity: string; body: string }
interface Props { data: { recommendations: Rec[] } }

const SEVERITY_COLORS: Record<string, string> = {
  high: "#ef4444", medium: "#f59e0b", low: "#94a3b8",
};

export function AiRecommendationsWidget({ data }: Props) {
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());

  async function dismiss(id: string) {
    try {
      await api.post(`/analytics/insights/${id}/dismiss`);
      setDismissed((prev) => new Set([...prev, id]));
    } catch {
      // ignore
    }
  }

  const visible = data.recommendations.filter((r) => !dismissed.has(r.id));

  if (visible.length === 0) {
    return (
      <div className="flex items-center justify-center h-full">
        <p className="text-[11px]" style={{ color: "var(--haip-fg-subtle)" }}>No recommendations at this time.</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2 h-full overflow-hidden">
      {visible.map((r) => (
        <div key={r.id} className="flex gap-2 items-start">
          <span
            className="w-1.5 h-1.5 rounded-full flex-shrink-0 mt-1"
            style={{ background: SEVERITY_COLORS[r.severity] ?? "#94a3b8" }}
          />
          <div className="flex-1 min-w-0">
            <p className="text-[11px] font-medium truncate" style={{ color: "var(--haip-fg)" }}>{r.title}</p>
            <p className="text-[10px] line-clamp-2" style={{ color: "var(--haip-fg-subtle)" }}>{r.body}</p>
          </div>
          <button
            onClick={() => dismiss(r.id)}
            className="text-[9px] flex-shrink-0 mt-0.5"
            style={{ color: "var(--haip-fg-subtle)" }}
          >
            ✕
          </button>
        </div>
      ))}
    </div>
  );
}
