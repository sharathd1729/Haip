"use client";
// My day -- the one queue. Everything waiting on this person, in the order
// it should be dealt with: overdue first, then whoever has waited longest.
// Backed by GET /work-queue (work_queue_service), the same source the
// dashboard cards use, so the numbers always agree.
import { useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import { ChannelBadges } from "@/components/inbox/ChannelBadges";
import { toGuestChannel } from "@/components/inbox/ChannelBadges";
import { Clock, MessageSquare, Sparkles, PhoneMissed, PhoneCall, UserPlus, CheckCircle2 } from "@/lib/icons";

type Kind = "followup" | "reply" | "draft" | "callback" | "call_new" | "unassigned";

interface Item {
  kind: Kind; title: string; detail: string; action: string; href: string;
  inquiry_id: string | null; guest_id: string | null; guest_phone: string | null;
  owner_id: string | null; owner_name: string | null;
  channels: string[]; since: string | null; overdue: boolean;
}
interface Queue {
  counts: Record<Kind, number>;
  oldest: Record<Kind, string | null>;
  total: number;
  items: Item[];
  scope: "mine" | "team";
}

const KINDS: { id: Kind; label: string; icon: typeof Clock; tone: string; dot: string }[] = [
  { id: "followup",   label: "Due now",        icon: Clock,        tone: "text-red-700",     dot: "bg-red-600" },
  { id: "reply",      label: "Waiting on us",  icon: MessageSquare, tone: "text-orange-700", dot: "bg-orange-600" },
  { id: "draft",      label: "Drafts to send", icon: Sparkles,     tone: "text-teal-700",    dot: "bg-teal-600" },
  { id: "callback",   label: "Call back",      icon: PhoneMissed,  tone: "text-red-700",     dot: "bg-red-600" },
  { id: "call_new",   label: "New, not called", icon: PhoneCall,   tone: "text-emerald-700", dot: "bg-emerald-600" },
  { id: "unassigned", label: "No owner",       icon: UserPlus,     tone: "text-violet-700",  dot: "bg-violet-600" },
];

function ago(iso: string | null): string {
  if (!iso) return "";
  const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (m < 0) return `in ${Math.abs(m) < 60 ? `${Math.abs(m)}m` : `${Math.round(Math.abs(m) / 60)}h`}`;
  if (m < 60) return `${Math.max(1, m)}m`;
  const h = Math.floor(m / 60);
  return h < 24 ? `${h}h` : `${Math.floor(h / 24)}d`;
}

function Row({ item }: { item: Item }) {
  const channels = item.channels.map(toGuestChannel).filter(Boolean) as ReturnType<typeof toGuestChannel>[];
  return (
    <Link href={item.href}
      className="flex items-center gap-3 px-4 py-3 hover:bg-[color:var(--muted)] outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-teal-600"
      style={{ borderTop: "1px solid var(--haip-border)" }}>
      <div className="flex-1 min-w-0">
        <span className="flex items-center gap-1.5 min-w-0">
          <span className="text-sm font-bold truncate" style={{ color: "var(--haip-fg)" }}>{item.title}</span>
          {channels.length > 0 && <ChannelBadges channels={channels as never} size={13} />}
        </span>
        <p className="text-xs mt-0.5 truncate" style={{ color: "var(--haip-fg-subtle)" }}>
          {item.detail}
          {item.owner_name ? ` · ${item.owner_name}` : ""}
        </p>
      </div>
      <span className={cn("text-xs font-semibold tabular-nums whitespace-nowrap",
        item.overdue ? "text-red-700" : "")} style={item.overdue ? undefined : { color: "var(--haip-fg-muted)" }}>
        {ago(item.since)}
      </span>
      <span className="text-xs font-bold px-3 py-1.5 rounded-lg bg-teal-700 text-white whitespace-nowrap">
        {item.action}
      </span>
    </Link>
  );
}

export default function MyDayPage() {
  const { data: session } = useSession();
  const role = session?.user?.role;
  const isOwnerView = role === "owner" || role === "manager";
  const [mineOnly, setMineOnly] = useState(false);
  // The dashboard cards deep-link here with ?kind=, so a card opens exactly
  // the rows it counted.
  const params0 = useSearchParams();
  const initial = params0.get("kind") as Kind | null;
  const [kind, setKind] = useState<Kind | "all">(
    initial && KINDS.some(k => k.id === initial) ? initial : "all",
  );

  const params = new URLSearchParams();
  if (isOwnerView && mineOnly) params.set("mine_only", "true");
  const qs = params.toString();

  const { data, isLoading, isError } = useQuery<Queue>({
    queryKey: ["work-queue", qs],
    queryFn: () => api.get(`/work-queue${qs ? `?${qs}` : ""}`).then(r => r.data),
    staleTime: 20_000,
    refetchInterval: 60_000,
  });

  const shown = (data?.items ?? []).filter(i => kind === "all" || i.kind === kind);
  const firstName = (session?.user?.name || "").split(" ")[0];

  return (
    <div className="h-full overflow-y-auto" style={{ background: "var(--haip-bg, var(--background))" }}>
      <div className="max-w-[1000px] mx-auto px-4 sm:px-6 py-5 space-y-4">
        <header className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="haip-page-title">My day{firstName ? `, ${firstName}` : ""}</h1>
            <p className="text-sm mt-0.5" style={{ color: "var(--haip-fg-subtle)" }}>
              {data ? (data.total === 0 ? "Nothing waiting. Enjoy it." : `${data.total} thing${data.total === 1 ? "" : "s"} waiting, most urgent first`) : "Loading…"}
            </p>
          </div>
          {isOwnerView && (
            <div className="flex gap-1 p-1 rounded-xl" style={{ background: "var(--muted)" }} role="tablist" aria-label="Scope">
              {[["team", "Whole team"], ["mine", "Mine"]].map(([id, label]) => {
                const on = (id === "mine") === mineOnly;
                return (
                  <button key={id} type="button" role="tab" aria-selected={on} onClick={() => setMineOnly(id === "mine")}
                    className="text-xs font-bold px-3 py-1.5 rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-teal-600"
                    style={on ? { background: "var(--haip-card)", color: "var(--primary)" } : { color: "var(--haip-fg-muted)" }}>
                    {label}
                  </button>
                );
              })}
            </div>
          )}
        </header>

        {/* Counts double as filters, so the summary and the list can't disagree. */}
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2">
          {KINDS.map(k => {
            const n = data?.counts[k.id] ?? 0;
            const on = kind === k.id;
            const Icon = k.icon;
            return (
              <button key={k.id} type="button" aria-pressed={on} onClick={() => setKind(on ? "all" : k.id)}
                className={cn("haip-card px-3 py-2.5 text-left transition-shadow hover:shadow-md outline-none focus-visible:ring-2 focus-visible:ring-teal-600",
                  on && "ring-2 ring-teal-600")}>
                <span className="flex items-center gap-1.5 text-[11px] font-semibold truncate" style={{ color: "var(--haip-fg-subtle)" }}>
                  <Icon size={12} className={k.tone} />{k.label}
                </span>
                <span className={cn("block text-xl font-bold tabular-nums mt-0.5", n ? k.tone : "")}
                  style={n ? undefined : { color: "var(--haip-fg-muted)" }}>
                  {n}
                </span>
              </button>
            );
          })}
        </div>

        <section className="haip-card overflow-hidden">
          {isError ? (
            <p className="p-8 text-center text-sm" style={{ color: "var(--haip-fg-muted)" }}>
              Couldn&apos;t load your queue. Refresh to try again.
            </p>
          ) : isLoading ? (
            <div className="p-4 space-y-2">{[0, 1, 2, 3].map(i => <Skeleton key={i} className="h-12" />)}</div>
          ) : shown.length === 0 ? (
            <div className="py-14 flex flex-col items-center gap-2 text-center px-6">
              <CheckCircle2 size={26} className="text-emerald-600" />
              <p className="font-semibold" style={{ color: "var(--haip-fg)" }}>
                {kind === "all" ? "All caught up" : "Nothing here right now"}
              </p>
              <p className="text-sm" style={{ color: "var(--haip-fg-subtle)" }}>
                {kind === "all"
                  ? "No one is waiting, every missed call has been returned and no follow-up is due."
                  : "Clear this filter to see the rest of your day."}
              </p>
            </div>
          ) : (
            shown.map((item, i) => <Row key={`${item.kind}-${item.inquiry_id ?? item.guest_id ?? i}`} item={item} />)
          )}
        </section>
      </div>
    </div>
  );
}
