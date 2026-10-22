"use client";
// Bookings (CRM), layout A · Cards by date: this month's figures, Upcoming / Staying now / Past / Cancelled, search + one Filters
// sheet, the next 14 days of each caravan, then ONE card per booking under its check-in day (never separate check-in and
// check-out rows: that agenda view, components/bookings/agenda/AgendaDays, is reserved for the Ops module). A booking opens
// beside the list from 1100px (kept in ?b= so a link or reload opens the same one) and full screen on a phone.
import { Suspense, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useSession } from "next-auth/react";
import { keepPreviousData, useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { Download, Plus, SlidersHorizontal, X } from "@/lib/icons";
import api from "@/lib/api";
import { downloadErrorMessage, saveBlob } from "@/lib/download";
import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, FilterSearch, PageHeader, Tabs } from "@/components/ui/kit";
import { MonthSummary } from "@/components/bookings/agenda/MonthSummary";
import { OccupancyStrip } from "@/components/bookings/agenda/OccupancyStrip";
import { BookingCards } from "@/components/bookings/cards/BookingCards";
import { FiltersSheet } from "@/components/bookings/agenda/FiltersSheet";
import { BookingFullSheet, BookingSidePane, useIsPaneWide } from "@/components/bookings/agenda/BookingPane";
import { WhatsAppSheet } from "@/components/bookings/WhatsAppSheet";
import { CollectSheet } from "@/components/bookings/CollectSheet";
import { useGuestCall } from "@/components/bookings/useGuestCall";
import { PAYMENT_STYLE, STATUS_STYLE } from "@/lib/bookings";
import {
  NO_FILTERS, SEGMENTS, canEditBookings, filterCount, filterParams, guestName, todayIST, useHydrated, vehicleSlot,
  type AgendaList, type AgendaRow, type Filters, type Segment,
} from "@/lib/bookingAgenda";

const PER_PAGE = 50;
// The Owner Command Center deep-links here with ?quick=..., so a figure opens the bookings it counted.
const QUICK_SEGMENT: Record<string, Segment> = { upcoming: "upcoming", current: "staying", past: "past" };
const outlineBtn = "inline-flex min-h-11 items-center gap-1.5 rounded-xl border border-[var(--haip-border)] bg-[var(--haip-card)] px-3.5 text-[13.5px] font-semibold text-[var(--haip-fg-2)] hover:bg-[var(--haip-surface)] disabled:opacity-40 md:min-h-10";

