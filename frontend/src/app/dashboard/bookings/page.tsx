"use client";
import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import dynamic from "next/dynamic";
import { useRouter, useSearchParams } from "next/navigation";
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Plus, X } from "@/lib/icons";
import api from "@/lib/api";
import { cn, formatINR, formatPhone } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { DataTable, FilterBar, FilterChip, FilterSearch, PageHeader, StatusPill, type Column } from "@/components/ui/kit";
import {
  CHANNEL_OPTIONS, CHANNEL_STYLE, PAYMENT_STYLE, PAYMENT_TONE, STATUS_OPTIONS, STATUS_STYLE, STATUS_TONE, errorMessage, fmtDate,
  type BookingList, type BookingRow,
} from "@/lib/bookings";

const CreateBookingModal = dynamic(
  () => import("@/components/bookings/CreateBookingModal").then(m => m.CreateBookingModal),
  { ssr: false },
);

const selectCls = "h-9 rounded-lg border border-[var(--haip-border)] bg-[var(--haip-card)] px-2.5 text-[12.5px] text-[var(--haip-fg)] focus:outline-none focus:ring-2 focus:ring-primary/30";

// Quick views. Each one sets filters on the server, so the count and the rows always agree.
const QUICK = [
  { id: "upcoming", label: "Upcoming" },
  { id: "current", label: "In house" },
  { id: "past", label: "Past" },
  { id: "due", label: "Needs payment" },
  { id: "needs_property", label: "Needs property" },
] as const;
type Quick = (typeof QUICK)[number]["id"];

function DueLine({ b }: { b: BookingRow }) {
  // A cancelled booking owes nothing, whatever its ledger says.
  if (b.status === "cancelled" || b.payment_status === "paid" || b.total <= 0) return null;
  return (
    <p className={cn("mt-0.5 text-[11px] tabular-nums", b.payment_overdue ? "font-medium text-[var(--haip-status-danger-fg)]" : "text-[var(--haip-fg-subtle)]")}>
      {formatINR(b.total_outstanding)} due{b.next_payment_due_date ? ` ${b.payment_overdue ? "since" : "on"} ${fmtDate(b.next_payment_due_date, false)}` : ""}
    </p>
  );
}

function Thumb({ b }: { b: BookingRow }) {
  const img = b.property?.image;
  return img
    // eslint-disable-next-line @next/next/no-img-element
    ? <img src={img} alt="" className="size-10 flex-shrink-0 rounded-lg object-cover" loading="lazy" />
    : <div className="flex size-10 flex-shrink-0 items-center justify-center rounded-lg bg-primary/10 text-sm font-bold text-primary" aria-hidden>{(b.property?.name ?? "?").slice(0, 1).toUpperCase()}</div>;
}

function ChannelPill({ channel }: { channel: string | null }) {
  const c = CHANNEL_STYLE[(channel ?? "direct").toLowerCase()];
  return <span className={cn("inline-flex items-center whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-semibold leading-4", c?.cls ?? "")}>{c?.label ?? channel ?? "Direct"}</span>;
}

