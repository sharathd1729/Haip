"use client";
// Filter the inbox by one chat label (GET /conversations/labels for the choices, ?label= on the list).
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { cn } from "@/lib/utils";

export function LabelFilter({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const q = useQuery<{ label: string; count: number }[]>({
    queryKey: ["conversations", "labels"],
    queryFn: () => api.get("/conversations/labels").then(r => r.data),
    staleTime: 60_000,
  });
  const labels = q.data ?? [];
  if (!labels.length && !value) return null;
  return (
    <div role="group" aria-label="Filter by label" className="flex gap-1.5 overflow-x-auto border-b border-[var(--haip-border)] px-3 py-2">
      {[{ label: "", count: 0 }, ...labels].map(l => {
        const on = value === l.label;
        return (
          <button key={l.label || "all"} type="button" aria-pressed={on} onClick={() => onChange(on && l.label ? "" : l.label)}
            className={cn("min-h-9 shrink-0 rounded-full border px-3 text-[12.5px] font-medium",
              on ? "border-primary bg-[var(--haip-primary-tint)] text-primary" : "border-[var(--haip-border)] text-[var(--haip-fg-muted)]")}>
            {l.label ? `${l.label} · ${l.count}` : "All labels"}
          </button>
        );
      })}
    </div>
  );
}
