"use client";
// Instagram automations dashboard (GET /instagram/automations/overview): comment to booking for the chosen period,
// compared with the period before; top posts; posts with no automation; what needs a look.
import { useQuery } from "@tanstack/react-query";
import { BadgeCheck, Eye, IndianRupee, Link2, MessageSquare, Plus } from "@/lib/icons";
import api from "@/lib/api";
import { cn, formatINR } from "@/lib/utils";
import { Card, EmptyState, Stat } from "@/components/ui/kit";
import type { Tone } from "@/components/ui/page";
import type { IgMedia } from "./automationTypes";

type Kpis = {
  comments_answered: number; dms_sent: number; opened: number; clicked: number; forms_started: number;
  forms_completed: number; triggered: number; leads: number; bookings: number; booked_amount: number | null;
};
type Post = { media_id: string; people: number; opened: number; leads: number; bookings: number; booked_amount: number | null };
type Bare = { media_id: string; comments: number; last_at: string | null };
type Alert = { kind: string; severity: "critical" | "warning" | "info"; count: number; detail?: string | null; media_id?: string; comments?: number };
export type Overview = {
  period: string; from: string; to: string; previous: { from: string; to: string };
  money_restricted: boolean; opens_tracked: boolean; kpis: Kpis; previous_kpis: Kpis;
  funnel: { key: string; label: string; value: number }[];
  top_posts: Post[]; posts_without_automation: Bare[]; alerts: Alert[];
};

const SEVERITY: Record<Alert["severity"], string> = {
  critical: "bg-[var(--haip-status-danger-fg)]",
  warning: "bg-[var(--haip-status-warning-fg)]",
  info: "bg-primary",
};

/** "+18%", "new", or nothing: never a percentage against an empty earlier period. */
export function change(cur: number, prev: number): { text: string; tone: Tone } | null {
  if (!prev) return cur ? { text: "new", tone: "info" } : null;
  const pct = Math.round(((cur - prev) / prev) * 100);
  if (pct === 0) return { text: "same", tone: "neutral" };
  return { text: `${pct > 0 ? "+" : ""}${pct}%`, tone: pct > 0 ? "success" : "danger" };
}

function alertText(a: Alert): { title: string; hint: string } {
  switch (a.kind) {
    case "ads_without_automation":
      return { title: `Ads running on ${a.count} ${a.count === 1 ? "post" : "posts"} with no automation`, hint: `${a.detail ? `${a.detail}: p` : "P"}eople who comment on these ads get no reply.` };
    case "other_app_answered_first":
      return { title: `Another app answered ${a.count} ${a.count === 1 ? "comment" : "comments"} first`, hint: "Instagram allows one private reply per comment. Check other tools connected to this account." };
    case "sends_failed":
      return { title: `${a.count} ${a.count === 1 ? "message" : "messages"} couldn't be sent`, hint: "Open the automation's runs to see Instagram's reason." };
    default:
      return { title: `${a.count} ${a.count === 1 ? "post is" : "posts are"} getting comments with no automation`, hint: a.comments ? `The busiest has ${a.comments} comments in this period.` : "" };
  }
}

function Thumb({ media }: { media?: IgMedia }) {
  return media?.thumbnail
    // eslint-disable-next-line @next/next/no-img-element -- Meta CDN images expire; next/image would cache a dead URL
    ? <img src={media.thumbnail} alt="" className="size-9 shrink-0 rounded-[8px] object-cover" />
    : <span className="size-9 shrink-0 rounded-[8px] bg-[var(--haip-surface)]" aria-hidden="true" />;
}

const postLabel = (m?: IgMedia, id?: string) => (m?.caption?.trim() ? m.caption.trim().slice(0, 48) : `Post ${id?.slice(-6) ?? ""}`);
const day = (iso: string) => new Date(`${iso}T00:00:00+05:30`).toLocaleDateString("en-IN", { day: "numeric", month: "short", timeZone: "Asia/Kolkata" });

