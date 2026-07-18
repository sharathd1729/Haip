"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Clock, Sparkles, AlertCircle, ChevronDown } from "lucide-react";
import { cn, timeAgo } from "@/lib/utils";
import { ChannelIcon } from "@/components/inbox/ChannelIcon";
import { Skeleton } from "@/components/ui/skeleton";
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
  assigned_agent_name?: string;
  last_touch_at?: string;
  created_at?: string;
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

function AgentAvatar({ name }: { name: string }) {
  const initials = name.split(" ").map(w => w[0]).join("").slice(0, 2).toUpperCase();
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

export function LeadCard({ lead }: { lead: LeadCard }) {
  const router = useRouter();
  const src = lead.source ?? lead.primary_channel ?? "";
  const hasPhone = lead.identity_signals?.includes("phone");

  const budget = lead.quoted_amount ?? lead.budget_estimate;
  const budgetLabel = lead.budget_range_label
    ?? (budget ? `₹${Number(budget).toLocaleString("en-IN")}` : null);

  const property = lead.property_interest?.[0] ?? null;

  return (
    <div
      className="bg-card rounded-xl p-4 cursor-pointer shadow-sm dark:shadow-none hover:shadow-md transition-shadow duration-150 space-y-2.5"
      onClick={() => router.push(`/dashboard/leads/${lead.inquiry_id}`)}
    >
      {/* Row 1: Guest name + source icon */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 min-w-0">
          <span className="font-medium text-sm truncate" style={{ color: "var(--haip-fg)" }}>
            {lead.display_name}
          </span>
          {!hasPhone && (
            <AlertCircle size={10} style={{ color: "var(--haip-fg-subtle)", flexShrink: 0 }} />
          )}
        </div>
        <div className="flex items-center gap-1.5 flex-shrink-0">
          <ChannelIcon channel={src} className="flex-shrink-0" />
          <StageSelect lead={lead} />
        </div>
      </div>

      {/* Row 2: Occasion + group type pills */}
      {(lead.occasion || lead.group_type) && (
        <div className="flex items-center gap-1 flex-wrap">
          {lead.occasion && <Pill label={lead.occasion} />}
          {lead.group_type && lead.group_type !== lead.occasion && (
            <Pill label={lead.group_type} />
          )}
          {lead.sla_breached && (
            <span className="rounded-full px-2 py-0.5 text-[10px] font-medium bg-rose-50 text-rose-600 dark:bg-rose-950 dark:text-rose-400">
              SLA
            </span>
          )}
        </div>
      )}

      {/* Row 3: Property name */}
      {(property || budgetLabel) && (
        <p className="text-xs truncate" style={{ color: "var(--haip-fg-subtle)" }}>
          {property ?? ""}
          {property && budgetLabel ? " · " : ""}
          {budgetLabel ?? ""}
        </p>
      )}

      {/* Row 4: Completeness bar */}
      <CompletenessBar pct={lead.profile_completeness_pct} />

      {/* Row 5: Last activity */}
      <p className="text-[10px] flex items-center gap-1" style={{ color: "var(--haip-fg-subtle)" }}>
        <Clock size={9} />
        {lead.last_touch_at ? timeAgo(lead.last_touch_at) : "—"}
      </p>

      {/* Row 6: Agent avatar + AI summary */}
      <div className="flex items-start gap-1.5 pt-0.5" style={{ borderTop: "1px solid var(--haip-border)" }}>
        {lead.assigned_agent_name && (
          <AgentAvatar name={lead.assigned_agent_name} />
        )}
        {lead.ai_summary ? (
          <p className="text-[10px] leading-relaxed line-clamp-2 flex-1" style={{ color: "var(--haip-fg-subtle)" }}>
            <Sparkles size={9} className="inline mr-1" style={{ color: "var(--primary)" }} />
            {lead.ai_summary}
          </p>
        ) : (
          <div className="flex-1 space-y-1">
            <Skeleton className="h-2.5 w-full rounded" />
            <Skeleton className="h-2.5 w-3/4 rounded" />
          </div>
        )}
      </div>
    </div>
  );
}
