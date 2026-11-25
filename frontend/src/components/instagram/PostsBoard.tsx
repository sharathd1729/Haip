"use client";
// Posts view of the Instagram automations page: every post and reel with what its automations did (all time, GET
// /instagram/automations/posts) and a way to set one up, edit it or copy another onto the post. Grid or month calendar;
// phones get the calendar as a list by day (nothing scrolls sideways). Posts come live from GET /instagram/media.
import { useMemo, useState } from "react";
import { useInfiniteQuery, useQueries } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, RefreshCw, Search } from "@/lib/icons";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { Card, EmptyState, StatusPill, Tabs } from "@/components/ui/kit";
import type { IgMedia, IgRule } from "./automationTypes";
import { PostInsights } from "./PostInsights";

type PostStat = { rules: string[]; covered_by_any: boolean; people: number; sent: number; public_replies: number; opened: number; clicks: number };
type Filter = "all" | "linked" | "unlinked";
const TZ = "Asia/Kolkata";
const dayKey = (ts?: string) => (ts ? new Date(ts).toLocaleDateString("en-CA", { timeZone: TZ }) : "");
const when = (ts?: string) => (ts ? new Date(ts).toLocaleString("en-IN", { timeZone: TZ, day: "numeric", month: "short", hour: "numeric", minute: "2-digit" }) : "");