export function AutomationsOverview({ period, onAdd }: { period: string; onAdd: (media: { id: string; thumb?: string; caption?: string }) => void }) {
  const q = useQuery<Overview>({
    queryKey: ["ig-automation-overview", period],
    queryFn: () => api.get("/instagram/automations/overview", { params: { period } }).then(r => r.data),
  });
  const media = useQuery<{ items: IgMedia[] }>({
    queryKey: ["ig-media-thumbs"],
    queryFn: () => api.get("/instagram/media", { params: { limit: 50 } }).then(r => r.data),
    staleTime: 5 * 60_000,
    retry: false,
  });
  const byId = new Map((media.data?.items ?? []).map(m => [m.id, m]));

  if (q.isError) {
    return <Card><EmptyState title="Couldn't load the dashboard" hint="Check your connection and try again."
      action={<button type="button" onClick={() => q.refetch()} className="min-h-11 rounded-full border border-[var(--haip-border)] px-4 text-[14px] font-medium">Try again</button>} /></Card>;
  }
  const d = q.data;
  const k = d?.kpis;
  const p = d?.previous_kpis;
  const loading = q.isLoading;
  const covers = d ? (d.from === d.to ? day(d.from) : `${day(d.from)} to ${day(d.to)}`) : "";
  const vs = d ? `vs ${d.previous.from === d.previous.to ? day(d.previous.from) : `${day(d.previous.from)} to ${day(d.previous.to)}`}` : "";
  const add = (id?: string) => id && onAdd({ id, thumb: byId.get(id)?.thumbnail ?? undefined, caption: byId.get(id)?.caption });
  const top = Math.max(1, ...(d?.funnel ?? []).map(f => f.value));

  return (
    <div className="grid gap-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-3 xl:grid-cols-6">
        <Stat label="Comments answered" value={k?.comments_answered ?? 0} hint={covers} change={k && p ? change(k.comments_answered, p.comments_answered) : null} icon={MessageSquare} loading={loading} />
        <Stat label="DMs sent" value={k?.dms_sent ?? 0} hint={covers} change={k && p ? change(k.dms_sent, p.dms_sent) : null} icon={MessageSquare} loading={loading} />
        <Stat label="DMs opened" value={d && !d.opens_tracked ? "–" : (k?.opened ?? 0)} hint={d && !d.opens_tracked ? "Reconnect Instagram to count opens" : covers}
          change={d?.opens_tracked && k && p ? change(k.opened, p.opened) : null} icon={Eye} loading={loading} />
        <Stat label="Link clicks" value={k?.clicked ?? 0} hint={covers} change={k && p ? change(k.clicked, p.clicked) : null} icon={Link2} loading={loading} />
        <Stat label="Leads" value={k?.leads ?? 0} hint="shared a WhatsApp number" change={k && p ? change(k.leads, p.leads) : null} icon={BadgeCheck} loading={loading} />
        <Stat label="Booked" variant="accent" icon={IndianRupee} loading={loading}
          value={d && !d.money_restricted && k?.booked_amount != null ? formatINR(k.booked_amount) : `${k?.bookings ?? 0} ${k?.bookings === 1 ? "stay" : "stays"}`}
          hint={d && !d.money_restricted ? `${k?.bookings ?? 0} ${k?.bookings === 1 ? "stay" : "stays"} from these leads` : "stays from these leads"}
          change={k && p ? change(k.bookings, p.bookings) : null} />
      </div>
      {d && <p className="-mt-2 text-[12.5px] text-[var(--haip-fg-subtle)]">Changes compare {covers} {vs}.</p>}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
        <Card className="p-4">
          <h2 className="text-[14.5px] font-semibold">From comment to booking</h2>
          <div className="mt-3 grid gap-2.5" aria-busy={loading}>
            {(d?.funnel ?? []).map(f => (
              <div key={f.key} className="grid grid-cols-[minmax(0,9rem)_1fr_3rem] items-center gap-3 text-[13.5px]">
                <span className="truncate text-[var(--haip-fg-muted)]">{f.label}</span>
                <span className="h-3 overflow-hidden rounded-full bg-[var(--haip-surface)]">
                  <span className="block h-full rounded-full bg-primary" style={{ width: `${Math.max(f.value ? 3 : 0, (f.value / top) * 100)}%` }} />
                </span>
                <span className="text-right font-semibold tabular-nums">{f.key === "opened" && !d?.opens_tracked ? "–" : f.value}</span>
              </div>
            ))}
            {loading && [0, 1, 2, 3].map(i => <div key={i} className="h-4 animate-pulse rounded bg-[var(--haip-surface)]" />)}
          </div>
        </Card>

        <Card className="p-4">
          <h2 className="text-[14.5px] font-semibold">Needs a look</h2>
          <div className="mt-3 grid gap-2">
            {(d?.alerts ?? []).map(a => {
              const t = alertText(a);
              const action = (a.kind === "ads_without_automation" || a.kind === "post_without_automation") && a.media_id;
              return (
                <div key={a.kind} className="grid grid-cols-[6px_1fr_auto] items-center gap-3 rounded-[12px] border border-[var(--haip-border)] p-3">
                  <span className={cn("h-full min-h-8 rounded-full", SEVERITY[a.severity])} aria-hidden="true" />
                  <span className="min-w-0"><span className="block text-[14px] font-medium">{t.title}</span>{t.hint && <span className="block text-[12.5px] text-[var(--haip-fg-subtle)]">{t.hint}</span>}</span>
                  {action ? <button type="button" onClick={() => add(a.media_id)} className="min-h-11 rounded-full px-3 text-[13.5px] font-semibold text-primary">Set up</button> : <span />}
                </div>
              );
            })}
            {d && d.alerts.length === 0 && (
              <p className="text-[13.5px] text-[var(--haip-fg-subtle)]">Nothing needs a look in this period.</p>
            )}
            {loading && <div className="h-14 animate-pulse rounded-[12px] bg-[var(--haip-surface)]" />}
          </div>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
        <Card className="p-4">
          <h2 className="text-[14.5px] font-semibold">Top posts <span className="font-normal text-[var(--haip-fg-subtle)]">· {covers}</span></h2>
          {d && d.top_posts.length === 0 ? (
            <p className="mt-3 text-[13.5px] text-[var(--haip-fg-subtle)]">No automation DMs from posts in this period.</p>
          ) : (
            <div className="mt-2 overflow-x-auto">
              <table className="w-full text-[13.5px] tabular-nums">
                <thead><tr className="text-left text-[12px] uppercase tracking-[0.04em] text-[var(--haip-fg-subtle)]">
                  <th className="py-2 pr-3 font-semibold">Post</th><th className="px-2 font-semibold">Reached</th>
                  <th className="px-2 font-semibold">Opened</th><th className="px-2 font-semibold">Leads</th><th className="pl-2 font-semibold">Booked</th>
                </tr></thead>
                <tbody>
                  {(d?.top_posts ?? []).map(t => (
                    <tr key={t.media_id} className="border-t border-[var(--haip-border)]">
                      <td className="py-2 pr-3"><span className="flex min-w-[10rem] items-center gap-2.5"><Thumb media={byId.get(t.media_id)} /><span className="line-clamp-2">{postLabel(byId.get(t.media_id), t.media_id)}</span></span></td>
                      <td className="px-2">{t.people}</td>
                      <td className="px-2">{d?.opens_tracked ? t.opened : "–"}</td>
                      <td className="px-2">{t.leads}</td>
                      <td className="whitespace-nowrap pl-2">{t.booked_amount != null && t.bookings ? formatINR(t.booked_amount) : t.bookings}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        <Card className="p-4">
          <h2 className="text-[14.5px] font-semibold">Posts with no automation</h2>
          {d && d.posts_without_automation.length === 0 ? (
            <p className="mt-3 text-[13.5px] text-[var(--haip-fg-subtle)]">Every post that got comments in this period has an automation.</p>
          ) : (
            <ul className="mt-2 grid gap-1">
              {(d?.posts_without_automation ?? []).map(b => (
                <li key={b.media_id} className="flex items-center gap-2.5 border-t border-[var(--haip-border)] py-2 first:border-t-0">
                  <Thumb media={byId.get(b.media_id)} />
                  <span className="min-w-0 flex-1"><span className="line-clamp-1 text-[13.5px]">{postLabel(byId.get(b.media_id), b.media_id)}</span>
                    <span className="block text-[12.5px] text-[var(--haip-fg-subtle)]">{b.comments} {b.comments === 1 ? "comment" : "comments"}</span></span>
                  <button type="button" onClick={() => add(b.media_id)} className="inline-flex min-h-11 items-center gap-1 rounded-full px-3 text-[13.5px] font-semibold text-primary"><Plus size={14} /> Add</button>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}
