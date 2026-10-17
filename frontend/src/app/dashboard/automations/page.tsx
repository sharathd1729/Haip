"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Zap, Plus, CheckCircle2, PauseCircle, XCircle, MessageSquare, Phone, Clock, ChevronRight, AlertCircle, Loader2, Settings2, Pencil, Trash2, X, ChevronDown, Info, CornerDownRight, Tag } from "@/lib/icons";
import { ToggleLeft, ToggleRight } from "lucide-react";
import { cn } from "@/lib/utils";
import api from "@/lib/api";

// Instagram glyph was removed from lucide v1+ -- same inline SVG pattern
// already used in components/inbox/ChannelIcon.tsx.
function InstagramIcon({ size = 13 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="2" width="20" height="20" rx="5" ry="5" />
      <circle cx="12" cy="12" r="4" />
      <circle cx="17.5" cy="6.5" r="1" fill="currentColor" stroke="none" />
    </svg>
  );
}

// ─── Types ────────────────────────────────────────────────────────────────────

interface AutomationRule {
  id: string;
  name: string;
  description?: string;
  trigger: string;
  trigger_config: Record<string, any>;
  action: string;
  action_config: Record<string, any>;
  is_active: boolean;
  run_count: number;
  last_run_at?: string;
  created_at?: string;
}

interface AutomationRun {
  id: string;
  automation_id: string;
  automation_name?: string;
  status: "success" | "failed" | "skipped";
  trigger_event?: string;
  context: Record<string, any>;
  detail?: string;
  error?: string;
  ran_at: string;
}

// ─── Dictionaries ─────────────────────────────────────────────────────────────

const TRIGGERS: { value: string; label: string; icon: React.ReactNode; hint: string }[] = [
  { value: "new_inquiry",       label: "New inquiry",        icon: <MessageSquare size={13} />, hint: "Fires when a new inquiry is created" },
  { value: "call_completed",    label: "Call completed",     icon: <Phone size={13} />,         hint: "Fires after every call wrap-up" },
  { value: "no_response_2h",    label: "No response 2h",     icon: <Clock size={13} />,         hint: "Guest messaged but no reply in 2 hours" },
  { value: "no_response_24h",   label: "No response 24h",    icon: <Clock size={13} />,         hint: "Guest messaged but no reply in 24 hours" },
  { value: "inquiry_lost",      label: "Inquiry lost",       icon: <XCircle size={13} />,       hint: "Stage moved to Lost or Ghosted" },
  { value: "stay_check_in_1d",  label: "Check-in tomorrow",  icon: <CheckCircle2 size={13} />,  hint: "Guest checks in tomorrow" },
  { value: "stay_check_out_1d", label: "Check-out tomorrow", icon: <CheckCircle2 size={13} />,  hint: "Guest checks out tomorrow" },
  { value: "ig_dm_received",    label: "Instagram DM received",      icon: <InstagramIcon size={13} />, hint: "Guest sends an Instagram DM matching your keywords" },
  { value: "ig_comment_received", label: "Instagram comment received", icon: <InstagramIcon size={13} />, hint: "Guest comments on a post matching your keywords" },
];

const ACTIONS: { value: string; label: string; hint: string; configFields: string[] }[] = [
  { value: "send_whatsapp_template", label: "Send WhatsApp template", hint: "Sends an approved Meta template to the guest", configFields: ["template_id"] },
  { value: "create_draft_reply",     label: "Draft AI reply",         hint: "Queues the AI concierge to draft a reply",  configFields: [] },
  { value: "notify_team",            label: "Notify team",            hint: "Sends a WhatsApp message to a team number",  configFields: ["to", "message"] },
  { value: "move_to_followup",       label: "Move to follow-up",      hint: "Advances inquiry stage to Responding",       configFields: [] },
  { value: "tag_guest",              label: "Tag guest",               hint: "Adds tags to the subscriber record",         configFields: ["tags"] },
  { value: "send_instagram_quick_reply", label: "Send Instagram quick reply", hint: "Sends a canned DM reply — instant, no AI involved", configFields: ["message", "public_ack_pool"] },
];

