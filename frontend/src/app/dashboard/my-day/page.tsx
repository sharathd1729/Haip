"use client";
// My day -- the one queue. Everything waiting on this person, in the order
// it should be dealt with: overdue first, then whoever has waited longest.
// Backed by GET /work-queue (work_queue_service), the same source the
// dashboard cards and the sidebar badge use, so the numbers always agree.
//
// Keyboard triage: J / K move down / up the list, Enter does the row's action
// (opens it, or places the call). Built on the shared kit (components/ui/kit).
import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { useToast } from "@/components/ui/toast";
import { Skeleton } from "@/components/ui/skeleton";
import { ChannelBadges, toGuestChannel } from "@/components/inbox/ChannelBadges";
import { Card, EmptyState, FilterBar, FilterChip, PageHeader, StatusPill, Tabs, type Tone } from "@/components/ui/kit";

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

// Order here is the order of the filter chips.
const KINDS: { id: Kind; label: string; tone: Tone }[] = [
  { id: "followup",   label: "Due now",         tone: "danger" },
  { id: "reply",      label: "Waiting on us",   tone: "warning" },
  { id: "draft",      label: "Drafts to send",  tone: "info" },
  { id: "callback",   label: "Call back",       tone: "danger" },
  { id: "call_new",   label: "New, not called", tone: "success" },
  { id: "unassigned", label: "No owner",        tone: "neutral" },
];
const KIND = Object.fromEntries(KINDS.map(k => [k.id, k])) as Record<Kind, (typeof KINDS)[number]>;

function ago(iso: string | null): string {
  if (!iso) return "";
  const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (m < 0) return `in ${Math.abs(m) < 60 ? `${Math.abs(m)}m` : `${Math.round(Math.abs(m) / 60)}h`}`;
  if (m < 60) return `${Math.max(1, m)}m`;
  const h = Math.floor(m / 60);
  return h < 24 ? `${h}h` : `${Math.floor(h / 24)}d`;
}

function Row({ item, active, index }: { item: Item; active: boolean; index: number }) {
  const { toast } = useToast();
  const channels = item.channels.map(toGuestChannel).filter(Boolean) as ReturnType<typeof toGuestChannel>[];

  // "Call" and "Call back" place the call -- the IVR rings your phone, then
  // connects the guest (POST /calls/click-to-call) -- instead of opening a
  // page and leaving you to dial by hand. A shared-a-number lead is named by
  // its inquiry (the server holds the number); a missed call carries its own.
  const dialPayload: { inquiry_id: string } | { guest_number: string } | null =
    item.kind === "call_new" && item.inquiry_id ? { inquiry_id: item.inquiry_id }
      : item.kind === "callback" && item.guest_phone ? { guest_number: item.guest_phone }
        : null;
  const dial = useMutation({
    mutationFn: () => api.post("/calls/click-to-call", dialPayload!),
    onSuccess: () => toast({
      variant: "success", title: "Calling…",
      description: `Your phone will ring first, then we'll connect you to ${item.title}.`,
    }),
    onError: (err: any) => {
      const raw = err?.response?.data?.detail;
      const description = typeof raw === "string"
        ? raw
        : Array.isArray(raw) ? raw.map((e: any) => e?.msg ?? JSON.stringify(e)).join("; ") : "Could not start the call.";
      toast({ variant: "error", title: "Call failed", description });
    },
  });

  const kind = KIND[item.kind];
  const rowCls = cn(
    "flex min-h-14 flex-1 min-w-0 items-center gap-3 px-4 py-3 outline-none transition-colors hover:bg-[var(--haip-surface)]",
    "focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary",
  );
  const actionCls = "inline-flex min-h-9 items-center whitespace-nowrap rounded-lg bg-primary px-3.5 text-xs font-bold text-primary-foreground disabled:opacity-60 outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2";

  const body = (
    <>
      <div className="min-w-0 flex-1">
        <span className="flex min-w-0 items-center gap-1.5">
          <span className="truncate text-sm font-bold text-[var(--haip-fg)]">{item.title}</span>
          {channels.length > 0 && <ChannelBadges channels={channels as never} size={13} />}
        </span>
        <p className="mt-0.5 truncate text-xs text-[var(--haip-fg-subtle)]">
          {item.detail}
          {item.owner_name ? ` · ${item.owner_name}` : ""}
        </p>
      </div>
      <StatusPill tone={kind.tone} className="hidden sm:inline-flex">{kind.label}</StatusPill>
      <span className={cn("min-w-10 text-right text-xs font-semibold tabular-nums", item.overdue ? "text-[var(--haip-status-danger-fg)]" : "text-[var(--haip-fg-subtle)]")}
        title={item.since ? `Waiting since ${new Date(item.since).toLocaleString("en-IN")}` : undefined}>
        {ago(item.since)}
      </span>
    </>
  );

  const wrap = cn("flex items-center border-t border-[var(--haip-border)] first:border-t-0", active && "bg-primary/5 shadow-[inset_3px_0_0_var(--primary)]");

  // Everything else opens where it says: the whole row is one link.
  if (!dialPayload) {
    return (
      <div className={wrap} data-row={index}>
        <Link href={item.href} data-primary className={rowCls}>
          {body}
          <span className={actionCls} aria-hidden>{item.action}</span>
        </Link>
      </div>
    );
  }
  // A call row: the details are a link, the action is a real button beside it
  // (a button can't sit inside a link).
  return (
    <div className={cn(wrap, "gap-3 pr-4")} data-row={index}>
      <Link href={item.href} className={rowCls}>{body}</Link>
      <button type="button" data-primary onClick={() => dial.mutate()} disabled={dial.isPending} className={actionCls}>
        {dial.isPending ? "Calling…" : item.action}
      </button>
    </div>
  );
}

