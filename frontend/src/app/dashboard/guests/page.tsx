"use client";
import { useState, useEffect, useMemo, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import {
  Search, ArrowLeft, Phone, MessageSquare, Star,
  Shield, AlertTriangle, Plus, ChevronRight,
  Calendar, TrendingUp, Users, Sparkles,
  BookOpen, X, ChevronLeft as ChevronLeftIcon,
  ChevronRight as ChevronRightIcon, Download,
  SlidersHorizontal, ExternalLink, Bed, CreditCard,
  RefreshCw,
} from "lucide-react";
import { timeAgo, cn } from "@/lib/utils";
import { EmptyGuests } from "@/components/empty-states/EmptyGuests";
import { useRWBookings } from "@/hooks/useRentalWise";
import {
  type RWBooking, type RWBookingStatus, type RWPaymentStatus,
  type RWBookingFilters,
} from "@/lib/rentalwise";

interface GuestItem {
  phone: string;
  full_name: string;
  email: string | null;
  nationality: string | null;
  language: string;
  source: string | null;
  gdpr_consent: boolean;
  tags: string[];
  blacklisted: boolean;
  created_at: string;
}

interface GuestProfile extends GuestItem {
  stays: Array<{ id: string; check_in: string; check_out: string; total_amount: string | null; currency: string; payment_status: string; booking_ref: string | null; channel: string | null }>;
  inquiries: Array<{ id: string; check_in: string | null; check_out: string | null; status: string; source: string | null }>;
  recent_calls: Array<{ id: string; call_date: string; agent_name: string | null; qa_score: string | null }>;
  recent_messages: Array<{ id: string; content: string; direction: string; created_at: string }>;
  activities: Array<{ id: string; type: string; content: string; created_at: string }>;
}

const SOURCE_LABELS: Record<string, string> = {
  airbnb: "Airbnb", booking: "Booking.com", direct: "Direct", referral: "Referral",
  whatsapp: "WhatsApp", instagram: "Instagram", retalwise: "RentalWise",
};

// ─── Guest 360 Profile View ───────────────────────────────────────────────────

function Guest360({ profile, onBack }: { profile: GuestProfile; onBack: () => void }) {
  const ltv = profile.stays.reduce((s, st) => s + parseFloat(st.total_amount ?? "0"), 0);
  const currency = profile.stays[0]?.currency ?? "₹";

  const timeline: Array<{ icon: React.ReactNode; label: string; sub: string; date: string; color: string }> = [
    ...profile.stays.map(s => ({
      icon: <Calendar size={11} />,
      label: `Stay: ${s.check_in} → ${s.check_out}`,
      sub: s.total_amount ? `${s.currency} ${Number(s.total_amount).toLocaleString()}` : "Amount TBD",
      date: s.check_in,
      color: "bg-teal-50 text-teal-600",
    })),
    ...profile.recent_calls.map(c => ({
      icon: <Phone size={11} />,
      label: `Call with ${c.agent_name ?? "team"}`,
      sub: c.qa_score ? `QA ${(parseFloat(c.qa_score) * 10).toFixed(0)}%` : "Unscored",
      date: c.call_date,
      color: "bg-blue-50 text-blue-600",
    })),
    ...profile.recent_messages.slice(0, 3).map(m => ({
      icon: <MessageSquare size={11} />,
      label: m.direction === "inbound" ? "Guest messaged" : "Team replied",
      sub: m.content.slice(0, 60) + (m.content.length > 60 ? "…" : ""),
      date: m.created_at,
      color: "bg-purple-50 text-purple-600",
    })),
  ].sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime()).slice(0, 12);

  return (
    <div className="flex flex-col h-full bg-[#F8FAFC]">
      {/* Header */}
      <div
        className="flex-shrink-0 px-6 py-4 flex items-center gap-4"
        style={{ background: "#FFFFFF", borderBottom: "1px solid #E5E7EB" }}
      >
        <button
          onClick={onBack}
          className="flex items-center gap-2 text-sm font-medium transition-colors"
          style={{ color: "#6B7280" }}
          onMouseEnter={e => { (e.currentTarget as HTMLElement).style.color = "#111827"; }}
          onMouseLeave={e => { (e.currentTarget as HTMLElement).style.color = "#6B7280"; }}
        >
          <ArrowLeft size={15} /> Guests
        </button>
        <span style={{ color: "#D1D5DB" }}>/</span>
        <span className="text-sm font-semibold" style={{ color: "#111827" }}>{profile.full_name}</span>
      </div>

      <div className="flex-1 overflow-y-auto">
        <div className="max-w-3xl mx-auto px-6 py-6 space-y-4">

          {/* Identity card */}
          <div className="haip-card p-6">
            <div className="flex items-start gap-5">
              {/* Avatar */}
              <div className="relative flex-shrink-0">
                <div
                  className="w-16 h-16 rounded-2xl flex items-center justify-center text-2xl font-bold text-white"
                  style={{ background: "linear-gradient(135deg, #14B8A6, #0F766E)" }}
                >
                  {profile.full_name?.[0]?.toUpperCase() ?? "?"}
                </div>
                {profile.tags.includes("VIP") && (
                  <div className="absolute -top-1 -right-1 w-5 h-5 rounded-full bg-amber-400 flex items-center justify-center">
                    <Star size={9} className="text-white fill-white" />
                  </div>
                )}
              </div>

              <div className="flex-1 min-w-0">
                <div className="flex items-start justify-between gap-2 flex-wrap">
                  <div>
                    <h2
                      className="text-xl font-bold leading-tight"
                      style={{ fontFamily: "var(--font-display), sans-serif", color: "var(--haip-text)" }}
                    >
                      {profile.full_name}
                    </h2>
                    <p className="text-sm mt-0.5" style={{ color: "var(--haip-text-muted)" }}>
                      {profile.phone}
                      {profile.email && <span className="ml-2 text-gray-400">· {profile.email}</span>}
                    </p>
                  </div>
                  <div className="flex items-center gap-1.5 flex-wrap">
                    {profile.tags.includes("VIP") && (
                      <span className="haip-badge-amber flex items-center gap-1">
                        <Star size={9} className="fill-current" /> VIP
                      </span>
                    )}
                    {profile.blacklisted && (
                      <span className="haip-badge-red flex items-center gap-1">
                        <AlertTriangle size={9} /> Blocked
                      </span>
                    )}
                    {profile.gdpr_consent && (
                      <span className="haip-badge-teal flex items-center gap-1">
                        <Shield size={9} /> Consented
                      </span>
                    )}
                    {profile.source && (
                      <span className="haip-badge-teal">
                        {SOURCE_LABELS[profile.source] ?? profile.source}
                      </span>
                    )}
                  </div>
                </div>

                {/* LTV stats */}
                <div className="grid grid-cols-3 gap-3 mt-4">
                  {[
                    { label: "Total stays",    value: profile.stays.length.toString() },
                    { label: "Lifetime value", value: ltv > 0 ? `${currency} ${ltv.toLocaleString()}` : "—" },
                    { label: "Inquiries",      value: profile.inquiries.length.toString() },
                  ].map(s => (
                    <div key={s.label} className="bg-gray-50 rounded-xl p-3 text-center">
                      <div
                        className="text-lg font-bold"
                        style={{ fontFamily: "var(--font-display), sans-serif", color: "var(--haip-text)" }}
                      >
                        {s.value}
                      </div>
                      <div className="haip-label mt-0.5">{s.label}</div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>

          {/* 2-column layout */}
          <div className="grid grid-cols-1 md:grid-cols-5 gap-4">
            {/* Timeline */}
            <div className="md:col-span-3 haip-card overflow-hidden">
              <div className="px-5 py-3.5 border-b border-gray-100 flex items-center gap-2">
                <Sparkles size={13} style={{ color: "#14B8A6" }} />
                <span className="text-sm font-semibold" style={{ fontFamily: "var(--font-display), sans-serif", color: "var(--haip-text)" }}>
                  Timeline
                </span>
              </div>
              <div className="divide-y divide-gray-50">
                {timeline.length === 0 ? (
                  <p className="px-5 py-6 text-sm text-gray-400 text-center">No activity yet</p>
                ) : (
                  timeline.map((item, i) => (
                    <div key={i} className="flex items-start gap-3 px-5 py-3">
                      <div className={`w-6 h-6 rounded-lg flex items-center justify-center flex-shrink-0 mt-0.5 ${item.color}`}>
                        {item.icon}
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-[13px] font-medium text-gray-800 truncate">{item.label}</p>
                        <p className="text-xs text-gray-500 mt-0.5 truncate">{item.sub}</p>
                      </div>
                      <span className="text-[11px] text-gray-400 flex-shrink-0 mt-0.5">{timeAgo(item.date)}</span>
                    </div>
                  ))
                )}
              </div>
            </div>

            {/* Stay history */}
            <div className="md:col-span-2 space-y-3">
              {profile.stays.length > 0 && (
                <div className="haip-card overflow-hidden">
                  <div className="px-4 py-3 border-b border-gray-100">
                    <span className="text-sm font-semibold" style={{ fontFamily: "var(--font-display), sans-serif", color: "var(--haip-text)" }}>
                      Stays
                    </span>
                  </div>
                  <div className="divide-y divide-gray-50">
                    {profile.stays.slice(0, 4).map(stay => (
                      <div key={stay.id} className="px-4 py-3">
                        <div className="flex justify-between items-start">
                          <div>
                            <p className="text-[12.5px] font-medium text-gray-800">{stay.check_in}</p>
                            <p className="text-xs text-gray-400">→ {stay.check_out}</p>
                          </div>
                          <div className="text-right">
                            <p className="text-[12.5px] font-semibold text-gray-900">
                              {stay.total_amount ? `${stay.currency} ${Number(stay.total_amount).toLocaleString()}` : "—"}
                            </p>
                            <span className={cn(
                              "text-[10px] font-medium px-1.5 py-0.5 rounded",
                              stay.payment_status === "fully_paid" ? "bg-teal-50 text-teal-700" :
                              stay.payment_status === "deposit_paid" ? "bg-blue-50 text-blue-700" : "bg-gray-100 text-gray-500"
                            )}>
                              {stay.payment_status.replace(/_/g, " ")}
                            </span>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {profile.inquiries.length > 0 && (
                <div className="haip-card overflow-hidden">
                  <div className="px-4 py-3 border-b border-gray-100">
                    <span className="text-sm font-semibold" style={{ fontFamily: "var(--font-display), sans-serif", color: "var(--haip-text)" }}>
                      Inquiries
                    </span>
                  </div>
                  <div className="divide-y divide-gray-50">
                    {profile.inquiries.slice(0, 4).map(inq => (
                      <div key={inq.id} className="px-4 py-3 flex items-center justify-between">
                        <div>
                          <p className="text-[12.5px] font-medium text-gray-800">
                            {inq.check_in && inq.check_out ? `${inq.check_in} → ${inq.check_out}` : "Dates TBD"}
                          </p>
                          <p className="text-xs text-gray-400">{inq.source ?? "—"}</p>
                        </div>
                        <span className={cn(
                          "text-[10px] font-semibold px-2 py-0.5 rounded capitalize",
                          inq.status === "confirmed" ? "haip-badge-teal" :
                          inq.status === "lost" ? "haip-badge-red" :
                          inq.status === "new" ? "haip-badge-amber" : "bg-gray-100 text-gray-600 px-2 py-0.5 rounded text-[10px]"
                        )}>
                          {inq.status}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Booking status + payment badges ─────────────────────────────────────────

const BOOKING_STATUS_CFG: Record<RWBookingStatus, { label: string; cls: string }> = {
  confirmed: { label: "Confirmed", cls: "bg-green-50  text-green-700  border-green-200"  },
  pending:   { label: "Pending",   cls: "bg-amber-50  text-amber-700  border-amber-200"  },
  cancelled: { label: "Cancelled", cls: "bg-red-50    text-red-700    border-red-200"    },
  completed: { label: "Completed", cls: "bg-blue-50   text-blue-700   border-blue-200"   },
  rejected:  { label: "Rejected",  cls: "bg-red-50    text-red-600    border-red-200"    },
  hold:      { label: "On Hold",   cls: "bg-purple-50 text-purple-700 border-purple-200" },
};

const PAYMENT_STATUS_CFG: Record<RWPaymentStatus, { label: string; cls: string }> = {
  paid:         { label: "Paid",         cls: "bg-green-50  text-green-700  border-green-200"  },
  partial_paid: { label: "Partial",      cls: "bg-amber-50  text-amber-700  border-amber-200"  },
  unpaid:       { label: "Unpaid",       cls: "bg-red-50    text-red-700    border-red-200"    },
  refunded:     { label: "Refunded",     cls: "bg-gray-50   text-gray-600   border-gray-200"   },
};

const CHANNEL_COLORS: Record<string, string> = {
  airbnb:      "#FF5A5F",
  "booking-com": "#003580",
  homeaway:    "#1D5AA1",
  direct:      "#0F766E",
  email:       "#6B7280",
};

function BookingStatusBadge({ status }: { status: RWBookingStatus }) {
  const cfg = BOOKING_STATUS_CFG[status] ?? { label: status, cls: "bg-gray-50 text-gray-600 border-gray-200" };
  return (
    <span className={cn("inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold border", cfg.cls)}>
      {cfg.label}
    </span>
  );
}

function PaymentBadge({ status }: { status: RWPaymentStatus }) {
  const cfg = PAYMENT_STATUS_CFG[status] ?? { label: status, cls: "bg-gray-50 text-gray-600 border-gray-200" };
  return (
    <span className={cn("inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold border", cfg.cls)}>
      {cfg.label}
    </span>
  );
}

function ChannelPill({ channel }: { channel: string | null }) {
  if (!channel) return <span className="text-xs text-gray-400">—</span>;
  const color = CHANNEL_COLORS[channel.toLowerCase()] ?? "#6B7280";
  const label = channel.charAt(0).toUpperCase() + channel.slice(1).replace("-", ".");
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded-md text-[10px] font-semibold"
      style={{ background: `${color}15`, color }}
    >
      {label}
    </span>
  );
}

// ─── CSV export helper ────────────────────────────────────────────────────────

function exportToCsv(bookings: RWBooking[]) {
  const headers = ["Booking ID","Guest","Property","Check In","Check Out","Adults","Children","Status","Payment","Channel","Total","Created"];
  const rows = bookings.map(b => [
    b.booking_id,
    b.main_guest ? `${b.main_guest.first_name} ${b.main_guest.last_name}` : "",
    b.property?.name ?? "",
    b.check_in,
    b.check_out,
    b.adults,
    b.children,
    b.status,
    b.payment_status,
    b.channel ?? "",
    b.total,
    b.created_at,
  ]);
  const csv = [headers, ...rows].map(r => r.map(v => `"${v}"`).join(",")).join("\n");
  const blob = new Blob([csv], { type: "text/csv" });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement("a");
  a.href     = url;
  a.download = `bookings_${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

// ─── Bookings table ────────────────────────────────────────────────────────────

function BookingsTable() {
  const [search, setSearch]               = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [statusFilter, setStatusFilter]   = useState<RWBookingStatus | "">("");
  const [paymentFilter, setPaymentFilter] = useState<RWPaymentStatus | "">("");
  const [channelFilter, setChannelFilter] = useState("");
  const [sort, setSort]                   = useState<RWBookingFilters["sort"]>("newest");
  const [page, setPage]                   = useState(1);
  const [showFilters, setShowFilters]     = useState(false);

  // Debounce search
  useEffect(() => {
    const t = setTimeout(() => { setDebouncedSearch(search); setPage(1); }, 400);
    return () => clearTimeout(t);
  }, [search]);

  // Reset page on filter changes
  useEffect(() => { setPage(1); }, [statusFilter, paymentFilter, channelFilter, sort]);

  const filters: RWBookingFilters = {
    search:         debouncedSearch || undefined,
    status:         statusFilter    || undefined,
    payment_status: paymentFilter   || undefined,
    channel:        channelFilter   || undefined,
    sort,
    page,
    per_page: 25,
  };

  const { data, isLoading, isError, refetch, isFetching } = useRWBookings(filters);
  const bookings: RWBooking[] = data?.data ?? [];
  const meta = data?.meta;

  function clearFilters() {
    setSearch(""); setDebouncedSearch(""); setStatusFilter(""); setPaymentFilter(""); setChannelFilter(""); setSort("newest"); setPage(1);
  }
  const hasFilters = !!(statusFilter || paymentFilter || channelFilter || debouncedSearch);

  return (
    <div className="flex flex-col h-full">

      {/* ── Filter bar ──────────────────────────────────────────────────── */}
      <div
        className="flex-shrink-0 px-5 py-3 border-b flex flex-wrap items-center gap-2"
        style={{ background: "#FFFFFF", borderColor: "#E5E7EB" }}
      >
        {/* Search */}
        <div className="relative flex-1 min-w-[180px] max-w-xs">
          <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 pointer-events-none" style={{ color: "#9CA3AF" }} />
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Booking ID, guest, property…"
            className="w-full pl-8 pr-8 py-1.5 text-[12.5px] rounded-xl focus:outline-none"
            style={{ background: "#F8FAFC", border: "1px solid #E5E7EB", color: "#374151" }}
            onFocus={e => { (e.currentTarget as HTMLElement).style.borderColor = "#0F766E"; }}
            onBlur={e => { (e.currentTarget as HTMLElement).style.borderColor = "#E5E7EB"; }}
          />
          {search && (
            <button onClick={() => setSearch("")} className="absolute right-2.5 top-1/2 -translate-y-1/2" style={{ color: "#9CA3AF" }}>
              <X size={12} />
            </button>
          )}
        </div>

        {/* Status */}
        <select
          value={statusFilter}
          onChange={e => setStatusFilter(e.target.value as RWBookingStatus | "")}
          className="py-1.5 px-2.5 rounded-xl text-[12px] font-medium focus:outline-none"
          style={{ background: "#F8FAFC", border: "1px solid #E5E7EB", color: "#374151" }}
        >
          <option value="">All statuses</option>
          {(Object.keys(BOOKING_STATUS_CFG) as RWBookingStatus[]).map(s => (
            <option key={s} value={s}>{BOOKING_STATUS_CFG[s].label}</option>
          ))}
        </select>

        {/* Payment */}
        <select
          value={paymentFilter}
          onChange={e => setPaymentFilter(e.target.value as RWPaymentStatus | "")}
          className="py-1.5 px-2.5 rounded-xl text-[12px] font-medium focus:outline-none"
          style={{ background: "#F8FAFC", border: "1px solid #E5E7EB", color: "#374151" }}
        >
          <option value="">All payments</option>
          {(Object.keys(PAYMENT_STATUS_CFG) as RWPaymentStatus[]).map(s => (
            <option key={s} value={s}>{PAYMENT_STATUS_CFG[s].label}</option>
          ))}
        </select>

        {/* Channel */}
        <select
          value={channelFilter}
          onChange={e => setChannelFilter(e.target.value)}
          className="py-1.5 px-2.5 rounded-xl text-[12px] font-medium focus:outline-none"
          style={{ background: "#F8FAFC", border: "1px solid #E5E7EB", color: "#374151" }}
        >
          <option value="">All channels</option>
          {["airbnb", "booking-com", "homeaway", "direct", "email"].map(c => (
            <option key={c} value={c}>{c.charAt(0).toUpperCase() + c.slice(1).replace("-",".")}</option>
          ))}
        </select>

        {/* Sort */}
        <select
          value={sort}
          onChange={e => setSort(e.target.value as RWBookingFilters["sort"])}
          className="py-1.5 px-2.5 rounded-xl text-[12px] font-medium focus:outline-none"
          style={{ background: "#F8FAFC", border: "1px solid #E5E7EB", color: "#374151" }}
        >
          <option value="newest">Newest first</option>
          <option value="oldest">Oldest first</option>
          <option value="check_in">Check-in date</option>
          <option value="check_out">Check-out date</option>
          <option value="total_desc">Highest revenue</option>
          <option value="total_asc">Lowest revenue</option>
        </select>

        <div className="flex items-center gap-1.5 ml-auto">
          {hasFilters && (
            <button
              onClick={clearFilters}
              className="flex items-center gap-1 px-2.5 py-1.5 rounded-xl text-[11px] font-medium text-gray-500 hover:bg-gray-100 transition-colors"
            >
              <X size={11} /> Clear
            </button>
          )}
          <button
            onClick={() => refetch()}
            className="flex items-center gap-1 px-2.5 py-1.5 rounded-xl text-[11px] font-medium border border-gray-200 text-gray-600 hover:bg-gray-50 transition-colors"
          >
            <RefreshCw size={11} className={isFetching ? "animate-spin" : ""} />
          </button>
          <button
            onClick={() => exportToCsv(bookings)}
            disabled={bookings.length === 0}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-[11.5px] font-semibold transition-colors disabled:opacity-40"
            style={{ background: "#0F766E", color: "#fff" }}
            onMouseEnter={e => { if (!bookings.length) return; (e.currentTarget as HTMLElement).style.background = "#0d6660"; }}
            onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = "#0F766E"; }}
          >
            <Download size={12} /> Export CSV
          </button>
        </div>
      </div>

      {/* ── Table ───────────────────────────────────────────────────────── */}
      <div className="flex-1 overflow-auto haip-scrollbar">
        {isLoading ? (
          <div className="p-5 space-y-3">
            {[...Array(8)].map((_, i) => (
              <div key={i} className="h-14 bg-white rounded-xl border border-gray-100 animate-pulse" />
            ))}
          </div>
        ) : isError ? (
          <div className="flex flex-col items-center justify-center py-20 gap-3">
            <AlertTriangle size={28} className="text-red-400" />
            <p className="text-sm text-gray-500">Failed to load bookings</p>
            <button
              onClick={() => refetch()}
              className="px-4 py-2 rounded-xl text-xs font-semibold bg-[#0F766E] text-white hover:bg-[#0d6660] transition-colors"
            >
              Retry
            </button>
          </div>
        ) : bookings.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 gap-2">
            <BookOpen size={32} className="text-gray-300" />
            <p className="text-sm font-medium text-gray-400">No bookings found</p>
            {hasFilters && (
              <button onClick={clearFilters} className="text-xs text-teal-600 font-medium hover:underline">Clear filters</button>
            )}
          </div>
        ) : (
          <table className="w-full text-left border-collapse">
            <thead>
              <tr style={{ background: "#F8FAFC", borderBottom: "1px solid #E5E7EB" }}>
                {["Booking", "Guest / Property", "Status", "Dates", "Guests", "Total", "Payment", "Channel", ""].map(h => (
                  <th key={h} className="px-4 py-3 text-[10px] font-bold uppercase tracking-wider whitespace-nowrap" style={{ color: "#6B7280" }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {bookings.map((b, idx) => {
                const guestName = b.main_guest
                  ? `${b.main_guest.first_name} ${b.main_guest.last_name}`.trim()
                  : "Unknown";
                const nights = Math.ceil(
                  (new Date(b.check_out).getTime() - new Date(b.check_in).getTime()) / 86400000
                );
                return (
                  <tr
                    key={b.id}
                    className="border-b transition-colors hover:bg-gray-50"
                    style={{ borderColor: "#F3F4F6", background: idx % 2 === 0 ? "#FFFFFF" : "#FAFAFA" }}
                  >
                    {/* Booking ID */}
                    <td className="px-4 py-3.5">
                      <span className="text-[12px] font-mono font-semibold" style={{ color: "#0F766E" }}>
                        #{b.booking_id}
                      </span>
                    </td>

                    {/* Guest + Property */}
                    <td className="px-4 py-3.5">
                      <div className="flex items-center gap-3">
                        {b.property?.image ? (
                          <img src={b.property.image} alt="" className="w-9 h-9 rounded-lg object-cover flex-shrink-0 border border-gray-100" />
                        ) : (
                          <div className="w-9 h-9 rounded-lg flex-shrink-0 flex items-center justify-center" style={{ background: "rgba(15,118,110,0.08)" }}>
                            <Bed size={14} style={{ color: "#0F766E" }} />
                          </div>
                        )}
                        <div className="min-w-0">
                          <p className="text-[13px] font-semibold truncate" style={{ color: "#111827" }}>{guestName}</p>
                          {b.property && (
                            <p className="text-[11px] truncate" style={{ color: "#6B7280" }}>
                              {b.property.name}
                              {b.property.type && <span className="ml-1 text-gray-400">· {b.property.type}</span>}
                            </p>
                          )}
                        </div>
                      </div>
                    </td>

                    {/* Status */}
                    <td className="px-4 py-3.5">
                      <BookingStatusBadge status={b.status} />
                    </td>

                    {/* Dates */}
                    <td className="px-4 py-3.5">
                      <p className="text-[12px] font-medium" style={{ color: "#374151" }}>
                        {new Date(b.check_in).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "2-digit" })}
                      </p>
                      <p className="text-[11px]" style={{ color: "#9CA3AF" }}>
                        → {new Date(b.check_out).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "2-digit" })}
                      </p>
                      <p className="text-[10px] mt-0.5" style={{ color: "#9CA3AF" }}>{nights}n</p>
                    </td>

                    {/* Guests */}
                    <td className="px-4 py-3.5">
                      <p className="text-[12px]" style={{ color: "#374151" }}>
                        {b.adults} adult{b.adults !== 1 ? "s" : ""}
                      </p>
                      {b.children > 0 && (
                        <p className="text-[11px]" style={{ color: "#9CA3AF" }}>{b.children} child{b.children !== 1 ? "ren" : ""}</p>
                      )}
                    </td>

                    {/* Total */}
                    <td className="px-4 py-3.5">
                      <p className="text-[13px] font-bold" style={{ color: "#111827", fontFamily: "var(--font-display), sans-serif" }}>
                        ₹{b.total.toLocaleString("en-IN")}
                      </p>
                    </td>

                    {/* Payment */}
                    <td className="px-4 py-3.5">
                      <PaymentBadge status={b.payment_status} />
                    </td>

                    {/* Channel */}
                    <td className="px-4 py-3.5">
                      <ChannelPill channel={b.channel} />
                      {b.source && (
                        <p className="text-[10px] mt-0.5" style={{ color: "#9CA3AF" }}>{b.source}</p>
                      )}
                    </td>

                    {/* Actions */}
                    <td className="px-4 py-3.5">
                      <button
                        className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11px] font-medium hover:bg-gray-100 transition-colors"
                        style={{ color: "#6B7280" }}
                        title="View in RentalWise"
                      >
                        <ExternalLink size={11} />
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* ── Pagination ──────────────────────────────────────────────────── */}
      {meta && meta.last_page > 1 && (
        <div
          className="flex-shrink-0 flex items-center justify-between px-5 py-3 border-t"
          style={{ background: "#FFFFFF", borderColor: "#E5E7EB" }}
        >
          <p className="text-[12px]" style={{ color: "#6B7280" }}>
            Page {meta.current_page} of {meta.last_page} · {meta.total} bookings
          </p>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setPage(p => Math.max(1, p - 1))}
              disabled={page <= 1 || isFetching}
              className="w-8 h-8 rounded-lg flex items-center justify-center border disabled:opacity-40 hover:bg-gray-50 transition-colors"
              style={{ borderColor: "#E5E7EB", color: "#6B7280" }}
            >
              <ChevronLeftIcon size={14} />
            </button>
            {[...Array(Math.min(5, meta.last_page))].map((_, i) => {
              const pg = Math.max(1, Math.min(meta.last_page - 4, page - 2)) + i;
              return (
                <button
                  key={pg}
                  onClick={() => setPage(pg)}
                  className={cn(
                    "w-8 h-8 rounded-lg text-[12px] font-medium transition-colors",
                    pg === page ? "bg-[#0F766E] text-white" : "hover:bg-gray-50 border text-gray-600"
                  )}
                  style={pg !== page ? { borderColor: "#E5E7EB" } : {}}
                >
                  {pg}
                </button>
              );
            })}
            <button
              onClick={() => setPage(p => Math.min(meta.last_page, p + 1))}
              disabled={page >= meta.last_page || isFetching}
              className="w-8 h-8 rounded-lg flex items-center justify-center border disabled:opacity-40 hover:bg-gray-50 transition-colors"
              style={{ borderColor: "#E5E7EB", color: "#6B7280" }}
            >
              <ChevronRightIcon size={14} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Guest list ───────────────────────────────────────────────────────────────

export default function GuestsPage() {
  const [search, setSearch] = useState("");
  const [selectedPhone, setSelectedPhone] = useState<string | null>(null);
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [activeTab, setActiveTab] = useState<"bookings" | "guests">("bookings");

  const { data: guests = [], isLoading } = useQuery<GuestItem[]>({
    queryKey: ["guests", debouncedSearch],
    queryFn: () => api.get("/guests", { params: debouncedSearch ? { q: debouncedSearch } : {} }).then(r => r.data),
    staleTime: 30_000,
    enabled: activeTab === "guests",
  });

  const { data: profile, isLoading: profileLoading } = useQuery<GuestProfile>({
    queryKey: ["guest", selectedPhone],
    queryFn: () => api.get(`/guests/${encodeURIComponent(selectedPhone!)}`).then(r => r.data),
    enabled: !!selectedPhone,
  });

  const handleSearch = (v: string) => {
    setSearch(v);
    clearTimeout((window as any).__guestSearchTimer);
    (window as any).__guestSearchTimer = setTimeout(() => setDebouncedSearch(v), 300);
  };

  // Guest 360 detail view
  if (selectedPhone) {
    if (profileLoading || !profile) {
      return (
        <div className="flex flex-col h-full bg-[#F8FAFC]">
          <div className="px-6 py-4 flex-shrink-0" style={{ background: "#FFFFFF", borderBottom: "1px solid #E5E7EB" }}>
            <button
              onClick={() => setSelectedPhone(null)}
              className="flex items-center gap-2 text-sm font-medium"
              style={{ color: "#6B7280" }}
            >
              <ArrowLeft size={15} /> Guests
            </button>
          </div>
          <div className="flex-1 flex items-center justify-center">
            <div className="text-sm text-gray-400">Loading guest profile…</div>
          </div>
        </div>
      );
    }
    return <Guest360 profile={profile} onBack={() => setSelectedPhone(null)} />;
  }

  return (
    <div className="flex flex-col h-full bg-[#F8FAFC]">
      {/* Header + Tabs */}
      <div
        className="flex-shrink-0 px-6 py-4"
        style={{ background: "#FFFFFF", borderBottom: "1px solid #E5E7EB" }}
      >
        <div className="flex items-center justify-between gap-4 mb-4">
          <div>
            <h1
              className="text-xl font-bold"
              style={{ fontFamily: "var(--font-display), sans-serif", color: "#111827" }}
            >
              Guests &amp; Bookings
            </h1>
            <p className="text-xs mt-0.5" style={{ color: "#6B7280" }}>
              Manage guest profiles and RentalWise bookings
            </p>
          </div>
        </div>

        {/* Tab switcher */}
        <div className="flex gap-1 p-1 rounded-xl w-fit" style={{ background: "#F3F4F6" }}>
          {[
            { id: "bookings" as const, label: "Bookings", icon: <BookOpen size={13} /> },
            { id: "guests"   as const, label: "Guest Profiles", icon: <Users size={13} /> },
          ].map(t => (
            <button
              key={t.id}
              onClick={() => setActiveTab(t.id)}
              className={cn(
                "flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-[12.5px] font-semibold transition-all",
                activeTab === t.id ? "bg-white shadow-sm text-gray-900" : "text-gray-500 hover:text-gray-700"
              )}
            >
              {t.icon}
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {/* Tab content */}
      {activeTab === "bookings" ? (
        <BookingsTable />
      ) : (
        /* Guest card grid (existing) */
        <div className="flex flex-col flex-1 overflow-hidden">
          {/* Guest search bar */}
          <div
            className="flex-shrink-0 px-6 py-3 border-b flex items-center justify-between gap-4"
            style={{ background: "#FFFFFF", borderColor: "#E5E7EB" }}
          >
            <p className="text-xs" style={{ color: "#6B7280" }}>
              {guests.length} guests
            </p>
            <div className="relative max-w-xs w-full">
              <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2" style={{ color: "#9CA3AF" }} />
              <input
                value={search}
                onChange={e => handleSearch(e.target.value)}
                placeholder="Search name, phone, email…"
                className="w-full pl-8 pr-3 py-2 text-sm rounded-xl focus:outline-none"
                style={{ background: "#F8FAFC", border: "1px solid #E5E7EB", color: "#111827" }}
                onFocus={e => { (e.currentTarget as HTMLElement).style.borderColor = "#0F766E"; }}
                onBlur={e => { (e.currentTarget as HTMLElement).style.borderColor = "#E5E7EB"; }}
              />
            </div>
          </div>

          <div className="flex-1 overflow-y-auto p-5">
            {isLoading ? (
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
                {[...Array(8)].map((_, i) => (
                  <div key={i} className="haip-card p-5 animate-pulse">
                    <div className="flex items-center gap-3 mb-3">
                      <div className="w-10 h-10 rounded-xl bg-gray-200" />
                      <div className="space-y-1.5 flex-1">
                        <div className="h-3 bg-gray-200 rounded w-24" />
                        <div className="h-2.5 bg-gray-200 rounded w-16" />
                      </div>
                    </div>
                    <div className="space-y-1.5">
                      <div className="h-2.5 bg-gray-100 rounded w-full" />
                      <div className="h-2.5 bg-gray-100 rounded w-2/3" />
                    </div>
                  </div>
                ))}
              </div>
            ) : guests.length === 0 ? (
              <div className="flex items-center justify-center py-20">
                <EmptyGuests />
              </div>
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
                {guests.map(guest => (
                  <GuestCard
                    key={guest.phone}
                    guest={guest}
                    onClick={() => setSelectedPhone(guest.phone)}
                  />
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Guest Card ───────────────────────────────────────────────────────────────

function GuestCard({ guest, onClick }: { guest: GuestItem; onClick: () => void }) {
  const initials = (guest.full_name ?? "?").split(" ").map(n => n[0]).join("").slice(0, 2).toUpperCase();

  // Derive a relationship signal from tags
  const isVip       = guest.tags.includes("VIP");
  const isBlocked   = guest.blacklisted;
  const hasConsent  = guest.gdpr_consent;
  const sourceName  = SOURCE_LABELS[guest.source ?? ""] ?? guest.source;

  return (
    <button
      onClick={onClick}
      className="haip-card p-4 text-left hover:shadow-md hover:border-teal-200 transition-all group w-full"
    >
      {/* Avatar + name */}
      <div className="flex items-start justify-between gap-2 mb-3">
        <div className="flex items-center gap-3">
          <div
            className="w-10 h-10 rounded-xl flex items-center justify-center text-sm font-bold text-white flex-shrink-0"
            style={{ background: isVip ? "linear-gradient(135deg, #F59E0B, #D97706)" : "linear-gradient(135deg, #14B8A6, #0F766E)" }}
          >
            {initials}
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-1.5">
              <p
                className="text-[13.5px] font-semibold truncate"
                style={{ color: "var(--haip-text)" }}
              >
                {guest.full_name || "Unknown"}
              </p>
              {isVip && <Star size={10} className="text-amber-500 fill-amber-500 flex-shrink-0" />}
              {isBlocked && <AlertTriangle size={10} className="text-red-400 flex-shrink-0" />}
            </div>
            <p className="text-[11px] font-mono" style={{ color: "var(--haip-text-subtle)" }}>
              {guest.phone}
            </p>
          </div>
        </div>
        <ChevronRight
          size={13}
          className="text-gray-300 group-hover:text-teal-500 transition-colors flex-shrink-0 mt-1"
        />
      </div>

      {/* Metadata row */}
      <div className="flex items-center gap-1.5 flex-wrap">
        {sourceName && (
          <span
            className="text-[10px] font-medium px-1.5 py-0.5 rounded-md"
            style={{ background: "rgba(20,184,166,0.08)", color: "#0F766E" }}
          >
            {sourceName}
          </span>
        )}
        {guest.tags.filter(t => t !== "VIP").slice(0, 2).map(t => (
          <span key={t} className="text-[10px] px-1.5 py-0.5 rounded-md bg-blue-50 text-blue-600 font-medium">
            {t}
          </span>
        ))}
        {hasConsent && (
          <span className="text-[10px] px-1.5 py-0.5 rounded-md bg-green-50 text-green-600 font-medium flex items-center gap-0.5">
            <Shield size={8} /> GDPR
          </span>
        )}
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between mt-3 pt-3 border-t border-gray-50">
        <span className="text-[11px]" style={{ color: "var(--haip-text-subtle)" }}>
          Since {timeAgo(guest.created_at)}
        </span>
        <span
          className="text-[11px] font-medium"
          style={{ color: "#0F766E" }}
        >
          View 360 →
        </span>
      </div>
    </button>
  );
}
