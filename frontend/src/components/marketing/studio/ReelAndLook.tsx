"use client";
// Agency M3. ReelPlayer: the rendered reel for the saved version (GET/POST /content/{id}/reel), the exact file that will
// be posted; muted, inline, with its cover as the poster. LookVariants: the first image drawn in each look
// (GET /content/{id}/variants) so the look is picked by seeing it, not by name.
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { Skeleton } from "@/components/ui/skeleton";
import { STUDIO, btn, studioError } from "./types";

interface Reel { version_id: string; ready: boolean; video?: string; cover?: string | null; duration_ms?: number }

export function ReelPlayer({ itemId, versionId, canRender }: { itemId: string; versionId: string; canRender: boolean }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const key = ["studio-reel", itemId, versionId];
  const [asked, setAsked] = useState(false);
  const q = useQuery<Reel>({
    queryKey: key, queryFn: () => api.get(`${STUDIO}/content/${itemId}/reel`).then(r => r.data),
    // Rendering takes ~10-60 s in the worker; poll only after someone asked for it, for at most ~5 minutes.
    refetchInterval: d => (asked && d.state.data && !d.state.data.ready && d.state.dataUpdateCount < 60 ? 5000 : false),
  });
  const render = useMutation({
    mutationFn: () => api.post(`${STUDIO}/content/${itemId}/reel/render`),
    onSuccess: () => { setAsked(true); qc.invalidateQueries({ queryKey: key }); },
    onError: e => toast({ variant: "error", title: "Not started", description: studioError(e, "Try again.") }),
  });
  return (
    <section className="space-y-2" aria-label="The reel">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-[13px] font-bold text-[var(--haip-fg)]">The reel</h3>
        {q.data?.ready && q.data.duration_ms ? <span className="text-xs text-[var(--haip-fg-subtle)]">{Math.round(q.data.duration_ms / 1000)} s · silent</span> : null}
      </div>
      {q.isLoading ? <Skeleton className="aspect-[9/16] w-[168px] rounded-lg" /> : q.isError ? (
        <p className="text-sm text-[var(--haip-status-danger-fg)]">{studioError(q.error, "Could not load the reel.")}</p>
      ) : q.data?.ready && q.data.video ? (
        <video src={q.data.video} poster={q.data.cover ?? undefined} controls muted playsInline preload="metadata"
          className="aspect-[9/16] w-[200px] rounded-lg border border-[var(--haip-border)] bg-black object-cover" />
      ) : asked ? (
        <p className="text-sm text-[var(--haip-fg-subtle)]">Cutting the reel… this takes up to a minute.</p>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-sm text-[var(--haip-fg-subtle)]">Not cut yet. The stills above show each clip.</p>
          {canRender && <button type="button" className={btn} disabled={render.isPending} onClick={() => render.mutate()}>Make the reel</button>}
        </div>
      )}
    </section>
  );
}

interface Variants { current: string; variants: { style: string; src: string }[]; problems: string[] }
const LOOK_LABEL: Record<string, string> = { overlay: "Text on a fade", panel: "Brand panel", photo: "Photo only" };

/** `selected` is the draft's look (picking one changes the draft; saving makes it a new version). `children` is shown
 *  instead when the previews cannot be drawn (no photo yet, storage down). */
export function LookVariants({ itemId, versionId, story, disabled, selected, onPick, children }: {
  itemId: string; versionId: string; story: boolean; disabled: boolean; selected: string; onPick: (style: string) => void;
  children: React.ReactNode;
}) {
  const q = useQuery<Variants>({
    queryKey: ["studio-variants", itemId, versionId], staleTime: Infinity,
    queryFn: () => api.get(`${STUDIO}/content/${itemId}/variants`).then(r => r.data),
  });
  if (q.isLoading) return <div className="flex gap-2">{[0, 1, 2].map(i => <Skeleton key={i} className={`${story ? "aspect-[9/16]" : "aspect-[4/5]"} w-[96px] rounded-lg`} />)}</div>;
  if (q.isError || !q.data || q.data.variants.length === 0) return <>{children}</>;
  return (
    <div role="radiogroup" aria-label="Look" className="flex gap-2 overflow-x-auto pb-1">
      {q.data.variants.map(v => {
        const on = v.style === selected;
        return (
          <button key={v.style} type="button" role="radio" aria-checked={on} disabled={disabled} onClick={() => onPick(v.style)}
            className={`shrink-0 space-y-1 rounded-xl border p-1 text-left transition-transform duration-150 ease-out active:scale-[0.97] ${on
              ? "border-primary ring-2 ring-primary/30" : "border-[var(--haip-border)] hover:bg-[var(--haip-surface)]"}`}>
            <img src={v.src} alt="" className={`${story ? "aspect-[9/16]" : "aspect-[4/5]"} w-[96px] rounded-lg object-cover`} />
            <span className="block px-1 text-xs font-semibold text-[var(--haip-fg-2)]">{LOOK_LABEL[v.style] ?? v.style}{v.style === q.data.current ? " · saved" : ""}</span>
          </button>
        );
      })}
    </div>
  );
}
