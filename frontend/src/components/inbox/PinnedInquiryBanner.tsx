"use client";
import { useQuery } from "@tanstack/react-query";
import { Calendar, Users, Wallet, Flame } from "@/lib/icons";
import api from "@/lib/api";

/**
 * HAIP Inbox UI-fidelity pass, ticket 5: prototype's "Pinned Inquiry" bar
 * above the thread -- dates/guests/budget + lead score at a glance without
 * opening the right panel. Reuses GET /leads/{inquiry_id} (same queryKey
 * ProfileCompletenessWidget/GuestPanel already fetch, so react-query
 * dedupes this into the same network call, no new backend endpoint).
 */

interface LeadSnapshot {
  check_in?: string | null;
  check_out?: string | null;
  adults?: number | null;
  children?: number | null;
  budget_estimate?: number | null;
  budget_currency?: string;
  profile_completeness_pct?: number;
}

function formatDate(iso?: string | null): string | null {
  if (!iso) return null;
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

export function PinnedInquiryBanner({ inquiryId }: { inquiryId: string | null }) {
  const { data: lead } = useQuery<LeadSnapshot>({
    queryKey: ["lead-detail", inquiryId],
    queryFn: () => api.get(`/leads/${inquiryId}`).then(r => r.data),
    enabled: !!inquiryId,
    staleTime: 30_000,
  });

  if (!inquiryId || !lead) return null;

  const dateRange = lead.check_in
    ? `${formatDate(lead.check_in)}${lead.check_out ? ` → ${formatDate(lead.check_out)}` : ""}`
    : null;
  const guestCount = lead.adults != null
    ? `${lead.adults} adult${lead.adults === 1 ? "" : "s"}${lead.children ? ` + ${lead.children} kids` : ""}`
    : null;
  const budget = lead.budget_estimate != null
    ? `${lead.budget_currency ?? "INR"} ${lead.budget_estimate.toLocaleString("en-IN")}`
    : null;

  if (!dateRange && !guestCount && !budget && lead.profile_completeness_pct == null) return null;

  return (
    <div
      className="px-3 md:px-5 py-1.5 flex items-center gap-3 md:gap-4 flex-wrap text-[11px] flex-shrink-0"
      style={{ borderBottom: "1px solid var(--haip-border)", background: "color-mix(in srgb, var(--primary) 5%, transparent)" }}
    >
      {dateRange && (
        <span className="flex items-center gap-1" style={{ color: "var(--haip-fg-muted)" }}>
          <Calendar size={11} style={{ color: "var(--primary)" }} />{dateRange}
        </span>
      )}
      {guestCount && (
        <span className="flex items-center gap-1" style={{ color: "var(--haip-fg-muted)" }}>
          <Users size={11} style={{ color: "var(--primary)" }} />{guestCount}
        </span>
      )}
      {budget && (
        <span className="flex items-center gap-1" style={{ color: "var(--haip-fg-muted)" }}>
          <Wallet size={11} style={{ color: "var(--primary)" }} />{budget}
        </span>
      )}
      {lead.profile_completeness_pct != null && (
        <span className="ml-auto flex items-center gap-1 font-semibold" style={{ color: "var(--primary)" }}>
          <Flame size={11} />{lead.profile_completeness_pct}%
        </span>
      )}
    </div>
  );
}
