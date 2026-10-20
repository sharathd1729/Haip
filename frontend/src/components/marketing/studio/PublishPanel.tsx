"use client";
// Scheduling + posting for an approved item. Only the approved version is ever posted; an edit cancels the schedule.
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { StatusPill, type Tone } from "@/components/ui/kit";
import { STUDIO, btn, btnPrimary, inputCls, studioError, when } from "./types";

interface Attempt { id: string; status: string; scheduled_for: string; tries: number; permalink: string | null; error: string | null; published_at: string | null }
interface Info { status: string; publish_level: string; problems: string[]; notes: string[]; suggested_time: string; attempts: Attempt[] }

const TONE: Record<string, Tone> = { scheduled: "info", publishing: "info", published: "success", failed: "danger", cancelled: "neutral" };

function toLocalInput(iso: string): string {
  const d = new Date(iso);
  const ist = new Date(d.getTime() + 330 * 60000);          // workspace time is IST
  return ist.toISOString().slice(0, 16);
}

export function PublishPanel({ itemId, canSchedule }: { itemId: string; canSchedule: boolean }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const [at, setAt] = useState<string | null>(null);
  const q = useQuery<Info>({
    queryKey: ["studio-publishing", itemId], queryFn: () => api.get(`${STUDIO}/content/${itemId}/publishing`).then(r => r.data),
    refetchInterval: d => (d.state.data?.attempts?.some(a => a.status === "publishing") ? 5000 : false),
  });
  const done = () => { qc.invalidateQueries({ queryKey: ["studio-publishing", itemId] }); qc.invalidateQueries({ queryKey: ["studio-item", itemId] }); qc.invalidateQueries({ queryKey: ["studio-content"] }); };
  const schedule = useMutation({
    mutationFn: () => api.post(`${STUDIO}/content/${itemId}/schedule`, at ? { scheduled_for: new Date(`${at}:00+05:30`).toISOString() } : {}),
    onSuccess: () => { toast({ variant: "success", title: "Scheduled", description: "It will be posted to Instagram at that time." }); done(); },
    onError: e => toast({ variant: "error", title: "Not scheduled", description: studioError(e, "Try again.") }),
  });
  const cancel = useMutation({ mutationFn: () => api.post(`${STUDIO}/content/${itemId}/unschedule`), onSuccess: done,
    onError: e => toast({ variant: "error", title: "Not cancelled", description: studioError(e, "Try again.") }) });

  const d = q.data;
  if (!d) return null;
  const latest = d.attempts[0];
  return (
    <section className="space-y-2 rounded-xl border border-[var(--haip-border)] p-3">
      <h3 className="text-[13px] font-bold">Post to Instagram</h3>
      {latest && (
        <p className="flex flex-wrap items-center gap-2 text-sm">
          <StatusPill tone={TONE[latest.status] ?? "neutral"}>{latest.status}</StatusPill>
          {latest.status === "published" ? <>posted {when(latest.published_at)} {latest.permalink && <a className="text-primary underline" href={latest.permalink} target="_blank" rel="noopener noreferrer">open on Instagram</a>}</>
            : latest.status === "scheduled" ? <>for {when(latest.scheduled_for)}{latest.tries ? ` · retry ${latest.tries}` : ""}</> : null}
        </p>
      )}
      {latest?.error && <p className="text-xs text-[var(--haip-status-danger-fg)]">{latest.error}</p>}
      {d.problems.map(p => <p key={p} className="text-xs text-[var(--haip-status-danger-fg)]">{p}</p>)}
      {d.notes.map(n => <p key={n} className="text-xs text-[var(--haip-fg-subtle)]">{n}</p>)}
      {d.status === "approved" && canSchedule && !d.problems.length && (
        <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
          <label className="space-y-1"><span className="text-xs font-semibold">When (IST)</span>
            <input type="datetime-local" className={inputCls} value={at ?? toLocalInput(d.suggested_time)} onChange={e => setAt(e.target.value)} /></label>
          <button type="button" className={btnPrimary} disabled={schedule.isPending} onClick={() => schedule.mutate()}>Schedule</button>
          <span className="text-xs text-[var(--haip-fg-subtle)]">Suggested from when your posts reach the most people.</span>
        </div>
      )}
      {d.status === "approved" && !canSchedule && <p className="text-xs text-[var(--haip-fg-subtle)]">An owner or manager schedules approved posts.</p>}
      {d.status === "scheduled" && canSchedule && <button type="button" className={btn} disabled={cancel.isPending} onClick={() => cancel.mutate()}>Cancel schedule</button>}
      {d.publish_level === "autopilot" && <p className="text-xs text-[var(--haip-fg-subtle)]">Publisher is on autopilot: approved posts are scheduled automatically.</p>}
    </section>
  );
}
