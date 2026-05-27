"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import {
  Search, ArrowLeft, Phone, MessageSquare, Star,
  Shield, AlertTriangle, Plus, ChevronRight,
  Calendar, TrendingUp, Users, Sparkles,
} from "lucide-react";
import { timeAgo, cn } from "@/lib/utils";
import { EmptyGuests } from "@/components/empty-states/EmptyGuests";

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

// ─── Guest list ───────────────────────────────────────────────────────────────

export default function GuestsPage() {
  const [search, setSearch] = useState("");
  const [selectedPhone, setSelectedPhone] = useState<string | null>(null);
  const [debouncedSearch, setDebouncedSearch] = useState("");

  const { data: guests = [], isLoading } = useQuery<GuestItem[]>({
    queryKey: ["guests", debouncedSearch],
    queryFn: () => api.get("/guests", { params: debouncedSearch ? { q: debouncedSearch } : {} }).then(r => r.data),
    staleTime: 30_000,
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

  // Guest card grid
  const returning = guests.filter(g => !g.tags.includes("new")).length;

  return (
    <div className="flex flex-col h-full bg-[#F8FAFC]">
      {/* Header */}
      <div
        className="flex-shrink-0 px-6 py-4 flex items-center justify-between gap-4"
        style={{ background: "#FFFFFF", borderBottom: "1px solid #E5E7EB" }}
      >
        <div>
          <h1
            className="text-xl font-bold"
            style={{ fontFamily: "var(--font-display), sans-serif", color: "#111827" }}
          >
            Guests
          </h1>
          <p className="text-xs mt-0.5" style={{ color: "#6B7280" }}>
            {guests.length} total · {returning} returning
          </p>
        </div>
        <div className="relative max-w-xs w-full">
          <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2" style={{ color: "#9CA3AF" }} />
          <input
            value={search}
            onChange={e => handleSearch(e.target.value)}
            placeholder="Search name, phone, email…"
            className="w-full pl-8 pr-3 py-2 text-sm rounded-xl focus:outline-none"
            style={{
              background: "#F8FAFC",
              border: "1px solid #E5E7EB",
              color: "#111827",
            }}
            onFocus={e => { (e.currentTarget as HTMLElement).style.borderColor = "#0F766E"; }}
            onBlur={e => { (e.currentTarget as HTMLElement).style.borderColor = "#E5E7EB"; }}
          />
        </div>
      </div>

      {/* KPI strip */}
      {guests.length > 0 && (
        <div
          className="flex-shrink-0 flex items-center gap-6 px-6 py-3 border-b"
          style={{ background: "#F8FAFC", borderColor: "#E2E8F0" }}
        >
          {[
            { icon: <Users size={12} className="text-teal-600" />, label: "Total guests", value: guests.length },
            { icon: <TrendingUp size={12} className="text-blue-600" />, label: "VIP guests", value: guests.filter(g => g.tags.includes("VIP")).length },
            { icon: <Shield size={12} className="text-green-600" />, label: "Consented", value: guests.filter(g => g.gdpr_consent).length },
          ].map(s => (
            <div key={s.label} className="flex items-center gap-2">
              {s.icon}
              <span className="text-xs text-gray-500">{s.label}:</span>
              <span className="text-xs font-semibold text-gray-900">{s.value}</span>
            </div>
          ))}
        </div>
      )}

      {/* Content */}
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
