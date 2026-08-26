"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Clock, AlertCircle, ChevronDown, MessageSquare, Loader2, Calendar } from "@/lib/icons";
import { UserCheck } from "lucide-react";
import { cn, timeAgo } from "@/lib/utils";
import { ChannelIcon } from "@/components/inbox/ChannelIcon";
import { usePipelineStages } from "@/hooks/usePipelineStages";
import { useToast } from "@/components/ui/toast";
import api from "@/lib/api";

// ─── Types ────────────────────────────────────────────────────────────────────

export interface LeadCard {
  inquiry_id: string;
  guest_id: string;
  display_name: string;
  profile_completeness_pct: number;
  identity_signals: string[];
  source?: string;
  primary_channel?: string;
  inquiry_stage: string;
  stage_key: string | null;
  sla_breached?: boolean;
  occasion?: string;
  group_type?: string;
  check_in?: string;
  check_out?: string;
  budget_estimate?: number;
  budget_currency?: string;
  budget_range_label?: string;
  quoted_amount?: number;
  property_interest?: string[];
  ai_summary?: string;
  ai_next_action?: string;
  assigned_agent_name?: string;
  assigned_agent_avatar_url?: string | null;
  last_touch_at?: string;
  created_at?: string;
  // Computed on read from messages (see LeadCardSchema): "waiting" = guest's
  // latest message unanswered, seconds = wait so far; "responded" = gap
  // between inbound and reply; null = no messages yet.
  response_time_seconds?: number | null;
  response_time_status?: "waiting" | "responded" | null;
  // M5+ WS3: most recent pending AI draft for this lead, if any.
  pending_draft?: { message_id: string; conversation_id: string; preview: string } | null;
  // Auto-send soft-escalation plan: the AI's last reply already went out
  // (not a pending_draft), but it judged the outcome needs a human's
  // personal follow-up -- e.g. a complex custom quote or a frustrated guest.
  needs_agent_followup?: boolean;
  needs_agent_followup_reason?: string | null;
}

function formatCardDate(iso?: string): string | null {
  if (!iso) return null;
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

// ─── Response time badge ─────────────────────────────────────────────────────

export function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return m % 60 ? `${h}h ${m % 60}m` : `${h}h`;
  const d = Math.floor(h / 24);
  return h % 24 ? `${d}d ${h % 24}h` : `${d}d`;
}

export function ResponseTimeBadge({ seconds, status }: { seconds?: number | null; status?: string | null }) {
  if (seconds == null || !status) return null;
  const waiting = status === "waiting";
  // Waiting escalates: subtle under 15m, amber under 1h, red beyond.
  const tone = !waiting
    ? { bg: "color-mix(in srgb, var(--haip-green) 12%, transparent)", fg: "var(--haip-green)" }
    : seconds < 15 * 60
    ? { bg: "var(--muted)", fg: "var(--haip-fg-muted)" }
    : seconds < 60 * 60
    ? { bg: "color-mix(in srgb, var(--haip-amber) 15%, transparent)", fg: "var(--haip-amber)" }
    : { bg: "rgba(244,63,94,0.12)", fg: "#e11d48" };
  return (
    <span
      className="rounded-full px-1.5 py-0.5 text-[9px] font-semibold whitespace-nowrap"
      style={{ background: tone.bg, color: tone.fg }}
      title={waiting ? "Guest is waiting for a reply" : "Time to first reply"}
    >
      {waiting ? `waiting ${formatDuration(seconds)}` : `replied in ${formatDuration(seconds)}`}
    </span>
  );
}

export function NeedsFollowupBadge({ reason }: { reason?: string | null }) {
  if (!reason) return null;
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[9px] font-semibold whitespace-nowrap"
      style={{ background: "color-mix(in srgb, var(--haip-amber) 15%, transparent)", color: "var(--haip-amber)" }}
      title={`AI replied automatically -- needs your follow-up: ${reason}`}
    >
      <UserCheck size={9} />
      needs you
    </span>
  );
}

// ─── Completeness bar ─────────────────────────────────────────────────────────

function CompletenessBar({ pct }: { pct: number }) {
  return (
    <div className="h-1 w-full rounded-full" style={{ background: "var(--muted)" }}>
      <div
        className="h-1 rounded-full transition-all duration-300"
        style={{
          width: `${Math.min(100, pct)}%`,
          background: pct >= 80
            ? "var(--haip-green)"
            : pct >= 50
            ? "var(--haip-amber)"
            : "var(--haip-fg-subtle)",
        }}
      />
    </div>
  );
}

// ─── Agent avatar ─────────────────────────────────────────────────────────────

