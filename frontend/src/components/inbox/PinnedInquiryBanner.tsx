"use client";
import { useQuery } from "@tanstack/react-query";
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

  // Inbox redesign "trip bar": one slim row with what the agent needs to
  // quote -- missing details shown in amber so the next question is obvious.
  // Profile completeness is no longer repeated here (it lives in the guest
  // panel).
  const dateRange = lead.check_in
    ? `${formatDate(lead.check_in)}${lead.check_out ? ` – ${formatDate(lead.check_out)}` : ""}`
    : null;
  const guestCount = lead.adults != null
    ? `${lead.adults} adult${lead.adults === 1 ? "" : "s"}${lead.children ? ` · ${lead.children} kid${lead.children === 1 ? "" : "s"}` : ""}`
    : null;
  const budget = lead.budget_estimate != null
    ? `₹${lead.budget_estimate.toLocaleString("en-IN")}`
    : null;

  const facts: [string, string | null][] = [
    ["Guests", guestCount],
    ["Dates", dateRange],
    ["Budget", budget],
  ];

  return (
    <div
      className="px-3 md:px-5 py-2 flex items-center gap-x-5 gap-y-1 flex-wrap text-xs flex-shrink-0"
      style={{ borderBottom: "1px solid var(--haip-border)", background: "var(--haip-card)" }}
    >
      {facts.map(([label, value]) => (
        <span key={label} className="inline-flex items-baseline gap-1.5">
          <span style={{ color: "var(--haip-fg-subtle)" }}>{label}</span>
          {value
            ? <span className="font-semibold" style={{ color: "var(--haip-fg)" }}>{value}</span>
            : <span className="font-semibold text-amber-700">Not shared</span>}
        </span>
      ))}
    </div>
  );
}
