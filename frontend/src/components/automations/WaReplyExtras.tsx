"use client";
// WhatsApp keyword reply options (services/wa_keyword_replies.py): exact match, every message, team hours, up to 5 PDFs or
// photos with the reply, repeat after N hours, and the per-reply delivery counts shown on the rule card.
import { useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronUp, FileText, Image as ImageIcon, Loader2, Trash2, Upload } from "@/lib/icons";
import { cn } from "@/lib/utils";
import api from "@/lib/api";

type Cfg = Record<string, any>;

export interface WaReplyStat { rule_id: string; sent: number; delivered: number; read: number; failed: number; people: number }

export const AWAY_PRESET = {
  name: "Away message",
  description: "Outside team hours, once every 12 hours per guest",
  trigger: "wa_message_received",
  trigger_config: { reply_all: true, hours: "closed", keywords: [] as string[] },
  action: "send_whatsapp_reply",
  action_config: {
    message: "Hi {first_name}, thanks for writing to us! Our team is away right now. We'll reply as soon as we're back.",
    repeat_after_hours: 12,
  },
};

const segBtn = (on: boolean) => cn("min-h-11 px-3 rounded-[10px] text-xs font-medium transition-colors",
  on ? "bg-[var(--haip-card)] text-[var(--haip-fg)] shadow-sm" : "text-[var(--haip-fg-subtle)] hover:text-[var(--haip-fg-2)]");

/** Trigger part: how keywords match, reply to every message, and when (team hours). */
export function WaTriggerExtras({ config, onChange }: { config: Cfg; onChange: (c: Cfg) => void }) {
  const { data: team } = useQuery<{ business_start: string; business_end: string; hours_summary?: string } | null>({
    queryKey: ["consult-settings"],
    queryFn: () => api.get("/ai/consult-settings").then(r => r.data).catch(() => null),
    staleTime: 300_000,
  });
  const hours = team ? team.hours_summary ?? `${team.business_start} to ${team.business_end}` : "your team hours";
  const match = config.match ?? "word";
  return (
    <div className="space-y-3">
      <div>
        <p className="text-xs font-semibold text-[var(--haip-fg-2)] mb-1.5">Match</p>
        <div className="inline-flex rounded-xl bg-[var(--haip-status-neutral-bg)] p-0.5" role="radiogroup" aria-label="How keywords match">
          {[["word", "Contains the word"], ["exact", "Whole message"]].map(([v, label]) => (
            <button key={v} type="button" role="radio" aria-checked={match === v} className={segBtn(match === v)}
              onClick={() => onChange({ ...config, match: v })}>{label}</button>
          ))}
        </div>
        <p className="text-[11.5px] text-[var(--haip-fg-subtle)] mt-1">
          {match === "exact" ? "Only a message that is just the keyword, like “Hi!”. “Hi, is Saturday free?” goes to the AI." : "Any message with one of the words in it."}
        </p>
      </div>
      <label className="flex min-h-11 items-center gap-2 text-sm text-[var(--haip-fg-2)]">
        <input type="checkbox" checked={!!config.reply_all} onChange={e => onChange({ ...config, reply_all: e.target.checked })} />
        Reply to every message, keywords or not
      </label>
      <div>
        <label htmlFor="wa-hours" className="text-xs font-semibold text-[var(--haip-fg-2)] block mb-1.5">When</label>
        <select id="wa-hours" value={config.hours ?? "any"} onChange={e => onChange({ ...config, hours: e.target.value })}
          className="w-full min-h-11 px-3 border border-[var(--haip-border)] rounded-xl text-[16px] sm:text-sm bg-[var(--haip-card)]">
          <option value="any">Any time</option>
          <option value="open">Only during team hours</option>
          <option value="closed">Only outside team hours (away message)</option>
        </select>
        <p className="text-[11.5px] text-[var(--haip-fg-subtle)] mt-1">
          Team hours: {hours}, set under <a href="/dashboard/automations/whatsapp-hours" className="underline">Automations, Hours and welcome</a> (off days and holidays count as closed).
          {config.hours === "closed" && " An away message does not count as an answer: the guest stays on My day for your team."}
        </p>
      </div>
    </div>
  );
}

/** "always" | "once" | hours: sets once_per_person / repeat_after_hours, never both. */
export function applyRepeat(config: Cfg, v: string): Cfg {
  const { once_per_person: _o, repeat_after_hours: _r, ...rest } = config;
  return v === "once" ? { ...rest, once_per_person: true } : v === "always" ? rest : { ...rest, repeat_after_hours: Number(v) };
}

