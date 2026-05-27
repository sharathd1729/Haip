"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Zap, Plus, CheckCircle2, PauseCircle, XCircle,
  MessageSquare, Phone, Clock, ChevronRight, ToggleLeft, ToggleRight,
  AlertCircle, Loader2, Settings2,
} from "lucide-react";
import api from "@/lib/api";

// ─── Types ────────────────────────────────────────────────────────────────────

interface AutomationRule {
  id: string;
  name: string;
  description?: string;
  trigger: string;
  action: string;
  is_active: boolean;
  run_count?: number;
  last_run_at?: string;
  created_at?: string;
}

interface AutomationRun {
  id: string;
  automation_id: string;
  automation_name?: string;
  status: "success" | "failed" | "skipped";
  ran_at: string;
  detail?: string;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

const TRIGGER_LABELS: Record<string, { label: string; icon: React.ReactNode }> = {
  new_inquiry:        { label: "New inquiry",        icon: <MessageSquare size={12} /> },
  call_completed:     { label: "Call completed",     icon: <Phone size={12} /> },
  no_response_2h:     { label: "No response 2h",     icon: <Clock size={12} /> },
  no_response_24h:    { label: "No response 24h",    icon: <Clock size={12} /> },
  inquiry_lost:       { label: "Inquiry lost",       icon: <XCircle size={12} /> },
  stay_check_in_1d:   { label: "Check-in tomorrow",  icon: <CheckCircle2 size={12} /> },
  stay_check_out_1d:  { label: "Check-out tomorrow", icon: <CheckCircle2 size={12} /> },
};

const ACTION_LABELS: Record<string, string> = {
  send_whatsapp_template: "Send WhatsApp template",
  create_draft_reply:     "Draft AI reply",
  notify_team:            "Notify team",
  move_to_followup:       "Move to follow-up",
  tag_guest:              "Tag guest",
};

function triggerInfo(trigger: string) {
  return TRIGGER_LABELS[trigger] ?? { label: trigger, icon: <Zap size={12} /> };
}
function actionLabel(action: string) {
  return ACTION_LABELS[action] ?? action;
}

function timeAgo(iso: string): string {
  const d = Date.now() - new Date(iso).getTime();
  const m = Math.floor(d / 60_000);
  if (m < 2) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function StatusBadge({ status }: { status: AutomationRun["status"] }) {
  if (status === "success")
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10.5px] font-medium"
        style={{ background: "rgba(20,184,166,0.10)", color: "#0F766E" }}>
        <CheckCircle2 size={9} /> Success
      </span>
    );
  if (status === "failed")
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10.5px] font-medium"
        style={{ background: "rgba(248,113,113,0.10)", color: "#dc2626" }}>
        <XCircle size={9} /> Failed
      </span>
    );
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10.5px] font-medium"
      style={{ background: "rgba(148,163,184,0.12)", color: "#64748b" }}>
      <PauseCircle size={9} /> Skipped
    </span>
  );
}

