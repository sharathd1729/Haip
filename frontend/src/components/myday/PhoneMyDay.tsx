"use client";
// My day on a phone (mobile-first plan, approved mockup 24 Oct 2026): one list, best chance first. Owners and managers pick
// Mine / Team; one chip row (All, Call backs, New, Replies) with the rest of the kinds behind Filters; then the server's lanes
// as "Call now", "Waiting for a reply" and "Chase when free". Each row: who, why, how late (the server's `severity`, the same
// rule the alerts use), and ONE action: Call (click-to-call), Reply, or Open. Same source as the desktop page: GET /work-queue.
import { useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import api from "@/lib/api";
import { ChevronRight, MessageCircle, Phone } from "@/lib/icons";
import { Skeleton } from "@/components/ui/skeleton";
import { GuestAvatar } from "@/components/crm/GuestAvatar";
import { CalendarClashes } from "@/components/dashboard/today/CalendarClashes";
import { ConsultsPanel } from "@/components/consults/ConsultsPanel";
import {
  BottomSheet, ChipRow, CompactRow, EmptyState, RowAction, RowList, RowSection, RowTag, Tabs,
} from "@/components/ui/kit";
import { SEVERITY_TONE, waitText, type Severity } from "@/lib/waitText";
import { dialPayload, useDial } from "./useDial";

type Kind = "consult" | "callback" | "new_lead" | "reply" | "no_reply" | "followup" | "clash";
type Lane = "now" | "today" | "chase";
export interface MyDayItem {
  kind: Kind; title: string; detail: string; action: string; href: string;
  inquiry_id: string | null; guest_id: string | null; guest_phone: string | null;
  owner_id: string | null; owner_name: string | null; channels: string[]; since: string | null;
  severity: Severity; facts: string[]; has_draft: boolean; flags?: string[]; lane?: Lane;
  tasks?: { title: string; due: string | null; overdue: boolean }[];
}
interface Queue { counts: Record<Kind, number>; people: number; people_waiting?: number; items: MyDayItem[]; scope: "mine" | "team" }

const CHIPS: { value: string; label: string; kind?: Kind }[] = [
  { value: "all", label: "All" },
  { value: "callback", label: "Call backs", kind: "callback" },
  { value: "new_lead", label: "New", kind: "new_lead" },
  { value: "reply", label: "Replies", kind: "reply" },
];
// The rest of the kinds live behind Filters.
const MORE: { value: Kind; label: string }[] = [
  { value: "no_reply", label: "Not replying to us" },
  { value: "followup", label: "Follow-ups" },
  { value: "clash", label: "Calendar clashes" },
];
const LANES: { id: Lane; title: string }[] = [
  { id: "now", title: "Call now" },
  { id: "today", title: "Reply or follow up today" },
  { id: "chase", title: "Chase when free" },
];
const CHASE_SHOWN = 5;
const FLAG_LABEL: Record<string, string> = { not_called: "Not called yet", open_lead: "On active leads", at_risk: "Promising leads at risk" };

const laneOf = (i: MyDayItem): Lane => i.lane ?? (i.severity === "stale" ? "chase" : "today");

function Row({ item }: { item: MyDayItem }) {
  const dial = useDial(item.title);
  const payload = dialPayload(item);
  const fact = item.facts[0];
  const task = item.tasks?.[0];
  const action = payload
    ? <RowAction icon={Phone} label={`${item.action} ${item.title}`} primary disabled={dial.isPending} onClick={() => dial.mutate(payload)} />
    : item.kind === "reply" || item.kind === "no_reply"
      ? <RowAction icon={MessageCircle} label={`Reply to ${item.title}`} href={item.href} />
      : <RowAction icon={ChevronRight} label={`Open ${item.title}`} href={item.href} />;
  return (
    <CompactRow href={item.href} avatar={<GuestAvatar name={item.title} phone={item.guest_phone} />}
      title={fact ? `${item.title} · ${fact}` : item.title}
      subtitle={task ? `${item.detail} · Task: ${task.title}` : item.detail}
      meta={waitText(item.since, item.severity) || undefined} metaTone={SEVERITY_TONE[item.severity]}
      extra={<>
        {item.has_draft && <RowTag tone="info">AI reply ready</RowTag>}
        {item.kind === "new_lead" && !item.owner_id && <RowTag tone="warning">unassigned</RowTag>}
      </>}
      actions={action} />
  );
}

export function PhoneMyDay() {
  const { data: session } = useSession();
  const role = session?.user?.role;
  const isOwnerView = role === "owner" || role === "manager";
  const params0 = useSearchParams();
  const k0 = params0.get("kind");
  const [chip, setChip] = useState<string>(k0 && [...CHIPS, ...MORE].some(c => c.value === k0) ? k0 : "all");
  const f0 = params0.get("flag");
  const [flag, setFlag] = useState<string | null>(f0 && f0 in FLAG_LABEL ? f0 : null);
  const [scope, setScope] = useState<"team" | "mine">("team");
  const [filters, setFilters] = useState(false);
  const [allChase, setAllChase] = useState(false);
  const mine = isOwnerView && scope === "mine";
  const qs = mine ? "mine_only=true" : "";

  // Same key as the desktop page, the Now button and Home, so they share one cached answer.
  const { data, isError, refetch } = useQuery<Queue>({
    queryKey: ["work-queue", qs],
    queryFn: () => api.get(`/work-queue${qs ? `?${qs}` : ""}`).then(r => r.data),
    staleTime: 15_000, refetchInterval: 30_000, refetchOnWindowFocus: true,
  });
  // The other scope's head count, for its tab (owners and managers only).
  const other = useQuery<{ people_waiting?: number; people: number }>({
    queryKey: ["work-queue-counts", mine ? "" : "mine_only=true"],
    queryFn: () => api.get("/work-queue/counts", { params: mine ? {} : { mine_only: true } }).then(r => r.data),
    enabled: isOwnerView, staleTime: 30_000,
  });

  const kind = chip === "all" ? null : (chip as Kind);
  const filtered = useMemo(() => (data?.items ?? []).filter(i =>
    (!kind || i.kind === kind || (kind === "followup" && (i.tasks?.length ?? 0) > 0)) && (!flag || (i.flags ?? []).includes(flag))), [data, kind, flag]);
  const clashes = filtered.filter(i => i.kind === "clash");
  const people = filtered.filter(i => i.kind !== "clash" && i.kind !== "consult");
  const byLane: Record<Lane, MyDayItem[]> = { now: [], today: [], chase: [] };
  for (const i of people) byLane[laneOf(i)].push(i);
  const count = (q?: { people_waiting?: number; people: number }) => q ? (q.people_waiting ?? q.people) : undefined;
  const moreOn = MORE.some(m => m.value === chip);

  return (
    <div className="h-full overflow-y-auto bg-[var(--haip-bg,var(--background))]">
      <div className="grid gap-3 px-4 pb-8 pt-3">
        {isOwnerView && (
          <Tabs label="Whose work" value={scope} onChange={v => setScope(v as "team" | "mine")} className="w-full [&>button]:flex-1 [&>button]:justify-center"
            items={[{ value: "mine", label: "Mine", count: mine ? count(data) : count(other.data) },
              { value: "team", label: "Team", count: mine ? count(other.data) : count(data) }]} />
        )}
        <ConsultsPanel />
        <ChipRow label="What kind" value={moreOn ? "" : chip} onChange={setChip} onFilters={() => setFilters(true)} filterCount={moreOn ? 1 : 0}
          items={CHIPS.map(c => ({ value: c.value, label: c.label, count: c.kind ? data?.counts[c.kind] : count(data) }))} />
        {(flag || moreOn) && (
          <p className="flex flex-wrap items-center gap-2 text-[13px] text-[var(--haip-fg-2)]">
            Showing only: <RowTag tone="brand">{flag ? FLAG_LABEL[flag] : MORE.find(m => m.value === chip)?.label}</RowTag>
            <button type="button" onClick={() => { setFlag(null); setChip("all"); }} className="min-h-11 px-1 font-semibold text-primary">Show everyone</button>
          </p>
        )}

        {isError ? (
          <div className="haip-card"><EmptyState title="Couldn't load your list" hint="Check your connection and try again."
            action={<button type="button" onClick={() => refetch()} className="haip-btn-secondary min-h-11">Try again</button>} /></div>
        ) : !data ? (
          <div className="grid gap-1.5" aria-busy="true">{[0, 1, 2, 3, 4].map(i => <Skeleton key={i} className="h-[64px] rounded-xl" />)}</div>
        ) : filtered.length === 0 ? (
          <div className="haip-card"><EmptyState title={chip === "all" && !flag ? "All caught up" : "Nothing here right now"}
            hint={chip === "all" && !flag ? "Every lead has been contacted, every missed call returned and no follow-up is due." : "Clear this filter to see everyone else."} /></div>
        ) : (
          <>
            <CalendarClashes items={clashes} />
            {LANES.map(l => {
              const rows = byLane[l.id];
              if (!rows.length) return null;
              const shown = l.id === "chase" && !allChase ? rows.slice(0, CHASE_SHOWN) : rows;
              return (
                <RowSection key={l.id} title={l.title} count={rows.length}>
                  <RowList label={l.title}>{shown.map((i, n) => <Row key={`${i.kind}-${i.guest_id ?? i.inquiry_id ?? n}-${n}`} item={i} />)}</RowList>
                  {l.id === "chase" && rows.length > CHASE_SHOWN ? (
                    <button type="button" aria-expanded={allChase} onClick={() => setAllChase(v => !v)}
                      className="min-h-11 justify-self-start text-[13px] font-semibold text-primary">
                      {allChase ? "Show fewer" : `Show ${rows.length - CHASE_SHOWN} more`}
                    </button>
                  ) : null}
                </RowSection>
              );
            })}
          </>
        )}
      </div>

      <BottomSheet open={filters} onOpenChange={setFilters} title="More filters" description="Pick one kind of work to see only that.">
        <ul className="grid">
          {MORE.map(m => (
            <li key={m.value}>
              <button type="button" aria-pressed={chip === m.value} onClick={() => { setChip(chip === m.value ? "all" : m.value); setFilters(false); }}
                className="flex min-h-12 w-full items-center justify-between border-t border-[var(--haip-border)] text-left text-[15px] text-[var(--haip-fg)] first:border-t-0">
                <span className={chip === m.value ? "font-bold text-primary" : undefined}>{m.label}</span>
                <span className="num text-[13px] font-semibold text-[var(--haip-fg-subtle)]">{data?.counts[m.value] ?? 0}</span>
              </button>
            </li>
          ))}
        </ul>
      </BottomSheet>
    </div>
  );
}
