"use client";
// Bookings on a phone (mobile-first plan, approved mockup 24 Oct 2026): one chip row (Upcoming / Staying / Past / Cancelled with
// counts) + the existing Filters sheet, the next 7 days of each vehicle, then one row per booking (guest and trip, dates and
// vehicle, the amount and a due / paid pill). A row opens its sheet: trip, vehicle, guests, Total / Paid / Still due, and
// Collect (the existing pay-link / record-payment sheet; never charges by itself), WhatsApp (the existing sheet) and Full page.
// Data: GET /bookings (the same list the desktop page reads; this page is only for roles with bookings.read).
import { useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useSession } from "next-auth/react";
import { keepPreviousData, useInfiniteQuery, useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { formatINR } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import { GuestAvatar } from "@/components/crm/GuestAvatar";
import { ChipRow, CompactRow, EmptyState, Fab, FilterSearch, RowList, RowTag } from "@/components/ui/kit";
import { FiltersSheet } from "@/components/bookings/agenda/FiltersSheet";
import { CollectSheet } from "@/components/bookings/CollectSheet";
import { WhatsAppSheet } from "@/components/bookings/WhatsAppSheet";
import {
  NO_FILTERS, SEGMENTS, canEditBookings, filterCount, filterParams, guestName, isOverdue, lakh, todayIST, useHydrated,
  type AgendaList, type AgendaRow, type Filters, type Segment,
} from "@/lib/bookingAgenda";
import { BookingRowSheet, dateSpan } from "./BookingRowSheet";
import { WeekStrip } from "./WeekStrip";

const PER_PAGE = 50;
const QUICK_SEGMENT: Record<string, Segment> = { upcoming: "upcoming", current: "staying", past: "past" };
const SHORT: Record<Segment, string> = { upcoming: "Upcoming", staying: "Staying", past: "Past", cancelled: "Cancelled" };

/** The due / paid pill on a row: overdue money (the one isOverdue rule) wins, then money still due, then paid. */
export function moneyTag(r: AgendaRow, today: string): { label: string; tone: "danger" | "warning" | "success" | "neutral" } | null {
  if (r.raw_status === "cancelled") return { label: "cancelled", tone: "neutral" };
  if (r.total <= 0) return null;
  if (isOverdue(r, today)) return { label: `${formatINR(r.total_outstanding)} overdue`, tone: "danger" };
  if (r.total_outstanding > 0) return { label: `${formatINR(r.total_outstanding)} due`, tone: "warning" };
  return { label: "paid", tone: "success" };
}

export function PhoneBookings() {
  const router = useRouter();
  const params = useSearchParams();
  const { data: session } = useSession();
  const canEdit = canEditBookings(session?.user?.role);
  const quick = params.get("quick") ?? "";
  const [segment, setSegment] = useState<Segment>(QUICK_SEGMENT[quick] ?? "upcoming");
  const [filters, setFilters] = useState<Filters>(quick === "due" ? { ...NO_FILTERS, pay: ["due"] } : NO_FILTERS);
  const [search, setSearch] = useState("");
  const [debounced, setDebounced] = useState("");
  const [showFilters, setShowFilters] = useState(false);
  const [picked, setPicked] = useState<AgendaRow | null>(null);
  const [waFor, setWaFor] = useState<string | null>(null);
  const [collectFor, setCollectFor] = useState<string | null>(null);
  const hydrated = useHydrated();
  useEffect(() => { const t = setTimeout(() => setDebounced(search.trim()), 350); return () => clearTimeout(t); }, [search]);

  const { data: vehicles = [] } = useQuery<{ id: string; name: string }[]>({
    queryKey: ["bookable-properties"], queryFn: () => api.get("/bookings/properties").then(r => r.data), staleTime: 5 * 60_000,
  });
  const base = { search: debounced || undefined, ...filterParams(filters) };
  const sort = segment === "past" || segment === "cancelled" ? "check_in" : "check_in_asc";
  const list = useInfiniteQuery<AgendaList>({
    queryKey: ["bookings", "cards", segment, base],
    queryFn: ({ pageParam }) => api.get("/bookings", {
      params: { ...base, segment, sort, page: pageParam, per_page: PER_PAGE, counts: pageParam === 1 || undefined },
    }).then(r => r.data),
    initialPageParam: 1,
    getNextPageParam: last => (last.meta.current_page < last.meta.last_page ? last.meta.current_page + 1 : undefined),
    placeholderData: keepPreviousData, staleTime: 20_000,
  });
  const pending = !hydrated || list.isPending;
  const first = pending ? undefined : list.data?.pages[0];
  const rows = useMemo(() => (pending ? [] : list.data?.pages.flatMap(p => p.data) ?? []), [pending, list.data]);
  const today = first?.meta.today ?? todayIST();
  const nFilters = filterCount(filters);

  // A bar on the strip may be a booking that is not in the loaded list (another segment): open its full page instead.
  const openById = (id: string) => {
    const r = rows.find(x => x.id === id);
    if (r) setPicked(r); else router.push(`/dashboard/bookings/${id}`);
  };

  return (
    <div className="h-full overflow-y-auto bg-[var(--haip-bg,var(--background))]">
      <div className="grid gap-3 px-4 pb-24 pt-3">
        <ChipRow label="Bookings by status" value={segment} onChange={v => setSegment(v as Segment)} onFilters={() => setShowFilters(true)} filterCount={nFilters}
          items={SEGMENTS.map(s => ({ value: s.value, label: SHORT[s.value], count: first?.meta.segment_counts?.[s.value] }))} />
        <FilterSearch value={search} onChange={setSearch} placeholder="Guest, phone or vehicle" label="Search bookings" className="min-w-0 max-w-none" />
        {(segment === "upcoming" || segment === "staying") && <WeekStrip onOpen={openById} />}

        {pending ? (
          <div className="grid gap-1.5" aria-busy="true">{[0, 1, 2, 3].map(i => <Skeleton key={i} className="h-[72px] rounded-xl" />)}</div>
        ) : list.isError ? (
          <div className="haip-card"><EmptyState title="Could not load bookings" hint="Check your connection and try again."
            action={<button type="button" onClick={() => list.refetch()} className="haip-btn-secondary min-h-11">Try again</button>} /></div>
        ) : rows.length === 0 ? (
          <div className="haip-card"><EmptyState
            title={debounced || nFilters ? "No bookings match" : segment === "staying" ? "Nobody is on a trip right now" : `No ${SHORT[segment].toLowerCase()} bookings`}
            hint={debounced || nFilters ? "Clear the search or a filter to see more." : undefined} /></div>
        ) : (
          <>
            <RowList label={`${SHORT[segment]} bookings`}>
              {rows.map(r => {
                const name = guestName(r);
                const tag = moneyTag(r, today);
                return (
                  <CompactRow key={r.id} onClick={() => setPicked(r)} label={`${name}, open booking details`} avatar={<GuestAvatar name={name} />}
                    title={r.trip ? `${name} · ${r.trip}` : name}
                    subtitle={[dateSpan(r.checkin, r.checkout), r.property?.name].filter(Boolean).join(" · ")}
                    meta={r.total > 0 ? lakh(r.total) : undefined} metaTone="neutral"
                    extra={tag ? <RowTag tone={tag.tone}>{tag.label}</RowTag> : undefined} />
                );
              })}
            </RowList>
            {list.hasNextPage && (
              <button type="button" onClick={() => list.fetchNextPage()} disabled={list.isFetchingNextPage} className="haip-btn-secondary min-h-11">
                {list.isFetchingNextPage ? "Loading…" : `Show more (${rows.length} of ${first?.meta.total ?? rows.length})`}
              </button>
            )}
          </>
        )}
      </div>

      <Fab label="New booking" href="/dashboard/bookings/new" />
      <BookingRowSheet row={picked} today={today} canCollect={canEdit} onClose={() => setPicked(null)}
        onCollect={id => { setPicked(null); setCollectFor(id); }} onWhatsApp={id => { setPicked(null); setWaFor(id); }} />
      <FiltersSheet open={showFilters} onClose={() => setShowFilters(false)} value={filters} onApply={setFilters} vehicles={vehicles} />
      {waFor && <WhatsAppSheet bookingId={waFor} open onClose={() => setWaFor(null)} />}
      {collectFor && <CollectSheet bookingId={collectFor} open onClose={() => setCollectFor(null)} />}
    </div>
  );
}
