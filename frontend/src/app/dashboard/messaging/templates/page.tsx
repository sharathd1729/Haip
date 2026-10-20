"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  MessageSquare, Plus, Send, Trash2, CheckCircle2, Clock, XCircle, FileText, Loader2, X, AlertCircle, Eye,
  Tag, Pencil, Copy, RotateCcw, Image as ImageIcon, RefreshCw,
} from "@/lib/icons";
import { cn } from "@/lib/utils";
import api from "@/lib/api";
import { Skeleton } from "@/components/ui/skeleton";
import { TemplateEditor } from "@/components/messaging/TemplateEditor";
import { WhatsAppPreview } from "@/components/messaging/WhatsAppPreview";
import { formFromTemplate, type Template } from "@/components/messaging/templateModel";

// ─── Constants ────────────────────────────────────────────────────────────────

type Status = Template["status"];

const STATUS_CFG: Record<Status, { label: string; cls: string; icon: React.ReactNode }> = {
  draft:             { label: "Draft",            cls: "bg-[var(--haip-surface)] text-[var(--haip-fg-muted)] border-[var(--haip-border)]",    icon: <FileText size={10} /> },
  pending:           { label: "In review",        cls: "bg-amber-50 text-amber-700 border-amber-200", icon: <Clock size={10} /> },
  approved:          { label: "Approved",         cls: "bg-green-50 text-green-700 border-green-200", icon: <CheckCircle2 size={10} /> },
  rejected:          { label: "Rejected",         cls: "bg-red-50 text-red-600 border-red-200",       icon: <XCircle size={10} /> },
  submission_failed: { label: "Couldn't submit",  cls: "bg-red-50 text-red-600 border-red-200",       icon: <AlertCircle size={10} /> },
};

const FILTERS = ["all", "draft", "pending", "approved", "rejected"] as const;

// Templates Meta isn't holding: safe to change and (re)submit.
const EDITABLE: Status[] = ["draft", "rejected", "submission_failed"];

function extractBody(t: Template): string {
  return t.components.find(c => c.type === "BODY")?.text ?? "—";
}

function headerFormat(t: Template): string | null {
  const fmt = t.components.find(c => c.type === "HEADER")?.format?.toUpperCase();
  return fmt && fmt !== "TEXT" ? fmt.toLowerCase() : null;
}

// A document header with no sample file yet: Submit first asks HAIP to attach a generated sample PDF
// (a dummy quote / invoice / receipt, marked SAMPLE), since Meta's review needs one.
function needsSampleDoc(t: Template): boolean {
  const h = t.components.find(c => c.type === "HEADER");
  return h?.format?.toUpperCase() === "DOCUMENT" && !h.example?.header_handle?.[0]?.trim();
}

// Mirrors wa_template_sample_doc.document_kind on the backend.
function sampleKind(name: string): string {
  const n = name.toLowerCase();
  if (n.includes("quote")) return "quote";
  if (n.includes("receipt") || n.includes("payment_received")) return "receipt";
  return "invoice";
}

// ─── Toast ────────────────────────────────────────────────────────────────────

function Toast({ msg, type, onClose }: { msg: string; type: "success" | "error"; onClose: () => void }) {
  return (
    <div className={cn(
      "fixed bottom-6 right-6 z-[60] flex items-center gap-3 px-4 py-3 rounded-xl shadow-lg border text-sm font-medium max-w-sm",
      type === "success" ? "bg-green-50 text-green-800 border-green-200" : "bg-red-50 text-red-800 border-red-200"
    )}>
      {type === "success" ? <CheckCircle2 size={15} className="text-green-600" /> : <AlertCircle size={15} className="text-red-600" />}
      <span className="flex-1">{msg}</span>
      <button onClick={onClose} aria-label="Dismiss"><X size={13} className="opacity-60" /></button>
    </div>
  );
}

// ─── Read-only preview ────────────────────────────────────────────────────────