function isTyping(el: EventTarget | null): boolean {
  const n = el as HTMLElement | null;
  return !!n && (n.tagName === "INPUT" || n.tagName === "TEXTAREA" || n.tagName === "SELECT" || n.isContentEditable);
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
  const [cursor, setCursor] = useState(0);
  const listRef = useRef<HTMLDivElement>(null);

  const params = new URLSearchParams();
  if (isOwnerView && mineOnly) params.set("mine_only", "true");
  const qs = params.toString();

  const { data, isLoading, isError, refetch } = useQuery<Queue>({
    queryKey: ["work-queue", qs],
    queryFn: () => api.get(`/work-queue${qs ? `?${qs}` : ""}`).then(r => r.data),
    staleTime: 20_000,
    refetchInterval: 60_000,
  });

  const shown = (data?.items ?? []).filter(i => kind === "all" || i.kind === kind);
  const firstName = (session?.user?.name || "").split(" ")[0];
  const at = Math.min(cursor, Math.max(0, shown.length - 1));

  // J / K / Enter. Ignored while typing, with modifier keys, or when nothing is listed.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.metaKey || e.ctrlKey || e.altKey || isTyping(e.target) || shown.length === 0) return;
      const k = e.key.toLowerCase();
      if (k === "j" || k === "k") {
        e.preventDefault();
        setCursor(c => {
          const next = Math.min(shown.length - 1, Math.max(0, Math.min(c, shown.length - 1) + (k === "j" ? 1 : -1)));
          listRef.current?.querySelector(`[data-row="${next}"]`)?.scrollIntoView({ block: "nearest" });
          return next;
        });
      } else if (e.key === "Enter" && !(e.target as HTMLElement).closest("a,button")) {
        (listRef.current?.querySelector(`[data-row="${at}"] [data-primary]`) as HTMLElement | null)?.click();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [shown.length, at]);

  const subtitle = !data ? "Loading…"
    : data.total === 0 ? "Nothing waiting. Enjoy it."
      : `${data.total} thing${data.total === 1 ? "" : "s"} waiting, most urgent first`;

  return (
    <div className="h-full overflow-y-auto bg-[var(--haip-bg,var(--background))]">
      <div className="mx-auto max-w-[1000px] space-y-4 px-4 py-5 sm:px-6">
        <PageHeader
          title={`My day${firstName ? `, ${firstName}` : ""}`}
          subtitle={subtitle}
          actions={isOwnerView && (
            <Tabs label="Scope" value={mineOnly ? "mine" : "team"} onChange={v => setMineOnly(v === "mine")}
              items={[{ value: "team", label: "Whole team" }, { value: "mine", label: "Mine" }]} />
          )}
        />

        {/* Counts double as filters, so the summary and the list can't disagree. */}
        <FilterBar className="flex-nowrap overflow-x-auto pb-1 sm:flex-wrap">
          <FilterChip active={kind === "all"} onClick={() => { setKind("all"); setCursor(0); }} count={data?.total}>All</FilterChip>
          {KINDS.map(k => (
            <FilterChip key={k.id} active={kind === k.id} count={data?.counts[k.id] ?? 0}
              onClick={() => { setKind(kind === k.id ? "all" : k.id); setCursor(0); }}>
              {k.label}
            </FilterChip>
          ))}
        </FilterBar>

        <Card className="overflow-hidden">
          {isError ? (
            <EmptyState title="Couldn't load your queue" hint="Check your connection and try again."
              action={<button type="button" onClick={() => refetch()} className="h-9 rounded-lg border border-[var(--haip-border)] px-4 text-[13px] font-semibold hover:bg-[var(--haip-surface)]">Try again</button>} />
          ) : !data ? (
            // No data yet. On the server a query is never "loading", so keying off `data` keeps the server
            // and browser renders identical (no hydration mismatch).
            <div className="space-y-2 p-4">{[0, 1, 2, 3].map(i => <Skeleton key={i} className="h-12" />)}</div>
          ) : shown.length === 0 ? (
            <EmptyState
              title={kind === "all" ? "All caught up" : "Nothing here right now"}
              hint={kind === "all"
                ? "No one is waiting, every missed call has been returned and no follow-up is due."
                : "Clear this filter to see the rest of your day."} />
          ) : (
            <div ref={listRef}>
              {shown.map((item, i) => (
                <Row key={`${item.kind}-${item.inquiry_id ?? item.guest_id ?? i}`} item={item} active={i === at} index={i} />
              ))}
            </div>
          )}
        </Card>

        {shown.length > 0 && (
          <p className="hidden text-xs text-[var(--haip-fg-subtle)] md:block">
            <kbd className="rounded border border-[var(--haip-border)] px-1.5 font-sans">J</kbd> next ·{" "}
            <kbd className="rounded border border-[var(--haip-border)] px-1.5 font-sans">K</kbd> previous ·{" "}
            <kbd className="rounded border border-[var(--haip-border)] px-1.5 font-sans">Enter</kbd> do the action
          </p>
        )}
      </div>
    </div>
  );
}