function AgentAvatar({ name, photoUrl }: { name: string; photoUrl?: string | null }) {
  const initials = name.split(" ").map(w => w[0]).join("").slice(0, 2).toUpperCase();
  const [imgFailed, setImgFailed] = useState(false);

  if (photoUrl && !imgFailed) {
    return (
      <img
        src={photoUrl}
        alt={name}
        title={name}
        onError={() => setImgFailed(true)}
        className="w-5 h-5 rounded-full object-cover flex-shrink-0"
      />
    );
  }

  return (
    <span
      className="w-5 h-5 rounded-full inline-flex items-center justify-center text-[9px] font-bold flex-shrink-0"
      style={{
        background: "color-mix(in srgb, var(--primary) 15%, transparent)",
        color: "var(--primary)",
      }}
      title={name}
    >
      {initials}
    </span>
  );
}

// ─── Pill ─────────────────────────────────────────────────────────────────────

function Pill({ label }: { label: string }) {
  return (
    <span
      className="rounded-full px-2 py-0.5 text-[10px] font-medium capitalize"
      style={{
        background: "var(--muted)",
        color: "var(--haip-fg-muted)",
      }}
    >
      {label.replace(/_/g, " ")}
    </span>
  );
}

// ─── Lead Card ────────────────────────────────────────────────────────────────

// ─── Stage select ──────────────────────────────────────────────────────────

