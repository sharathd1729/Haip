"use client";
// Pick one of the account's posts or reels (GET /instagram/media, fetched live: Meta's image links expire).
import { useInfiniteQuery } from "@tanstack/react-query";
import { Loader2, CheckCircle2 } from "@/lib/icons";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import type { IgMedia } from "./automationTypes";

interface Page { items: IgMedia[]; next: string | null }

export function MediaPicker({ value, onPick }: { value?: string; onPick: (m: IgMedia) => void }) {
  const q = useInfiniteQuery<Page, { response?: { data?: { detail?: string } } }>({
    queryKey: ["ig-media"],
    queryFn: ({ pageParam }) =>
      api.get("/instagram/media", { params: { limit: 24, ...(pageParam ? { after: pageParam } : {}) } }).then(r => r.data),
    initialPageParam: null as string | null,
    getNextPageParam: last => last.next,
    staleTime: 5 * 60_000,
  });

  if (q.isLoading) {
    return (
      <div className="grid grid-cols-3 gap-2" aria-busy="true" aria-label="Loading your posts">
        {Array.from({ length: 6 }).map((_, i) => <div key={i} className="aspect-square animate-pulse rounded-[10px] bg-[var(--haip-surface)]" />)}
      </div>
    );
  }
  if (q.isError) {
    return (
      <div className="rounded-[12px] border border-[var(--haip-status-danger-border)] bg-[var(--haip-status-danger-bg)] px-3 py-3 text-[14px] text-[var(--haip-status-danger-fg)]">
        {q.error?.response?.data?.detail || "Couldn't load your posts."}{" "}
        <button type="button" className="font-semibold underline" onClick={() => q.refetch()}>Try again</button>
      </div>
    );
  }
  const items = q.data?.pages.flatMap(p => p.items) ?? [];
  if (!items.length) {
    return <p className="text-[14px] text-[var(--haip-fg-subtle)]">No posts or reels on this account yet. Use “Any post” or “Next post” instead.</p>;
  }
  return (
    <div>
      <div className="grid grid-cols-3 gap-2">
        {items.map(m => {
          const picked = m.id === value;
          return (
            <button key={m.id} type="button" onClick={() => onPick(m)} aria-pressed={picked}
              title={m.caption || m.type}
              className={cn("group relative aspect-square overflow-hidden rounded-[10px] border-2 bg-[var(--haip-surface)] transition-transform active:scale-[0.97]",
                picked ? "border-primary" : "border-transparent hover:border-[var(--haip-border-strong)]")}>
              {m.thumbnail
                ? /* eslint-disable-next-line @next/next/no-img-element */ <img src={m.thumbnail} alt={m.caption?.slice(0, 80) || "Instagram post"} className="size-full object-cover" loading="lazy" />
                : <span className="flex size-full items-center justify-center p-2 text-[12px] text-[var(--haip-fg-subtle)]">{m.caption?.slice(0, 60) || "No preview"}</span>}
              {m.type === "reel" && <span className="absolute left-1.5 top-1.5 rounded-full bg-[var(--haip-fg)] px-2 py-0.5 text-[11px] font-semibold text-[var(--haip-card)]">Reel</span>}
              {picked && <CheckCircle2 size={22} className="absolute right-1.5 top-1.5 rounded-full bg-[var(--haip-card)] text-primary" />}
            </button>
          );
        })}
      </div>
      {q.hasNextPage && (
        <button type="button" onClick={() => q.fetchNextPage()} disabled={q.isFetchingNextPage}
          className="mt-3 inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-full border border-[var(--haip-border)] text-[14px] font-medium">
          {q.isFetchingNextPage && <Loader2 size={15} className="animate-spin" />} Show older posts
        </button>
      )}
    </div>
  );
}
