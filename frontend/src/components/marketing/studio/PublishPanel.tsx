"use client";
// Scheduling + posting for an approved item. Only the approved version is ever posted; an edit cancels the schedule.
// One approval covers every channel the post targets (Instagram, Facebook Page, Google Business Profile); the Facebook
// and Google text is derived from the approved caption by fixed rules and shown here before scheduling.
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { StatusPill, type Tone } from "@/components/ui/kit";
import { STUDIO, btn, btnPrimary, inputCls, studioError, when } from "./types";

type Channel = "instagram" | "facebook" | "google";
interface Attempt { id: string; status: string; scheduled_for: string; tries: number; permalink: string | null; error: string | null; published_at: string | null; channel?: Channel }
interface Info {
  status: string; publish_level: string; problems: string[]; notes: string[]; suggested_time: string; attempts: Attempt[];
  targets?: Channel[]; available_channels?: Channel[];
  previews?: Partial<Record<Channel, { text: string | null; images: string; button?: { actionType: string; url?: string } }>>;
}
interface Channels { facebook: { connected: boolean; page_name: string | null }; google: { connected: boolean; location_title: string | null } }

const TONE: Record<string, Tone> = { scheduled: "info", publishing: "info", published: "success", failed: "danger", cancelled: "neutral" };
export const CHANNEL_LABEL: Record<Channel, string> = { instagram: "Instagram", facebook: "Facebook Page", google: "Google Business" };

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
  const ch = useQuery<Channels>({ queryKey: ["studio-channels"], queryFn: () => api.get(`${STUDIO}/channels`).then(r => r.data), staleTime: 60_000 });
  const done = () => { qc.invalidateQueries({ queryKey: ["studio-publishing", itemId] }); qc.invalidateQueries({ queryKey: ["studio-item", itemId] }); qc.invalidateQueries({ queryKey: ["studio-content"] }); };
  const schedule = useMutation({
    mutationFn: () => api.post(`${STUDIO}/content/${itemId}/schedule`, at ? { scheduled_for: new Date(`${at}:00+05:30`).toISOString() } : {}),
    onSuccess: r => { toast({ variant: "success", title: "Scheduled", description: `It will be posted to ${(r.data.channels as Channel[] ?? ["instagram"]).map(c => CHANNEL_LABEL[c]).join(", ")} at that time.` }); done(); },
    onError: e => toast({ variant: "error", title: "Not scheduled", description: studioError(e, "Try again.") }),
  });
  const cancel = useMutation({ mutationFn: () => api.post(`${STUDIO}/content/${itemId}/unschedule`), onSuccess: done,
    onError: e => toast({ variant: "error", title: "Not cancelled", description: studioError(e, "Try again.") }) });
  const targets = useMutation({ mutationFn: (t: Channel[]) => api.put(`${STUDIO}/content/${itemId}/targets`, { targets: t }), onSuccess: done,
    onError: e => toast({ variant: "error", title: "Not changed", description: studioError(e, "Try again.") }) });

  const d = q.data;
  if (!d) return null;
  const chosen = d.targets ?? ["instagram"];
  const connected = (c: Channel) => c === "instagram" || (c === "facebook" ? ch.data?.facebook.connected : ch.data?.google.connected);
  const latestPer = (d.attempts ?? []).reduce<Partial<Record<Channel, Attempt>>>((acc, a) => {
    const c = a.channel ?? "instagram";
    if (!acc[c]) acc[c] = a;                                  // attempts come newest first
    return acc;
  }, {});
  const toggle = (c: Channel) => {
    const next = chosen.includes(c) ? chosen.filter(x => x !== c) : [...chosen, c];
    if (next.length) targets.mutate(next);
  };

  return (
    <section className="space-y-3 rounded-xl border border-[var(--haip-border)] p-3">
      <h3 className="text-[13px] font-bold">Post to</h3>
      <div className="flex flex-wrap gap-2" role="group" aria-label="Channels">
        {(d.available_channels ?? ["instagram"]).map(c => (
          <label key={c} className={`flex min-h-11 items-center gap-2 rounded-full border px-3 text-[13px] sm:min-h-9 ${chosen.includes(c) ? "border-primary" : "border-[var(--haip-border)]"} ${!connected(c) ? "opacity-60" : ""}`}
            title={!connected(c) ? `Connect ${CHANNEL_LABEL[c]} in Library › Channels first` : undefined}>
            <input type="checkbox" className="size-4" checked={chosen.includes(c)} disabled={!connected(c) || targets.isPending || d.status === "scheduled" || d.status === "published"}
              onChange={() => toggle(c)} />
            {CHANNEL_LABEL[c]}
          </label>
        ))}
      </div>
      {chosen.filter(c => c !== "instagram").map(c => d.previews?.[c] && (
        <div key={c} className="rounded-lg bg-[var(--haip-surface)] p-2 text-xs text-[var(--haip-fg-2)]">
          <p className="font-semibold">{CHANNEL_LABEL[c]} will show</p>
          <p className="mt-1 whitespace-pre-line">{d.previews[c]?.text}</p>
          <p className="mt-1 text-[var(--haip-fg-subtle)]">{d.previews[c]?.images === "first" ? "First image only" : "All images"}
            {d.previews[c]?.button ? ` · button: ${d.previews[c]?.button?.actionType === "CALL" ? "Call" : d.previews[c]?.button?.actionType === "BOOK" ? "Book" : "Learn more"}` : ""}</p>
        </div>
      ))}
      {Object.entries(latestPer).map(([c, a]) => a && (
        <p key={c} className="flex flex-wrap items-center gap-2 text-sm">
          <span className="font-semibold">{CHANNEL_LABEL[c as Channel]}</span>
          <StatusPill tone={TONE[a.status] ?? "neutral"}>{a.status}</StatusPill>
          {a.status === "published" ? <>posted {when(a.published_at)} {a.permalink && <a className="text-primary underline" href={a.permalink} target="_blank" rel="noopener noreferrer">open</a>}</>
            : a.status === "scheduled" ? <>for {when(a.scheduled_for)}{a.tries ? ` · retry ${a.tries}` : ""}</> : null}
          {a.error && <span className="block w-full text-xs text-[var(--haip-status-danger-fg)]">{a.error}</span>}
        </p>
      ))}
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