function StageSelect({ lead }: { lead: LeadCard }) {
  const { data: stages = [] } = usePipelineStages();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [saving, setSaving] = useState(false);

  const current = stages.find(s => s.key === lead.stage_key);

  async function handleChange(newStageId: string) {
    if (!newStageId || newStageId === current?.id) return;
    setSaving(true);
    try {
      await api.patch(`/inquiries/${lead.inquiry_id}`, { stage_id: newStageId });
      await queryClient.invalidateQueries({ queryKey: ["leads"] });
      toast({ title: "Stage updated", variant: "success" });
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast({
        title: "Couldn't update stage",
        description: typeof msg === "string" ? msg : "Backward moves may require a reason and manager approval.",
        variant: "error",
      });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="relative flex-shrink-0" onClick={e => e.stopPropagation()}>
      <select
        value={current?.id ?? ""}
        disabled={saving}
        onChange={e => handleChange(e.target.value)}
        className="appearance-none text-[10px] font-medium rounded-full pl-2.5 pr-6 py-1 cursor-pointer disabled:opacity-50"
        style={{
          background: current?.color ? `color-mix(in srgb, ${current.color} 15%, transparent)` : "var(--muted)",
          color: current?.color ?? "var(--haip-fg-subtle)",
          border: "none",
        }}
      >
        {!current && <option value="" disabled>Stage…</option>}
        {stages.map(s => (
          <option key={s.id} value={s.id}>{s.label}</option>
        ))}
      </select>
      <ChevronDown size={10} className="absolute right-2 top-1/2 -translate-y-1/2 pointer-events-none" style={{ color: current?.color ?? "var(--haip-fg-subtle)" }} />
    </div>
  );
}

// M5+ WS3: reuses the existing approve-and-queue endpoint
// (conversations.py::approve_ai_draft) rather than a new one — same one
// the call detail page's recommended-action button uses.
// AI Autonomy Plan Phase 2, 2.3: "one action contract, everywhere" -- this
// used to post straight to /conversations/{id}/messages/{id}/approve, a
// third copy of the same "approve + send a pending AI draft" logic (the
// other two: conversations.py's own endpoint, and automation_engine.py's
// send_whatsapp_draft handler used by AIRecommendationCard). Redirected to
// the shared one-click action endpoint so all three surfaces share one
// dispatch path and one audit trail; the compact card UI is unchanged.
function useApproveAndSendDraft(inquiryId: string) {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  return useMutation({
    mutationFn: ({ conversationId, messageId }: { conversationId: string; messageId: string }) =>
      api.post("/automations/actions/execute", {
        action_type: "send_whatsapp_draft",
        entity_refs: { inquiry_id: inquiryId },
        action_config: { message_id: messageId, conversation_id: conversationId },
        source: "leads360_card",
      }),
    onSuccess: () => {
      toast({ variant: "success", title: "Draft sent", description: "The WhatsApp reply is on its way." });
      queryClient.invalidateQueries({ queryKey: ["leads"] });
    },
    onError: (e: unknown) => {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast({ title: "Send failed", description: typeof msg === "string" ? msg : "Please try again.", variant: "error" });
    },
  });
}

export function LeadCard({ lead }: { lead: LeadCard }) {
  const router = useRouter();
  const src = lead.source ?? lead.primary_channel ?? "";
  const hasPhone = lead.identity_signals?.includes("phone");
  const approveAndSend = useApproveAndSendDraft(lead.inquiry_id);

  const budget = lead.quoted_amount ?? lead.budget_estimate;
  const budgetLabel = lead.budget_range_label
    ?? (budget ? `₹${Number(budget).toLocaleString("en-IN")}` : null);

  const property = lead.property_interest?.[0] ?? null;
  const checkInLabel = formatCardDate(lead.check_in);
  const checkOutLabel = formatCardDate(lead.check_out);

  // Left accent rail (prototype .k-card.urgent / .warm). Driven by the two
  // signals the card already carries: a breached SLA is urgent, a guest still
  // waiting on a reply is warm. Everything else stays unaccented so the
  // colour actually means something when it does appear.
  const accent = lead.sla_breached
    ? "var(--haip-red)"
    : lead.response_time_status === "waiting"
    ? "var(--haip-gold)"
    : null;

  return (
    <div
      className="haip-card p-3 cursor-pointer hover:shadow-md transition-shadow duration-150 space-y-2.5"
      style={accent ? { borderLeft: `3px solid ${accent}` } : undefined}
      onClick={() => router.push(`/dashboard/leads/${lead.inquiry_id}`)}
    >
      {/* Row 1: Guest name + source icon */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 flex-1 min-w-0">
          <span className="font-medium text-sm truncate" style={{ color: "var(--haip-fg)" }}>
            {lead.display_name}
          </span>
          {!hasPhone && (
            <AlertCircle size={10} style={{ color: "var(--haip-fg-subtle)", flexShrink: 0 }} />
          )}
        </div>
        <ChannelIcon channel={src} showLabel className="flex-shrink-0" />
      </div>

      {/* Row 1b: stage dropdown on its own line so it never squeezes the name */}
      <StageSelect lead={lead} />

      {/* Row 2: Occasion + group type pills */}
      {(lead.occasion || lead.group_type) && (
        <div className="flex items-center gap-1 flex-wrap">
          {lead.occasion && <Pill label={lead.occasion} />}
          {lead.group_type && lead.group_type !== lead.occasion && (
            <Pill label={lead.group_type} />
          )}
        </div>
      )}

      {/* Row 3: Property name + budget */}
      {(property || budgetLabel) && (
        <p className="text-xs truncate" style={{ color: "var(--haip-fg-subtle)" }}>
          {property ?? ""}
          {property && budgetLabel ? " · " : ""}
          {budgetLabel ?? ""}
        </p>
      )}

      {/* Row 3b: Check-in / check-out dates, only when at least one is set */}
      {(checkInLabel || checkOutLabel) && (
        <p className="text-xs flex items-center gap-1" style={{ color: "var(--haip-fg-subtle)" }}>
          <Calendar size={10} className="flex-shrink-0" />
          {checkInLabel ?? "?"}
          {checkInLabel && checkOutLabel ? " – " : ""}
          {checkOutLabel ?? ""}
        </p>
      )}

      {/* Row 4: Completeness bar */}
      <CompletenessBar pct={lead.profile_completeness_pct} />

      {/* Row 5: Last activity + response time */}
      <div className="flex items-center justify-between gap-2">
        <p className="text-[10px] flex items-center gap-1" style={{ color: "var(--haip-fg-subtle)" }}>
          <Clock size={9} />
          {lead.last_touch_at ? timeAgo(lead.last_touch_at) : "—"}
        </p>
        <div className="flex items-center gap-1">
          <NeedsFollowupBadge reason={lead.needs_agent_followup_reason} />
          <ResponseTimeBadge seconds={lead.response_time_seconds} status={lead.response_time_status} />
        </div>
      </div>

      {/* Row 6: Assigned agent — AI summary intentionally removed from this
          card (kept on the lead detail page); the card now stays scoped to
          source/name/dates/budget the agent needs at a glance. */}
      {lead.assigned_agent_name && (
        <div className="flex items-center gap-1.5 pt-0.5" style={{ borderTop: "1px solid var(--haip-border)" }}>
          <AgentAvatar name={lead.assigned_agent_name} photoUrl={lead.assigned_agent_avatar_url} />
          <span className="text-[10px] truncate" style={{ color: "var(--haip-fg-subtle)" }}>
            {lead.assigned_agent_name}
          </span>
        </div>
      )}

      {/* Row 7: pending AI draft — one-click send */}
      {lead.pending_draft && (
        <div
          className="lx-draft-card flex items-center justify-between gap-2 px-2 py-1.5"
          onClick={e => e.stopPropagation()}
        >
          <p className="text-[10px] truncate flex-1" style={{ color: "var(--haip-fg-2)" }} title={lead.pending_draft.preview}>
            {lead.pending_draft.preview}
          </p>
          <button
            type="button"
            onClick={() => approveAndSend.mutate({
              conversationId: lead.pending_draft!.conversation_id,
              messageId: lead.pending_draft!.message_id,
            })}
            disabled={approveAndSend.isPending}
            className="lx-draft-send-btn inline-flex items-center gap-1 px-2 py-1 text-[10px] font-semibold flex-shrink-0 transition-colors disabled:opacity-60"
          >
            {approveAndSend.isPending ? <Loader2 size={10} className="animate-spin" /> : <MessageSquare size={10} />}
            Send
          </button>
        </div>
      )}
    </div>
  );
}