function triggerInfo(val: string) {
  return TRIGGERS.find(t => t.value === val) ?? { label: val, icon: <Zap size={13} />, hint: "" };
}
function actionInfo(val: string) {
  return ACTIONS.find(a => a.value === val) ?? { label: val, hint: "", configFields: [] };
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

// ─── Small UI atoms ───────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: AutomationRun["status"] }) {
  if (status === "success") return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10.5px] font-medium bg-[var(--haip-primary-tint)] text-primary border border-[color-mix(in_srgb,var(--primary)_25%,transparent)]">
      <CheckCircle2 size={9} /> Success
    </span>
  );
  if (status === "failed") return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10.5px] font-medium bg-red-50 text-red-600 border border-red-100">
      <XCircle size={9} /> Failed
    </span>
  );
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10.5px] font-medium bg-[var(--haip-surface)] text-[var(--haip-fg-subtle)] border border-[var(--haip-border)]">
      <PauseCircle size={9} /> Skipped
    </span>
  );
}

// T2.4: unlimited-keyword chip input (comma or Enter to add) — explicitly
// not Meta's native 5-keyword cap.
function ChipInput({
  values, onChange, placeholder, chipClassName,
}: {
  values: string[];
  onChange: (next: string[]) => void;
  placeholder: string;
  chipClassName?: string;
}) {
  const [draft, setDraft] = useState("");

  const commit = () => {
    const parts = draft.split(",").map(s => s.trim()).filter(Boolean);
    if (parts.length === 0) return;
    const merged = Array.from(new Set([...values, ...parts]));
    onChange(merged);
    setDraft("");
  };

  return (
    <div>
      <div className="flex flex-wrap gap-1.5 mb-1.5">
        {values.map(v => (
          <span key={v} className={cn(
            "inline-flex items-center gap-1 px-2 py-1 rounded-lg text-[11px] font-medium",
            chipClassName ?? "bg-[var(--haip-primary-tint)] text-primary border border-[color-mix(in_srgb,var(--primary)_25%,transparent)]"
          )}>
            {v}
            <button type="button" onClick={() => onChange(values.filter(x => x !== v))} className="opacity-60 hover:opacity-100">
              <X size={10} />
            </button>
          </span>
        ))}
      </div>
      <input
        value={draft}
        onChange={e => setDraft(e.target.value)}
        onKeyDown={e => {
          if (e.key === "Enter" || e.key === ",") { e.preventDefault(); commit(); }
        }}
        onBlur={commit}
        placeholder={placeholder}
        className="w-full px-3 py-2 border border-[var(--haip-border)] rounded-xl text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary/30"
      />
    </div>
  );
}

function Toast({ msg, type, onClose }: { msg: string; type: "success" | "error"; onClose: () => void }) {
  return (
    <div className={cn("fixed bottom-5 right-5 z-50 flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-medium shadow-lg border max-w-sm",
      type === "success" ? "bg-primary text-white border-primary" : "bg-red-600 text-white border-red-700")}>
      <span className="flex-1">{msg}</span>
      <button onClick={onClose}><X size={13} className="opacity-70" /></button>
    </div>
  );
}

// ─── Rule Form Modal ──────────────────────────────────────────────────────────

