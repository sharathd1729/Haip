"use client";
// My day -- the "act now" list. Everyone who gave us a number, called, or is waiting on a person, worst first, so no enquiry sits
// unseen. Backed by GET /work-queue (work_queue_service), the same source the dashboard cards read, so the numbers always agree.
//
// A person appears once, under the most specific reason. How late something is comes from the server (`severity`), the same
// rule the WhatsApp/reminder alerts use, so this screen and an alert never disagree about what is urgent.
// Keyboard triage: J / K move down / up the list, Enter does the row's action. Built on the shared kit (components/ui/kit).
import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { useToast } from "@/components/ui/toast";
import { Skeleton } from "@/components/ui/skeleton";
import { ChannelBadges, toGuestChannel } from "@/components/inbox/ChannelBadges";
import { SendQuoteButton } from "@/components/quotes/SendQuoteButton";
import { Card, EmptyState, FilterBar, FilterChip, PageHeader, StatusPill, Tabs, type Tone } from "@/components/ui/kit";

type Kind = "callback" | "new_lead" | "reply" | "followup";
type Severity = "fresh" | "late" | "urgent" | "critical" | "stale";

interface Item {
  kind: Kind; title: string; detail: string; action: string; href: string;
  inquiry_id: string | null; guest_id: string | null; guest_phone: string | null;
  owner_id: string | null; owner_name: string | null;
  channels: string[]; since: string | null; overdue: boolean;
  severity: Severity; attempts: number; facts: string[]; has_draft: boolean;
}
interface Queue {
  counts: Record<Kind, number>;
  oldest: Record<Kind, string | null>;
  severity: Record<Severity, number>;
  total: number;
  people: number;
  unowned: number;
  items: Item[];
  scope: "mine" | "team";
}

// Order here is the order of the filter chips.
const KINDS: { id: Kind; label: string }[] = [
  { id: "new_lead", label: "New leads" },
  { id: "callback", label: "Missed calls" },
  { id: "reply",    label: "Waiting for a reply" },
  { id: "followup", label: "Follow-ups" },
];
const KIND_LABEL: Record<Kind, string> = {
  new_lead: "New lead", callback: "Missed call", reply: "Waiting for a reply", followup: "Follow-up",
};

const SEVERITY: Record<Severity, { label: string; tone: Tone; stripe: string }> = {
  fresh:    { label: "New",          tone: "info",    stripe: "shadow-[inset_3px_0_0_var(--haip-status-info-fg)]" },
  late:     { label: "Waiting",      tone: "warning", stripe: "shadow-[inset_3px_0_0_var(--haip-status-warning-fg)]" },
  urgent:   { label: "Overdue",      tone: "danger",  stripe: "shadow-[inset_3px_0_0_var(--haip-status-danger-fg)]" },
  critical: { label: "Very overdue", tone: "danger",  stripe: "shadow-[inset_3px_0_0_var(--haip-status-danger-fg)]" },
  stale:    { label: "Gone cold",    tone: "neutral", stripe: "" },
};

function ago(iso: string | null): string {
  if (!iso) return "";
  const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (m < 0) return `in ${Math.abs(m) < 60 ? `${Math.abs(m)}m` : `${Math.round(Math.abs(m) / 60)}h`}`;
  if (m < 1) return "just now";
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return m % 60 && h < 6 ? `${h}h ${m % 60}m` : `${h}h`;
  return `${Math.floor(h / 24)}d`;
}

