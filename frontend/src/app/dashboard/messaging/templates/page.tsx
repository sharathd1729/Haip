"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { MessageSquare, Plus, Send, Trash2, CheckCircle2, Clock, XCircle, FileText, Loader2, X, AlertCircle, Eye, ChevronRight, Tag } from "@/lib/icons";
import { cn } from "@/lib/utils";
import api from "@/lib/api";
import { Skeleton } from "@/components/ui/skeleton";

// ─── Types ─────────────────────────────────────────────────────────────────────

interface Template {
  id: string;
  name: string;
  language: string;
  category: string;
  status: "draft" | "pending" | "approved" | "rejected";
  components: TemplateComponent[];
  meta_template_id: string | null;
  rejection_reason: string | null;
  created_at: string | null;
}

interface TemplateComponent {
  type: string;
  format?: string;
  text?: string;
  buttons?: { type: string; text: string; url?: string; phone_number?: string }[];
}

// ─── Constants ────────────────────────────────────────────────────────────────

const STATUS_CFG = {
  draft:    { label: "Draft",    cls: "bg-gray-50 text-gray-600 border-gray-200",   icon: <FileText size={10} /> },
  pending:  { label: "Pending",  cls: "bg-amber-50 text-amber-700 border-amber-200", icon: <Clock size={10} /> },
  approved: { label: "Approved", cls: "bg-green-50 text-green-700 border-green-200", icon: <CheckCircle2 size={10} /> },
  rejected: { label: "Rejected", cls: "bg-red-50 text-red-600 border-red-200",       icon: <XCircle size={10} /> },
};

const LANGUAGES = [
  { value: "en", label: "English" },
  { value: "en_US", label: "English (US)" },
  { value: "hi", label: "Hindi" },
  { value: "te", label: "Telugu" },
  { value: "ta", label: "Tamil" },
  { value: "kn", label: "Kannada" },
  { value: "ml", label: "Malayalam" },
];

// ─── Helpers ─────────────────────────────────────────────────────────────────

function extractBody(components: TemplateComponent[]): string {
  return components.find(c => c.type === "BODY")?.text ?? "—";
}

function extractHeader(components: TemplateComponent[]): string | null {
  const h = components.find(c => c.type === "HEADER");
  return h?.text ?? null;
}

// ─── Toast ────────────────────────────────────────────────────────────────────

function Toast({ msg, type, onClose }: { msg: string; type: "success" | "error"; onClose: () => void }) {
  return (
    <div className={cn(
      "fixed bottom-6 right-6 z-50 flex items-center gap-3 px-4 py-3 rounded-xl shadow-lg border text-sm font-medium max-w-sm",
      type === "success" ? "bg-green-50 text-green-800 border-green-200" : "bg-red-50 text-red-800 border-red-200"
    )}>
      {type === "success" ? <CheckCircle2 size={15} className="text-green-600" /> : <AlertCircle size={15} className="text-red-600" />}
      <span className="flex-1">{msg}</span>
      <button onClick={onClose}><X size={13} className="opacity-60" /></button>
    </div>
  );
}

// ─── Create Template Modal ────────────────────────────────────────────────────

function CreateTemplateModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [step, setStep] = useState<"info" | "body" | "preview">("info");
  const [form, setForm] = useState({
    name: "",
    language: "en",
    category: "MARKETING",
    header: "",
    body: "",
    footer: "",
    ctaText: "",
    ctaUrl: "",
    ctaPhone: "",
    ctaType: "none" as "none" | "url" | "phone",
  });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const buildComponents = (): TemplateComponent[] => {
    const comps: TemplateComponent[] = [];
    if (form.header) comps.push({ type: "HEADER", format: "TEXT", text: form.header });
    if (form.body) comps.push({ type: "BODY", text: form.body });
    if (form.footer) comps.push({ type: "FOOTER", text: form.footer });
    if (form.ctaType !== "none" && form.ctaText) {
      comps.push({
        type: "BUTTONS",
        buttons: [{
          type: form.ctaType === "url" ? "URL" : "PHONE_NUMBER",
          text: form.ctaText,
          ...(form.ctaType === "url" ? { url: form.ctaUrl } : { phone_number: form.ctaPhone }),
        }],
      });
    }
    return comps;
  };

  const handleCreate = async () => {
    if (!form.name.trim() || !form.body.trim()) { setError("Template name and body are required."); return; }
    setError("");
    setSubmitting(true);
    try {
      await api.post("/messaging/templates", {
        name: form.name,
        language: form.language,
        category: form.category,
        components: buildComponents(),
      });
      onCreated();
      onClose();
    } catch (err: any) {
      // Surface the status when the backend gives no `detail` (a 500 from
      // response-model validation did exactly that, leaving the user with a
      // bare "Failed to create template." and nothing to act on).
      const detail = err?.response?.data?.detail;
      const status = err?.response?.status;
      setError(
        detail
          ? String(detail)
          : status
          ? `Failed to create template (HTTP ${status}). Please retry — if it persists, check the server logs.`
          : "Failed to create template — could not reach the server."
      );
    } finally {
      setSubmitting(false);
    }
  };

  const previewComponents = buildComponents();

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-2xl mx-4 overflow-hidden flex flex-col max-h-[90vh]">
        {/* Header */}
        <div className="px-6 pt-6 pb-4 border-b border-gray-100 flex-shrink-0 flex items-center justify-between">
          <div>
            <h2 className="text-base font-bold text-gray-900">Create message template</h2>
            <p className="text-xs text-gray-400 mt-0.5">Templates must be approved by Meta before sending.</p>
          </div>
          <button onClick={onClose}><X size={18} className="text-gray-400 hover:text-gray-600" /></button>
        </div>

        {/* Step indicator */}
        <div className="px-6 py-3 bg-gray-50 border-b border-gray-100 flex-shrink-0 flex items-center gap-2">
          {(["info", "body", "preview"] as const).map((s, i) => (
            <div key={s} className="flex items-center gap-2">
              <div className={cn("w-6 h-6 rounded-full flex items-center justify-center text-[11px] font-bold",
                step === s ? "bg-teal-500 text-white" : (["info", "body", "preview"].indexOf(step) > i) ? "bg-teal-100 text-teal-700" : "bg-gray-200 text-gray-500"
              )}>{i + 1}</div>
              <span className={cn("text-xs capitalize", step === s ? "font-semibold text-gray-800" : "text-gray-400")}>{s}</span>
              {i < 2 && <ChevronRight size={12} className="text-gray-300" />}
            </div>
          ))}
        </div>

        <div className="flex-1 overflow-y-auto">
          {/* Step 1: Info */}
          {step === "info" && (
            <div className="p-6 space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="text-xs font-semibold text-gray-700 block mb-1.5">Template name <span className="text-red-500">*</span></label>
                  <input
                    value={form.name}
                    onChange={e => setForm(f => ({ ...f, name: e.target.value.toLowerCase().replace(/\s+/g, "_") }))}
                    placeholder="booking_confirmation"
                    className="w-full px-3 py-2.5 border border-gray-200 rounded-xl text-sm font-mono focus:outline-none focus:ring-2 focus:ring-teal-500/30"
                  />
                  <p className="text-[10px] text-gray-400 mt-1">Lowercase, underscores only. Cannot be changed after creation.</p>
                </div>
                <div>
                  <label className="text-xs font-semibold text-gray-700 block mb-1.5">Language</label>
                  <select value={form.language} onChange={e => setForm(f => ({ ...f, language: e.target.value }))}
                    className="w-full px-3 py-2.5 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-teal-500/30">
                    {LANGUAGES.map(l => <option key={l.value} value={l.value}>{l.label}</option>)}
                  </select>
                </div>
              </div>
              <div>
                <label className="text-xs font-semibold text-gray-700 block mb-1.5">Category</label>
                <div className="grid grid-cols-3 gap-2">
                  {["MARKETING", "UTILITY", "AUTHENTICATION"].map(cat => (
                    <label key={cat} className={cn("flex flex-col gap-1 p-3 rounded-xl border cursor-pointer transition-all text-xs",
                      form.category === cat ? "border-teal-400 bg-teal-50/50" : "border-gray-200 hover:border-gray-300"
                    )}>
                      <input type="radio" name="cat" value={cat} checked={form.category === cat}
                        onChange={() => setForm(f => ({ ...f, category: cat }))} className="sr-only" />
                      <span className="font-semibold text-gray-800 capitalize">{cat.toLowerCase()}</span>
                      <span className="text-[10px] text-gray-400">
                        {cat === "MARKETING" ? "Promotions, offers, re-engagement" :
                         cat === "UTILITY" ? "Confirmations, reminders, updates" :
                         "OTPs and authentication codes"}
                      </span>
                    </label>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* Step 2: Body */}
          {step === "body" && (
            <div className="p-6 space-y-4">
              <div>
                <label className="text-xs font-semibold text-gray-700 block mb-1.5">Header <span className="text-gray-400 font-normal">(optional)</span></label>
                <input value={form.header} onChange={e => setForm(f => ({ ...f, header: e.target.value }))}
                  placeholder="Welcome to {{1}}"
                  className="w-full px-3 py-2.5 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-teal-500/30" />
              </div>
              <div>
                <label className="text-xs font-semibold text-gray-700 block mb-1.5">Body <span className="text-red-500">*</span></label>
                <textarea value={form.body} onChange={e => setForm(f => ({ ...f, body: e.target.value }))} rows={5}
                  placeholder={"Hi {{1}},\n\nYour booking at {{2}} is confirmed for {{3}}.\n\nLooking forward to welcoming you!"}
                  className="w-full px-3 py-2.5 border border-gray-200 rounded-xl text-sm resize-none focus:outline-none focus:ring-2 focus:ring-teal-500/30" />
                <p className="text-[10px] text-gray-400 mt-1">Use {`{{1}}`}, {`{{2}}`} etc. for dynamic variables.</p>
              </div>
              <div>
                <label className="text-xs font-semibold text-gray-700 block mb-1.5">Footer <span className="text-gray-400 font-normal">(optional)</span></label>
                <input value={form.footer} onChange={e => setForm(f => ({ ...f, footer: e.target.value }))}
                  placeholder="Reply STOP to opt out"
                  className="w-full px-3 py-2.5 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-teal-500/30" />
              </div>
              <div>
                <label className="text-xs font-semibold text-gray-700 block mb-1.5">Call-to-action button <span className="text-gray-400 font-normal">(optional)</span></label>
                <div className="flex gap-2 mb-2">
                  {(["none", "url", "phone"] as const).map(t => (
                    <button key={t} onClick={() => setForm(f => ({ ...f, ctaType: t }))}
                      className={cn("px-3 py-1.5 rounded-lg text-xs font-medium transition-colors capitalize",
                        form.ctaType === t ? "bg-teal-500 text-white" : "bg-gray-100 text-gray-600 hover:bg-gray-200")}>
                      {t === "none" ? "No button" : t === "url" ? "Visit URL" : "Call phone"}
                    </button>
                  ))}
                </div>
                {form.ctaType !== "none" && (
                  <div className="grid grid-cols-2 gap-3">
                    <input value={form.ctaText} onChange={e => setForm(f => ({ ...f, ctaText: e.target.value }))}
                      placeholder="Button label" className="px-3 py-2 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-teal-500/30" />
                    <input value={form.ctaType === "url" ? form.ctaUrl : form.ctaPhone}
                      onChange={e => setForm(f => form.ctaType === "url" ? { ...f, ctaUrl: e.target.value } : { ...f, ctaPhone: e.target.value })}
                      placeholder={form.ctaType === "url" ? "https://…" : "+91XXXXXXXXXX"}
                      className="px-3 py-2 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-teal-500/30" />
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Step 3: Preview */}
          {step === "preview" && (
            <div className="p-6">
              <div className="grid grid-cols-2 gap-6">
                <div>
                  <p className="text-xs font-semibold text-gray-700 mb-3">Template details</p>
                  <div className="space-y-2 text-xs text-gray-600">
                    <div className="flex gap-2"><span className="text-gray-400 w-20">Name:</span><span className="font-mono font-medium">{form.name}</span></div>
                    <div className="flex gap-2"><span className="text-gray-400 w-20">Language:</span><span>{LANGUAGES.find(l => l.value === form.language)?.label}</span></div>
                    <div className="flex gap-2"><span className="text-gray-400 w-20">Category:</span><span className="capitalize">{form.category.toLowerCase()}</span></div>
                    <div className="flex gap-2"><span className="text-gray-400 w-20">Components:</span><span>{previewComponents.length} components</span></div>
                  </div>
                </div>
                <div>
                  <p className="text-xs font-semibold text-gray-700 mb-3">WhatsApp preview</p>
                  <div className="bg-[#075E54]/10 rounded-2xl p-3 border border-[#075E54]/20">
                    <div className="bg-white rounded-xl p-3 shadow-sm max-w-[220px] mx-auto">
                      {form.header && <p className="text-[11px] font-bold text-gray-900 mb-1.5">{form.header}</p>}
                      <p className="text-[11px] text-gray-700 leading-relaxed whitespace-pre-wrap">{form.body}</p>
                      {form.footer && <p className="text-[10px] text-gray-400 mt-1.5">{form.footer}</p>}
                      {form.ctaType !== "none" && form.ctaText && (
                        <button className="w-full mt-2 py-1.5 text-[11px] font-semibold text-[#075E54] border-t border-gray-100">
                          {form.ctaText}
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>

        {error && (
          <div className="mx-6 mb-2 flex items-center gap-2 text-xs text-red-700 bg-red-50 rounded-xl px-3 py-2 flex-shrink-0">
            <AlertCircle size={13} /> {error}
          </div>
        )}

        {/* Footer */}
        <div className="px-6 pb-5 pt-3 border-t border-gray-100 flex-shrink-0 flex items-center justify-between">
          <button onClick={onClose} className="text-sm text-gray-500 hover:text-gray-700 transition-colors">Cancel</button>
          <div className="flex gap-2">
            {step !== "info" && (
              <button onClick={() => setStep(s => s === "preview" ? "body" : "info")}
                className="px-4 py-2 border border-gray-200 rounded-xl text-sm text-gray-600 hover:bg-gray-50 transition-colors">
                Back
              </button>
            )}
            {step !== "preview" ? (
              <button
                onClick={() => setStep(s => s === "info" ? "body" : "preview")}
                disabled={step === "info" ? !form.name.trim() : !form.body.trim()}
                className="px-5 py-2 bg-teal-500 text-white rounded-xl text-sm font-semibold hover:bg-teal-600 disabled:opacity-50 transition-colors"
              >
                Continue
              </button>
            ) : (
              <button
                onClick={handleCreate}
                disabled={submitting}
                className="px-5 py-2 bg-teal-500 text-white rounded-xl text-sm font-semibold hover:bg-teal-600 disabled:opacity-50 transition-colors flex items-center gap-2"
              >
                {submitting ? <Loader2 size={13} className="animate-spin" /> : <FileText size={13} />}
                Save template
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function TemplatesPage() {
  const queryClient = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [toast, setToast] = useState<{ msg: string; type: "success" | "error" } | null>(null);
  const [filter, setFilter] = useState<"all" | "draft" | "pending" | "approved" | "rejected">("all");

  const showToast = (msg: string, type: "success" | "error") => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 4000);
  };

  const { data: templates = [], isLoading, isError, refetch, isFetching } = useQuery<Template[]>({
    queryKey: ["wa-templates"],
    queryFn: () => api.get("/messaging/templates").then(r => r.data),
    staleTime: 30_000,
  });

  const submitMutation = useMutation({
    mutationFn: (id: string) => api.post(`/messaging/templates/${id}/submit`),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ["wa-templates"] });
      if (res.data?.status === "pending") {
        showToast("Template submitted for Meta review!", "success");
      } else {
        // submit_template returns 200 even when Meta rejected it or the
        // request itself failed (status: rejected/submission_failed) --
        // treat that the same as an error instead of a false "success".
        showToast(res.data?.rejection_reason || "Submission failed.", "error");
      }
    },
    onError: (err) => {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      showToast(msg || "Submission failed.", "error");
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.delete(`/messaging/templates/${id}`),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["wa-templates"] }); showToast("Template deleted.", "success"); },
    onError: () => showToast("Delete failed.", "error"),
  });

  const filtered = filter === "all" ? templates : templates.filter(t => t.status === filter);

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="px-6 py-5 bg-white border-b border-gray-100 flex-shrink-0">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h1 className="haip-page-title">Message Templates</h1>
            <p className="text-sm text-gray-400 mt-0.5">Create and manage WhatsApp Business templates for campaigns and automated messages.</p>
          </div>
          <button onClick={() => setShowCreate(true)}
            className="flex items-center gap-2 bg-teal-500 text-white px-4 py-2.5 rounded-xl text-sm font-semibold hover:bg-teal-600 transition-colors shadow-sm shadow-teal-200">
            <Plus size={15} /> New template
          </button>
        </div>

        {/* Filters */}
        <div className="flex gap-1 flex-wrap">
          {(["all", "draft", "pending", "approved", "rejected"] as const).map(f => (
            <button key={f} onClick={() => setFilter(f)}
              className={cn("px-3 py-1.5 rounded-lg text-xs font-medium capitalize transition-colors",
                filter === f ? "bg-[#0F766E] text-white" : "text-gray-500 hover:bg-gray-100"
              )}>
              {f} {f !== "all" && `(${templates.filter(t => t.status === f).length})`}
            </button>
          ))}
        </div>
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto p-6">
        {isError ? (
          <div className="py-20 text-center">
            <AlertCircle size={32} className="text-red-300 mx-auto mb-3" />
            <p className="text-sm text-gray-700 font-medium">Couldn't load templates</p>
            <p className="text-xs text-gray-400 mt-1">The server didn't respond — this isn't your saved template list.</p>
            <button
              onClick={() => refetch()}
              disabled={isFetching}
              className="mt-4 text-xs font-semibold text-teal-600 border border-teal-200 bg-teal-50 hover:bg-teal-100 px-3 py-1.5 rounded-lg transition-colors"
            >
              {isFetching ? "Retrying…" : "Retry"}
            </button>
          </div>
        ) : isLoading ? (
          <div className="space-y-3">{Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-24 rounded-2xl" />)}</div>
        ) : filtered.length === 0 ? (
          <div className="py-20 text-center">
            <MessageSquare size={40} className="text-gray-200 mx-auto mb-3" />
            <p className="text-sm text-gray-500 font-medium">No templates yet</p>
            <p className="text-xs text-gray-400 mt-1">Create your first template to start sending WhatsApp messages at scale.</p>
            <button onClick={() => setShowCreate(true)}
              className="mt-4 flex items-center gap-2 bg-teal-500 text-white px-4 py-2 rounded-xl text-sm font-medium hover:bg-teal-600 transition-colors mx-auto">
              <Plus size={14} /> Create template
            </button>
          </div>
        ) : (
          <div className="space-y-3">
            {filtered.map(tmpl => {
              const sc = STATUS_CFG[tmpl.status] ?? STATUS_CFG.draft;
              return (
                <div key={tmpl.id} className="haip-card p-4 hover:shadow-sm transition-shadow">
                  <div className="flex items-start gap-4">
                    <div className="w-10 h-10 rounded-xl bg-green-50 flex items-center justify-center flex-shrink-0">
                      <MessageSquare size={18} className="text-green-600" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap mb-1">
                        <span className="text-sm font-bold text-gray-900 font-mono">{tmpl.name}</span>
                        <span className={cn("inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full border", sc.cls)}>
                          {sc.icon} {sc.label}
                        </span>
                        <span className="text-[10px] bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full capitalize">{tmpl.category.toLowerCase()}</span>
                        <span className="text-[10px] text-gray-400">{tmpl.language.toUpperCase()}</span>
                      </div>
                      <p className="text-xs text-gray-500 truncate leading-relaxed">{extractBody(tmpl.components)}</p>
                      {tmpl.rejection_reason && (
                        <p className="text-[10px] text-red-500 mt-1">Reason: {tmpl.rejection_reason}</p>
                      )}
                      {tmpl.meta_template_id && (
                        <p className="text-[10px] text-gray-400 mt-0.5 font-mono">Meta ID: {tmpl.meta_template_id}</p>
                      )}
                    </div>
                    <div className="flex items-center gap-2 flex-shrink-0">
                      {tmpl.status === "draft" && (
                        <button
                          onClick={() => submitMutation.mutate(tmpl.id)}
                          disabled={submitMutation.isPending}
                          className="flex items-center gap-1.5 text-xs bg-teal-500 text-white px-3 py-1.5 rounded-lg font-medium hover:bg-teal-600 transition-colors disabled:opacity-50"
                        >
                          {submitMutation.isPending ? <Loader2 size={11} className="animate-spin" /> : <Send size={11} />}
                          Submit
                        </button>
                      )}
                      <button
                        onClick={() => { if (confirm("Delete this template?")) deleteMutation.mutate(tmpl.id); }}
                        className="text-gray-400 hover:text-red-500 transition-colors p-1.5 rounded-lg hover:bg-red-50"
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </div>
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
            <p className="text-sm font-semibold text-gray-800 mb-1">How template approval works</p>
            <ol className="text-xs text-gray-500 space-y-1 list-decimal list-inside leading-relaxed">
              <li>Create your template and add content with dynamic variables like {`{{1}}`}</li>
              <li>Click <strong>Submit</strong> — this sends it to Meta for review (usually 24–48 hours)</li>
              <li>Once approved, use it in campaigns or automated concierge replies</li>
              <li>Marketing templates require opt-in. Utility templates can be sent anytime.</li>
            </ol>
          </div>
        </div>
      </div>

      {showCreate && (
        <CreateTemplateModal
          onClose={() => setShowCreate(false)}
          onCreated={() => { queryClient.invalidateQueries({ queryKey: ["wa-templates"] }); showToast("Template created!", "success"); }}
        />
      )}
      {toast && <Toast msg={toast.msg} type={toast.type} onClose={() => setToast(null)} />}
    </div>
  );
}
