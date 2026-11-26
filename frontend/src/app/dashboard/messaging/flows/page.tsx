"use client";
// WhatsApp Flow Builder: the list of flows (activate, logs, delete) and the drag-and-drop canvas editor
// (components/flows/canvas, spec docs/whatsapp/FLOW_CANVAS_SPEC.md).
import { useState } from "react";
import { AutomationsNav } from "@/components/automations/AutomationsNav";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Play, Pause, Trash2, X, CheckCircle2, AlertCircle, Zap, Settings, History } from "@/lib/icons";
import { GitBranch } from "lucide-react";
import { cn } from "@/lib/utils";
import api from "@/lib/api";
import { Skeleton } from "@/components/ui/skeleton";
import { FlowCanvasEditor, type FlowRecord } from "@/components/flows/canvas/FlowCanvasEditor";
import { TRIGGER_OPTIONS, triggerOf } from "@/components/flows/canvas/flowModel";
import { blankFlow } from "@/components/flows/canvas/flowTemplates";

interface Flow extends FlowRecord { id: string; created_at: string | null }

// ─── Toast ────────────────────────────────────────────────────────────────────

function Toast({ msg, type, onClose }: { msg: string; type: "success" | "error"; onClose: () => void }) {
  return (
    <div className={cn("fixed bottom-6 right-6 z-50 flex items-center gap-3 px-4 py-3 rounded-xl shadow-lg border text-sm font-medium max-w-sm",
      type === "success" ? "bg-[var(--haip-status-success-bg)] text-[var(--haip-status-success-fg)] border-[var(--haip-status-success-border)]" : "bg-[var(--haip-status-danger-bg)] text-[var(--haip-status-danger-fg)] border-[var(--haip-status-danger-border)]")}>
      {type === "success" ? <CheckCircle2 size={15} className="text-[var(--haip-status-success-fg)]" /> : <AlertCircle size={15} className="text-[var(--haip-status-danger-fg)]" />}
      <span className="flex-1">{msg}</span>
      <button onClick={onClose}><X size={13} className="opacity-60" /></button>
    </div>
  );
}

// ─── Main page (flow list) ────────────────────────────────────────────────────