function Row({ item, active, index }: { item: Item; active: boolean; index: number }) {
  const { toast } = useToast();
  const channels = item.channels.map(toGuestChannel).filter(Boolean) as ReturnType<typeof toGuestChannel>[];
  const sev = SEVERITY[item.severity];
  const late = item.severity !== "fresh" && item.severity !== "stale";

  // "Call" and "Call back" place the call -- the IVR rings your phone, then connects the guest (POST /calls/click-to-call) --
  // instead of opening a page and leaving you to dial by hand. A lead is named by its enquiry (the server holds the number);
  // a lead with no enquiry yet, or a missed call, carries its own number.
  const dialPayload: { inquiry_id: string } | { guest_number: string } | null =
    item.kind === "new_lead" && item.inquiry_id ? { inquiry_id: item.inquiry_id }
      : (item.kind === "new_lead" || item.kind === "callback") && item.guest_phone ? { guest_number: item.guest_phone }
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

  const rowCls = cn(
    "flex min-h-16 flex-1 min-w-0 items-center gap-3 px-4 py-3 outline-none transition-colors hover:bg-[var(--haip-surface)]",
    "focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary",
  );
  const actionCls = "inline-flex min-h-11 items-center justify-center whitespace-nowrap rounded-lg bg-primary px-4 text-[13px] font-bold text-primary-foreground disabled:opacity-60 outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2";

  const body = (
    <>
      <div className="min-w-0 flex-1">
        <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5">
          <span className="truncate text-sm font-bold text-[var(--haip-fg)]">{item.title}</span>
          {channels.length > 0 && <ChannelBadges channels={channels as never} size={13} />}
          <StatusPill tone={sev.tone}>{sev.label}</StatusPill>
          {/* Phones: the wait sits in this line, so the right-hand column (and its width) is not needed. */}
          <span className={cn("text-[11.5px] font-bold tabular-nums sm:hidden", late ? "text-[var(--haip-status-danger-fg)]" : "text-[var(--haip-fg-subtle)]")}>
            {ago(item.since)}
          </span>
          {item.kind !== "new_lead" && <span className="text-[11px] font-semibold uppercase tracking-wide text-[var(--haip-fg-subtle)]">{KIND_LABEL[item.kind]}</span>}
        </span>
        <p className="mt-0.5 line-clamp-2 text-xs text-[var(--haip-fg-subtle)]">{item.detail}</p>
        {(item.facts.length > 0 || item.has_draft || item.guest_phone || item.owner_name || item.kind === "new_lead") && (
          <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11.5px] text-[var(--haip-fg-subtle)]">
            {item.facts.map(f => <span key={f} className="rounded bg-[var(--haip-surface)] px-1.5 py-0.5 font-medium text-[var(--haip-fg-2)]">{f}</span>)}
            {item.guest_phone && <span className="tabular-nums">{item.guest_phone}</span>}
            {item.has_draft && <span className="font-semibold text-[var(--haip-status-info-fg)]">AI reply ready to review</span>}
            {item.owner_name
              ? <span>· {item.owner_name}</span>
              : item.kind === "new_lead" && <span className="font-semibold text-[var(--haip-status-warning-fg)]">· Nobody owns this yet</span>}
          </p>
        )}
      </div>
      <div className="hidden min-w-12 flex-col items-end text-right sm:flex">
        <span className={cn("text-sm font-bold tabular-nums", late ? "text-[var(--haip-status-danger-fg)]" : "text-[var(--haip-fg-subtle)]")}
          title={item.since ? `Waiting since ${new Date(item.since).toLocaleString("en-IN")}` : undefined}>
          {ago(item.since)}
        </span>
        <span className="text-[10.5px] text-[var(--haip-fg-subtle)]">{item.kind === "followup" ? "overdue" : "waiting"}</span>
      </div>
    </>
  );

  const wrap = cn("flex items-center border-t border-[var(--haip-border)] first:border-t-0", sev.stripe, active && "bg-primary/5");

  // "Quote": the rate calculator for this person, beside the row (a button can't sit inside a link). Same work-queue item;
  // the sheet resolves the lead (open lead, a new one after Sold/Lost, or "Add as new lead" for a number with none).
  const quote = (
    <SendQuoteButton iconOnlyBelowSm label="Quote" className="mr-1"
      args={{ inquiryId: item.inquiry_id, guestId: item.guest_id, phone: item.inquiry_id || item.guest_id ? null : item.guest_phone,
        from: "my_day", name: item.title }} />
  );
  // Everything else opens where it says: the whole row is one link.
  if (!dialPayload) {
    return (
      <div className={cn(wrap, "pr-3")} data-row={index}>
        <Link href={item.href} data-primary className={rowCls}>
          {body}
          <span className={actionCls} aria-hidden>{item.action}</span>
        </Link>
        {quote}
      </div>
    );
  }
  // A call row: the details are a link, the action is a real button beside it (a button can't sit inside a link).
  return (
    <div className={cn(wrap, "gap-3 pr-4")} data-row={index}>
      <Link href={item.href} className={rowCls}>{body}</Link>
      {quote}
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

function Section({ title, hint, count, children }: { title: string; hint?: string; count: number; children: React.ReactNode }) {
  return (
    <section className="space-y-2">
      <h2 className="flex items-baseline gap-2 text-[13px] font-bold uppercase tracking-wide text-[var(--haip-fg-2)]">
        {title}
        <span className="rounded-full bg-[var(--haip-surface)] px-2 py-0.5 text-[11px] font-semibold tabular-nums text-[var(--haip-fg-subtle)]">{count}</span>
        {hint && <span className="text-[11.5px] font-normal normal-case tracking-normal text-[var(--haip-fg-subtle)]">{hint}</span>}
      </h2>
      <Card className="overflow-hidden">{children}</Card>
    </section>
  );
}

export default function MyDayPage() {
  const { data: session } = useSession();
  const role = session?.user?.role;
  const isOwnerView = role === "owner" || role === "manager";
  const [mineOnly, setMineOnly] = useState(false);
  const [showCold, setShowCold] = useState(false);
  // The dashboard cards deep-link here with ?kind=, so a card opens exactly the rows it counted.
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

  const { data, isError, refetch } = useQuery<Queue>({
    queryKey: ["work-queue", qs],
    queryFn: () => api.get(`/work-queue${qs ? `?${qs}` : ""}`).then(r => r.data),
    staleTime: 15_000,
    refetchInterval: 30_000,
    refetchOnWindowFocus: true,
  });

  const filtered = (data?.items ?? []).filter(i => kind === "all" || i.kind === kind);
  const act = filtered.filter(i => i.severity !== "stale" && i.severity !== "fresh");
  const fresh = filtered.filter(i => i.severity === "fresh");
  const cold = filtered.filter(i => i.severity === "stale");
  // One flat order for the keyboard cursor: exactly what is on screen, top to bottom.
  const shown = useMemo(() => [...act, ...fresh, ...(showCold ? cold : [])], [act, fresh, cold, showCold]);
  const at = Math.min(cursor, Math.max(0, shown.length - 1));
  const offset = { act: 0, fresh: act.length, cold: act.length + fresh.length };
  const firstName = (session?.user?.name || "").split(" ")[0];

  // The tab title carries the number, so a pinned tab works as an alert.
  useEffect(() => {
    if (!data) return;
    const n = data.counts.new_lead + data.counts.callback;
    document.title = n > 0 ? `(${n}) My day · HAIP` : "My day · HAIP";
    return () => { document.title = "HAIP"; };
  }, [data]);

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

  const late = data ? data.severity.late + data.severity.urgent + data.severity.critical : 0;
  const subtitle = !data ? "Loading…"
    : data.total === 0 ? "Nobody is waiting. Nice."
      : `${data.people} ${data.people === 1 ? "person is" : "people are"} waiting${late ? `, ${late} past their target time` : ""}${data.unowned ? `, ${data.unowned} with no owner` : ""}`;

  const rows = (list: Item[], start: number) => list.map((item, i) => (
    <Row key={`${item.kind}-${item.guest_id ?? item.inquiry_id ?? i}-${i}`} item={item} active={start + i === at} index={start + i} />
  ));

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
          <FilterChip active={kind === "all"} onClick={() => { setKind("all"); setCursor(0); }} count={data?.total}>Everyone</FilterChip>
          {KINDS.map(k => (
            <FilterChip key={k.id} active={kind === k.id} count={data?.counts[k.id] ?? 0}
              onClick={() => { setKind(kind === k.id ? "all" : k.id); setCursor(0); }}>
              {k.label}
            </FilterChip>
          ))}
        </FilterBar>

        <div ref={listRef} className="space-y-5">
          {isError ? (
            <Card><EmptyState title="Couldn't load your list" hint="Check your connection and try again."
              action={<button type="button" onClick={() => refetch()} className="h-11 rounded-lg border border-[var(--haip-border)] px-4 text-[13px] font-semibold hover:bg-[var(--haip-surface)]">Try again</button>} /></Card>
          ) : !data ? (
            // No data yet. On the server a query is never "loading", so keying off `data` keeps the server
            // and browser renders identical (no hydration mismatch).
            <Card><div className="space-y-2 p-4">{[0, 1, 2, 3].map(i => <Skeleton key={i} className="h-14" />)}</div></Card>
          ) : filtered.length === 0 ? (
            <Card><EmptyState
              title={kind === "all" ? "All caught up" : "Nothing here right now"}
              hint={kind === "all"
                ? "Every lead has been contacted, every missed call returned and no follow-up is due."
                : "Clear this filter to see everyone else."} /></Card>
          ) : (
            <>
              {act.length > 0 && (
                <Section title="Past their target time" count={act.length} hint="call these first">{rows(act, offset.act)}</Section>
              )}
              {fresh.length > 0 && (
                <Section title="Just arrived" count={fresh.length} hint="inside the target time">{rows(fresh, offset.fresh)}</Section>
              )}
              {cold.length > 0 && (
                <section className="space-y-2">
                  <button type="button" onClick={() => setShowCold(v => !v)} aria-expanded={showCold}
                    className="flex min-h-11 w-full items-center justify-between rounded-lg border border-dashed border-[var(--haip-border)] px-4 text-left text-[13px] font-semibold text-[var(--haip-fg-2)] hover:bg-[var(--haip-surface)]">
                    <span>Gone cold ({cold.length}) <span className="font-normal text-[var(--haip-fg-subtle)]">· waiting over 3 days, worth one last try</span></span>
                    <span aria-hidden>{showCold ? "Hide" : "Show"}</span>
                  </button>
                  {showCold && <Card className="overflow-hidden">{rows(cold, offset.cold)}</Card>}
                </section>
              )}
            </>
          )}
        </div>

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
