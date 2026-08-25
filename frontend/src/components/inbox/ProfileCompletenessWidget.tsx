"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, XCircle, Phone, Sparkles, PartyPopper } from "@/lib/icons";
import confetti from "canvas-confetti";
import api from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { Skeleton } from "@/components/ui/skeleton";

/**
 * HAIP Inbox prototype-wiring plan, ticket 5. Replaces the prototype's
 * "Qualification Widget" -- that concept ("unqualified conversation
 * converts to a CRM lead once phone is collected") doesn't match how HAIP's
 * identity model actually works: every conversation already has an Inquiry
 * from first touch (CLAUDE.md -- phone is one signal among many, may never
 * exist). This shows real profile-completeness data instead, backed by the
 * existing GET /leads/{inquiry_id} (leads_service.get_profile_completeness
 * under the hood) and the existing POST /leads/{inquiry_id}/signals for
 * adding a phone number -- no new backend built for this widget.
 */

interface LeadDetail {
  inquiry_id: string;
  guest_id: string;
  display_name: string;
  profile_completeness_pct: number;
  identity_signals: string[];
  check_in?: string | null;
  check_out?: string | null;
  adults?: number | null;
  budget_estimate?: number | null;
  property_interest: string[];
}

interface ChecklistItem {
  key: string;
  label: string;
  done: boolean;
}

export function ProfileCompletenessWidget({ inquiryId }: { inquiryId: string | null }) {
  const { toast } = useToast();
  const qc = useQueryClient();
  const [showPhoneInput, setShowPhoneInput] = useState(false);
  const [phoneValue, setPhoneValue] = useState("");
  const [showSuccessBanner, setShowSuccessBanner] = useState(false);

  const { data: lead, isLoading } = useQuery<LeadDetail>({
    queryKey: ["lead-detail", inquiryId],
    queryFn: () => api.get(`/leads/${inquiryId}`).then(r => r.data),
    enabled: !!inquiryId,
    staleTime: 30_000,
  });

  const addPhone = useMutation({
    mutationFn: (phone: string) =>
      api.post(`/leads/${inquiryId}/signals`, { type: "phone", value: phone }),
    onSuccess: () => {
      // HAIP Inbox full-parity pass, ticket 4: real celebratory moment on a
      // real event (a phone signal was actually recorded) -- matches the
      // prototype's confetti pattern, not a fake "converted to CRM lead"
      // claim (every conversation already has an Inquiry from first touch).
      confetti({ particleCount: 80, spread: 65, origin: { y: 0.7 } });
      setShowSuccessBanner(true);
      setTimeout(() => setShowSuccessBanner(false), 4000);
      toast({ variant: "success", title: "Phone added", description: "Guest signal recorded." });
      qc.invalidateQueries({ queryKey: ["lead-detail", inquiryId] });
      setShowPhoneInput(false);
      setPhoneValue("");
    },
    onError: (e: unknown) => {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast({ variant: "error", title: "Could not add phone", description: typeof msg === "string" ? msg : "Please try again." });
    },
  });

  if (!inquiryId) return null;
  if (isLoading || !lead) {
    return (
      <div className="p-3.5 rounded-xl border" style={{ borderColor: "var(--haip-border)" }}>
        <Skeleton className="h-4 w-32 mb-2" />
        <Skeleton className="h-2 w-full" />
      </div>
    );
  }

  const hasPhone = lead.identity_signals.includes("phone");
  const items: ChecklistItem[] = [
    { key: "name", label: "Guest name", done: !!lead.display_name && lead.display_name !== "Unknown Guest" },
    { key: "phone", label: "Phone number", done: hasPhone },
    { key: "dates", label: "Travel dates", done: !!(lead.check_in && lead.check_out) },
    { key: "guests", label: "Guest count", done: lead.adults != null },
    { key: "budget", label: "Budget", done: lead.budget_estimate != null },
    { key: "property", label: "Property interest", done: lead.property_interest.length > 0 },
  ];

  return (
    <div
      id="profile-completeness-widget"
      className="p-3.5 rounded-xl border space-y-2.5"
      style={{ borderColor: "var(--haip-border)", background: "var(--card)" }}
    >
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-bold uppercase tracking-wider flex items-center gap-1.5" style={{ color: "var(--haip-fg-subtle)" }}>
          <Sparkles size={12} style={{ color: "var(--primary)" }} />
          Profile completeness
        </span>
        <span className="text-xs font-mono font-extrabold" style={{ color: "var(--primary)" }}>
          {lead.profile_completeness_pct}%
        </span>
      </div>

      {showSuccessBanner && (
        <div
          className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-[11px] font-semibold"
          style={{ background: "color-mix(in srgb, var(--haip-green) 12%, transparent)", color: "var(--haip-green)" }}
        >
          <PartyPopper size={13} className="flex-shrink-0" />
          Phone number added — profile updated!
        </div>
      )}

      <div className="h-1.5 w-full rounded-full overflow-hidden" style={{ background: "var(--muted)" }}>
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: `${lead.profile_completeness_pct}%`, background: "var(--primary)" }}
        />
      </div>

      <div className="grid grid-cols-2 gap-1.5 text-[11px]">
        {items.map(item => (
          <div key={item.key} className="flex items-center gap-1.5">
            {item.done ? (
              <CheckCircle2 size={12} className="text-emerald-500 flex-shrink-0" />
            ) : item.key === "phone" ? (
              <button
                type="button"
                onClick={() => setShowPhoneInput(true)}
                className="flex items-center gap-1 hover:underline"
                style={{ color: "var(--haip-amber, #d97706)" }}
              >
                <XCircle size={12} className="flex-shrink-0" /> {item.label}
              </button>
            ) : (
              <XCircle size={12} className="text-rose-400 flex-shrink-0" />
            )}
            {!(item.key === "phone" && !item.done) && <span style={{ color: "var(--haip-fg-muted)" }}>{item.label}</span>}
          </div>
        ))}
      </div>

      {!hasPhone && showPhoneInput && (
        <form
          onSubmit={e => { e.preventDefault(); if (phoneValue.trim()) addPhone.mutate(phoneValue.trim()); }}
          className="flex gap-1.5 pt-1"
        >
          <input
            type="tel"
            value={phoneValue}
            onChange={e => setPhoneValue(e.target.value)}
            placeholder="+91 98765 43210"
            autoFocus
            className="flex-1 px-2 py-1 rounded-lg text-xs border outline-none"
            style={{ borderColor: "var(--haip-border)" }}
          />
          <button
            type="submit"
            disabled={addPhone.isPending}
            className="px-2.5 py-1 rounded-lg text-xs font-semibold text-white disabled:opacity-60"
            style={{ background: "var(--primary)" }}
          >
            <Phone size={11} className="inline mr-1" />
            Add
          </button>
        </form>
      )}
    </div>
  );
}
