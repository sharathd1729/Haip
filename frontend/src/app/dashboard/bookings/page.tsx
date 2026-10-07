"use client";
import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import dynamic from "next/dynamic";
import { useRouter, useSearchParams } from "next/navigation";
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Plus, Search, X, ChevronRight } from "@/lib/icons";
import api from "@/lib/api";
import { cn, formatINR, formatPhone } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import {
  CHANNEL_OPTIONS, CHANNEL_STYLE, PAYMENT_STYLE, STATUS_OPTIONS, STATUS_STYLE, fmtDate,
  type BookingList, type BookingRow,
} from "@/lib/bookings";

const CreateBookingModal = dynamic(
  () => import("@/components/bookings/CreateBookingModal").then(m => m.CreateBookingModal),
  { ssr: false },
);

const selectCls = "text-[12.5px] rounded-lg border border-gray-200 bg-white px-2.5 py-1.5 text-gray-700 focus:outline-none focus:ring-2 focus:ring-teal-500";

function Pill({ style }: { style: { label: string; cls: string } }) {
  return <span className={cn("inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-semibold whitespace-nowrap", style.cls)}>{style.label}</span>;
}

function DueLine({ b }: { b: BookingRow }) {
  if (b.payment_status === "paid" || b.total <= 0) return null;
  return (
    <p className={cn("text-[11px] mt-0.5 tabular-nums", b.payment_overdue ? "text-red-600 font-medium" : "text-gray-400")}>
      {formatINR(b.total_outstanding)} due{b.next_payment_due_date ? ` ${b.payment_overdue ? "since" : "on"} ${fmtDate(b.next_payment_due_date, false)}` : ""}
    </p>
  );
}

function Thumb({ b }: { b: BookingRow }) {
  const img = b.property?.image;
  return img
    // eslint-disable-next-line @next/next/no-img-element
    ? <img src={img} alt="" className="w-10 h-10 rounded-lg object-cover flex-shrink-0" loading="lazy" />
    : <div className="w-10 h-10 rounded-lg bg-teal-50 text-teal-700 flex items-center justify-center text-sm font-bold flex-shrink-0" aria-hidden>{(b.property?.name ?? "?").slice(0, 1).toUpperCase()}</div>;
}

