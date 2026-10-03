"use client";
import { useEffect, useMemo, useState } from "react";
import { X, Loader2, FileText, AlertCircle, CheckCircle2, XCircle } from "@/lib/icons";
import { cn } from "@/lib/utils";
import api from "@/lib/api";
import { WhatsAppPreview } from "./WhatsAppPreview";
import { BodyField, ButtonsField, Counter, HeaderField } from "./TemplateEditorFields";
import {
  LANGUAGES, LIMITS, buildComponents, emptyForm, formFromTemplate, localProblems,
  type Template, type TemplateForm,
} from "./templateModel";

interface LintFinding { level: "error" | "warn"; message: string; field_path: string }

const INPUT = "w-full px-3 py-2.5 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-teal-500/30";

const CATEGORIES = [
  { value: "MARKETING", hint: "Offers, promotions, re-engagement" },
  { value: "UTILITY", hint: "Confirmations, reminders, updates" },
  { value: "AUTHENTICATION", hint: "One-time codes" },
];

export function TemplateEditor({ template, duplicateOf, onClose, onSaved }: {
  template?: Template | null;        // edit this one
  duplicateOf?: Template | null;     // start a new template from this one
  onClose: () => void;
  onSaved: (message: string) => void;
}) {
  const editing = !!template;
  const [form, setForm] = useState<TemplateForm>(() =>
    template ? formFromTemplate(template)
    : duplicateOf ? { ...formFromTemplate(duplicateOf), name: `${duplicateOf.name}_copy`.slice(0, 512) }
    : emptyForm());
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [lint, setLint] = useState<LintFinding[]>([]);

  const components = useMemo(() => buildComponents(form), [form]);
  const problems = useMemo(() => localProblems(form), [form]);
  const lintErrors = lint.filter(f => f.level === "error");
  const canSave = problems.length === 0 && lintErrors.length === 0 && !saving;

  // Meta's known rejection reasons (URL shorteners, promo wording in a utility
  // template, ...) checked as you type, not after you've saved.
  useEffect(() => {
    if (!form.body.trim()) { setLint([]); return; }
    const timer = setTimeout(async () => {
      try {
        const res = await api.post("/messaging/templates/lint", {
          name: form.name, language: form.language, category: form.category, components,
        });
        setLint(res.data?.findings ?? []);
      } catch {
        setLint([]);     // the check is advisory; saving still validates on the server
      }
    }, 700);
    return () => clearTimeout(timer);
  }, [components, form.name, form.language, form.category, form.body]);

  const patch = (fn: (f: TemplateForm) => TemplateForm) => { setError(""); setForm(fn); };

  const save = async () => {
    setError("");
    setSaving(true);
    try {
      const body = {
        language: form.language, category: form.category, components,
        header_media_key: form.media?.key ?? null,
      };
      if (editing && template) {
        await api.put(`/messaging/templates/${template.id}`, body);
        onSaved("Template updated.");
      } else {
        await api.post("/messaging/templates", { name: form.name, ...body });
        onSaved("Template saved. Submit it to Meta when you're ready.");
      }
      onClose();
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      const status = err?.response?.status;
      setError(
        detail ? String(detail)
        : status === 403 ? "Only Owner, Manager, and Marketing roles can edit templates."
        : status ? `Couldn't save the template (HTTP ${status}). Try again — if it keeps happening, check the server logs.`
        : "Couldn't reach the server."
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-3 sm:p-6" role="dialog" aria-modal="true" aria-label={editing ? "Edit template" : "Create template"}>
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-5xl max-h-[94vh] flex flex-col overflow-hidden" style={{ maxHeight: "calc(100dvh - 3rem)" }}>
        <div className="px-6 pt-5 pb-4 border-b border-gray-100 flex items-center justify-between flex-shrink-0">
          <div>
            <h2 className="text-base font-bold text-gray-900">{editing ? "Edit template" : "Create message template"}</h2>
            <p className="text-xs text-gray-400 mt-0.5">Templates must be approved by Meta before you can send them.</p>
          </div>
          <button onClick={onClose} aria-label="Close"><X size={18} className="text-gray-400 hover:text-gray-600" /></button>
        </div>

        <div className="flex-1 min-h-0 grid lg:grid-cols-[minmax(0,1fr)_340px]">
          {/* Form */}
          <div className="overflow-y-auto p-6 space-y-5">
            <div className="grid sm:grid-cols-2 gap-4">
              <div>
                <label className="text-xs font-semibold text-gray-700 block mb-1.5">Template name <span className="text-red-500">*</span></label>
                <input value={form.name} disabled={editing}
                  onChange={e => patch(f => ({ ...f, name: e.target.value.toLowerCase().replace(/[^a-z0-9_\s]/g, "").replace(/\s+/g, "_") }))}
                  placeholder="booking_confirmation"
                  className={cn(INPUT, "font-mono", editing && "bg-gray-50 text-gray-500")} />
                <p className="text-[10px] text-gray-400 mt-1">Lowercase letters, numbers and underscores. Can't be changed later.</p>
              </div>
              <div>
                <label className="text-xs font-semibold text-gray-700 block mb-1.5">Language</label>
                <select value={form.language} onChange={e => patch(f => ({ ...f, language: e.target.value }))} className={INPUT}>
                  {LANGUAGES.map(l => <option key={l.value} value={l.value}>{l.label}</option>)}
                </select>
              </div>
            </div>

            <div>
              <label className="text-xs font-semibold text-gray-700 block mb-1.5">Category</label>
              <div className="grid grid-cols-3 gap-2">
                {CATEGORIES.map(c => (
                  <label key={c.value} className={cn("flex flex-col gap-0.5 p-2.5 rounded-xl border cursor-pointer text-xs transition-colors",
                    form.category === c.value ? "border-teal-400 bg-teal-50/50" : "border-gray-200 hover:border-gray-300")}>
                    <input type="radio" name="category" value={c.value} checked={form.category === c.value}
                      onChange={() => patch(f => ({ ...f, category: c.value }))} className="sr-only" />
                    <span className="font-semibold text-gray-800 capitalize">{c.value.toLowerCase()}</span>
                    <span className="text-[10px] text-gray-400 leading-snug">{c.hint}</span>
                  </label>
                ))}
              </div>
            </div>

            <HeaderField form={form} patch={patch} />
            <BodyField form={form} patch={patch} />

            <div>
              <div className="flex items-center justify-between mb-1.5">
                <label className="text-xs font-semibold text-gray-700">Footer <span className="text-gray-400 font-normal">(optional)</span></label>
                <Counter value={form.footer.length} max={LIMITS.footer} />
              </div>
              <input value={form.footer} onChange={e => patch(f => ({ ...f, footer: e.target.value }))} placeholder="Reply STOP to opt out" className={INPUT} />
            </div>

            <ButtonsField form={form} patch={patch} />
          </div>

          {/* Preview + checks */}
          <aside className="border-t lg:border-t-0 lg:border-l border-gray-100 bg-gray-50/60 p-5 overflow-y-auto space-y-4">
            <div>
              <p className="text-xs font-semibold text-gray-700 mb-2">Live preview</p>
              <WhatsAppPreview form={form} />
            </div>
            <div>
              <p className="text-xs font-semibold text-gray-700 mb-2">Before you save</p>
              {problems.length === 0 && lint.length === 0 ? (
                <p className="text-[11px] text-green-600 flex items-center gap-1"><CheckCircle2 size={12} /> Looks good.</p>
              ) : (
                <ul className="space-y-1.5">
                  {problems.map((p, i) => (
                    <li key={`p${i}`} className="text-[11px] text-amber-700 flex items-start gap-1.5"><AlertCircle size={11} className="mt-0.5 flex-shrink-0" />{p}</li>
                  ))}
                  {lint.map((f, i) => (
                    <li key={`l${i}`} className={cn("text-[11px] flex items-start gap-1.5", f.level === "error" ? "text-red-600" : "text-amber-700")}>
                      {f.level === "error" ? <XCircle size={11} className="mt-0.5 flex-shrink-0" /> : <AlertCircle size={11} className="mt-0.5 flex-shrink-0" />}{f.message}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </aside>
        </div>

        {error && (
          <div className="mx-6 mt-3 flex items-center gap-2 text-xs text-red-700 bg-red-50 rounded-xl px-3 py-2 flex-shrink-0">
            <AlertCircle size={13} className="flex-shrink-0" /> {error}
          </div>
        )}

        <div className="px-6 py-4 border-t border-gray-100 flex items-center justify-between flex-shrink-0">
          <button onClick={onClose} className="text-sm text-gray-500 hover:text-gray-700 transition-colors">Cancel</button>
          <button onClick={save} disabled={!canSave} title={!canSave && !saving ? "Fix the items under “Before you save” first" : undefined}
            className="px-5 py-2 bg-teal-500 text-white rounded-xl text-sm font-semibold hover:bg-teal-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-2">
            {saving ? <Loader2 size={13} className="animate-spin" /> : <FileText size={13} />}
            {editing ? "Save changes" : "Save template"}
          </button>
        </div>
      </div>
    </div>
  );
}
