"use client";
// Outside research (studio plan phase 2): each source off until the owner switches it on; what it found, the rising
// sounds and the swipe file. Every row says where it came from: own, platform or Google.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import api from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardBody, CardHeader, EmptyState, StatusPill, type Tone } from "@/components/ui/kit";
import { STUDIO, btn, day, studioError } from "./types";

interface Source { key: string; label: string; evidence: string; on: boolean; ready: boolean; missing_keys: string[]; needs_facebook_login: boolean }
interface Sources { sources: Source[]; hashtags_this_week: number; hashtag_limit: number; media_retention_days: number }
interface Signal { source: string; evidence: string; title: string | null; url: string | null; value: number | null; query: string | null; observed_on: string }
interface Signals { signals: Signal[]; rising_sounds: { audio: string; uses: number; uses_before: number }[] }
interface Swipe { id: string; source_url: string | null; hook_text?: string; hook_type?: string; format?: string; pacing: string | null; cta?: string; cuts: number }

const EVIDENCE_TONE: Record<string, Tone> = { own: "success", platform: "info", google: "highlight" };

function state(s: Source): { text: string; tone: Tone } {
  if (!s.on) return { text: "Off", tone: "neutral" };
  if (s.missing_keys.length) return { text: `Needs ${s.missing_keys.join(", ")}`, tone: "warning" };
  if (s.needs_facebook_login) return { text: "Needs the Facebook connection", tone: "warning" };
  return { text: "On", tone: "success" };
}

export function SourcesPanel() {
  const { data: session } = useSession();
  const isOwner = session?.user?.role === "owner";
  const qc = useQueryClient();
  const { toast } = useToast();
  const q = useQuery<Sources>({ queryKey: ["studio-sources"], queryFn: () => api.get(`${STUDIO}/sources`).then(r => r.data) });
  const sig = useQuery<Signals>({ queryKey: ["studio-signals"], queryFn: () => api.get(`${STUDIO}/signals`).then(r => r.data) });
  const sw = useQuery<{ items: Swipe[] }>({ queryKey: ["studio-swipe"], queryFn: () => api.get(`${STUDIO}/swipe`).then(r => r.data) });
  const save = useMutation({
    mutationFn: (body: Record<string, boolean>) => api.put(`${STUDIO}/sources`, body),
    onSuccess: r => qc.setQueryData(["studio-sources"], (old: Sources | undefined) => old && { ...old, sources: r.data.sources }),
    onError: e => toast({ variant: "error", title: "Not saved", description: studioError(e, "Try again.") }),
  });
  const run = useMutation({
    mutationFn: () => api.post(`${STUDIO}/sources/run`),
    onSuccess: () => toast({ variant: "success", title: "Collecting", description: "New findings appear here in a minute." }),
    onError: e => toast({ variant: "error", title: "Not started", description: studioError(e, "Try again.") }),
  });
  if (q.isLoading) return <Skeleton className="h-64 w-full" />;
  if (q.isError || !q.data) return <Card><EmptyState title="Could not load the research sources" hint={studioError(q.error, "Try again.")} /></Card>;
  const signals = sig.data?.signals ?? [];
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader title="Research sources" description={`Each is off until you switch it on. Competitor data is public only, collected logged out; kept videos are deleted after ${q.data.media_retention_days} days.`}
          actions={<button type="button" className={btn} disabled={run.isPending} onClick={() => run.mutate()}>Collect now</button>} />
        <CardBody>
          <ul className="divide-y divide-[var(--haip-border)]">
            {q.data.sources.map(s => {
              const st = state(s);
              return (
                <li key={s.key} className="flex flex-col gap-2 py-3 sm:flex-row sm:items-center sm:justify-between">
                  <div className="min-w-0">
                    <p className="font-semibold">{s.label} <StatusPill tone={EVIDENCE_TONE[s.evidence] ?? "neutral"} className="ml-1">{s.evidence}</StatusPill></p>
                    <p className="text-xs text-[var(--haip-fg-subtle)]"><StatusPill tone={st.tone}>{st.text}</StatusPill>{s.missing_keys.length ? " Ask your HAIP admin to set these." : ""}</p>
                  </div>
                  {isOwner && (
                    <label className="flex min-h-11 items-center gap-2 text-sm">
                      <input type="checkbox" className="h-5 w-5" checked={s.on} disabled={save.isPending}
                        onChange={e => save.mutate({ [s.key]: e.target.checked })} aria-label={`${s.label} on`} />
                      {s.on ? "On" : "Off"}
                    </label>
                  )}
                </li>
              );
            })}
          </ul>
          <p className="mt-2 text-xs text-[var(--haip-fg-subtle)]">Hashtags looked up this week: {q.data.hashtags_this_week} of {q.data.hashtag_limit} (Instagram's limit).</p>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="What the sources found" description="Last 30 days, newest first." />
        <CardBody>
          {sig.isLoading ? <Skeleton className="h-24 w-full" /> : sig.isError ? <p className="text-sm text-[var(--haip-status-danger-fg)]">{studioError(sig.error, "Could not load findings.")}</p>
            : !signals.length ? <p className="text-sm text-[var(--haip-fg-subtle)]">Nothing collected yet.</p> : (
            <ul className="space-y-2 text-sm">
              {signals.slice(0, 30).map((s, i) => (
                <li key={i} className="flex flex-wrap items-center justify-between gap-2">
                  <span className="min-w-0 truncate">{s.url ? <a className="underline" href={s.url} target="_blank" rel="noopener noreferrer">{s.title ?? s.url}</a> : s.title}</span>
                  <span className="text-xs text-[var(--haip-fg-subtle)]">{s.source.replace("_", " ")}{s.value != null ? ` · ${s.value.toLocaleString("en-IN")}` : ""} · {day(s.observed_on)} <StatusPill tone={EVIDENCE_TONE[s.evidence] ?? "neutral"} className="ml-1">{s.evidence}</StatusPill></span>
                </li>
              ))}
            </ul>
          )}
          {!!sig.data?.rising_sounds.length && (
            <p className="mt-3 text-xs text-[var(--haip-fg-muted)]">Rising sounds on competitor Reels (last 14 days vs the 14 before): {sig.data.rising_sounds.map(r => `${r.audio} (${r.uses_before} → ${r.uses})`).join(", ")}.</p>
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Swipe file" description="Hooks and shots read from competitor Reels, with the link to each." />
        <CardBody>
          {sw.isLoading ? <Skeleton className="h-24 w-full" /> : sw.isError ? <p className="text-sm text-[var(--haip-status-danger-fg)]">{studioError(sw.error, "Could not load the swipe file.")}</p>
            : !sw.data?.items.length ? <p className="text-sm text-[var(--haip-fg-subtle)]">Empty. Switch on the collector and the video reader.</p> : (
            <ul className="space-y-2 text-sm">
              {sw.data.items.map(i => (
                <li key={i.id} className="rounded-xl border border-[var(--haip-border)] p-3">
                  <p className="font-semibold">“{i.hook_text || "(no words)"}” <span className="text-xs font-normal text-[var(--haip-fg-subtle)]">{i.hook_type} · {i.format} · {i.pacing ?? "—"} pacing · {i.cuts} cuts</span></p>
                  <p className="text-xs text-[var(--haip-fg-muted)]">CTA: {i.cta || "none"}{i.source_url && <> · <a className="underline" href={i.source_url} target="_blank" rel="noopener noreferrer">source</a></>}</p>
                </li>
              ))}
            </ul>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
