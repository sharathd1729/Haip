"use client";
// One post's Instagram insights, live (GET /instagram/media/{id}/insights). "—" = Instagram does not give that number
// for this post (profile visits and follows exist for feed posts, not reels).
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { Drawer } from "@/components/ui/kit";

type Insights = Record<"views" | "reach" | "interactions" | "likes" | "comments" | "saves" | "shares" | "profile_visits" | "follows", number | null>;
const ROWS: [keyof Insights, string][] = [["views", "Views"], ["reach", "Reach"], ["interactions", "Interactions"], ["likes", "Likes"],
  ["comments", "Comments"], ["saves", "Saves"], ["shares", "Shares"], ["profile_visits", "Profile visits"], ["follows", "Follows"]];
const fmt = (n: number | null) => (n == null ? "—" : n >= 1000 ? `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}K` : String(n));

export function PostInsights({ mediaId, caption, onClose }: { mediaId: string; caption: string; onClose: () => void }) {
  const q = useQuery<Insights>({
    queryKey: ["ig-media-insights", mediaId],
    queryFn: () => api.get(`/instagram/media/${mediaId}/insights`).then(r => r.data),
    staleTime: 5 * 60_000,
  });
  return (
    <Drawer open onOpenChange={o => { if (!o) onClose(); }} title="Post insights" description={caption ? caption.slice(0, 90) : "Live from Instagram, since the post went up."}>
      {q.isError ? (
        <div className="grid gap-2">
          <p className="text-[14px] text-[var(--haip-fg-muted)]">Instagram did not return the numbers for this post.</p>
          <button type="button" onClick={() => q.refetch()} className="min-h-11 justify-self-start rounded-full border border-[var(--haip-border)] px-4 text-[14px] font-medium">Try again</button>
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3" aria-busy={q.isLoading}>
          {ROWS.map(([k, label]) => (
            <div key={k} className="rounded-[12px] border border-[var(--haip-border)] bg-[var(--haip-card)] p-3">
              <p className="text-[12.5px] text-[var(--haip-fg-subtle)]">{label}</p>
              {q.isLoading ? <div className="mt-1 h-7 w-12 animate-pulse rounded bg-[var(--haip-surface)]" />
                : <p className="mt-0.5 text-[22px] font-semibold tabular-nums">{fmt(q.data?.[k] ?? null)}</p>}
            </div>
          ))}
        </div>
      )}
      <p className="mt-3 text-[12.5px] text-[var(--haip-fg-subtle)]">Live from Instagram, all time. “—” means Instagram does not report it for this post.</p>
    </Drawer>
  );
}