function ChannelPill({ channel }: { channel: string | null }) {
  const c = CHANNEL_STYLE[(channel ?? "direct").toLowerCase()] ?? { label: channel ?? "Direct", cls: "bg-gray-100 text-gray-600 border-gray-200" };
  return <Pill style={c} />;
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
  const guestId = params.get("guest") ?? "";
  const initialQ = params.get("q") ?? params.get("phone") ?? "";

  const [search, setSearch] = useState(initialQ);
  const [debounced, setDebounced] = useState(initialQ);
  const [status, setStatus] = useState("");
  const [payment, setPayment] = useState("");
  const [range, setRange] = useState("");
  const [propertyId, setPropertyId] = useState("");
  const [channel, setChannel] = useState("");
  const [exporting, setExporting] = useState(false);
  const [sort, setSort] = useState("check_in");
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => { setDebounced(search.trim()); setPage(1); }, 350);
    return () => clearTimeout(t);
  }, [search]);
  useEffect(() => { setPage(1); }, [status, payment, range, propertyId, channel, sort, guestId]);

  const { data: properties = [] } = useQuery<{ id: string; name: string }[]>({
    queryKey: ["bookable-properties"],
    queryFn: () => api.get("/bookings/properties").then(r => r.data),
    staleTime: 5 * 60_000,
  });

  const filterParams = {
    search: debounced || undefined, status: status || undefined, payment_status: payment || undefined,
    date_preset: range || undefined, guest_id: guestId || undefined, property_id: propertyId || undefined,
    channel: channel || undefined, sort,
  };

  const { data, isLoading, isError, refetch } = useQuery<BookingList>({
    queryKey: ["bookings", { ...filterParams, page }],
    queryFn: () => api.get("/bookings", { params: { ...filterParams, page, per_page: 25 } }).then(r => r.data),
    placeholderData: keepPreviousData,
    staleTime: 20_000,
  });

  const rows = data?.data ?? [];
  const meta = data?.meta;
  const filtered = !!(debounced || status || payment || range || guestId || propertyId || channel);

  function clearAll() {
    setSearch(""); setDebounced(""); setStatus(""); setPayment(""); setRange(""); setPropertyId(""); setChannel("");
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
      const blob = new Blob(["\uFEFF" + [head.join(","), ...lines].join("\n")], { type: "text/csv;charset=utf-8" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `bookings-${new Date().toISOString().slice(0, 10)}.csv`;
      a.click();
      URL.revokeObjectURL(a.href);
    } finally {
      setExporting(false);
    }
  }

  return (
    <div className="flex flex-col h-full bg-[#F8FAFC]">
      <div className="flex-shrink-0 bg-white border-b border-gray-200 px-4 sm:px-6 py-3 space-y-3">
        <div className="flex items-center gap-3">
          <div>
            <h1 className="haip-page-title">Bookings</h1>
            <p className="text-xs text-gray-400">{meta ? `${meta.total} booking${meta.total === 1 ? "" : "s"}` : " "}</p>
          </div>
          <button onClick={exportCsv} disabled={exporting || !rows.length}
            className="ml-auto flex items-center gap-1.5 text-xs border border-gray-200 bg-white text-gray-700 px-3 py-2 rounded-lg font-semibold hover:bg-gray-50 disabled:opacity-40">
            <Download size={13} /> {exporting ? "Exporting..." : "Export"}
          </button>
          <button
            onClick={() => setCreating(true)}
            className="flex items-center gap-1.5 text-xs bg-teal-500 text-white px-3.5 py-2 rounded-lg font-semibold hover:bg-teal-600 transition-colors"
          >
            <Plus size={14} /> New booking
          </button>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div className="relative flex-1 min-w-[200px] max-w-sm">
            <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
            <input
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Guest, phone, property or booking ID"
              className="w-full pl-8 pr-3 py-1.5 text-[12.5px] rounded-lg border border-gray-200 bg-white focus:outline-none focus:ring-2 focus:ring-teal-500"
            />
          </div>
          <select value={status} onChange={e => setStatus(e.target.value)} className={selectCls} aria-label="Status">
            <option value="">All statuses</option>
            {STATUS_OPTIONS.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
          </select>
          <select value={payment} onChange={e => setPayment(e.target.value)} className={selectCls} aria-label="Payment">
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
          {filtered && (
            <button onClick={clearAll} className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-800">
              <X size={12} /> Clear
            </button>
          )}
        </div>
        {guestId && <p className="text-xs text-teal-700 bg-teal-50 border border-teal-100 rounded-lg px-3 py-1.5 w-fit">Showing one guest&apos;s bookings</p>}
      </div>

      <div className="flex-1 overflow-y-auto p-4 sm:p-6">
        {isLoading ? (
          <div className="space-y-2">{Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-16 rounded-xl" />)}</div>
        ) : isError ? (
          <div className="text-center py-16 text-sm text-gray-500">
            Could not load bookings. <button onClick={() => refetch()} className="text-teal-600 font-medium hover:underline">Try again</button>
          </div>
        ) : rows.length === 0 ? (
          <div className="text-center py-20 text-sm text-gray-400">
            {filtered ? "No bookings match these filters." : "No bookings yet. Create one, or move a lead to Sold."}
          </div>
        ) : (
          <>
            {/* Desktop table */}
            <div className="hidden md:block haip-card overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-[11px] uppercase tracking-wide text-gray-400 border-b border-gray-100">
                    <th className="px-4 py-2.5 font-semibold">Guest</th>
                    <th className="px-4 py-2.5 font-semibold">Stay</th>
                    <th className="px-4 py-2.5 font-semibold">Channel</th>
                    <th className="px-4 py-2.5 font-semibold">Status</th>
                    <th className="px-4 py-2.5 font-semibold text-right">Total</th>
                    <th className="px-4 py-2.5 font-semibold">Payment</th>
                    <th className="w-8" />
                  </tr>
                </thead>
                <tbody>
                  {rows.map(b => (
                    <tr
                      key={b.id}
                      onClick={() => router.push(`/dashboard/bookings/${b.id}`)}
                      className="border-b border-gray-50 last:border-0 hover:bg-gray-50 cursor-pointer"
                    >
                      <td className="px-4 py-3">
                        <Link href={`/dashboard/bookings/${b.id}`} className="font-semibold text-gray-900 hover:text-teal-700" onClick={e => e.stopPropagation()}>
                          {guestName(b)}
                        </Link>
                        <p className="text-xs text-gray-400">#{b.external_id}{b.main_guest?.phone ? ` · ${formatPhone(b.main_guest.phone)}` : ""}</p>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-3">
                          <Thumb b={b} />
                          <div className="min-w-0">
                            <p className="text-gray-800 truncate">{b.property?.name ?? "No property"}</p>
                            <p className="text-xs text-gray-400">{fmtDate(b.checkin, false)} to {fmtDate(b.checkout)} · {b.adults + b.children} guest{b.adults + b.children === 1 ? "" : "s"}</p>
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-3"><ChannelPill channel={b.channel} /></td>
                      <td className="px-4 py-3"><Pill style={STATUS_STYLE[b.status] ?? STATUS_STYLE.confirmed} /></td>
                      <td className="px-4 py-3 text-right tabular-nums font-medium text-gray-900">{formatINR(b.total)}</td>
                      <td className="px-4 py-3">
                        <Pill style={PAYMENT_STYLE[b.payment_status]} />
                        <DueLine b={b} />
                      </td>
                      <td className="pr-3 text-gray-300"><ChevronRight size={14} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Mobile cards */}
            <div className="md:hidden space-y-2">
              {rows.map(b => (
                <Link key={b.id} href={`/dashboard/bookings/${b.id}`} className="block haip-card p-4">
                  <div className="flex items-start gap-2">
                    <div className="min-w-0 flex-1">
                      <p className="font-semibold text-gray-900 truncate">{guestName(b)}</p>
                      <p className="text-xs text-gray-500 truncate">{b.property?.name ?? "No property"}</p>
                    </div>
                    <Pill style={STATUS_STYLE[b.status] ?? STATUS_STYLE.confirmed} />
                  </div>
                  <p className="text-xs text-gray-400 mt-1">{fmtDate(b.checkin, false)} to {fmtDate(b.checkout)}</p>
                  <div className="flex items-center justify-between mt-3 gap-2">
                    <span className="text-sm font-semibold tabular-nums">{formatINR(b.total)}</span>
                    <ChannelPill channel={b.channel} />
                    <div className="text-right"><Pill style={PAYMENT_STYLE[b.payment_status]} /><DueLine b={b} /></div>
                  </div>
                </Link>
              ))}
            </div>

            {meta && meta.last_page > 1 && (
              <div className="flex items-center justify-between mt-4 text-xs text-gray-500">
                <span>{meta.from} to {meta.to} of {meta.total}</span>
                <div className="flex gap-2">
                  <button disabled={page <= 1} onClick={() => setPage(p => p - 1)} className="px-3 py-1.5 rounded-lg border border-gray-200 bg-white disabled:opacity-40">Previous</button>
                  <button disabled={page >= meta.last_page} onClick={() => setPage(p => p + 1)} className="px-3 py-1.5 rounded-lg border border-gray-200 bg-white disabled:opacity-40">Next</button>
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
