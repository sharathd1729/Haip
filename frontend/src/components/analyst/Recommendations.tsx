"use client";
// Recommendations from the brief. "Approve" appears when the learning loop already turned the recommendation into a suggested
// change (same change type, from this report); "Assign" gives it to a team member (pushed to them, audited).
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { Card, CardBody, CardHeader, StatusPill } from "@/components/ui/kit";
import { Sparkles } from "@/lib/icons";
import { useToast } from "@/components/ui/toast";
import type { Board, Recommendation } from "./types";

interface Person { id: string; name: string; role: string; is_active?: boolean }
type Actions = Record<string, { assigned_to: string; name: string }>;

const btn = "inline-flex min-h-[44px] items-center rounded-full px-4 text-sm font-semibold disabled:opacity-60";
const select = "min-h-[44px] rounded-xl border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 text-[16px] text-[var(--haip-fg)] sm:text-sm";

export function Recommendations({ reportId, items, actions, canDecide }: {
  reportId: string; items: Recommendation[]; actions: Actions; canDecide: boolean;
}) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const [picking, setPicking] = useState<number | null>(null);
  const board = useQuery<Board>({ queryKey: ["learning-board"], queryFn: () => api.get("/learning/board").then(r => r.data) });
  const people = useQuery<Person[]>({ queryKey: ["team-people"], queryFn: () => api.get("/users").then(r => r.data), enabled: picking !== null });
  const assign = useMutation({
    mutationFn: ({ i, userId }: { i: number; userId: string }) =>
      api.post(`/analyst/reports/${reportId}/recommendations/${i}/assign`, { user_id: userId }).then(r => r.data),
    onSuccess: () => { setPicking(null); qc.invalidateQueries({ queryKey: ["analyst-report", reportId] }); toast({ variant: "success", title: "Assigned" }); },
    onError: () => toast({ variant: "error", title: "Couldn't assign", description: "Try again." }),
  });
  const approve = useMutation({
    mutationFn: (id: string) => api.post(`/learning/experiments/${id}/approve`).then(r => r.data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["learning-board"] }); toast({ variant: "success", title: "Approved: the safety bench runs first" }); },
    onError: (e: unknown) => {
      const d = (e as { response?: { data?: { detail?: { message?: string } } } })?.response?.data?.detail;
      toast({ variant: "error", title: "Couldn't approve", description: d?.message ?? "Try again." });
    },
  });
  if (!items.length) return null;
  return (
    <Card>
      <CardHeader icon={Sparkles} title="Recommendations" description="What to do this week." />
      <CardBody>
        <ol className="space-y-3">
          {items.map((r, i) => {
            const suggestion = board.data?.suggested.find(e => e.change_type === r.change_proposal);
            const done = actions[String(i)];
            return (
              <li key={i} className="rounded-xl border border-[var(--haip-border)] p-3">
                <p className="text-sm font-semibold text-[var(--haip-fg)]">{r.action}</p>
                <p className="mt-0.5 text-xs text-[var(--haip-fg-subtle)]">{r.owner_role} · {r.due}{r.expected_effect ? ` · ${r.expected_effect}` : ""}</p>
                {done && <StatusPill tone="brand" className="mt-2">Assigned to {done.name}</StatusPill>}
                {canDecide && (
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    {suggestion && (
                      <button type="button" className={`${btn} bg-primary text-primary-foreground`} disabled={approve.isPending}
                        onClick={() => approve.mutate(suggestion.id)}>Approve change</button>
                    )}
                    {picking === i ? (
                      <select aria-label="Assign to" className={select} defaultValue="" disabled={assign.isPending || people.isPending}
                        onChange={e => e.target.value && assign.mutate({ i, userId: e.target.value })}>
                        <option value="" disabled>{people.isPending ? "Loading…" : "Assign to…"}</option>
                        {(people.data ?? []).filter(p => p.is_active !== false).map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
                      </select>
                    ) : (
                      <button type="button" className={`${btn} border border-[var(--haip-border)] text-[var(--haip-fg)]`} onClick={() => setPicking(i)}>
                        {done ? "Reassign" : "Assign"}
                      </button>
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ol>
      </CardBody>
    </Card>
  );
}