export interface WaFile { key: string; kind: "document" | "image"; filename?: string }
export const MAX_REPLY_FILES = 5;

/** The reply's files in send order. Rules saved before several files were allowed have one `file`. */
export function readFiles(config: Cfg): WaFile[] {
  const list: WaFile[] = Array.isArray(config.files) ? config.files : config.file?.key ? [config.file] : [];
  return list.filter(f => f?.key);
}

/** The config with this file list (the old single `file` dropped). */
export function withFiles(config: Cfg, files: WaFile[]): Cfg {
  const { file: _f, ...rest } = config;
  return { ...rest, files };
}

/** Move file `i` one place up (-1) or down (+1); unchanged at either end. */
export function moveFile(files: WaFile[], i: number, dir: -1 | 1): WaFile[] {
  const j = i + dir;
  if (j < 0 || j >= files.length) return files;
  const out = [...files];
  [out[i], out[j]] = [out[j], out[i]];
  return out;
}

const fileName = (f: WaFile) => f.filename || (f.kind === "image" ? "Photo" : "PDF");
const iconBtn = "grid h-11 w-11 place-items-center rounded-lg text-[var(--haip-fg-subtle)] hover:text-[var(--haip-fg)] disabled:opacity-30";

/** What the guest gets, in order: one file rides with the text; several follow it one by one. */
function SequencePreview({ message, files }: { message: string; files: WaFile[] }) {
  const lone = files.length === 1;
  const bubble = "rounded-lg rounded-tl-none bg-[var(--haip-card)] p-2 shadow-sm text-[13px] leading-snug text-[var(--haip-fg)]";
  const chip = (f: WaFile) => (
    <span className="flex items-center gap-1.5 rounded-md bg-[var(--haip-status-neutral-bg)] px-2 py-1.5 text-[12px] text-[var(--haip-fg-muted)]">
      {f.kind === "image" ? <ImageIcon size={14} /> : <FileText size={14} />}<span className="truncate">{fileName(f)}</span>
    </span>
  );
  return (
    <div className="rounded-2xl bg-[var(--haip-status-neutral-bg)] p-3">
      <p className="mb-2 text-[11.5px] font-semibold text-[var(--haip-fg-subtle)]">What the guest gets</p>
      <div className="max-w-[300px] space-y-1.5">
        <div className={bubble}>
          {lone && <div className="mb-1.5">{chip(files[0])}</div>}
          <p className="whitespace-pre-wrap break-words">{message.replace("{first_name}", "Ananya") || "Your reply text"}</p>
        </div>
        {!lone && files.map(f => <div key={f.key} className={bubble}>{chip(f)}</div>)}
      </div>
    </div>
  );
}