export default function FlowsPage() {
  const queryClient = useQueryClient();
  const [editingFlow, setEditingFlow] = useState<FlowRecord | null>(null);
  const newFlow = () => setEditingFlow({ name: "New flow", description: null, is_active: false, trigger: null, ...blankFlow() });
  const [viewingLogsFlow, setViewingLogsFlow] = useState<Flow | null>(null);
  const [toast, setToast] = useState<{ msg: string; type: "success" | "error" } | null>(null);

  const showToast = (msg: string, type: "success" | "error") => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 4000);
  };

  const { data: flows = [], isLoading, isError, refetch, isFetching } = useQuery<Flow[]>({
    queryKey: ["wa-flows"],
    queryFn: () => api.get("/messaging/flows").then(r => r.data),
    staleTime: 30_000,
  });

  const toggleMutation = useMutation({
    mutationFn: (id: string) => api.patch(`/messaging/flows/${id}/activate`),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["wa-flows"] }); showToast("Flow updated.", "success"); },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.delete(`/messaging/flows/${id}`),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["wa-flows"] }); showToast("Flow deleted.", "success"); },
  });

  // If editing a flow, show the editor full-page
  if (editingFlow) {
    return (
      <FlowCanvasEditor
        flow={editingFlow}
        onBack={() => setEditingFlow(null)}
        onSaved={() => { queryClient.invalidateQueries({ queryKey: ["wa-flows"] }); }}
        key={editingFlow.id ?? "new"}
      />
    );
  }

  return (
    <div className="h-full flex flex-col">
      <div className="px-6 py-5 bg-white border-b border-[var(--haip-border)] flex-shrink-0">
        <AutomationsNav className="mb-4" />
        <div className="flex items-center justify-between">
          <div>
            <h1 className="haip-page-title">Flow Builder</h1>
            <p className="text-sm text-[var(--haip-fg-subtle)] mt-0.5">Automate multi-step WhatsApp conversations triggered by guest actions.</p>
          </div>
          <button onClick={newFlow}
            className="flex items-center gap-2 bg-primary text-white px-4 py-2.5 rounded-xl text-sm font-semibold hover:bg-primary transition-colors shadow-sm shadow-[color-mix(in_srgb,var(--primary)_18%,transparent)]">
            <Plus size={15} /> New flow
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        {isError ? (
          <div className="py-20 text-center">
            <AlertCircle size={32} className="text-[var(--haip-status-danger-fg)] mx-auto mb-3" />
            <p className="text-sm text-[var(--haip-fg-2)] font-medium">Couldn't load flows</p>
            <p className="text-xs text-[var(--haip-fg-subtle)] mt-1">The server didn't respond — this isn't your saved flow list.</p>
            <button
              onClick={() => refetch()}
              disabled={isFetching}
              className="mt-4 text-xs font-semibold text-primary border border-[color-mix(in_srgb,var(--primary)_25%,transparent)] bg-[var(--haip-primary-tint)] hover:bg-[var(--haip-primary-tint)] px-3 py-1.5 rounded-lg transition-colors"
            >
              {isFetching ? "Retrying…" : "Retry"}
            </button>
          </div>
        ) : isLoading ? (
          <div className="space-y-3">{Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-24 rounded-2xl" />)}</div>
        ) : flows.length === 0 ? (
          <div className="py-20 text-center">
            <GitBranch size={40} className="text-[var(--haip-fg-subtle)]/70 mx-auto mb-3" />
            <p className="text-sm text-[var(--haip-fg-subtle)] font-medium">No flows yet</p>
            <p className="text-xs text-[var(--haip-fg-subtle)] mt-1">Build automated message sequences triggered by guest actions.</p>
            <button onClick={newFlow}
              className="mt-4 flex items-center gap-2 bg-primary text-white px-4 py-2 rounded-xl text-sm font-medium hover:bg-primary transition-colors mx-auto">
              <Plus size={14} /> Create flow
            </button>
          </div>
        ) : (
          <div className="space-y-3">
            {flows.map(flow => {
              const stepCount = flow.nodes.length;
              const triggerNode = flow.nodes.find(n => n.type === "trigger");
              const trig = triggerNode ? triggerOf(triggerNode) : "";
              const triggerLabel = trig === "keyword" ? `Keyword: ${(triggerNode?.keywords ?? []).join(", ") || "none"}`
                : TRIGGER_OPTIONS.find(t => t.value === trig)?.label ?? (trig || "No trigger");

              return (
                <div key={flow.id} className="haip-card p-5 hover:shadow-sm transition-shadow">
                  <div className="flex items-start gap-4">
                    <div className={cn("w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0",
                      flow.is_active ? "bg-[var(--haip-primary-tint)]" : "bg-[var(--haip-status-neutral-bg)]")}>
                      <GitBranch size={18} className={flow.is_active ? "text-primary" : "text-[var(--haip-fg-subtle)]"} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <h3 className="text-sm font-bold text-[var(--haip-fg)]">{flow.name}</h3>
                        <span className={cn("inline-flex items-center gap-1 text-[11.5px] font-semibold px-2 py-0.5 rounded-full border",
                          flow.is_active ? "bg-[var(--haip-primary-tint)] text-primary border-[color-mix(in_srgb,var(--primary)_25%,transparent)]" : "bg-[var(--haip-surface)] text-[var(--haip-fg-subtle)] border-[var(--haip-border)]")}>
                          {flow.is_active ? <><Play size={8} /> Active</> : <><Pause size={8} /> Inactive</>}
                        </span>
                      </div>
                      {flow.description && <p className="text-xs text-[var(--haip-fg-subtle)] mb-1">{flow.description}</p>}
                      <div className="flex items-center gap-3 text-[11px] text-[var(--haip-fg-subtle)] flex-wrap">
                        <span className="flex items-center gap-1"><Zap size={10} /> Trigger: {triggerLabel}</span>
                        <span className="flex items-center gap-1"><GitBranch size={10} /> {stepCount} steps</span>
                      </div>
                    </div>
                    <div className="flex items-center gap-2 flex-shrink-0">
                      <button onClick={() => setViewingLogsFlow(flow)}
                        className="flex items-center gap-1.5 text-xs border border-[var(--haip-border)] text-[var(--haip-fg-muted)] px-3 py-1.5 rounded-lg hover:bg-[var(--haip-surface)] transition-colors font-medium">
                        <History size={12} /> Logs
                      </button>
                      <button onClick={() => setEditingFlow(flow)}
                        className="flex items-center gap-1.5 text-xs border border-[var(--haip-border)] text-[var(--haip-fg-muted)] px-3 py-1.5 rounded-lg hover:bg-[var(--haip-surface)] transition-colors font-medium">
                        <Settings size={12} /> Edit
                      </button>
                      <button onClick={() => toggleMutation.mutate(flow.id)}
                        className={cn("text-xs px-3 py-1.5 rounded-lg font-medium transition-colors border",
                          flow.is_active ? "text-[var(--haip-status-warning-fg)] border-[var(--haip-status-warning-border)] hover:bg-[var(--haip-status-warning-bg)]" : "text-primary border-[color-mix(in_srgb,var(--primary)_25%,transparent)] hover:bg-[var(--haip-primary-tint)]")}>
                        {flow.is_active ? "Pause" : "Activate"}
                      </button>
                      <button onClick={() => { if (confirm("Delete this flow?")) deleteMutation.mutate(flow.id); }}
                        className="text-[var(--haip-fg-subtle)] hover:text-[var(--haip-status-danger-fg)] transition-colors p-1.5 rounded-lg hover:bg-[var(--haip-status-danger-bg)]">
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* How it works */}
        <div className="mt-8 haip-card p-5">
          <p className="text-sm font-bold text-[var(--haip-fg)] mb-3">How Flow Builder works</p>
          <div className="grid grid-cols-1 sm:grid-cols-4 gap-3">
            {[
              { step: "1", title: "Set a trigger", desc: "Choose what event starts the flow (opt-in, keyword, check-in…)" },
              { step: "2", title: "Add blocks", desc: "Drag messages, buttons, questions and actions onto the canvas and connect them" },
              { step: "3", title: "Activate", desc: "Turn on the flow — it runs automatically for new contacts" },
              { step: "4", title: "Measure", desc: "Track delivery, read rates, and drop-off per step" },
            ].map(s => (
              <div key={s.step} className="flex gap-3">
                <div className="w-6 h-6 rounded-full bg-[var(--haip-primary-tint)] text-primary flex items-center justify-center text-[11px] font-bold flex-shrink-0 mt-0.5">{s.step}</div>
                <div>
                  <p className="text-xs font-semibold text-[var(--haip-fg)]">{s.title}</p>
                  <p className="text-[11.5px] text-[var(--haip-fg-subtle)] leading-relaxed mt-0.5">{s.desc}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {viewingLogsFlow && (
        <FlowLogsModal flow={viewingLogsFlow} onClose={() => setViewingLogsFlow(null)} />
      )}
      {toast && <Toast msg={toast.msg} type={toast.type} onClose={() => setToast(null)} />}
    </div>
  );
}

// ─── Flow execution logs (T2.3) ────────────────────────────────────────────────

interface FlowRun {
  id: string;
  guest_id: string;
  node_id: string;
  node_type: string;
  status: string;
  detail: string | null;
  error: string | null;
  ran_at: string | null;
}

const RUN_STATUS_STYLE: Record<string, string> = {
  success: "bg-[var(--haip-primary-tint)] text-primary border-[color-mix(in_srgb,var(--primary)_25%,transparent)]",
  failed: "bg-[var(--haip-status-danger-bg)] text-[var(--haip-status-danger-fg)] border-[var(--haip-status-danger-border)]",
  waiting: "bg-[var(--haip-status-warning-bg)] text-[var(--haip-status-warning-fg)] border-[var(--haip-status-warning-border)]",
  skipped: "bg-[var(--haip-surface)] text-[var(--haip-fg-subtle)] border-[var(--haip-border)]",
};

function FlowLogsModal({ flow, onClose }: { flow: Flow; onClose: () => void }) {
  const { data: runs = [], isLoading, isError } = useQuery<FlowRun[]>({
    queryKey: ["wa-flow-runs", flow.id],
    queryFn: () => api.get(`/messaging/flows/${flow.id}/runs`).then(r => r.data),
    staleTime: 15_000,
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-2xl max-h-[80vh] flex flex-col" style={{ maxHeight: "calc(100dvh - 2rem)" }}>
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--haip-border)]">
          <div>
            <h2 className="text-sm font-bold text-[var(--haip-fg)]">Execution Logs</h2>
            <p className="text-xs text-[var(--haip-fg-subtle)]">{flow.name}</p>
          </div>
          <button onClick={onClose} className="text-[var(--haip-fg-subtle)] hover:text-[var(--haip-fg-muted)]"><X size={16} /></button>
        </div>
        <div className="flex-1 overflow-y-auto p-4">
          {isLoading ? (
            <div className="space-y-2">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-12 rounded-lg" />)}</div>
          ) : isError ? (
            <p className="text-sm text-[var(--haip-status-danger-fg)] text-center py-8">Couldn't load logs.</p>
          ) : runs.length === 0 ? (
            <div className="text-center py-10">
              <History size={32} className="text-[var(--haip-fg-subtle)]/70 mx-auto mb-2" />
              <p className="text-sm text-[var(--haip-fg-subtle)] font-medium">No runs yet</p>
              <p className="text-xs text-[var(--haip-fg-subtle)] mt-1">
                {flow.is_active ? "Nothing has triggered this flow yet." : "Activate this flow to start seeing execution logs here."}
              </p>
            </div>
          ) : (
            <div className="space-y-1.5">
              {runs.map(run => (
                <div key={run.id} className="flex items-center gap-3 px-3 py-2 rounded-lg border border-[var(--haip-border)] text-xs">
                  <span className={cn("px-2 py-0.5 rounded-full border font-medium flex-shrink-0", RUN_STATUS_STYLE[run.status] ?? "bg-[var(--haip-surface)] text-[var(--haip-fg-subtle)] border-[var(--haip-border)]")}>
                    {run.status}
                  </span>
                  <span className="text-[var(--haip-fg-2)] font-medium flex-shrink-0">{run.node_type}</span>
                  <span className="text-[var(--haip-fg-subtle)] truncate flex-1">{run.error || run.detail || "—"}</span>
                  <span className="text-[var(--haip-fg-subtle)]/70 flex-shrink-0">{run.ran_at ? new Date(run.ran_at).toLocaleString("en-IN") : ""}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