function csvCell(v: unknown): string {
  const t = String(v ?? "");
  return /[",\n]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t;
}

function guestName(b: BookingRow): string {
  const g = b.main_guest;
  if (!g) return "Unknown guest";
  return `${g.first_name} ${g.last_name}`.trim() || (g.phone ? formatPhone(g.phone) : "Unknown guest");
}

function BookingsList() {
  const router = useRouter();
  const params = useSearchParams();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const guestId = params.get("guest") ?? "";
  const initialQ = params.get("q") ?? params.get("phone") ?? "";

  const [search, setSearch] = useState(initialQ);
  const [debounced, setDebounced] = useState(initialQ);
  const [quick, setQuick] = useState<Quick | "">("");
  const [status, setStatus] = useState("");
  const [payment, setPayment] = useState("");
  const [range, setRange] = useState("");
  const [propertyId, setPropertyId] = useState("");
  const [channel, setChannel] = useState("");
  const [exporting, setExporting] = useState(false);
  const [sort, setSort] = useState("check_in");
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [moveTo, setMoveTo] = useState("");
  const [moving, setMoving] = useState(false);
  // On a phone the dropdowns sit behind a "Filters" button so the bookings are visible first.
  const [showFilters, setShowFilters] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => { setDebounced(search.trim()); setPage(1); }, 350);
    return () => clearTimeout(t);
  }, [search]);
  useEffect(() => { setPage(1); setSelected(new Set()); }, [quick, status, payment, range, propertyId, channel, sort, guestId]);

  const { data: properties = [] } = useQuery<{ id: string; name: string }[]>({
    queryKey: ["bookable-properties"],
    queryFn: () => api.get("/bookings/properties").then(r => r.data),
    staleTime: 5 * 60_000,
  });

  // A quick view and the matching dropdown can both be set; the quick view's payment rule wins.
  const filterParams = {
    search: debounced || undefined, status: status || undefined,
    payment_status: (quick === "due" ? "due" : payment) || undefined,
    when: quick === "upcoming" || quick === "current" || quick === "past" ? quick : undefined,
    needs_property: quick === "needs_property" ? true : undefined,
    date_preset: range || undefined, guest_id: guestId || undefined, property_id: propertyId || undefined,
    channel: channel || undefined, sort,
  };

  const { data, isLoading, isError, refetch } = useQuery<BookingList>({
    queryKey: ["bookings", { ...filterParams, page }],
    queryFn: () => api.get("/bookings", { params: { ...filterParams, page, per_page: 25 } }).then(r => r.data),
    placeholderData: keepPreviousData,
    staleTime: 20_000,
  });

  const activeDropdowns = [status, payment, propertyId, channel, range].filter(Boolean).length;
  const rows = data?.data ?? [];
  const meta = data?.meta;
  const filtered = !!(debounced || quick || status || payment || range || guestId || propertyId || channel);

  function clearAll() {
    setSearch(""); setDebounced(""); setQuick(""); setStatus(""); setPayment(""); setRange(""); setPropertyId(""); setChannel("");
    if (guestId) router.replace("/dashboard/bookings");
  }

  async function exportCsv() {
    setExporting(true);
    try {
      const all: BookingRow[] = [];
      for (let pg = 1; pg <= 20; pg++) {   // 2,000 bookings is plenty for one export
        const res = await api.get<BookingList>("/bookings", { params: { ...filterParams, page: pg, per_page: 100 } });
        all.push(...res.data.data);
        if (pg >= res.data.meta.last_page) break;
      }
      const head = ["Booking", "Guest", "Phone", "Property", "Check-in", "Check-out", "Guests", "Status", "Channel", "Total", "Paid", "Due", "Payment status"];
      const lines = all.map(b => [
        b.external_id, guestName(b), b.main_guest?.phone ?? "", b.property?.name ?? "", b.checkin, b.checkout, b.adults + b.children,
        STATUS_STYLE[b.status]?.label ?? b.status, b.channel ?? "direct", b.total, b.total_paid, b.total_outstanding, PAYMENT_STYLE[b.payment_status].label,
      ].map(csvCell).join(","));
      const blob = new Blob(["﻿" + [head.join(","), ...lines].join("\n")], { type: "text/csv;charset=utf-8" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `bookings-${new Date().toISOString().slice(0, 10)}.csv`;
      a.click();
      URL.revokeObjectURL(a.href);
    } finally {
      setExporting(false);
    }
  }

  // Move the selected bookings to one property. Each is saved on its own so an overlap with another booking
  // stops only that one; nothing is forced.
  async function moveSelected() {
    if (!moveTo || selected.size === 0) return;
    setMoving(true);
    const ids = Array.from(selected);
    const results = await Promise.allSettled(ids.map(id => api.patch(`/bookings/${id}`, { property_id: moveTo })));
    const failed = results.map((r, i) => ({ r, id: ids[i] })).filter(x => x.r.status === "rejected");
    const ok = ids.length - failed.length;
    setMoving(false);
    queryClient.invalidateQueries({ queryKey: ["bookings"] });
    setSelected(new Set(failed.map(f => f.id)));
    if (failed.length === 0) {
      setMoveTo("");
      toast({ variant: "success", title: `Moved ${ok} booking${ok === 1 ? "" : "s"}` });
    } else {
      const why = errorMessage((failed[0].r as PromiseRejectedResult).reason, "Could not save");
      toast({ variant: "error", title: `${ok} moved, ${failed.length} not moved`, description: `${why} The unmoved ones stay selected.` });
    }
  }

  const columns: Column<BookingRow>[] = [
    {
      key: "guest", header: "Guest",
      cell: b => (
        <div className="min-w-0">
          <Link href={`/dashboard/bookings/${b.id}`} className="font-semibold text-[var(--haip-fg)] hover:text-primary" onClick={e => e.stopPropagation()}>
            {guestName(b)}
          </Link>
          <p className="text-xs text-[var(--haip-fg-subtle)]">#{b.external_id}{b.main_guest?.phone ? ` · ${formatPhone(b.main_guest.phone)}` : ""}</p>
          {/* On a phone the Stay column is hidden, so the essentials sit under the name. */}
          <p className="mt-0.5 text-xs text-[var(--haip-fg-2)] md:hidden">
            {b.property?.name ?? "No property"} · {fmtDate(b.checkin, false)} to {fmtDate(b.checkout)}
          </p>
        </div>
      ),
    },
    {
      key: "stay", header: "Stay", hideBelow: "md",
      cell: b => (
        <div className="flex items-center gap-3">
          <Thumb b={b} />
          <div className="min-w-0">
            <p className="truncate text-[var(--haip-fg)]">{b.property?.name ?? "No property"}</p>
            <p className="text-xs text-[var(--haip-fg-subtle)]">{fmtDate(b.checkin, false)} to {fmtDate(b.checkout)} · {b.adults + b.children} guest{b.adults + b.children === 1 ? "" : "s"}</p>
          </div>
        </div>
      ),
    },
    { key: "channel", header: "Channel", hideBelow: "lg", cell: b => <ChannelPill channel={b.channel} /> },
    { key: "status", header: "Status", cell: b => <StatusPill tone={STATUS_TONE[b.status] ?? "info"}>{(STATUS_STYLE[b.status] ?? STATUS_STYLE.confirmed).label}</StatusPill> },
    { key: "total", header: "Total", align: "right", cell: b => <span className={cn("font-medium", b.status === "cancelled" && "text-[var(--haip-fg-subtle)] line-through")}>{formatINR(b.total)}</span> },
    {
      key: "payment", header: "Payment", hideBelow: "sm",
      cell: b => b.status === "cancelled"
        ? <span className="text-xs text-[var(--haip-fg-subtle)]">Cancelled</span>
        : <><StatusPill tone={PAYMENT_TONE[b.payment_status]}>{PAYMENT_STYLE[b.payment_status].label}</StatusPill><DueLine b={b} /></>,
    },
  ];

  const unassignedHint = quick === "needs_property"
    ? "These sit on a placeholder property. Select them and move them to the real one."
    : null;

  return (
    <div className="flex h-full flex-col bg-[var(--haip-bg,var(--background))]">
      <div className="flex-shrink-0 space-y-3 border-b border-[var(--haip-border)] bg-[var(--haip-card)] px-4 py-3 sm:px-6">
        <PageHeader
          title="Bookings"
          subtitle={meta ? `${meta.total} booking${meta.total === 1 ? "" : "s"}${filtered ? " match" : ""}` : " "}
          actions={
            <>
              <button onClick={exportCsv} disabled={exporting || !rows.length}
                className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 text-xs font-semibold text-[var(--haip-fg-2)] hover:bg-[var(--haip-surface)] disabled:opacity-40">
                <Download size={13} /> {exporting ? "Exporting..." : "Export"}
              </button>
              <button onClick={() => setCreating(true)}
                className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-primary px-3.5 text-xs font-semibold text-primary-foreground hover:opacity-90">
                <Plus size={14} /> New booking
              </button>
            </>
          }
        />

        <FilterBar className="flex-nowrap overflow-x-auto pb-1 sm:flex-wrap">
          {QUICK.map(q => (
            <FilterChip key={q.id} active={quick === q.id} onClick={() => setQuick(quick === q.id ? "" : q.id)}>{q.label}</FilterChip>
          ))}
        </FilterBar>

        <FilterBar>
          <FilterSearch value={search} onChange={setSearch} placeholder="Guest, phone, property or booking ID" label="Search bookings" />
          <button type="button" aria-expanded={showFilters} onClick={() => setShowFilters(v => !v)}
            className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 text-[12.5px] font-semibold text-[var(--haip-fg-2)] sm:hidden">
            Filters{activeDropdowns > 0 && <span className="rounded-full bg-primary px-1.5 text-[11px] text-primary-foreground">{activeDropdowns}</span>}
          </button>
          <div className={cn("w-full flex-wrap items-center gap-2 sm:flex sm:w-auto", showFilters ? "flex" : "hidden")}>
          <select value={status} onChange={e => setStatus(e.target.value)} className={selectCls} aria-label="Status">
            <option value="">All statuses</option>
            {STATUS_OPTIONS.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
          </select>
          <select value={payment} onChange={e => setPayment(e.target.value)} className={selectCls} aria-label="Payment" disabled={quick === "due"}>
            <option value="">All payments</option>
            <option value="unpaid">Unpaid</option>
            <option value="partial">Part paid</option>
            <option value="paid">Paid</option>
          </select>
          <select value={propertyId} onChange={e => setPropertyId(e.target.value)} className={selectCls} aria-label="Property">
            <option value="">All properties</option>
            {properties.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          <select value={channel} onChange={e => setChannel(e.target.value)} className={selectCls} aria-label="Channel">
            <option value="">All channels</option>
            {CHANNEL_OPTIONS.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
          </select>
          <select value={range} onChange={e => setRange(e.target.value)} className={selectCls} aria-label="Dates">
            <option value="">Any dates</option>
            <option value="today">Today</option>
            <option value="this_month">This month</option>
            <option value="last_month">Last month</option>
            <option value="last_7d">Last 7 days</option>
          </select>
          <select value={sort} onChange={e => setSort(e.target.value)} className={selectCls} aria-label="Sort">
            <option value="check_in">Latest check-in</option>
            <option value="newest">Newest created</option>
            <option value="total_desc">Highest amount</option>
          </select>
          </div>
          {filtered && (
            <button onClick={clearAll} className="inline-flex h-9 items-center gap-1 text-xs text-[var(--haip-fg-subtle)] hover:text-[var(--haip-fg)]">
              <X size={12} /> Clear
            </button>
          )}
        </FilterBar>
        {guestId && <p className="w-fit rounded-lg border border-primary/20 bg-primary/10 px-3 py-1.5 text-xs text-primary">Showing one guest&apos;s bookings</p>}
        {unassignedHint && <p className="text-xs text-[var(--haip-fg-subtle)]">{unassignedHint}</p>}
      </div>

      {selected.size > 0 && (
        <div className="flex flex-shrink-0 flex-wrap items-center gap-2 border-b border-primary/20 bg-primary/10 px-4 py-2 sm:px-6">
          <span className="text-xs font-semibold text-primary">{selected.size} selected</span>
          <select value={moveTo} onChange={e => setMoveTo(e.target.value)} className={selectCls} aria-label="Move to property">
            <option value="">Move to property…</option>
            {properties.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          <button onClick={moveSelected} disabled={!moveTo || moving}
            className="h-9 rounded-lg bg-primary px-3.5 text-xs font-semibold text-primary-foreground disabled:opacity-50">
            {moving ? "Moving…" : "Move"}
          </button>
          <button onClick={() => setSelected(new Set())} className="ml-auto text-xs text-[var(--haip-fg-subtle)] hover:text-[var(--haip-fg)]">Clear selection</button>
        </div>
      )}

      <div className="flex-1 overflow-y-auto p-4 sm:p-6">
        {!data && !isError ? (
          <div className="space-y-2">{Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-16 rounded-xl" />)}</div>
        ) : (
          <>
            <DataTable<BookingRow>
              columns={columns} rows={rows} rowKey={b => b.id}
              error={isError ? "Could not load bookings." : null} onRetry={() => refetch()}
              empty={{
                title: filtered ? "No bookings match these filters" : "No bookings yet",
                hint: filtered ? "Clear a filter to see more." : "Create one, or move a lead to Sold.",
                action: filtered ? <button onClick={clearAll} className="h-9 rounded-lg border border-[var(--haip-border)] px-4 text-[13px] font-semibold hover:bg-[var(--haip-surface)]">Clear filters</button> : undefined,
              }}
              onRowClick={b => router.push(`/dashboard/bookings/${b.id}`)}
              selectedKeys={selected} onSelectionChange={setSelected}
              maxHeightClass="max-h-none"
            />

            {meta && meta.last_page > 1 && (
              <div className="mt-4 flex items-center justify-between text-xs text-[var(--haip-fg-subtle)]">
                <span>{meta.from} to {meta.to} of {meta.total}</span>
                <div className="flex gap-2">
                  <button disabled={page <= 1} onClick={() => setPage(p => p - 1)} className="h-9 rounded-lg border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 disabled:opacity-40">Previous</button>
                  <button disabled={page >= meta.last_page} onClick={() => setPage(p => p + 1)} className="h-9 rounded-lg border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 disabled:opacity-40">Next</button>
                </div>
              </div>
            )}
          </>
        )}
      </div>

      {creating && (
        <CreateBookingModal
          onClose={() => setCreating(false)}
          onCreated={() => { setCreating(false); queryClient.invalidateQueries({ queryKey: ["bookings"] }); }}
        />
      )}
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