function RuleModal({ initial, onClose, onSaved }: {
  initial?: AutomationRule;
  onClose: () => void;
  onSaved: () => void;
}) {
  const isEdit = !!initial;
  const [form, setForm] = useState({
    name: initial?.name ?? "",
    description: initial?.description ?? "",
    trigger: initial?.trigger ?? "",
    trigger_config: initial?.trigger_config ?? {} as Record<string, any>,
    action: initial?.action ?? "",
    action_config: initial?.action_config ?? {} as Record<string, any>,
  });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const { data: templates = [] } = useQuery<{ id: string; name: string; status: string }[]>({
    queryKey: ["wa-templates"],
    queryFn: () => api.get("/messaging/templates").then(r => r.data).catch(() => []),
    staleTime: 60_000,
  });
  const approvedTemplates = (templates as any[]).filter((t: any) => t.status === "approved");

  const selectedAction = ACTIONS.find(a => a.value === form.action);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.name.trim()) { setError("Name is required"); return; }
    if (!form.trigger) { setError("Select a trigger"); return; }
    if (!form.action) { setError("Select an action"); return; }
    const isIgTrigger = form.trigger === "ig_dm_received" || form.trigger === "ig_comment_received";
    const hasReplyAll = form.trigger === "ig_comment_received" && !!form.trigger_config.media_id && !!form.trigger_config.reply_all;
    if (isIgTrigger && !hasReplyAll && (form.trigger_config.keywords ?? []).length === 0) {
      setError("Add at least one keyword (or enable reply-all on a scoped post)"); return;
    }
    if (form.action === "send_instagram_quick_reply" && !form.action_config.message?.trim()) {
      setError("Reply message is required"); return;
    }
    setError("");
    setSubmitting(true);
    try {
      if (isEdit) {
        await api.patch(`/automations/${initial!.id}`, {
          name: form.name,
          description: form.description || null,
          trigger: form.trigger,
          trigger_config: form.trigger_config,
          action: form.action,
          action_config: form.action_config,
        });
      } else {
        await api.post("/automations", {
          name: form.name,
          description: form.description || null,
          trigger: form.trigger,
          trigger_config: form.trigger_config,
          action: form.action,
          action_config: form.action_config,
        });
      }
      onSaved();
      onClose();
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Save failed");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg max-h-[90vh] flex flex-col overflow-hidden" style={{ maxHeight: "calc(100dvh - 2rem)" }}>
        <div className="px-6 pt-6 pb-4 border-b border-[var(--haip-border)] flex items-center justify-between flex-shrink-0">
          <div>
            <h2 className="text-base font-bold text-[var(--haip-fg)]">{isEdit ? "Edit automation" : "New automation"}</h2>
            <p className="text-xs text-[var(--haip-fg-subtle)] mt-0.5">When a trigger fires, run the action automatically.</p>
          </div>
          <button onClick={onClose}><X size={18} className="text-[var(--haip-fg-subtle)] hover:text-[var(--haip-fg-muted)]" /></button>
        </div>

        <form onSubmit={handleSubmit} className="px-6 py-5 space-y-5 overflow-y-auto flex-1">
          {/* Name */}
          <div>
            <label className="text-xs font-semibold text-[var(--haip-fg-2)] block mb-1.5">Rule name <span className="text-red-500">*</span></label>
            <input value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
              placeholder="e.g. Follow-up after 2h silence"
              className="w-full px-3 py-2.5 border border-[var(--haip-border)] rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-primary/30" />
          </div>

          {/* Description */}
          <div>
            <label className="text-xs font-semibold text-[var(--haip-fg-2)] block mb-1.5">Description <span className="text-[var(--haip-fg-subtle)] font-normal">(optional)</span></label>
            <input value={form.description} onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
              placeholder="What does this rule do?"
              className="w-full px-3 py-2.5 border border-[var(--haip-border)] rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-primary/30" />
          </div>

          {/* Trigger selector */}
          <div>
            <label className="text-xs font-semibold text-[var(--haip-fg-2)] block mb-1.5">Trigger <span className="text-red-500">*</span></label>
            <div className="grid grid-cols-1 gap-1.5">
              {TRIGGERS.map(t => (
                <button key={t.value} type="button" onClick={() => setForm(f => ({ ...f, trigger: t.value, trigger_config: {} }))}
                  className={cn("flex items-center gap-3 px-3 py-2.5 rounded-xl border text-left text-sm transition-all",
                    form.trigger === t.value
                      ? "border-primary bg-[var(--haip-primary-tint)] text-[var(--accent-foreground)]"
                      : "border-[var(--haip-border)] text-[var(--haip-fg-muted)] hover:border-[color-mix(in_srgb,var(--primary)_25%,transparent)]")}>
                  <span className={cn("flex-shrink-0", form.trigger === t.value ? "text-primary" : "text-[var(--haip-fg-subtle)]")}>{t.icon}</span>
                  <span className="font-medium flex-1">{t.label}</span>
                  <span className="text-[10px] text-[var(--haip-fg-subtle)] hidden sm:block">{t.hint}</span>
                </button>
              ))}
            </div>
          </div>

          {/* T2.4: keyword rule config — shown for both Instagram triggers */}
          {(form.trigger === "ig_dm_received" || form.trigger === "ig_comment_received") && (
            <div className="border border-pink-100 bg-pink-50 rounded-xl p-4 space-y-4">
              <div>
                <label className="text-xs font-semibold text-[var(--haip-fg-2)] block mb-1.5 flex items-center gap-1">
                  <Tag size={12} /> Keywords <span className="text-red-500">*</span>
                </label>
                <ChipInput
                  values={form.trigger_config.keywords ?? []}
                  onChange={vals => setForm(f => ({ ...f, trigger_config: { ...f.trigger_config, keywords: vals } }))}
                  placeholder="price, rate, availability — press Enter to add"
                />
                <p className="text-[10px] text-[var(--haip-fg-subtle)] mt-1">Matches whole words, case-insensitive. Unlimited keywords.</p>
              </div>

              <div>
                <label className="text-xs font-semibold text-[var(--haip-fg-2)] block mb-1.5">Exclude keywords <span className="text-[var(--haip-fg-subtle)] font-normal">(optional)</span></label>
                <ChipInput
                  values={form.trigger_config.exclude_keywords ?? []}
                  onChange={vals => setForm(f => ({ ...f, trigger_config: { ...f.trigger_config, exclude_keywords: vals } }))}
                  placeholder="cancel — press Enter to add"
                  chipClassName="bg-red-50 text-red-700 border border-red-200"
                />
                <p className="text-[10px] text-[var(--haip-fg-subtle)] mt-1">If any of these appear, the rule never fires — even if a keyword above also matched.</p>
              </div>

              {form.trigger === "ig_comment_received" && (
                <>
                  <div>
                    <label className="text-xs font-semibold text-[var(--haip-fg-2)] block mb-1.5">Scope to a specific post/reel <span className="text-[var(--haip-fg-subtle)] font-normal">(optional)</span></label>
                    <input
                      value={form.trigger_config.media_id ?? ""}
                      onChange={e => setForm(f => ({ ...f, trigger_config: { ...f.trigger_config, media_id: e.target.value || undefined } }))}
                      placeholder="Instagram media/post ID — leave blank to match on any post"
                      className="w-full px-3 py-2 border border-[var(--haip-border)] rounded-xl text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary/30"
                    />
                  </div>
                  {form.trigger_config.media_id && (
                    <label className="flex items-center gap-2 text-xs text-[var(--haip-fg-2)] cursor-pointer">
                      <input
                        type="checkbox"
                        checked={!!form.trigger_config.reply_all}
                        onChange={e => setForm(f => ({ ...f, trigger_config: { ...f.trigger_config, reply_all: e.target.checked } }))}
                        className="rounded border-[var(--haip-border-strong)] text-primary focus:ring-primary"
                      />
                      Reply to every comment on this post, ignoring keywords
                    </label>
                  )}
                </>
              )}
            </div>
          )}

          {/* Action selector */}
          <div>
            <label className="text-xs font-semibold text-[var(--haip-fg-2)] block mb-1.5">Then do <span className="text-red-500">*</span></label>
            <select value={form.action}
              onChange={e => setForm(f => ({ ...f, action: e.target.value, action_config: {} }))}
              className="w-full px-3 py-2.5 border border-[var(--haip-border)] rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-primary/30">
              <option value="">Select an action…</option>
              {ACTIONS.map(a => <option key={a.value} value={a.value}>{a.label}</option>)}
            </select>
            {selectedAction && (
              <p className="text-[11px] text-[var(--haip-fg-subtle)] mt-1 flex items-center gap-1">
                <Info size={10} /> {selectedAction.hint}
              </p>
            )}
          </div>

          {/* Action config fields */}
          {form.action === "send_whatsapp_template" && (
            <div className="border border-amber-100 bg-amber-50 rounded-xl p-4">
              <label className="text-xs font-semibold text-[var(--haip-fg-2)] block mb-1.5">Template to send <span className="text-red-500">*</span></label>
              {approvedTemplates.length === 0 ? (
                <p className="text-xs text-amber-700">No approved templates. <a href="/dashboard/messaging/templates" className="underline font-medium">Create one first.</a></p>
              ) : (
                <select value={form.action_config.template_id ?? ""}
                  onChange={e => setForm(f => ({ ...f, action_config: { ...f.action_config, template_id: e.target.value } }))}
                  className="w-full px-3 py-2.5 border border-[var(--haip-border)] rounded-xl text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary/30">
                  <option value="">Select template…</option>
                  {approvedTemplates.map((t: any) => <option key={t.id} value={t.id}>{t.name}</option>)}
                </select>
              )}
            </div>
          )}

          {form.action === "notify_team" && (
            <div className="border border-blue-100 bg-blue-50 rounded-xl p-4 space-y-3">
              <div>
                <label className="text-xs font-semibold text-[var(--haip-fg-2)] block mb-1.5">Notify number (WhatsApp)</label>
                <input value={form.action_config.to ?? ""}
                  onChange={e => setForm(f => ({ ...f, action_config: { ...f.action_config, to: e.target.value } }))}
                  placeholder="+91 98765 43210"
                  className="w-full px-3 py-2 border border-[var(--haip-border)] rounded-xl text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary/30" />
              </div>
              <div>
                <label className="text-xs font-semibold text-[var(--haip-fg-2)] block mb-1.5">Message</label>
                <input value={form.action_config.message ?? ""}
                  onChange={e => setForm(f => ({ ...f, action_config: { ...f.action_config, message: e.target.value } }))}
                  placeholder="New high-priority inquiry — check HAIP"
                  className="w-full px-3 py-2 border border-[var(--haip-border)] rounded-xl text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary/30" />
              </div>
            </div>
          )}

          {form.action === "tag_guest" && (
            <div className="border border-purple-100 bg-purple-50 rounded-xl p-4">
              <label className="text-xs font-semibold text-[var(--haip-fg-2)] block mb-1.5">Tags to apply (comma-separated)</label>
              <input value={(form.action_config.tags ?? []).join(", ")}
                onChange={e => setForm(f => ({
                  ...f, action_config: { ...f.action_config, tags: e.target.value.split(",").map(t => t.trim()).filter(Boolean) }
                }))}
                placeholder="vip, high-intent"
                className="w-full px-3 py-2 border border-[var(--haip-border)] rounded-xl text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary/30" />
            </div>
          )}

          {form.action === "send_instagram_quick_reply" && (
            <div className="border border-pink-100 bg-pink-50 rounded-xl p-4 space-y-3">
              <div>
                <label className="text-xs font-semibold text-[var(--haip-fg-2)] block mb-1.5">Reply message <span className="text-red-500">*</span></label>
                <textarea
                  value={form.action_config.message ?? ""}
                  onChange={e => setForm(f => ({ ...f, action_config: { ...f.action_config, message: e.target.value } }))}
                  placeholder="Our villas start at ₹18,000/night — check availability at ..."
                  rows={3}
                  className="w-full px-3 py-2 border border-[var(--haip-border)] rounded-xl text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary/30 resize-none"
                />
                <p className="text-[10px] text-[var(--haip-fg-subtle)] mt-1">Sent as a private DM — deterministic, no AI involved.</p>
              </div>

              {form.trigger === "ig_comment_received" && (
                <div>
                  <label className="text-xs font-semibold text-[var(--haip-fg-2)] block mb-1.5">
                    Public comment ack <span className="text-[var(--haip-fg-subtle)] font-normal">(one picked at random)</span>
                  </label>
                  <ChipInput
                    values={form.action_config.public_ack_pool ?? []}
                    onChange={vals => setForm(f => ({ ...f, action_config: { ...f.action_config, public_ack_pool: vals } }))}
                    placeholder="Check your DMs! 📥 — press Enter to add"
                    chipClassName="bg-white text-[var(--haip-fg-2)] border border-[var(--haip-border)]"
                  />
                  <p className="text-[10px] text-[var(--haip-fg-subtle)] mt-1">Posted publicly as a reply to the comment. Falls back to a default if left empty.</p>
                </div>
              )}
            </div>
          )}

          {error && (
            <div className="flex items-center gap-2 text-xs text-red-700 bg-red-50 rounded-xl px-3 py-2 border border-red-200">
              <AlertCircle size={12} /> {error}
            </div>
          )}
        </form>

        <div className="px-6 pb-5 flex gap-3 flex-shrink-0 border-t border-[var(--haip-border)] pt-4">
          <button onClick={onClose} className="flex-1 py-2.5 border border-[var(--haip-border)] rounded-xl text-sm text-[var(--haip-fg-muted)] hover:bg-[var(--haip-surface)] transition-colors">Cancel</button>
          <button onClick={handleSubmit as any} disabled={submitting}
            className="flex-1 py-2.5 bg-primary text-white rounded-xl text-sm font-semibold hover:bg-[var(--haip-primary-hover)] disabled:opacity-50 transition-colors flex items-center justify-center gap-2">
            {submitting ? <Loader2 size={13} className="animate-spin" /> : <Zap size={13} />}
            {isEdit ? "Save changes" : "Create automation"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Run Detail Drawer ────────────────────────────────────────────────────────

function RunDetail({ run, onClose }: { run: AutomationRun; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />
      <div className="relative w-full max-w-md bg-white h-full shadow-2xl flex flex-col overflow-hidden">
        <div className="px-5 py-4 border-b border-[var(--haip-border)] flex items-center justify-between flex-shrink-0">
          <div className="flex items-center gap-2">
            <StatusBadge status={run.status} />
            <p className="text-sm font-semibold text-[var(--haip-fg)] truncate">{run.automation_name || "Run detail"}</p>
          </div>
          <button onClick={onClose}><X size={16} className="text-[var(--haip-fg-subtle)] hover:text-[var(--haip-fg-muted)]" /></button>
        </div>

        <div className="flex-1 overflow-y-auto p-5 space-y-5">
          {/* Meta */}
          <div className="grid grid-cols-2 gap-3">
            {[
              { label: "Trigger", value: run.trigger_event || "—" },
              { label: "Ran", value: timeAgo(run.ran_at) },
              { label: "Run ID", value: run.id.slice(0, 8) + "…" },
              { label: "Rule ID", value: run.automation_id.slice(0, 8) + "…" },
            ].map(f => (
              <div key={f.label} className="bg-[var(--haip-surface)] rounded-xl p-3">
                <p className="text-[10px] text-[var(--haip-fg-subtle)] uppercase tracking-wider mb-0.5">{f.label}</p>
                <p className="text-xs font-mono font-medium text-[var(--haip-fg-2)]">{f.value}</p>
              </div>
            ))}
          </div>

          {/* Outcome detail */}
          {run.detail && (
            <div>
              <p className="text-xs font-semibold text-[var(--haip-fg-muted)] mb-1.5">Outcome</p>
              <div className="bg-[var(--haip-primary-tint)] border border-[color-mix(in_srgb,var(--primary)_25%,transparent)] rounded-xl p-3 text-xs text-[var(--accent-foreground)]">{run.detail}</div>
            </div>
          )}

          {/* Error trace */}
          {run.error && (
            <div>
              <p className="text-xs font-semibold text-red-600 mb-1.5">Error</p>
              <pre className="bg-red-50 border border-red-100 rounded-xl p-3 text-[11px] text-red-700 overflow-x-auto whitespace-pre-wrap">{run.error}</pre>
            </div>
          )}

          {/* Context */}
          {Object.keys(run.context).length > 0 && (
            <div>
              <p className="text-xs font-semibold text-[var(--haip-fg-muted)] mb-1.5">Context</p>
              <div className="bg-[var(--haip-surface)] rounded-xl p-3 space-y-1.5">
                {Object.entries(run.context).map(([k, v]) => (
                  <div key={k} className="flex items-center gap-2">
                    <CornerDownRight size={10} className="text-[var(--haip-fg-subtle)] flex-shrink-0" />
                    <span className="text-[11px] font-mono text-[var(--haip-fg-subtle)]">{k}:</span>
                    <span className="text-[11px] font-mono text-[var(--haip-fg-2)] truncate">{String(v)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function AutomationsPage() {
  const queryClient = useQueryClient();
  const [toast, setToast] = useState<{ type: "success" | "error"; text: string } | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [editRule, setEditRule] = useState<AutomationRule | null>(null);
  const [selectedRun, setSelectedRun] = useState<AutomationRun | null>(null);

  function showToast(type: "success" | "error", text: string) {
    setToast({ type, text });
    setTimeout(() => setToast(null), 3500);
  }

  const { data: rules = [], isLoading: rulesLoading } = useQuery<AutomationRule[]>({
    queryKey: ["automations"],
    queryFn: () => api.get("/automations").then(r => r.data).catch(() => []),
    staleTime: 30_000,
  });

  const { data: runs = [], isLoading: runsLoading } = useQuery<AutomationRun[]>({
    queryKey: ["automation-runs"],
    queryFn: () => api.get("/automations/runs?limit=20").then(r => r.data).catch(() => []),
    staleTime: 30_000,
  });

  const toggleMutation = useMutation({
    mutationFn: (rule: AutomationRule) =>
      api.patch(`/automations/${rule.id}`, { is_active: !rule.is_active }),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["automations"] }); showToast("success", "Automation updated"); },
    onError: () => showToast("error", "Update failed"),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.delete(`/automations/${id}`),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["automations"] }); showToast("success", "Rule deleted"); },
    onError: () => showToast("error", "Delete failed"),
  });

  const activeCount = rules.filter(r => r.is_active).length;
  const successCount = runs.filter(r => r.status === "success").length;
  const failedCount = runs.filter(r => r.status === "failed").length;

  return (
    <div className="h-full flex flex-col">

      {/* Header */}
      <div className="flex-shrink-0 px-6 py-5 bg-white border-b border-[var(--haip-border)]">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-[22px] font-bold text-[var(--haip-fg)]">Automations</h1>
            <p className="text-[13px] mt-0.5 text-[var(--haip-fg-subtle)]">
              {rulesLoading ? "Loading…" : `${rules.length} rules · ${activeCount} active`}
            </p>
          </div>
          <button
            onClick={() => setShowCreate(true)}
            className="flex items-center gap-1.5 px-4 py-2 rounded-xl text-[13px] font-semibold bg-primary text-white hover:bg-[var(--haip-primary-hover)] transition-colors">
            <Plus size={14} /> New automation
          </button>
        </div>

        {/* KPI strip */}
        {!rulesLoading && runs.length > 0 && (
          <div className="flex items-center gap-6 mt-4">
            <div>
              <p className="text-[11px] text-[var(--haip-fg-subtle)]">Total runs</p>
              <p className="text-[22px] font-bold text-[var(--haip-fg)]">{runs.length}</p>
            </div>
            <div className="w-px h-8 bg-[var(--haip-border)]" />
            <div>
              <p className="text-[11px] text-[var(--haip-fg-subtle)]">Succeeded</p>
              <p className="text-[22px] font-bold text-primary">{successCount}</p>
            </div>
            {failedCount > 0 && (
              <>
                <div className="w-px h-8 bg-[var(--haip-border)]" />
                <div>
                  <p className="text-[11px] text-[var(--haip-fg-subtle)]">Failed</p>
                  <p className="text-[22px] font-bold text-red-500">{failedCount}</p>
                </div>
              </>
            )}
          </div>
        )}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-6">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 max-w-6xl">

          {/* Rules list */}
          <div className="lg:col-span-2 space-y-3">
            <h2 className="text-[13px] font-bold text-[var(--haip-fg-2)] mb-3">Rules</h2>

            {rulesLoading ? (
              Array.from({ length: 3 }).map((_, i) => (
                <div key={i} className="bg-white rounded-2xl p-5 border border-[var(--haip-border)] animate-pulse">
                  <div className="flex items-start justify-between mb-3">
                    <div className="w-36 h-4 rounded bg-[var(--haip-status-neutral-bg)]" />
                    <div className="w-10 h-5 rounded-full bg-[var(--haip-status-neutral-bg)]" />
                  </div>
                  <div className="w-48 h-3 rounded bg-[var(--haip-status-neutral-bg)] mb-4" />
                  <div className="flex gap-2"><div className="w-20 h-5 rounded-full bg-[var(--haip-status-neutral-bg)]" /><div className="w-28 h-5 rounded-full bg-[var(--haip-status-neutral-bg)]" /></div>
                </div>
              ))
            ) : rules.length === 0 ? (
              <div className="bg-white rounded-2xl p-10 text-center border border-[var(--haip-border)]">
                <div className="w-14 h-14 rounded-2xl mx-auto mb-4 flex items-center justify-center bg-[var(--haip-primary-tint)]">
                  <Zap size={26} className="text-primary" />
                </div>
                <p className="font-semibold text-[var(--haip-fg)] mb-1">No automations yet</p>
                <p className="text-[13px] text-[var(--haip-fg-subtle)] mb-5">Automate follow-ups, draft replies, and team alerts</p>
                <button onClick={() => setShowCreate(true)}
                  className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold bg-primary text-white hover:bg-[var(--haip-primary-hover)] transition-colors">
                  <Plus size={15} /> Create first automation
                </button>
              </div>
            ) : (
              rules.map(rule => {
                const trigger = triggerInfo(rule.trigger);
                const action = actionInfo(rule.action);
                return (
                  <div key={rule.id}
                    className={cn("bg-white rounded-2xl p-5 border transition-all",
                      rule.is_active ? "border-[color-mix(in_srgb,var(--primary)_25%,transparent)]" : "border-[var(--haip-border)] opacity-65")}>
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex items-start gap-3 flex-1 min-w-0">
                        <div className={cn("w-9 h-9 rounded-xl flex items-center justify-center flex-shrink-0 mt-0.5",
                          rule.is_active ? "bg-[var(--haip-primary-tint)] text-primary" : "bg-[var(--haip-surface)] text-[var(--haip-fg-subtle)]")}>
                          <Zap size={16} />
                        </div>
                        <div className="min-w-0 flex-1">
                          <p className="font-semibold text-[14px] text-[var(--haip-fg)]">{rule.name}</p>
                          {rule.description && (
                            <p className="text-[12px] text-[var(--haip-fg-subtle)] mt-0.5 line-clamp-1">{rule.description}</p>
                          )}
                          {/* trigger → action */}
                          <div className="flex items-center gap-1.5 mt-2 flex-wrap">
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10.5px] font-medium bg-[var(--haip-primary-tint)] text-primary border border-[color-mix(in_srgb,var(--primary)_25%,transparent)]">
                              {trigger.icon} {trigger.label}
                            </span>
                            <ChevronRight size={10} className="text-[var(--haip-fg-subtle)]" />
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10.5px] font-medium bg-amber-50 text-amber-700 border border-amber-100">
                              {action.label}
                            </span>
                          </div>
                          <div className="flex items-center gap-4 mt-1.5">
                            <span className="text-[11px] text-[var(--haip-fg-subtle)]">{rule.run_count} runs</span>
                            {rule.last_run_at && <span className="text-[11px] text-[var(--haip-fg-subtle)]">Last: {timeAgo(rule.last_run_at)}</span>}
                          </div>
                        </div>
                      </div>

                      {/* Actions */}
                      <div className="flex items-center gap-1.5 flex-shrink-0">
                        <button onClick={() => setEditRule(rule)}
                          className="p-1.5 rounded-lg text-[var(--haip-fg-subtle)] hover:text-primary hover:bg-[var(--haip-primary-tint)] transition-colors">
                          <Pencil size={14} />
                        </button>
                        <button onClick={() => { if (confirm(`Delete "${rule.name}"?`)) deleteMutation.mutate(rule.id); }}
                          className="p-1.5 rounded-lg text-[var(--haip-fg-subtle)] hover:text-red-500 hover:bg-red-50 transition-colors">
                          <Trash2 size={14} />
                        </button>
                        <button onClick={() => toggleMutation.mutate(rule)} disabled={toggleMutation.isPending}
                          className={cn("transition-colors", rule.is_active ? "text-primary" : "text-[var(--haip-fg-subtle)]/70")}>
                          {toggleMutation.isPending ? <Loader2 size={22} className="animate-spin" /> :
                            rule.is_active ? <ToggleRight size={26} /> : <ToggleLeft size={26} />}
                        </button>
                      </div>
                    </div>
                  </div>
                );
              })
            )}
          </div>

          {/* Recent runs */}
          <div className="space-y-3">
            <h2 className="text-[13px] font-bold text-[var(--haip-fg-2)] mb-3">Recent runs</h2>

            {runsLoading ? (
              Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="bg-white rounded-xl p-3 border border-[var(--haip-border)] animate-pulse">
                  <div className="h-3 bg-[var(--haip-status-neutral-bg)] rounded w-3/4 mb-2" />
                  <div className="h-2.5 bg-[var(--haip-status-neutral-bg)] rounded w-1/2" />
                </div>
              ))
            ) : runs.length === 0 ? (
              <div className="bg-white rounded-2xl p-6 text-center border border-[var(--haip-border)]">
                <Settings2 size={22} className="mx-auto mb-2 text-[var(--haip-fg-subtle)]/70" />
                <p className="text-[12px] text-[var(--haip-fg-subtle)]">No runs yet — rules haven&apos;t triggered</p>
              </div>
            ) : (
              <div className="bg-white rounded-2xl overflow-hidden border border-[var(--haip-border)]">
                <div className="divide-y divide-[var(--haip-border)]">
                  {runs.slice(0, 15).map(run => (
                    <button key={run.id} onClick={() => setSelectedRun(run)}
                      className="w-full px-4 py-3 flex items-start gap-3 hover:bg-[var(--haip-surface)] transition-colors text-left">
                      <div className="flex-1 min-w-0">
                        <p className="text-[12px] font-medium text-[var(--haip-fg)] truncate">{run.automation_name || "Automation"}</p>
                        {run.detail && <p className="text-[11px] text-[var(--haip-fg-subtle)] truncate mt-0.5">{run.detail}</p>}
                        <p className="text-[10.5px] text-[var(--haip-fg-subtle)]/70 mt-0.5">{timeAgo(run.ran_at)}</p>
                      </div>
                      <StatusBadge status={run.status} />
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Modals */}
      {(showCreate || editRule) && (
        <RuleModal
          initial={editRule ?? undefined}
          onClose={() => { setShowCreate(false); setEditRule(null); }}
          onSaved={() => {
            queryClient.invalidateQueries({ queryKey: ["automations"] });
            showToast("success", editRule ? "Rule updated" : "Automation created");
          }}
        />
      )}
      {selectedRun && <RunDetail run={selectedRun} onClose={() => setSelectedRun(null)} />}
      {toast && <Toast msg={toast.text} type={toast.type} onClose={() => setToast(null)} />}
    </div>
  );
}
