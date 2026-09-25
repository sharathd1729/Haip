"use client";
import { useRef, useState } from "react";
import { Loader2, Plus, Trash2, Upload, AlertCircle, RefreshCw } from "@/lib/icons";
import { cn } from "@/lib/utils";
import api from "@/lib/api";
import {
  LIMITS, MEDIA_ACCEPT, extractVarIndices, newButton,
  type ButtonType, type HeaderKind, type TemplateForm,
} from "./templateModel";

const INPUT = "w-full px-3 py-2.5 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-teal-500/30";

export function Counter({ value, max }: { value: number; max: number }) {
  return <span className={cn("text-[10px] tabular-nums", value > max ? "text-red-500 font-semibold" : "text-gray-400")}>{value}/{max}</span>;
}

type Patch = (fn: (f: TemplateForm) => TemplateForm) => void;

// ─── Header ──────────────────────────────────────────────────────────────────

const HEADER_KINDS: { value: HeaderKind; label: string }[] = [
  { value: "none", label: "None" }, { value: "text", label: "Text" },
  { value: "image", label: "Image" }, { value: "video", label: "Video" }, { value: "document", label: "PDF" },
];

export function HeaderField({ form, patch }: { form: TemplateForm; patch: Patch }) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const kind = form.headerKind;
  const mediaKind = kind === "image" || kind === "video" || kind === "document" ? kind : null;
  const headerVars = extractVarIndices(form.headerText);

  const chooseKind = (next: HeaderKind) => {
    setUploadError("");
    // A file uploaded for one header type can't serve another.
    patch(f => ({ ...f, headerKind: next, media: next === f.headerKind ? f.media : null }));
  };

  const upload = async (file: File) => {
    if (!mediaKind) return;
    const rules = MEDIA_ACCEPT[mediaKind];
    if (file.size > rules.maxMb * 1024 * 1024) {
      setUploadError(`That file is ${(file.size / 1048576).toFixed(1)} MB. The limit is ${rules.maxMb} MB.`);
      return;
    }
    setUploadError("");
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("format", mediaKind.toUpperCase());
      fd.append("file", file);
      const res = await api.post("/messaging/templates/media", fd, { headers: { "Content-Type": "multipart/form-data" } });
      patch(f => ({
        ...f,
        media: { key: res.data.media_key, handle: res.data.header_handle, previewUrl: res.data.preview_url ?? null, fileName: file.name },
      }));
    } catch (err: any) {
      setUploadError(err?.response?.data?.detail || "Upload failed. Check your connection and try again.");
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  return (
    <div>
      <label className="text-xs font-semibold text-gray-700 block mb-1.5">Header <span className="text-gray-400 font-normal">(optional)</span></label>
      <div className="inline-flex rounded-xl bg-gray-100 p-0.5 mb-2" role="tablist" aria-label="Header type">
        {HEADER_KINDS.map(k => (
          <button key={k.value} type="button" role="tab" aria-selected={kind === k.value} onClick={() => chooseKind(k.value)}
            className={cn("px-3 py-1.5 rounded-[10px] text-xs font-medium transition-colors",
              kind === k.value ? "bg-white text-gray-900 shadow-sm" : "text-gray-500 hover:text-gray-700")}>
            {k.label}
          </button>
        ))}
      </div>

      {kind === "text" && (
        <>
          <div className="relative">
            <input value={form.headerText} onChange={e => patch(f => ({ ...f, headerText: e.target.value }))}
              placeholder="Welcome to {{1}}" className={INPUT} />
            <span className="absolute right-3 top-1/2 -translate-y-1/2"><Counter value={form.headerText.length} max={LIMITS.header} /></span>
          </div>
          {headerVars.length > 0 && (
            <div className="mt-2 p-2.5 bg-amber-50 border border-amber-100 rounded-xl">
              <p className="text-[10px] font-semibold text-amber-800 mb-1.5">Example for {`{{1}}`} <span className="font-normal text-amber-600">— Meta needs this to review it</span></p>
              <input value={form.headerExample} onChange={e => patch(f => ({ ...f, headerExample: e.target.value }))}
                placeholder="e.g. Ratha Retreats"
                className="w-full px-2.5 py-1.5 border border-amber-200 rounded-lg text-xs focus:outline-none focus:ring-2 focus:ring-amber-400/30" />
            </div>
          )}
        </>
      )}

      {mediaKind && (
        <div>
          <input ref={fileRef} type="file" accept={MEDIA_ACCEPT[mediaKind].accept} className="sr-only"
            onChange={e => { const f = e.target.files?.[0]; if (f) upload(f); }} />
          {form.media ? (
            <div className="flex items-center gap-3 p-3 border border-gray-200 rounded-xl">
              {mediaKind === "image" && form.media.previewUrl && (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={form.media.previewUrl} alt="" className="h-12 w-12 rounded-lg object-cover flex-shrink-0" />
              )}
              <div className="min-w-0 flex-1">
                <p className="text-xs font-medium text-gray-800 truncate">{form.media.fileName}</p>
                <p className="text-[10px] text-gray-400">Sent to Meta as the review sample.</p>
              </div>
              <button type="button" onClick={() => fileRef.current?.click()} disabled={uploading}
                className="flex items-center gap-1.5 text-xs text-teal-700 border border-teal-200 bg-teal-50 hover:bg-teal-100 px-2.5 py-1.5 rounded-lg disabled:opacity-50">
                {uploading ? <Loader2 size={11} className="animate-spin" /> : <RefreshCw size={11} />} Replace
              </button>
            </div>
          ) : (
            <button type="button" onClick={() => fileRef.current?.click()} disabled={uploading}
              className="w-full flex flex-col items-center justify-center gap-1.5 py-6 border-2 border-dashed border-gray-200 rounded-xl text-gray-500 hover:border-teal-300 hover:bg-teal-50/40 transition-colors disabled:opacity-60">
              {uploading ? <Loader2 size={18} className="animate-spin" /> : <Upload size={18} />}
              <span className="text-xs font-medium">{uploading ? "Uploading…" : `Upload ${mediaKind === "document" ? "a PDF" : `an ${mediaKind === "image" ? "image" : "video"}`}`}</span>
              <span className="text-[10px] text-gray-400">{MEDIA_ACCEPT[mediaKind].hint}</span>
            </button>
          )}
          {uploadError && (
            <p className="mt-1.5 flex items-start gap-1.5 text-[11px] text-red-600"><AlertCircle size={12} className="mt-0.5 flex-shrink-0" />{uploadError}</p>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Body ────────────────────────────────────────────────────────────────────

export function BodyField({ form, patch }: { form: TemplateForm; patch: Patch }) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const vars = extractVarIndices(form.body);

  const edit = (build: (before: string, sel: string, after: string) => { text: string; cursor: number }) => {
    const el = ref.current;
    const start = el?.selectionStart ?? form.body.length;
    const end = el?.selectionEnd ?? form.body.length;
    const { text, cursor } = build(form.body.slice(0, start), form.body.slice(start, end), form.body.slice(end));
    patch(f => ({ ...f, body: text }));
    requestAnimationFrame(() => { el?.focus(); el?.setSelectionRange(cursor, cursor); });
  };

  const wrap = (mark: string) => edit((b, s, a) => {
    const text = `${b}${mark}${s || "text"}${mark}${a}`;
    return { text, cursor: b.length + mark.length + (s || "text").length + mark.length };
  });
  const addVariable = () => edit((b, s, a) => {
    const next = (vars.length ? Math.max(...vars) : 0) + 1;
    const token = `{{${next}}}`;
    return { text: `${b}${token}${a}`, cursor: b.length + token.length };
  });

  const tool = "px-2.5 py-1 rounded-md text-xs text-gray-600 hover:bg-gray-100 transition-colors";
  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <label className="text-xs font-semibold text-gray-700">Body <span className="text-red-500">*</span></label>
        <Counter value={form.body.length} max={LIMITS.body} />
      </div>
      <div className="border border-gray-200 rounded-xl focus-within:ring-2 focus-within:ring-teal-500/30">
        <div className="flex items-center gap-0.5 px-1.5 py-1 border-b border-gray-100">
          <button type="button" onClick={() => wrap("*")} className={cn(tool, "font-bold")} title="Bold">B</button>
          <button type="button" onClick={() => wrap("_")} className={cn(tool, "italic")} title="Italic">I</button>
          <button type="button" onClick={() => wrap("~")} className={cn(tool, "line-through")} title="Strikethrough">S</button>
          <span className="mx-1 h-4 w-px bg-gray-200" />
          <button type="button" onClick={addVariable} className={cn(tool, "font-mono")} title="Add the next variable">{`{{+}}`} Variable</button>
        </div>
        <textarea ref={ref} value={form.body} onChange={e => patch(f => ({ ...f, body: e.target.value }))} rows={7}
          placeholder={"Hi {{1}},\n\nYour booking at {{2}} is confirmed for {{3}}.\n\nLooking forward to welcoming you!"}
          className="w-full px-3 py-2.5 text-sm resize-y rounded-b-xl focus:outline-none" />
      </div>
      <p className="text-[10px] text-gray-400 mt-1">Formatting: *bold*  _italic_  ~strike~. Variables are numbered {`{{1}}, {{2}}…`} and filled in per guest when you send.</p>
      {vars.length > 0 && (
        <div className="mt-2 p-2.5 bg-amber-50 border border-amber-100 rounded-xl space-y-2">
          <p className="text-[10px] font-semibold text-amber-800">Example values <span className="font-normal text-amber-600">— Meta rejects variables with no example</span></p>
          {vars.map(i => (
            <div key={i} className="flex items-center gap-2">
              <span className="text-xs font-mono text-amber-700 w-10 flex-shrink-0">{`{{${i}}}`}</span>
              <input value={form.bodyExamples[i] ?? ""} onChange={e => patch(f => ({ ...f, bodyExamples: { ...f.bodyExamples, [i]: e.target.value } }))}
                placeholder={`Example for {{${i}}}`}
                className="flex-1 px-2.5 py-1.5 border border-amber-200 rounded-lg text-xs focus:outline-none focus:ring-2 focus:ring-amber-400/30" />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Buttons ─────────────────────────────────────────────────────────────────

const BUTTON_LABEL: Record<ButtonType, string> = { QUICK_REPLY: "Quick reply", URL: "Visit website", PHONE_NUMBER: "Call phone" };

export function ButtonsField({ form, patch }: { form: TemplateForm; patch: Patch }) {
  const count = (t: ButtonType) => form.buttons.filter(b => b.type === t).length;
  const canAdd = (t: ButtonType) =>
    form.buttons.length < LIMITS.buttons &&
    (t !== "URL" || count("URL") < LIMITS.urlButtons) &&
    (t !== "PHONE_NUMBER" || count("PHONE_NUMBER") < LIMITS.phoneButtons);

  const update = (id: string, change: Partial<TemplateForm["buttons"][number]>) =>
    patch(f => ({ ...f, buttons: f.buttons.map(b => (b.id === id ? { ...b, ...change } : b)) }));

  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <label className="text-xs font-semibold text-gray-700">Buttons <span className="text-gray-400 font-normal">(optional)</span></label>
        <span className="text-[10px] text-gray-400 tabular-nums">{form.buttons.length}/{LIMITS.buttons}</span>
      </div>

      {form.buttons.length > 0 && (
        <div className="space-y-2 mb-2">
          {form.buttons.map(b => (
            <div key={b.id} className="border border-gray-200 rounded-xl p-2.5">
              <div className="flex items-center gap-2">
                <span className="text-[10px] font-semibold text-teal-700 bg-teal-50 border border-teal-100 rounded-full px-2 py-0.5 flex-shrink-0">{BUTTON_LABEL[b.type]}</span>
                <input value={b.text} maxLength={LIMITS.buttonText + 10} onChange={e => update(b.id, { text: e.target.value })}
                  placeholder="Button label" aria-label="Button label"
                  className="flex-1 min-w-0 px-2.5 py-1.5 border border-gray-200 rounded-lg text-xs focus:outline-none focus:ring-2 focus:ring-teal-500/30" />
                <Counter value={b.text.length} max={LIMITS.buttonText} />
                <button type="button" aria-label="Remove button" onClick={() => patch(f => ({ ...f, buttons: f.buttons.filter(x => x.id !== b.id) }))}
                  className="text-gray-400 hover:text-red-500 p-1 rounded-lg hover:bg-red-50"><Trash2 size={13} /></button>
              </div>
              {b.type === "URL" && (
                <input value={b.url} onChange={e => update(b.id, { url: e.target.value })} placeholder="https://ratha.example/book" aria-label="Link"
                  className="mt-2 w-full px-2.5 py-1.5 border border-gray-200 rounded-lg text-xs focus:outline-none focus:ring-2 focus:ring-teal-500/30" />
              )}
              {b.type === "PHONE_NUMBER" && (
                <input value={b.phone} onChange={e => update(b.id, { phone: e.target.value })} placeholder="+919876543210" aria-label="Phone number"
                  className="mt-2 w-full px-2.5 py-1.5 border border-gray-200 rounded-lg text-xs focus:outline-none focus:ring-2 focus:ring-teal-500/30" />
              )}
            </div>
          ))}
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        {(["QUICK_REPLY", "URL", "PHONE_NUMBER"] as ButtonType[]).map(t => (
          <button key={t} type="button" disabled={!canAdd(t)} onClick={() => patch(f => ({ ...f, buttons: [...f.buttons, newButton(t)] }))}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-gray-100 text-gray-700 hover:bg-gray-200 disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
            <Plus size={12} /> {BUTTON_LABEL[t]}
          </button>
        ))}
      </div>
      <p className="text-[10px] text-gray-400 mt-1.5">Up to {LIMITS.urlButtons} website buttons and {LIMITS.phoneButtons} call button. Quick replies are shown first.</p>
    </div>
  );
}
