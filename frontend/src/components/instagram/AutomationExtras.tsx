"use client";
// Extra pieces of the Instagram automation builder (ReplyRush parity, Nov 2026): a photo or video and one of your own
// posts sent after the final message, and the reply delay. Server checks: schemas/ig_automation.py.
import { useRef, useState } from "react";
import { ImageIcon, Loader2, Trash2, Upload } from "@/lib/icons";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { MediaPicker } from "./MediaPicker";
import type { IgAttachment, IgSharePost } from "./automationTypes";

const LIMIT_MB = { image: 8, video: 25 } as const; // Instagram's limits for a DM attachment

export function AttachmentField({ value, onChange }: { value: IgAttachment | null; onChange: (a: IgAttachment | null) => void }) {
  const ref = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const upload = async (f: File) => {
    const kind = f.type.startsWith("video/") ? "video" : "image";
    if (f.size > LIMIT_MB[kind] * 1048576) {
      setErr(`That ${kind === "video" ? "video" : "photo"} is ${(f.size / 1048576).toFixed(1)} MB. Instagram takes up to ${LIMIT_MB[kind]} MB.`);
      return;
    }
    setErr("");
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", f);
      const res = await api.post("/instagram/automations/media", fd, { headers: { "Content-Type": "multipart/form-data" } });
      onChange({ kind: res.data.kind, key: res.data.key, filename: res.data.filename });
    } catch (e) {
      setErr((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || "Upload failed. Check your connection and try again.");
    } finally {
      setBusy(false);
      if (ref.current) ref.current.value = "";
    }
  };

  return (
    <div>
      {value ? (
        <div className="flex min-h-11 items-center gap-2 rounded-[12px] border border-[var(--haip-border)] bg-[var(--haip-card)] pl-3">
          <ImageIcon size={15} className="text-[var(--haip-fg-subtle)]" />
          <span className="min-w-0 flex-1 truncate text-[14px]">{value.filename || (value.kind === "video" ? "Video" : "Photo")}</span>
          <button type="button" aria-label="Remove the photo or video" onClick={() => onChange(null)}
            className="grid size-11 place-items-center text-[var(--haip-fg-subtle)] hover:text-[var(--haip-status-danger-fg)]"><Trash2 size={15} /></button>
        </div>
      ) : (
        <button type="button" disabled={busy} onClick={() => ref.current?.click()}
          className="inline-flex min-h-11 items-center gap-2 rounded-[12px] border border-dashed border-[var(--haip-border-strong)] px-3 text-[14px] text-[var(--haip-fg-2)] hover:bg-[var(--haip-surface)] disabled:opacity-60">
          {busy ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />} {busy ? "Uploading…" : "Add a photo or video"}
        </button>
      )}
      <input ref={ref} type="file" accept="image/jpeg,image/png,video/mp4,video/quicktime" className="hidden"
        onChange={e => { const f = e.target.files?.[0]; if (f) void upload(f); }} />
      <p className="mt-1 text-[12.5px] text-[var(--haip-fg-subtle)]">JPEG or PNG up to 8 MB, MP4 up to 25 MB. Sent right after the message.</p>
      {err && <p role="alert" className="mt-1 text-[12.5px] text-[var(--haip-status-danger-fg)]">{err}</p>}
    </div>
  );
}

export function SharePostField({ value, onChange, isComment }: { value: IgSharePost; onChange: (v: IgSharePost) => void; isComment: boolean }) {
  const other = !!value.media_id || !isComment;
  return (
    <div className="grid gap-2">
      {isComment && (
        <div className="flex flex-wrap gap-2">
          {([[false, "The post they commented on"], [true, "Another post"]] as const).map(([pick, label]) => (
            <button key={label} type="button" aria-pressed={other === pick}
              onClick={() => onChange(pick ? { ...value, media_id: value.media_id ?? "" } : { enabled: true, media_id: null, media_thumb: null })}
              className={cn("min-h-11 rounded-full border px-4 text-[13.5px] font-medium",
                other === pick ? "border-primary bg-[var(--haip-primary-tint)] text-primary" : "border-[var(--haip-border)]")}>{label}</button>
          ))}
        </div>
      )}
      {other && <MediaPicker value={value.media_id ?? ""} onPick={m => onChange({ enabled: true, media_id: m.id, media_thumb: m.thumbnail ?? null })} />}
    </div>
  );
}

const DELAYS: [number, string][] = [[0, "Reply right away"], [30, "After 30 seconds"], [60, "After 1 minute"], [120, "After 2 minutes"],
  [300, "After 5 minutes"], [600, "After 10 minutes"], [1800, "After 30 minutes"], [3600, "After 1 hour"]];

export function DelayField({ value, onChange, className }: { value: number; onChange: (s: number) => void; className?: string }) {
  const options = DELAYS.some(([s]) => s === value) ? DELAYS : [...DELAYS, [value, `After ${Math.round(value / 60)} minutes`] as [number, string]];
  return (
    <select className={className} value={value} onChange={e => onChange(Number(e.target.value))} aria-label="When to reply">
      {options.map(([s, l]) => <option key={s} value={s}>{l}</option>)}
    </select>
  );
}