function RuleSkeleton() {
  return (
    <div className="haip-card rounded-2xl p-5 animate-pulse" style={{ border: "1px solid var(--haip-border)" }}>
      <div className="flex items-start justify-between mb-3">
        <div className="w-36 h-4 rounded bg-gray-100" />
        <div className="w-10 h-5 rounded-full bg-gray-100" />
      </div>
      <div className="w-48 h-3 rounded bg-gray-100 mb-4" />
      <div className="flex gap-2">
        <div className="w-20 h-5 rounded-full bg-gray-100" />
        <div className="w-28 h-5 rounded-full bg-gray-100" />
      </div>
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function AutomationsPage() {
  const queryClient = useQueryClient();
  const [toastMsg, setToastMsg] = useState<{ type: "success" | "error"; text: string } | null>(null);

  function showToast(type: "success" | "error", text: string) {
    setToastMsg({ type, text });
    setTimeout(() => setToastMsg(null), 3500);
  }

  const { data: rules = [], isLoading: rulesLoading } = useQuery<AutomationRule[]>({
    queryKey: ["automations"],
    queryFn: () => api.get("/automations").then(r => r.data),
    staleTime: 30_000,
  });

  const { data: runs = [], isLoading: runsLoading } = useQuery<AutomationRun[]>({
    queryKey: ["automation-runs"],
    queryFn: () => api.get("/automations/runs?limit=20").then(r => r.data),
    staleTime: 30_000,
  });

  const toggleMutation = useMutation({
    mutationFn: (rule: AutomationRule) =>
      api.patch(`/automations/${rule.id}`, { is_active: !rule.is_active }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["automations"] });
      showToast("success", "Automation updated");
    },
    onError: () => showToast("error", "Update failed"),
  });

  const activeCount = rules.filter(r => r.is_active).length;
  const successCount = runs.filter(r => r.status === "success").length;
  const failedCount = runs.filter(r => r.status === "failed").length;

  return (
    <div className="h-full flex flex-col" style={{ background: "var(--haip-surface)" }}>

      {/* ── Page header ─────────────────────────────────────────────────── */}
      <div
        className="flex-shrink-0 px-6 py-5"
        style={{
          background: "#FFFFFF",
          borderBottom: "1px solid #E5E7EB",
        }}
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1
              className="text-[22px] font-bold leading-tight"
              style={{ fontFamily: "var(--font-display), sans-serif", color: "#111827" }}
            >
              Automations
            </h1>
            <p className="text-[13px] mt-0.5" style={{ color: "#6B7280" }}>
              {rulesLoading ? "Loading…" : `${rules.length} rules · ${activeCount} active`}
            </p>
          </div>

          <button
            className="flex items-center gap-1.5 px-4 py-2 rounded-xl text-[13px] font-semibold transition-all"
            style={{ background: "#0F766E", color: "#FFFFFF", border: "1px solid #0F766E" }}
            onClick={() => showToast("error", "Automation builder coming soon")}
            onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = "#0d6660"; }}
            onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = "#0F766E"; }}
          >
            <Plus size={14} />
            New automation
          </button>
        </div>

        {/* KPI strip */}
        {!rulesLoading && runs.length > 0 && (
          <div className="flex items-center gap-6 mt-4">
            <div>
              <p className="text-[11px]" style={{ color: "#9CA3AF" }}>Total runs</p>
              <p className="text-[22px] font-bold leading-none mt-0.5"
                style={{ color: "#111827", fontFamily: "var(--font-display), sans-serif" }}>
                {runs.length}
              </p>
            </div>
            <div className="w-px h-8" style={{ background: "#E5E7EB" }} />
            <div>
              <p className="text-[11px]" style={{ color: "#9CA3AF" }}>Succeeded</p>
              <p className="text-[22px] font-bold leading-none mt-0.5"
                style={{ fontFamily: "var(--font-display), sans-serif", color: "#14B8A6" }}>
                {successCount}
              </p>
            </div>
            {failedCount > 0 && (
              <>
                <div className="w-px h-8" style={{ background: "#E5E7EB" }} />
                <div>
                  <p className="text-[11px]" style={{ color: "#9CA3AF" }}>Failed</p>
                  <p className="text-[22px] font-bold leading-none mt-0.5"
                    style={{ fontFamily: "var(--font-display), sans-serif", color: "#f87171" }}>
                    {failedCount}
                  </p>
                </div>
              </>
            )}
          </div>
        )}
      </div>

      {/* ── Content ──────────────────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto haip-scrollbar p-6">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 max-w-6xl">

          {/* ── Rules list ─────────────────────────────────────────────── */}
          <div className="lg:col-span-2 space-y-3">
            <h2
              className="text-[13px] font-bold mb-3"
              style={{ color: "var(--haip-fg)", fontFamily: "var(--font-display), sans-serif" }}
            >
              Rules
            </h2>

            {rulesLoading ? (
              Array.from({ length: 3 }).map((_, i) => <RuleSkeleton key={i} />)
            ) : rules.length === 0 ? (
              <div className="haip-card rounded-2xl p-10 text-center" style={{ border: "1px solid var(--haip-border)" }}>
                <div className="w-14 h-14 rounded-2xl mx-auto mb-4 flex items-center justify-center"
                  style={{ background: "rgba(20,184,166,0.08)" }}>
                  <Zap size={26} style={{ color: "#0F766E" }} />
                </div>
                <p className="font-semibold mb-1" style={{ color: "var(--haip-fg)", fontFamily: "var(--font-display), sans-serif" }}>
                  No automations yet
                </p>
                <p className="text-[13px] mb-5" style={{ color: "var(--haip-fg-muted)" }}>
                  Automate follow-ups, draft replies, and team alerts
                </p>
                <button
                  className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold transition-all"
                  style={{ background: "#14B8A6", color: "#fff" }}
                  onClick={() => showToast("error", "Automation builder coming soon")}
                  onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = "#0F766E"; }}
                  onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = "#14B8A6"; }}
                >
                  <Plus size={15} /> Create first automation
                </button>
              </div>
            ) : (
              rules.map(rule => {
                const trigger = triggerInfo(rule.trigger);
                return (
                  <div
                    key={rule.id}
                    className="haip-card rounded-2xl p-5 transition-all"
                    style={{
                      border: rule.is_active
                        ? "1px solid rgba(20,184,166,0.25)"
                        : "1px solid var(--haip-border)",
                      opacity: rule.is_active ? 1 : 0.65,
                    }}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex items-start gap-3 flex-1 min-w-0">
                        <div
                          className="w-9 h-9 rounded-xl flex items-center justify-center flex-shrink-0 mt-0.5"
                          style={{
                            background: rule.is_active ? "rgba(20,184,166,0.10)" : "rgba(148,163,184,0.08)",
                            color: rule.is_active ? "#0F766E" : "#94a3b8",
                          }}
                        >
                          <Zap size={16} />
                        </div>
                        <div className="min-w-0 flex-1">
                          <p
                            className="font-semibold text-[14px] leading-snug"
                            style={{ fontFamily: "var(--font-display), sans-serif", color: "var(--haip-fg)" }}
                          >
                            {rule.name}
                          </p>
                          {rule.description && (
                            <p className="text-[12px] mt-0.5 line-clamp-2" style={{ color: "var(--haip-fg-muted)" }}>
                              {rule.description}
                            </p>
                          )}

                          {/* trigger → action flow */}
                          <div className="flex items-center gap-1.5 mt-2 flex-wrap">
                            <span
                              className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10.5px] font-medium"
                              style={{ background: "rgba(20,184,166,0.08)", color: "#0F766E" }}
                            >
                              {trigger.icon}
                              {trigger.label}
                            </span>
                            <ChevronRight size={10} style={{ color: "var(--haip-fg-muted)" }} />
                            <span
                              className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10.5px] font-medium"
                              style={{ background: "rgba(245,158,11,0.08)", color: "#B45309" }}
                            >
                              {actionLabel(rule.action)}
                            </span>
                          </div>

                          {/* run count + last run */}
                          <div className="flex items-center gap-4 mt-2">
                            {rule.run_count != null && (
                              <span className="text-[11px]" style={{ color: "var(--haip-fg-muted)" }}>
                                {rule.run_count} runs
                              </span>
                            )}
                            {rule.last_run_at && (
                              <span className="text-[11px]" style={{ color: "var(--haip-fg-muted)" }}>
                                Last: {timeAgo(rule.last_run_at)}
                              </span>
                            )}
                          </div>
                        </div>
                      </div>

                      {/* toggle */}
                      <button
                        onClick={() => toggleMutation.mutate(rule)}
                        disabled={toggleMutation.isPending}
                        className="flex-shrink-0 transition-colors"
                        title={rule.is_active ? "Disable" : "Enable"}
                        style={{ color: rule.is_active ? "#14B8A6" : "#94a3b8" }}
                      >
                        {toggleMutation.isPending ? (
                          <Loader2 size={20} className="animate-spin" />
                        ) : rule.is_active ? (
                          <ToggleRight size={24} />
                        ) : (
                          <ToggleLeft size={24} />
                        )}
                      </button>
                    </div>
                  </div>
                );
              })
            )}
          </div>

          {/* ── Recent runs ────────────────────────────────────────────── */}
          <div className="space-y-3">
            <h2
              className="text-[13px] font-bold mb-3"
              style={{ color: "var(--haip-fg)", fontFamily: "var(--font-display), sans-serif" }}
            >
              Recent runs
            </h2>

            {runsLoading ? (
              Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="haip-card rounded-xl p-3 animate-pulse" style={{ border: "1px solid var(--haip-border)" }}>
                  <div className="h-3 bg-gray-100 rounded w-3/4 mb-2" />
                  <div className="h-2.5 bg-gray-100 rounded w-1/2" />
                </div>
              ))
            ) : runs.length === 0 ? (
              <div className="haip-card rounded-2xl p-6 text-center" style={{ border: "1px solid var(--haip-border)" }}>
                <Settings2 size={22} className="mx-auto mb-2" style={{ color: "var(--haip-fg-muted)" }} />
                <p className="text-[12px]" style={{ color: "var(--haip-fg-muted)" }}>
                  No runs yet — rules haven't triggered
                </p>
              </div>
            ) : (
              <div className="haip-card rounded-2xl overflow-hidden" style={{ border: "1px solid var(--haip-border)" }}>
                <div className="divide-y" style={{ borderColor: "var(--haip-border)" }}>
                  {runs.slice(0, 15).map(run => (
                    <div key={run.id} className="px-4 py-3 flex items-start gap-3">
                      <div className="flex-1 min-w-0">
                        <p className="text-[12px] font-medium truncate" style={{ color: "var(--haip-fg)" }}>
                          {run.automation_name || "Automation"}
                        </p>
                        {run.detail && (
                          <p className="text-[11px] truncate mt-0.5" style={{ color: "var(--haip-fg-muted)" }}>
                            {run.detail}
                          </p>
                        )}
                        <p className="text-[10.5px] mt-0.5" style={{ color: "rgba(100,116,139,0.55)" }}>
                          {timeAgo(run.ran_at)}
                        </p>
                      </div>
                      <StatusBadge status={run.status} />
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Coming soon hint */}
            <div
              className="rounded-2xl p-4 mt-2"
              style={{ background: "rgba(20,184,166,0.06)", border: "1px solid rgba(20,184,166,0.15)" }}
            >
              <p className="text-[11.5px] font-semibold mb-1" style={{ color: "#0F766E" }}>
                Coming soon
              </p>
              <p className="text-[11px]" style={{ color: "#0F766E", opacity: 0.7 }}>
                Visual rule builder, conditional branching, and multi-step workflows
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Toast */}
      {toastMsg && (
        <div
          className="fixed bottom-5 right-5 z-50 px-4 py-3 rounded-xl text-sm font-medium shadow-lg"
          style={{
            background: toastMsg.type === "success" ? "#0F766E" : "#dc2626",
            color: "#fff",
          }}
        >
          {toastMsg.text}
        </div>
      )}
    </div>
  );
}
