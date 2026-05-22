"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { Search, ArrowLeft, Phone, MessageSquare, Star, Shield, AlertTriangle } from "lucide-react";
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
  whatsapp: "WhatsApp", instagram: "Instagram",
};

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

  const totalRevenue = guests.reduce((acc, _) => acc, 0); // computed from stays in profile

  // ── Guest 360 detail ──────────────────────────────────────
  if (selectedPhone) {
    return (
      <div className="h-full bg-gray-50 overflow-y-auto">
        <div className="max-w-2xl mx-auto p-5">
          <button onClick={() => setSelectedPhone(null)}
            className="flex items-center gap-2 text-sm text-gray-500 hover:text-gray-800 mb-5 transition-colors">
            <ArrowLeft size={16} /> Back to guests
          </button>

          {profileLoading || !profile ? (
            <div className="bg-white rounded-xl border p-8 text-center text-sm text-gray-400">Loading guest profile…</div>
          ) : (
            <>
              {/* Identity card */}
              <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-5 mb-4">
                <div className="flex items-start gap-4">
                  <div className="w-14 h-14 rounded-full bg-teal-100 flex items-center justify-center text-xl font-bold text-teal-700 flex-shrink-0">
                    {profile.full_name[0]}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <h2 className="text-lg font-bold text-gray-900">{profile.full_name}</h2>
                      {profile.tags.includes("VIP") && (
                        <span className="text-[10px] bg-amber-100 text-amber-700 px-2 py-0.5 rounded-full font-semibold flex items-center gap-1">
                          <Star size={9} className="fill-amber-500 text-amber-500" /> VIP
                        </span>
                      )}
                      {profile.blacklisted && (
                        <span className="text-[10px] bg-red-100 text-red-700 px-2 py-0.5 rounded-full font-semibold flex items-center gap-1">
                          <AlertTriangle size={9} /> Blacklisted
                        </span>
                      )}
                      {profile.gdpr_consent && (
                        <span className="text-[10px] bg-green-100 text-green-700 px-2 py-0.5 rounded-full font-semibold flex items-center gap-1">
                          <Shield size={9} /> GDPR ✓
                        </span>
                      )}
                    </div>
                    <div className="text-sm text-gray-500 mt-0.5">{profile.phone}</div>
                    {profile.email && <div className="text-xs text-gray-400">{profile.email}</div>}
                    <div className="flex items-center gap-3 mt-2 flex-wrap">
                      {profile.nationality && <Pill>{profile.nationality}</Pill>}
                      {profile.source && <Pill>{SOURCE_LABELS[profile.source] ?? profile.source}</Pill>}
                      {profile.language && <Pill>Lang: {profile.language.toUpperCase()}</Pill>}
                      {profile.tags.filter(t => t !== "VIP").map(t => <Pill key={t}>{t}</Pill>)}
                    </div>
                  </div>
                </div>

                {/* Quick stats */}
                <div className="grid grid-cols-3 gap-3 mt-4">
                  <Stat label="Stays" value={String(profile.stays.length)} />
                  <Stat label="Inquiries" value={String(profile.inquiries.length)} />
                  <Stat label="Revenue" value={
                    profile.stays.length > 0
                      ? `€${profile.stays.reduce((s, st) => s + parseFloat(st.total_amount ?? "0"), 0).toLocaleString()}`
                      : "—"
                  } />
                </div>
              </div>

              {/* Stays */}
              {profile.stays.length > 0 && (
                <Section title="Stay History" count={profile.stays.length}>
                  {profile.stays.map(stay => (
                    <div key={stay.id} className="flex items-center justify-between py-2.5 border-b border-gray-50 last:border-0">
                      <div>
                        <div className="text-sm font-medium text-gray-900">{stay.check_in} → {stay.check_out}</div>
                        <div className="text-xs text-gray-400">{stay.channel ?? "—"} · {stay.booking_ref ?? "no ref"}</div>
                      </div>
                      <div className="text-right">
                        <div className="text-sm font-semibold text-gray-900">
                          {stay.total_amount ? `${stay.currency} ${Number(stay.total_amount).toLocaleString()}` : "—"}
                        </div>
                        <span className={cn("text-[10px] px-1.5 py-0.5 rounded font-medium",
                          stay.payment_status === "fully_paid" ? "bg-green-100 text-green-700" :
                          stay.payment_status === "deposit_paid" ? "bg-blue-100 text-blue-700" : "bg-gray-100 text-gray-500"
                        )}>
                          {stay.payment_status.replace("_", " ")}
                        </span>
                      </div>
                    </div>
                  ))}
                </Section>
              )}

              {/* Inquiries */}
              {profile.inquiries.length > 0 && (
                <Section title="Inquiries" count={profile.inquiries.length}>
                  {profile.inquiries.map(inq => (
                    <div key={inq.id} className="flex items-center justify-between py-2.5 border-b border-gray-50 last:border-0">
                      <div>
                        <div className="text-sm text-gray-700">
                          {inq.check_in && inq.check_out ? `${inq.check_in} → ${inq.check_out}` : "Dates TBD"}
                        </div>
                        <div className="text-xs text-gray-400">{inq.source ?? "—"}</div>
                      </div>
                      <span className={cn("text-[10px] px-2 py-0.5 rounded font-medium capitalize",
                        inq.status === "confirmed" ? "bg-green-100 text-green-700" :
                        inq.status === "lost" ? "bg-red-100 text-red-700" :
                        inq.status === "new" ? "bg-blue-100 text-blue-700" : "bg-gray-100 text-gray-600"
                      )}>
                        {inq.status}
                      </span>
                    </div>
                  ))}
                </Section>
              )}

              {/* Recent calls */}
              {profile.recent_calls.length > 0 && (
                <Section title="Recent Calls" count={profile.recent_calls.length}>
                  {profile.recent_calls.map(call => (
                    <div key={call.id} className="flex items-center gap-3 py-2.5 border-b border-gray-50 last:border-0">
                      <div className="w-7 h-7 rounded-full bg-blue-50 flex items-center justify-center flex-shrink-0">
                        <Phone size={12} className="text-blue-600" />
                      </div>
                      <div className="flex-1">
                        <div className="text-sm text-gray-700">{call.agent_name ?? "Unknown Agent"}</div>
                        <div className="text-xs text-gray-400">{call.call_date}</div>
                      </div>
                      {call.qa_score && (
                        <span className={cn("text-[10px] font-bold px-2 py-0.5 rounded",
                          parseFloat(call.qa_score) >= 8 ? "bg-green-100 text-green-700" :
                          parseFloat(call.qa_score) >= 6 ? "bg-amber-100 text-amber-700" : "bg-red-100 text-red-700"
                        )}>
                          QA {(parseFloat(call.qa_score) * 10).toFixed(0)}%
                        </span>
                      )}
                    </div>
                  ))}
                </Section>
              )}

              {/* Recent messages */}
              {profile.recent_messages.length > 0 && (
                <Section title="Recent Messages" count={profile.recent_messages.length}>
                  {profile.recent_messages.map(msg => (
                    <div key={msg.id} className={cn("flex gap-2 py-2", msg.direction === "outbound" ? "flex-row-reverse" : "")}>
                      <div className={cn("flex-shrink-0 w-6 h-6 rounded-full flex items-center justify-center",
                        msg.direction === "inbound" ? "bg-gray-100" : "bg-teal-100"
                      )}>
                        <MessageSquare size={11} className={msg.direction === "inbound" ? "text-gray-500" : "text-teal-600"} />
                      </div>
                      <div className={cn("flex-1 max-w-[80%]", msg.direction === "outbound" && "text-right")}>
                        <div className={cn("text-xs px-3 py-2 rounded-xl inline-block",
                          msg.direction === "inbound" ? "bg-gray-100 text-gray-800" : "bg-teal-500 text-white"
                        )}>
                          {msg.content}
                        </div>
                        <div className="text-[10px] text-gray-400 mt-0.5">{timeAgo(msg.created_at)}</div>
                      </div>
                    </div>
                  ))}
                </Section>
              )}

              {/* Activities */}
              {profile.activities.length > 0 && (
                <Section title="Activity Log" count={profile.activities.length}>
                  {profile.activities.map(act => (
                    <div key={act.id} className="flex gap-3 py-2.5 border-b border-gray-50 last:border-0">
                      <div className={cn("w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0 text-xs",
                        act.type === "call" ? "bg-blue-100 text-blue-600" :
                        act.type === "email" ? "bg-amber-100 text-amber-600" : "bg-gray-100 text-gray-500"
                      )}>
                        {act.type === "call" ? "📞" : act.type === "email" ? "✉" : "📝"}
                      </div>
                      <div className="flex-1">
                        <div className="text-xs text-gray-700 leading-snug">{act.content}</div>
                        <div className="text-[10px] text-gray-400 mt-0.5">{timeAgo(act.created_at)}</div>
                      </div>
                    </div>
                  ))}
                </Section>
              )}
            </>
          )}
        </div>
      </div>
    );
  }

  // ── Guest list ────────────────────────────────────────────
  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-5 py-4 border-b border-gray-100 bg-white flex items-center justify-between flex-shrink-0 gap-3">
        <div>
          <h1 className="text-lg font-bold text-gray-900">Guests</h1>
          <p className="text-xs text-gray-400 mt-0.5">{guests.length} guests</p>
        </div>
        <div className="relative flex-1 max-w-xs">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            value={search}
            onChange={e => handleSearch(e.target.value)}
            placeholder="Search name, phone, email…"
            className="w-full pl-8 pr-3 py-2 bg-gray-50 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500/30"
          />
        </div>
      </div>

      {/* Table */}
      <div className="flex-1 overflow-auto p-4">
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
          {isLoading ? (
            <div className="p-8 text-center text-sm text-gray-400">Loading guests…</div>
          ) : guests.length === 0 ? (
            <EmptyGuests />
          ) : (
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b border-gray-100">
                <tr>
                  {["Guest", "Phone", "Source", "Tags", "Consent", "Since", ""].map(h => (
                    <th key={h} className="text-left px-4 py-3 text-xs font-semibold text-gray-500 whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {guests.map(guest => (
                  <tr
                    key={guest.phone}
                    className="hover:bg-gray-50 cursor-pointer transition-colors"
                    onClick={() => setSelectedPhone(guest.phone)}
                  >
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2.5">
                        <div className="w-8 h-8 rounded-full bg-teal-100 flex items-center justify-center text-xs font-bold text-teal-700 flex-shrink-0">
                          {guest.full_name[0]}
                        </div>
                        <div>
                          <div className="font-medium text-gray-900 flex items-center gap-1">
                            {guest.full_name}
                            {guest.tags.includes("VIP") && <Star size={10} className="text-amber-500 fill-amber-500" />}
                            {guest.blacklisted && <AlertTriangle size={10} className="text-red-500" />}
                          </div>
                          <div className="text-xs text-gray-400">{guest.email ?? "—"}</div>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-gray-600 font-mono text-xs">{guest.phone}</td>
                    <td className="px-4 py-3 text-gray-500 text-xs capitalize">{SOURCE_LABELS[guest.source ?? ""] ?? guest.source ?? "—"}</td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-1">
                        {guest.tags.map(t => <span key={t} className="text-[9px] bg-blue-50 text-blue-700 px-1.5 py-0.5 rounded-full">{t}</span>)}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      {guest.gdpr_consent
                        ? <span className="text-[10px] bg-green-100 text-green-700 px-1.5 py-0.5 rounded font-medium">✓ Given</span>
                        : <span className="text-[10px] bg-red-50 text-red-400 px-1.5 py-0.5 rounded">Pending</span>
                      }
                    </td>
                    <td className="px-4 py-3 text-gray-400 text-xs">{timeAgo(guest.created_at)}</td>
                    <td className="px-4 py-3">
                      <span className="text-xs text-teal-600 hover:underline">360 →</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}

function Section({ title, count, children }: { title: string; count: number; children: React.ReactNode }) {
  return (
    <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-5 mb-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-gray-800">{title}</h3>
        <span className="text-xs text-gray-400">{count}</span>
      </div>
      {children}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-gray-50 rounded-lg p-3 text-center">
      <div className="text-xs text-gray-500 mb-0.5">{label}</div>
      <div className="text-sm font-bold text-gray-900">{value}</div>
    </div>
  );
}

function Pill({ children }: { children: React.ReactNode }) {
  return <span className="text-[10px] bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full">{children}</span>;
}