export function PostsBoard({ rules, onSetUp, onEdit, onCopy }: {
  rules: IgRule[];
  onSetUp: (m: { id: string; thumb?: string; caption?: string }) => void;
  onEdit: (r: IgRule) => void;
  onCopy: (r: IgRule, m: { id: string; thumb?: string; caption?: string }) => void;
}) {
  const [view, setView] = useState("grid");
  const [filter, setFilter] = useState<Filter>("all");
  const [q, setQ] = useState("");
  const [insights, setInsights] = useState<IgMedia | null>(null);
  const [month, setMonth] = useState(() => { const d = new Date(); return new Date(d.getFullYear(), d.getMonth(), 1); });

  const media = useInfiniteQuery<{ items: IgMedia[]; next: string | null }>({
    queryKey: ["ig-posts-board"],
    queryFn: ({ pageParam }) => api.get("/instagram/media", { params: { limit: 24, ...(pageParam ? { after: pageParam } : {}) } }).then(r => r.data),
    initialPageParam: null as string | null,
    getNextPageParam: last => last.next,
    staleTime: 60_000,
  });
  const posts = useMemo(() => media.data?.pages.flatMap(p => p.items) ?? [], [media.data]);
  const statQs = useQueries({ queries: (media.data?.pages ?? []).map(pg => { // one stats call per page of 24 posts
    const ids = pg.items.map(p => p.id).join(",");
    return { queryKey: ["ig-post-stats", ids], enabled: !!ids,
      queryFn: () => api.get("/instagram/automations/posts", { params: { ids } }).then(r => r.data as { posts: Record<string, PostStat> }) };
  }) });
  const statMap: Record<string, PostStat> = Object.assign({}, ...statQs.map(x => x.data?.posts ?? {}));
  const byId = new Map(rules.map(r => [r.id, r]));
  const commentRules = rules.filter(r => r.trigger === "ig_comment_received");
  const linked = (p: IgMedia) => (statMap[p.id]?.rules.length ?? 0) > 0;
  const shown = posts.filter(p => (filter === "all" || (filter === "linked") === linked(p))
    && (!q.trim() || p.caption.toLowerCase().includes(q.trim().toLowerCase())));

  if (media.isLoading) return <div className="grid grid-cols-2 gap-3 sm:grid-cols-3" aria-busy="true">{[0, 1, 2, 3, 4, 5].map(i => <div key={i} className="aspect-[4/5] animate-pulse rounded-[16px] bg-[var(--haip-surface)]" />)}</div>;
  if (media.isError) return <Card><EmptyState title="Couldn't load your posts" hint="Instagram may be busy, or the account needs connecting again."
    action={<button type="button" onClick={() => media.refetch()} className="min-h-11 rounded-full border border-[var(--haip-border)] px-4 text-[14px] font-medium">Try again</button>} /></Card>;

  const card = (p: IgMedia, compact = false) => {
    const st = statMap[p.id];
    const own = (st?.rules ?? []).map(id => byId.get(id)).filter(Boolean) as IgRule[];
    const m = { id: p.id, thumb: p.thumbnail ?? undefined, caption: p.caption };
    return (
      <Card key={p.id} className={cn("flex gap-3 p-2.5", compact ? "items-center" : "flex-col")}>
        <div className={cn("relative shrink-0 overflow-hidden rounded-[12px] bg-[var(--haip-surface)]", compact ? "size-14" : "aspect-square w-full")}>
          {p.thumbnail && /* eslint-disable-next-line @next/next/no-img-element */ <img src={p.thumbnail} alt="" className="size-full object-cover" loading="lazy" />}
          {!compact && <span className="absolute left-2 top-2 rounded-full bg-[var(--haip-card)] px-2 py-0.5 text-[11.5px] font-semibold">{p.type === "reel" ? "Reel" : "Post"}</span>}
        </div>
        <div className="grid min-w-0 flex-1 gap-1">
          <p className="line-clamp-2 text-[13.5px] font-medium leading-snug">{p.caption || "No caption"}</p>
          <p className="text-[12.5px] text-[var(--haip-fg-subtle)]">{when(p.timestamp)}{p.comments ? ` · ${p.comments} comments` : ""}</p>
          <div className="flex flex-wrap items-center gap-1.5">
            {own.length ? <StatusPill tone={own.some(r => r.is_active) ? "success" : "neutral"}>{own.some(r => r.is_active) ? "Automation on" : "Paused"}</StatusPill>
              : st?.covered_by_any ? <StatusPill tone="info">Any-post automation</StatusPill> : <StatusPill tone="neutral">No automation</StatusPill>}
          </div>
          {st && (st.sent || st.public_replies) ? (
            <p className="text-[12.5px] tabular-nums text-[var(--haip-fg-muted)]">{st.sent} DMs · {st.opened} opened · {st.clicks} clicks · {st.public_replies} public replies</p>
          ) : null}
          <div className="flex flex-wrap gap-1.5 pt-1">
            {own[0] ? (
              <button type="button" onClick={() => onEdit(own[0])} className="min-h-11 rounded-full border border-[var(--haip-border)] px-3 text-[13px] font-semibold">Edit automation</button>
            ) : (
              <button type="button" onClick={() => onSetUp(m)} className="min-h-11 rounded-full bg-primary px-3 text-[13px] font-semibold text-primary-foreground">Set up</button>
            )}
            <button type="button" onClick={() => setInsights(p)} className="min-h-11 rounded-full border border-[var(--haip-border)] px-3 text-[13px] font-medium">Insights</button>
            {commentRules.length > 0 && (
              <select aria-label={`Copy an automation to this post`} value="" onChange={e => { const r = byId.get(e.target.value); if (r) onCopy(r, m); }}
                className="min-h-11 max-w-[11rem] rounded-full border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 text-[13px] font-medium">
                <option value="">Copy one…</option>
                {commentRules.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}
              </select>
            )}
          </div>
        </div>
      </Card>
    );
  };

  // Month calendar: the posts loaded so far, placed on their IST day.
  const first = new Date(month.getFullYear(), month.getMonth(), 1);
  const lead = (first.getDay() + 6) % 7; // weeks start Monday
  const days = new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate();
  const byDay = new Map<string, IgMedia[]>();
  shown.forEach(p => { const k = dayKey(p.timestamp); byDay.set(k, [...(byDay.get(k) ?? []), p]); });
  const key = (d: number) => `${month.getFullYear()}-${String(month.getMonth() + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
  const oldest = posts.length ? new Date(posts[posts.length - 1].timestamp ?? 0) : null;
  const needOlder = !!(oldest && oldest > first && media.hasNextPage);
  const monthDays = Array.from({ length: days }, (_, i) => i + 1).filter(d => byDay.get(key(d))?.length);

  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <Tabs label="Posts view" value={view} onChange={setView} items={[{ value: "grid", label: "Grid" }, { value: "calendar", label: "Calendar" }]} />
        <div className="flex flex-wrap gap-1.5">
          {([["all", "All"], ["linked", "With automation"], ["unlinked", "Without"]] as const).map(([v, l]) => (
            <button key={v} type="button" aria-pressed={filter === v} onClick={() => setFilter(v)}
              className={cn("min-h-11 rounded-full border px-3 text-[13px] font-medium", filter === v ? "border-primary bg-[var(--haip-primary-tint)] text-primary" : "border-[var(--haip-border)]")}>{l}</button>
          ))}
        </div>
        <button type="button" onClick={() => media.refetch()} disabled={media.isFetching} aria-label="Fetch your latest posts"
          className="ml-auto inline-flex min-h-11 items-center gap-1.5 rounded-full border border-[var(--haip-border)] px-3 text-[13px] font-medium disabled:opacity-60">
          <RefreshCw size={14} className={media.isFetching ? "animate-spin" : ""} /> Latest posts
        </button>
      </div>
      <label className="relative block">
        <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[var(--haip-fg-subtle)]" />
        <input value={q} onChange={e => setQ(e.target.value)} placeholder="Search by caption" aria-label="Search posts by caption"
          className="min-h-11 w-full rounded-[12px] border border-[var(--haip-border)] bg-[var(--haip-card)] pl-9 pr-3 text-[16px] sm:text-[14.5px]" />
      </label>

      {view === "grid" ? (
        shown.length === 0 ? <Card><EmptyState title={posts.length ? "No posts match" : "No posts yet"} hint={posts.length ? "Try another filter or search." : "Posts and reels you publish show here."} /></Card>
          : <div className="grid grid-cols-1 gap-3 min-[420px]:grid-cols-2 lg:grid-cols-3">{shown.map(p => card(p))}</div>
      ) : (
        <Card className="p-3">
          <div className="mb-2 flex items-center justify-between">
            <button type="button" aria-label="Previous month" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() - 1, 1))} className="grid size-11 place-items-center rounded-full hover:bg-[var(--haip-surface)]"><ChevronLeft size={18} /></button>
            <p className="text-[15px] font-semibold">{month.toLocaleDateString("en-IN", { month: "long", year: "numeric" })}</p>
            <button type="button" aria-label="Next month" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() + 1, 1))} className="grid size-11 place-items-center rounded-full hover:bg-[var(--haip-surface)]"><ChevronRight size={18} /></button>
          </div>
          <div className="hidden grid-cols-7 gap-1 md:grid">
            {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map(d => <p key={d} className="pb-1 text-center text-[12px] font-semibold text-[var(--haip-fg-subtle)]">{d}</p>)}
            {Array.from({ length: lead }, (_, i) => <div key={`pad-${i}`} />)}
            {Array.from({ length: days }, (_, i) => i + 1).map(d => (
              <div key={d} className="min-h-24 rounded-[10px] border border-[var(--haip-border)] p-1.5">
                <p className="text-[12px] font-semibold text-[var(--haip-fg-subtle)]">{d}</p>
                {(byDay.get(key(d)) ?? []).map(p => {
                  const st = statMap[p.id];
                  return (
                    <button key={p.id} type="button" title={p.caption} onClick={() => { const r = st?.rules[0] && byId.get(st.rules[0]); if (r) onEdit(r); else onSetUp({ id: p.id, thumb: p.thumbnail ?? undefined, caption: p.caption }); }}
                      className="mt-1 flex w-full items-center gap-1.5 rounded-[8px] bg-[var(--haip-surface)] p-1 text-left">
                      {p.thumbnail && /* eslint-disable-next-line @next/next/no-img-element */ <img src={p.thumbnail} alt="" className="size-7 rounded-[6px] object-cover" />}
                      <span className="min-w-0 flex-1 truncate text-[11.5px] tabular-nums">{st?.rules.length ? `${st.sent} DMs` : "Set up"}</span>
                    </button>
                  );
                })}
              </div>
            ))}
          </div>
          <div className="grid gap-2 md:hidden">
            {monthDays.length === 0 && <p className="py-4 text-center text-[13.5px] text-[var(--haip-fg-subtle)]">No posts this month.</p>}
            {monthDays.map(d => (
              <div key={d} className="grid gap-1.5">
                <p className="text-[12.5px] font-semibold text-[var(--haip-fg-subtle)]">{new Date(month.getFullYear(), month.getMonth(), d).toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" })}</p>
                {(byDay.get(key(d)) ?? []).map(p => card(p, true))}
              </div>
            ))}
          </div>
          {needOlder && (
            <button type="button" onClick={() => media.fetchNextPage()} disabled={media.isFetchingNextPage} className="mt-2 min-h-11 w-full rounded-full border border-[var(--haip-border)] text-[13.5px] font-medium">
              {media.isFetchingNextPage ? "Loading…" : "Load older posts for this month"}
            </button>
          )}
        </Card>
      )}
      {insights && <PostInsights mediaId={insights.id} caption={insights.caption} onClose={() => setInsights(null)} />}
      {view === "grid" && media.hasNextPage && (
        <button type="button" onClick={() => media.fetchNextPage()} disabled={media.isFetchingNextPage} className="min-h-11 rounded-full border border-[var(--haip-border)] text-[14px] font-medium">
          {media.isFetchingNextPage ? "Loading…" : "Load more posts"}
        </button>
      )}
    </div>
  );
}