function PreviewModal({ template, onClose }: { template: Template; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-sm overflow-hidden" onClick={e => e.stopPropagation()} role="dialog" aria-label="Template preview">
        <div className="px-5 pt-4 pb-3 border-b border-[var(--haip-border)] flex items-center justify-between">
          <div className="min-w-0">
            <p className="text-sm font-bold text-[var(--haip-fg)] font-mono truncate">{template.name}</p>
            <p className="text-[10px] text-[var(--haip-fg-subtle)] capitalize">{template.category.toLowerCase()} · {template.language.toUpperCase()}</p>
          </div>
          <button onClick={onClose} aria-label="Close"><X size={16} className="text-[var(--haip-fg-subtle)] hover:text-[var(--haip-fg-muted)]" /></button>
        </div>
        <div className="p-4">
          <WhatsAppPreview form={formFromTemplate(template)} />
          {template.rejection_reason && (
            <p className="mt-3 text-[11px] text-red-600 flex items-start gap-1.5"><AlertCircle size={12} className="mt-0.5 flex-shrink-0" />{template.rejection_reason}</p>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function TemplatesPage() {
  const queryClient = useQueryClient();
  const [editor, setEditor] = useState<{ template?: Template; duplicateOf?: Template } | null>(null);
  const [previewing, setPreviewing] = useState<Template | null>(null);
  const [toast, setToast] = useState<{ msg: string; type: "success" | "error" } | null>(null);
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>("all");

  const showToast = (msg: string, type: "success" | "error") => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 4000);
  };
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["wa-templates"] });

  const { data: templates = [], isLoading, isError, refetch, isFetching } = useQuery<Template[]>({
    queryKey: ["wa-templates"],
    queryFn: () => api.get("/messaging/templates").then(r => r.data),
    staleTime: 30_000,
  });

  const [syncNote, setSyncNote] = useState<{ ok: boolean; text: string } | null>(null);
  const syncMutation = useMutation({
    mutationFn: () => api.post("/messaging/templates/sync").then(r => r.data),
    onSuccess: (d: { added: number; updated: number; removed: number }) => {
      refresh();
      setSyncNote({ ok: true, text: d.added + d.updated + d.removed === 0 ? "Already matches WhatsApp Manager."
        : `Synced: ${d.added} added, ${d.updated} updated, ${d.removed} removed.` });
    },
    onError: (e: unknown) => setSyncNote({ ok: false, text: (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "Couldn't sync with Meta." }),
  });

  const submitMutation = useMutation({
    mutationFn: async (tmpl: Template) => {
      if (needsSampleDoc(tmpl)) await api.post(`/messaging/templates/${tmpl.id}/sample-document`);
      return api.post(`/messaging/templates/${tmpl.id}/submit`);
    },
    onSuccess: (res) => {
      refresh();
      if (res.data?.status === "pending") {
        showToast("Submitted to Meta for review.", "success");
      } else {
        // The endpoint answers 200 even when Meta refused it or the request
        // itself failed -- that is not a success.
        showToast(res.data?.rejection_reason || "Submission failed.", "error");
      }
    },
    onError: (err) => {
      refresh();
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      showToast(msg || "Submission failed.", "error");
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.delete(`/messaging/templates/${id}`),
    onSuccess: () => { refresh(); showToast("Template deleted.", "success"); },
    onError: () => showToast("Delete failed.", "error"),
  });

  const filtered = filter === "all" ? templates : templates.filter(t => t.status === filter || (filter === "rejected" && t.status === "submission_failed"));
  const countOf = (f: (typeof FILTERS)[number]) => templates.filter(t => t.status === f || (f === "rejected" && t.status === "submission_failed")).length;

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="px-6 py-5 bg-white border-b border-[var(--haip-border)] flex-shrink-0">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h1 className="haip-page-title">Message Templates</h1>
            <p className="text-sm text-[var(--haip-fg-subtle)] mt-0.5">Create and manage WhatsApp Business templates for campaigns and automated messages.</p>
          </div>
          <div className="flex items-center gap-2">
          <button onClick={() => { setSyncNote(null); syncMutation.mutate(); }} disabled={syncMutation.isPending}
            className="flex items-center gap-2 border border-[var(--haip-border)] bg-white text-[var(--haip-fg-2)] px-3.5 py-2.5 rounded-xl text-sm font-medium hover:bg-[var(--haip-surface)] disabled:opacity-60">
            {syncMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />} Sync from Meta
          </button>
          <button onClick={() => setEditor({})}
            className="flex items-center gap-2 bg-primary text-white px-4 py-2.5 rounded-xl text-sm font-semibold hover:bg-primary transition-colors shadow-sm shadow-[color-mix(in_srgb,var(--primary)_18%,transparent)]">
            <Plus size={15} /> New template
          </button>
          </div>
        </div>
        {syncNote && <p className={cn("text-xs mb-3", syncNote.ok ? "text-green-700" : "text-red-600")} role="status">{syncNote.text}</p>}

        <div className="flex gap-1 flex-wrap">
          {FILTERS.map(f => (
            <button key={f} onClick={() => setFilter(f)}
              className={cn("px-3 py-1.5 rounded-lg text-xs font-medium capitalize transition-colors",
                filter === f ? "bg-primary text-white" : "text-[var(--haip-fg-subtle)] hover:bg-[var(--haip-status-neutral-bg)]")}>
              {f === "pending" ? "In review" : f} {f !== "all" && `(${countOf(f)})`}
            </button>
          ))}
        </div>
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto p-6">
        {isError ? (
          <div className="py-20 text-center">
            <AlertCircle size={32} className="text-red-300 mx-auto mb-3" />
            <p className="text-sm text-[var(--haip-fg-2)] font-medium">Couldn't load templates</p>
            <p className="text-xs text-[var(--haip-fg-subtle)] mt-1">The server didn't respond — this isn't your saved template list.</p>
            <button onClick={() => refetch()} disabled={isFetching}
              className="mt-4 text-xs font-semibold text-primary border border-[color-mix(in_srgb,var(--primary)_25%,transparent)] bg-[var(--haip-primary-tint)] hover:bg-[var(--haip-primary-tint)] px-3 py-1.5 rounded-lg transition-colors">
              {isFetching ? "Retrying…" : "Retry"}
            </button>
          </div>
        ) : isLoading ? (
          <div className="space-y-3">{Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-24 rounded-2xl" />)}</div>
        ) : filtered.length === 0 ? (
          <div className="py-20 text-center">
            <MessageSquare size={40} className="text-[var(--haip-fg-subtle)]/70 mx-auto mb-3" />
            <p className="text-sm text-[var(--haip-fg-subtle)] font-medium">No templates here</p>
            <p className="text-xs text-[var(--haip-fg-subtle)] mt-1">Create your first template to start sending WhatsApp messages at scale.</p>
            <button onClick={() => setEditor({})}
              className="mt-4 flex items-center gap-2 bg-primary text-white px-4 py-2 rounded-xl text-sm font-medium hover:bg-primary transition-colors mx-auto">
              <Plus size={14} /> Create template
            </button>
          </div>
        ) : (
          <div className="space-y-3">
            {filtered.map(tmpl => {
              const sc = STATUS_CFG[tmpl.status] ?? STATUS_CFG.draft;
              const editable = EDITABLE.includes(tmpl.status);
              const media = headerFormat(tmpl);
              const submitting = submitMutation.isPending && submitMutation.variables?.id === tmpl.id;
              return (
                <div key={tmpl.id} className="haip-card p-4 hover:shadow-sm transition-shadow">
                  <div className="flex items-start gap-4">
                    {media === "image" && tmpl.header_media_url ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={tmpl.header_media_url} alt="" className="w-10 h-10 rounded-xl object-cover flex-shrink-0" />
                    ) : (
                      <div className="w-10 h-10 rounded-xl bg-green-50 flex items-center justify-center flex-shrink-0">
                        {media ? <ImageIcon size={18} className="text-green-600" /> : <MessageSquare size={18} className="text-green-600" />}
                      </div>
                    )}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap mb-1">
                        <span className="text-sm font-bold text-[var(--haip-fg)] font-mono">{tmpl.name}</span>
                        <span className={cn("inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full border", sc.cls)}>
                          {sc.icon} {sc.label}
                        </span>
                        <span className="text-[10px] bg-[var(--haip-status-neutral-bg)] text-[var(--haip-fg-muted)] px-2 py-0.5 rounded-full capitalize">{tmpl.category.toLowerCase()}</span>
                        <span className="text-[10px] text-[var(--haip-fg-subtle)]">{tmpl.language.toUpperCase()}</span>
                        {media && <span className="text-[10px] bg-blue-50 text-blue-700 px-2 py-0.5 rounded-full capitalize">{media} header</span>}
                      </div>
                      <p className="text-xs text-[var(--haip-fg-subtle)] truncate leading-relaxed">{extractBody(tmpl)}</p>
                      {tmpl.rejection_reason && <p className="text-[10px] text-red-500 mt-1">Reason: {tmpl.rejection_reason}</p>}
                      {tmpl.meta_template_id && <p className="text-[10px] text-[var(--haip-fg-subtle)] mt-0.5 font-mono">Meta ID: {tmpl.meta_template_id}</p>}
                    </div>
                    <div className="flex items-center gap-1.5 flex-shrink-0 flex-wrap justify-end">
                      <button onClick={() => setPreviewing(tmpl)} title="Preview" aria-label="Preview"
                        className="text-[var(--haip-fg-subtle)] hover:text-primary transition-colors p-1.5 rounded-lg hover:bg-[var(--haip-primary-tint)]"><Eye size={14} /></button>
                      {editable && (
                        <button onClick={() => setEditor({ template: tmpl })} title="Edit" aria-label="Edit"
                          className="text-[var(--haip-fg-subtle)] hover:text-primary transition-colors p-1.5 rounded-lg hover:bg-[var(--haip-primary-tint)]"><Pencil size={14} /></button>
                      )}
                      <button onClick={() => setEditor({ duplicateOf: tmpl })} title="Duplicate" aria-label="Duplicate"
                        className="text-[var(--haip-fg-subtle)] hover:text-primary transition-colors p-1.5 rounded-lg hover:bg-[var(--haip-primary-tint)]"><Copy size={14} /></button>
                      {editable && (
                        <button onClick={() => submitMutation.mutate(tmpl)} disabled={submitMutation.isPending}
                          className="flex items-center gap-1.5 text-xs bg-primary text-white px-3 py-1.5 rounded-lg font-medium hover:bg-primary transition-colors disabled:opacity-50">
                          {submitting ? <Loader2 size={11} className="animate-spin" /> : tmpl.status === "draft" ? <Send size={11} /> : <RotateCcw size={11} />}
                          {tmpl.status === "draft" ? "Submit" : "Resubmit"}
                        </button>
                      )}
                      <button onClick={() => { if (confirm("Delete this template?")) deleteMutation.mutate(tmpl.id); }} title="Delete" aria-label="Delete"
                        className="text-[var(--haip-fg-subtle)] hover:text-red-500 transition-colors p-1.5 rounded-lg hover:bg-red-50"><Trash2 size={14} /></button>
                    </div>
                  </div>
                  {editable && needsSampleDoc(tmpl) && (
                    <p className="text-[11px] text-[var(--haip-fg-subtle)] mt-2">No sample PDF yet. Submit adds a sample {sampleKind(tmpl.name)} (dummy guest, marked SAMPLE).</p>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {/* Info card */}
        <div className="mt-8 haip-card p-5 flex gap-4">
          <div className="w-10 h-10 rounded-xl bg-amber-50 flex items-center justify-center flex-shrink-0">
            <Tag size={18} className="text-amber-600" />
          </div>
          <div>
            <p className="text-sm font-semibold text-[var(--haip-fg)] mb-1">How template approval works</p>
            <ol className="text-xs text-[var(--haip-fg-subtle)] space-y-1 list-decimal list-inside leading-relaxed">
              <li>Create your template — add an image, video or PDF header, variables like {`{{1}}`}, and buttons.</li>
              <li>Click <strong>Submit</strong> — this sends it to Meta for review (usually 24–48 hours).</li>
              <li>If Meta rejects it, <strong>Edit</strong> it and <strong>Resubmit</strong>. An approved template is locked; <strong>Duplicate</strong> it to change it.</li>
              <li>Once approved, use it in campaigns or automated concierge replies. Marketing templates require opt-in.</li>
            </ol>
          </div>
        </div>
      </div>

      {editor && (
        <TemplateEditor
          template={editor.template}
          duplicateOf={editor.duplicateOf}
          onClose={() => setEditor(null)}
          onSaved={(msg) => { refresh(); showToast(msg, "success"); }}
        />
      )}
      {previewing && <PreviewModal template={previewing} onClose={() => setPreviewing(null)} />}
      {toast && <Toast msg={toast.msg} type={toast.type} onClose={() => setToast(null)} />}
    </div>
  );
}