/** Reply part: up to 5 PDFs or photos sent with the text, and how often a guest may get this reply. */
export function WaReplyExtras({ config, onChange }: { config: Cfg; onChange: (c: Cfg) => void }) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const files = readFiles(config);
  const setFiles = (next: WaFile[]) => onChange(withFiles(config, next));

  const upload = async (f: File) => {
    const isPdf = f.type === "application/pdf";
    const max = isPdf ? 16 : 5;
    if (f.size > max * 1048576) { setErr(`That file is ${(f.size / 1048576).toFixed(1)} MB. The limit is ${max} MB.`); return; }
    setErr("");
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", f);
      const res = await api.post("/automations/wa-reply-file", fd, { headers: { "Content-Type": "multipart/form-data" } });
      setFiles([...files, { key: res.data.key, kind: res.data.kind, filename: res.data.filename }]);
    } catch (e: any) {
      setErr(e?.response?.data?.detail || "Upload failed. Check your connection and try again.");
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const repeat = config.once_per_person ? "once" : config.repeat_after_hours ? String(config.repeat_after_hours) : "always";
  const setRepeat = (v: string) => onChange(applyRepeat(config, v));

  return (
    <div className="space-y-3">
      <div>
        <p className="text-xs font-semibold text-[var(--haip-fg-2)] mb-1.5">Files <span className="text-[var(--haip-fg-subtle)] font-normal">(optional: up to {MAX_REPLY_FILES}, PDFs up to 16 MB, JPEG or PNG photos up to 5 MB)</span></p>
        {files.length > 0 && (
          <ol className="mb-2 space-y-1.5">
            {files.map((f, i) => (
              <li key={f.key} className="flex min-h-11 items-center gap-1 rounded-xl border border-[var(--haip-border)] bg-[var(--haip-card)] pl-3">
                <span className="w-5 text-[11.5px] text-[var(--haip-fg-subtle)]">{i + 1}.</span>
                {f.kind === "image" ? <ImageIcon size={15} className="text-[var(--haip-fg-subtle)]" /> : <FileText size={15} className="text-[var(--haip-fg-subtle)]" />}
                <span className="min-w-0 flex-1 truncate text-sm">{fileName(f)}</span>
                {files.length > 1 && (
                  <>
                    <button type="button" aria-label={`Move ${fileName(f)} up`} disabled={i === 0}
                      onClick={() => setFiles(moveFile(files, i, -1))} className={iconBtn}><ChevronUp size={15} /></button>
                    <button type="button" aria-label={`Move ${fileName(f)} down`} disabled={i === files.length - 1}
                      onClick={() => setFiles(moveFile(files, i, 1))} className={iconBtn}><ChevronDown size={15} /></button>
                  </>
                )}
                <button type="button" aria-label={`Remove ${fileName(f)}`} onClick={() => setFiles(files.filter((_, j) => j !== i))}
                  className={cn(iconBtn, "hover:text-[var(--haip-status-danger-fg)]")}>
                  <Trash2 size={15} />
                </button>
              </li>
            ))}
          </ol>
        )}
        {files.length < MAX_REPLY_FILES ? (
          <button type="button" disabled={busy} onClick={() => fileRef.current?.click()}
            className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-dashed border-[var(--haip-border-strong)] px-3 text-sm text-[var(--haip-fg-2)] hover:bg-[var(--haip-surface)] disabled:opacity-60">
            {busy ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />} {busy ? "Uploading…" : files.length ? "Add another file" : "Add a PDF or photo"}
          </button>
        ) : (
          <p className="text-[11.5px] text-[var(--haip-fg-subtle)]">{MAX_REPLY_FILES} files is the most one reply can send.</p>
        )}
        <input ref={fileRef} type="file" accept="application/pdf,image/jpeg,image/png" className="hidden"
          onChange={e => { const f = e.target.files?.[0]; if (f) void upload(f); }} />
        <p className="text-[11.5px] text-[var(--haip-fg-subtle)] mt-1">
          {files.length > 1 ? "Your reply goes first, then each file as its own message, in this order."
            : "One file goes in the same message: your reply becomes its caption, or the file sits above the buttons."}
        </p>
        {err && <p role="alert" className="text-[11.5px] text-[var(--haip-status-danger-fg)] mt-1">{err}</p>}
      </div>
      {files.length > 0 && <SequencePreview message={config.message ?? ""} files={files} />}
      <div>
        <label htmlFor="wa-repeat" className="text-xs font-semibold text-[var(--haip-fg-2)] block mb-1.5">How often</label>
        <select id="wa-repeat" value={repeat} onChange={e => setRepeat(e.target.value)}
          className="w-full min-h-11 px-3 border border-[var(--haip-border)] rounded-xl text-[16px] sm:text-sm bg-[var(--haip-card)]">
          <option value="always">Every time it matches</option>
          <option value="once">Only once per person (after that the AI or your team answers)</option>
          <option value="12">At most once every 12 hours per person</option>
          <option value="24">At most once a day per person</option>
        </select>
      </div>
    </div>
  );
}

/** One line on the rule card: what happened to this reply in the last 30 days. */
export function WaReplyStatsLine({ stat }: { stat?: WaReplyStat }) {
  if (!stat || stat.sent + stat.failed === 0) {
    return <span className="text-[11px] text-[var(--haip-fg-subtle)]">Last 30 days: not sent yet</span>;
  }
  const pct = stat.sent ? `${Math.round((stat.delivered / stat.sent) * 100)}% delivered` : "none delivered";
  return (
    <span className="text-[11px] text-[var(--haip-fg-subtle)]">
      Last 30 days: {stat.sent} sent · {pct} · {stat.read} read · {stat.people} {stat.people === 1 ? "person" : "people"}
      {stat.failed > 0 && <span className="text-[var(--haip-status-danger-fg)]"> · {stat.failed} failed</span>}
    </span>
  );
}