function csvCell(v: unknown): string {
  const t = String(v ?? "");
  return /[",\n]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t;
}

function BookingsList() {
  const router = useRouter();
  const params = useSearchParams();
  const call = useGuestCall();
  const { data: session } = useSession();
  const canEdit = canEditBookings(session?.user?.role);
  const guestId = params.get("guest") ?? "";
  const quick = params.get("quick") ?? "";
  const initialQ = params.get("q") ?? params.get("phone") ?? "";

  const [segment, setSegment] = useState<Segment>(QUICK_SEGMENT[quick] ?? "upcoming");
  const [search, setSearch] = useState(initialQ);
  const [debounced, setDebounced] = useState(initialQ);
  const [filters, setFilters] = useState<Filters>(quick === "due" ? { ...NO_FILTERS, pay: ["due"] } : NO_FILTERS);
  const [needsProperty, setNeedsProperty] = useState(quick === "needs_property");
  const [showFilters, setShowFilters] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const [waFor, setWaFor] = useState<string | null>(null);
  const [collectFor, setCollectFor] = useState<string | null>(null);
  const [picked, setPicked] = useState(params.get("b") ?? "");
  const wide = useIsPaneWide();
  // Every query-driven branch waits for hydration: the server and the first client render then match even when the persisted
  // query cache already holds bookings.
  const hydrated = useHydrated();

  useEffect(() => { const t = setTimeout(() => setDebounced(search.trim()), 350); return () => clearTimeout(t); }, [search]);

  function open(id: string) {
    setPicked(id);
    const u = new URLSearchParams(window.location.search);
    u.set("b", id);
    window.history.replaceState(null, "", `?${u.toString()}`);
  }
  function close() {
    setPicked("");
    const u = new URLSearchParams(window.location.search);
    u.delete("b");
    window.history.replaceState(null, "", u.toString() ? `?${u.toString()}` : window.location.pathname);
  }

  const { data: vehicles = [] } = useQuery<{ id: string; name: string }[]>({
    queryKey: ["bookable-properties"], queryFn: () => api.get("/bookings/properties").then(r => r.data), staleTime: 5 * 60_000,
  });
  const vehicleNames = useMemo(() => vehicles.map(v => v.name), [vehicles]);

  const base = {
    search: debounced || undefined, guest_id: guestId || undefined, needs_property: needsProperty || undefined, ...filterParams(filters),
  };
  const sort = segment === "past" || segment === "cancelled" ? "check_in" : "check_in_asc";
  const list = useInfiniteQuery<AgendaList>({
    queryKey: ["bookings", "cards", segment, base],
    queryFn: ({ pageParam }) => api.get("/bookings", {
      params: { ...base, segment, sort, page: pageParam, per_page: PER_PAGE, counts: pageParam === 1 || undefined },
    }).then(r => r.data),
    initialPageParam: 1,
    getNextPageParam: last => (last.meta.current_page < last.meta.last_page ? last.meta.current_page + 1 : undefined),
    placeholderData: keepPreviousData,
    staleTime: 20_000,
  });
  const pending = !hydrated || list.isPending;
  const first = pending ? undefined : list.data?.pages[0];
  const rows = useMemo(() => (pending ? [] : list.data?.pages.flatMap(p => p.data) ?? []), [pending, list.data]);
  const today = first?.meta.today ?? todayIST();
  const counts = first?.meta.segment_counts;
  const nFilters = filterCount(filters) + (needsProperty ? 1 : 0);
  const filtered = !!(debounced || nFilters || guestId);
  const slotOf = (r: AgendaRow) => vehicleSlot(r.property?.name, vehicleNames);

  function clearAll() {
    setSearch(""); setDebounced(""); setFilters(NO_FILTERS); setNeedsProperty(false);
    if (guestId || quick) router.replace("/dashboard/bookings");
  }

  async function exportCsv() {
    setExporting(true);
    setExportError(null);
    try {
      const all: AgendaRow[] = [];
      for (let pg = 1; pg <= 20; pg++) {   // 2,000 bookings is plenty for one export
        const res = await api.get<AgendaList>("/bookings", { params: { ...base, segment, sort, page: pg, per_page: 100 } });
        all.push(...res.data.data);
        if (pg >= res.data.meta.last_page) break;
      }
      const head = ["Booking", "Guest", "Phone", "Vehicle", "Check-in", "Check-out", "Guests", "Status", "Channel", "Total", "Paid", "Due", "Payment status"];
      const lines = all.map(b => [
        b.external_id, guestName(b), b.main_guest?.phone ?? "", b.property?.name ?? "", b.checkin, b.checkout, b.adults + b.children,
        STATUS_STYLE[b.raw_status]?.label ?? b.raw_status, b.channel ?? "direct", b.total, b.total_paid, b.total_outstanding, PAYMENT_STYLE[b.payment_status].label,
      ].map(csvCell).join(","));
      const blob = new Blob(["﻿" + [head.join(","), ...lines].join("\n")], { type: "text/csv;charset=utf-8" });
      await saveBlob(blob, `bookings-${segment}-${today}.csv`);
    } catch (e) {
      setExportError(await downloadErrorMessage(e, "The export failed. Please try again."));
    } finally {
      setExporting(false);
    }
  }

  const segLabel = segment === "staying" ? "current stays" : `${segment} bookings`;
  const showStrip = segment === "upcoming" || segment === "staying";

  return (
    <div className="flex h-full min-h-0 bg-[var(--haip-bg,var(--background))]">
      <div className="min-w-0 flex-1 overflow-y-auto">
        <div className="mx-auto grid max-w-[1280px] gap-3.5 px-4 pb-14 pt-4 sm:px-6">
          <PageHeader title="Bookings"
            actions={<>
              <button type="button" onClick={exportCsv} disabled={exporting || pending || !rows.length} className={cn(outlineBtn, "max-sm:hidden")}>
                <Download size={14} /> {exporting ? "Exporting…" : "Export"}
              </button>
              <Link href="/dashboard/bookings/new"
                className="inline-flex min-h-11 items-center gap-1.5 rounded-xl bg-primary px-4 text-[13.5px] font-semibold text-primary-foreground hover:opacity-90 md:min-h-10">
                <Plus size={15} /> New booking
              </Link>
            </>} />

          {exportError && <p role="alert" className="rounded-xl bg-[var(--haip-status-danger-bg)] px-3 py-2 text-[13.5px] text-[var(--haip-status-danger-fg)]">{exportError}</p>}
          <MonthSummary />

          <Tabs label="Bookings by status" value={segment} onChange={v => setSegment(v as Segment)} className="w-full md:w-fit"
            items={SEGMENTS.map(s => ({
              value: s.value, count: counts?.[s.value],
              label: s.value === "staying" ? <>Staying<span className="max-sm:hidden"> now</span></> : s.label,
            }))} />

          <div className="flex items-center gap-2">
            <FilterSearch value={search} onChange={setSearch} placeholder="Search guest, phone or vehicle" label="Search bookings" className="min-w-0 sm:max-w-none" />
            <button type="button" onClick={() => setShowFilters(true)} className={outlineBtn} aria-label={nFilters ? `Filters, ${nFilters} on` : "Filters"}>
              <SlidersHorizontal size={15} /> Filters
              {nFilters > 0 && <span className="rounded-full bg-primary px-1.5 text-[12px] text-primary-foreground">{nFilters}</span>}
            </button>
          </div>
          {(guestId || needsProperty || filtered) && (
            <div className="flex flex-wrap items-center gap-2 text-[12.5px]">
              {guestId && <span className="rounded-lg bg-[var(--haip-primary-tint)] px-2.5 py-1 font-semibold text-primary">One guest&apos;s bookings</span>}
              {needsProperty && <span className="rounded-lg bg-[var(--haip-status-warning-bg)] px-2.5 py-1 font-semibold text-[var(--haip-status-warning-fg)]">Waiting for a vehicle (on the Unassigned placeholder)</span>}
              <button type="button" onClick={clearAll} className="inline-flex min-h-11 items-center gap-1 px-1 font-semibold text-[var(--haip-fg-subtle)] hover:text-[var(--haip-fg)]">
                <X size={12} /> Clear search and filters
              </button>
            </div>
          )}

          {showStrip && <OccupancyStrip onOpen={open} selectedId={picked} />}

          <div aria-busy={pending} aria-live="polite">
            {pending ? (
              <div className="grid gap-3 sm:grid-cols-2">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-[170px] rounded-2xl" />)}</div>
            ) : list.isError ? (
              <div className="haip-card">
                <EmptyState title="Could not load bookings" hint="Check your connection and try again."
                  action={<button type="button" onClick={() => list.refetch()} className={outlineBtn}>Try again</button>} />
              </div>
            ) : rows.length === 0 ? (
              <div className="haip-card">
                <EmptyState
                  title={filtered ? `No ${segLabel} match` : segment === "staying" ? "Nobody is on a trip right now" : `No ${segLabel}`}
                  hint={filtered ? "Clear the search or a filter to see more." : segment === "upcoming" ? "Create one, or move a lead to Sold." : undefined}
                  action={filtered ? <button type="button" onClick={clearAll} className={outlineBtn}>Clear search and filters</button> : undefined} />
              </div>
            ) : (
              <>
                <BookingCards rows={rows} segment={segment} today={today} selectedId={picked} paneOpen={!!(wide && picked)}
                  canCollect={canEdit} slotOf={slotOf} onOpen={open} onWhatsApp={setWaFor} onCollect={setCollectFor}
                  onCall={r => r.main_guest?.phone && call.mutate({ phone: r.main_guest.phone, name: guestName(r).split(" ")[0] })} />
                {list.hasNextPage && (
                  <div className="mt-3 flex justify-center">
                    <button type="button" onClick={() => list.fetchNextPage()} disabled={list.isFetchingNextPage} className={outlineBtn}>
                      {list.isFetchingNextPage ? "Loading…" : `Show more (${rows.length} of ${first?.meta.total ?? rows.length})`}
                    </button>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      </div>

      {wide && picked && <BookingSidePane id={picked} onClose={close} />}
      {wide === false && <BookingFullSheet id={picked || null} onClose={close} />}

      <FiltersSheet open={showFilters} onClose={() => setShowFilters(false)} value={filters} onApply={setFilters} vehicles={vehicles} />
      {waFor && <WhatsAppSheet bookingId={waFor} open onClose={() => setWaFor(null)} />}
      {collectFor && <CollectSheet bookingId={collectFor} open onClose={() => setCollectFor(null)} />}
    </div>
  );
}

export default function BookingsPage() {
  return (
    <Suspense fallback={<div className="p-6"><Skeleton className="h-10 w-48" /></div>}>
      <BookingsList />
    </Suspense>
  );
}
