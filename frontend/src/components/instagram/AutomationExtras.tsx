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

const input = "min-h-11 w-full rounded-[12px] border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 text-[16px] sm:text-[14.5px]";
const addBtn = "inline-flex min-h-11 items-center self-start text-[14px] font-medium text-primary";
const removeBtn = "grid size-11 shrink-0 place-items-center rounded-full border border-[var(--haip-border)] text-[var(--haip-fg-subtle)]";

/** Other versions of the DM; one of the message and these goes out at random. */
export function VariantsField({ value, onChange }: { value: string[]; onChange: (v: string[]) => void }) {
  return (
    <div className="grid gap-2">
      {value.map((v, i) => (
        <div key={i} className="flex gap-2">
          <textarea className={cn(input, "min-h-[72px] py-2")} value={v} maxLength={900} aria-label={`Version ${i + 2}`}
            onChange={e => onChange(value.map((x, j) => (j === i ? e.target.value : x)))} placeholder="Another way to say it…" />
          <button type="button" aria-label="Remove this version" onClick={() => onChange(value.filter((_, j) => j !== i))} className={removeBtn}><Trash2 size={15} /></button>
        </div>
      ))}
      {value.length < 5 && <button type="button" onClick={() => onChange([...value, ""])} className={addBtn}>+ Add another version (sent at random)</button>}
    </div>
  );
}

export type QuickReply = { title: string; reply: string };

/** Tap buttons under the final message, each with the text sent back when tapped. */
export function QuickRepliesField({ value, onChange }: { value: QuickReply[]; onChange: (v: QuickReply[]) => void }) {
  const set = (i: number, patch: Partial<QuickReply>) => onChange(value.map((q, j) => (j === i ? { ...q, ...patch } : q)));
  return (
    <div className="grid gap-2">
      {value.map((q, i) => (
        <div key={i} className="grid gap-2 rounded-[12px] border border-[var(--haip-border)] p-2 sm:grid-cols-[150px_1fr_auto]">
          <input className={input} value={q.title} maxLength={20} placeholder="Button, e.g. Location" aria-label={`Button ${i + 1} text`} onChange={e => set(i, { title: e.target.value })} />
          <input className={input} value={q.reply} maxLength={640} placeholder="What HAIP sends when it is tapped" aria-label={`Button ${i + 1} reply`} onChange={e => set(i, { reply: e.target.value })} />
          <button type="button" aria-label="Remove this button" onClick={() => onChange(value.filter((_, j) => j !== i))} className={removeBtn}><Trash2 size={15} /></button>
        </div>
      ))}
      {value.length < 5 && <button type="button" onClick={() => onChange([...value, { title: "", reply: "" }])} className={addBtn}>+ Add a quick reply button</button>}
    </div>
  );
}

export type IgCardDraft = { image_key?: string | null; title: string; subtitle?: string; buttons: { title: string; url: string }[] };

function CardImage({ value, onChange }: { value?: string | null; onChange: (key: string | null) => void }) {
  const ref = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const upload = async (f: File) => {
    if (f.size > LIMIT_MB.image * 1048576) { setErr("Instagram takes photos up to 8 MB."); return; }
    setBusy(true); setErr("");
    try {
      const fd = new FormData();
      fd.append("file", f);
      const res = await api.post("/instagram/automations/media", fd, { headers: { "Content-Type": "multipart/form-data" } });
      if (res.data.kind !== "image") throw new Error("not an image");
      onChange(res.data.key);
    } catch { setErr("Use a JPEG or PNG photo."); } finally { setBusy(false); if (ref.current) ref.current.value = ""; }
  };
  return (
    <div>
      <button type="button" disabled={busy} onClick={() => (value ? onChange(null) : ref.current?.click())}
        className="inline-flex min-h-11 items-center gap-2 rounded-[12px] border border-dashed border-[var(--haip-border-strong)] px-3 text-[13.5px] disabled:opacity-60">
        {busy ? <Loader2 size={14} className="animate-spin" /> : value ? <Trash2 size={14} /> : <ImageIcon size={14} />} {busy ? "Uploading…" : value ? "Photo added · remove" : "Add a photo"}
      </button>
      <input ref={ref} type="file" accept="image/jpeg,image/png" className="hidden" onChange={e => { const f = e.target.files?.[0]; if (f) void upload(f); }} />
      {err && <p role="alert" className="mt-1 text-[12.5px] text-[var(--haip-status-danger-fg)]">{err}</p>}
    </div>
  );
}

type Saved = { name: string; cards: IgCardDraft[] };

/** Swipeable cards after the final message (up to 10, each with up to 3 link buttons), plus the saved card library. */
export function CardsField({ value, onChange }: { value: IgCardDraft[]; onChange: (v: IgCardDraft[]) => void }) {
  const [msg, setMsg] = useState("");
  const [saved, setSaved] = useState<Saved[] | null>(null);
  const [name, setName] = useState("");
  const set = (i: number, patch: Partial<IgCardDraft>) => onChange(value.map((c, j) => (j === i ? { ...c, ...patch } : c)));
  const library = async () => (await api.get("/instagram/card-library")).data.items as Saved[];
  const open = async () => {
    try { const items = await library(); setSaved(items); if (!items.length) setMsg("No saved cards yet. Make some below and save them."); }
    catch { setMsg("Could not load the saved cards."); }
  };
  const save = async () => {
    if (!name.trim()) return setMsg("Give the cards a name first.");
    try {
      const items = (await library()).filter(i => i.name !== name.trim());
      await api.put("/instagram/card-library", { items: [...items, { name: name.trim(), cards: value }] });
      setMsg(`Saved as “${name.trim()}”.`);
    } catch (e) { setMsg((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || "Could not save. Every card needs a headline."); }
  };
  return (
    <div className="grid gap-2">
      {value.map((c, i) => (
        <div key={i} className="grid gap-2 rounded-[12px] border border-[var(--haip-border)] p-2">
          <div className="flex items-center justify-between gap-2">
            <p className="text-[13px] font-semibold">Card {i + 1}</p>
            <button type="button" aria-label={`Remove card ${i + 1}`} onClick={() => onChange(value.filter((_, j) => j !== i))} className={removeBtn}><Trash2 size={15} /></button>
          </div>
          <CardImage value={c.image_key} onChange={k => set(i, { image_key: k })} />
          <input className={input} value={c.title} maxLength={80} placeholder="Headline" aria-label={`Card ${i + 1} headline`} onChange={e => set(i, { title: e.target.value })} />
          <input className={input} value={c.subtitle ?? ""} maxLength={80} placeholder="Short text (optional)" aria-label={`Card ${i + 1} text`} onChange={e => set(i, { subtitle: e.target.value })} />
          {c.buttons.map((b, k) => (
            <div key={k} className="grid gap-2 sm:grid-cols-[140px_1fr_auto]">
              <input className={input} value={b.title} maxLength={20} placeholder="Button" aria-label={`Card ${i + 1} button ${k + 1} text`}
                onChange={e => set(i, { buttons: c.buttons.map((x, n) => (n === k ? { ...x, title: e.target.value } : x)) })} />
              <input className={input} value={b.url} inputMode="url" placeholder="https://…" aria-label={`Card ${i + 1} button ${k + 1} link`}
                onChange={e => set(i, { buttons: c.buttons.map((x, n) => (n === k ? { ...x, url: e.target.value } : x)) })} />
              <button type="button" aria-label="Remove this button" onClick={() => set(i, { buttons: c.buttons.filter((_, n) => n !== k) })} className={removeBtn}><Trash2 size={15} /></button>
            </div>
          ))}
          {c.buttons.length < 3 && <button type="button" onClick={() => set(i, { buttons: [...c.buttons, { title: "See details", url: "" }] })} className={addBtn}>+ Add a link button</button>}
        </div>
      ))}
      <div className="flex flex-wrap gap-3">
        {value.length < 10 && <button type="button" onClick={() => onChange([...value, { title: "", subtitle: "", buttons: [] }])} className={addBtn}>+ Add a card</button>}
        <button type="button" onClick={open} className={addBtn}>Use saved cards</button>
      </div>
      {saved && saved.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {saved.map(s => (
            <button key={s.name} type="button" onClick={() => { onChange(s.cards.map(c => ({ ...c, buttons: c.buttons ?? [] }))); setSaved(null); setMsg(`Loaded “${s.name}”.`); }}
              className="min-h-11 rounded-full border border-[var(--haip-border)] px-4 text-[13.5px] font-medium">{s.name} · {s.cards.length}</button>
          ))}
        </div>
      )}
      {value.length > 0 && (
        <div className="flex gap-2">
          <input className={input} value={name} maxLength={60} onChange={e => setName(e.target.value)} placeholder="Name, e.g. Our villas" aria-label="Name for the saved cards" />
          <button type="button" onClick={save} className="min-h-11 shrink-0 rounded-full border border-[var(--haip-border)] px-4 text-[14px] font-medium">Save cards</button>
        </div>
      )}
      {msg && <p className="text-[12.5px] text-[var(--haip-fg-subtle)]">{msg}</p>}
    </div>
  );
}

const SURFACES: [string, string][] = [["comment", "Post comments"], ["live", "Live comments"], ["story", "Story replies"], ["dm", "DMs"], ["ad", "Ad chats"]];

/** Where a global automation answers. */
export function SurfacesField({ value, onChange }: { value: string[]; onChange: (v: string[]) => void }) {
  return (
    <div className="flex flex-wrap gap-2">
      {SURFACES.map(([v, l]) => {
        const on = value.includes(v);
        return (
          <button key={v} type="button" aria-pressed={on} onClick={() => onChange(on ? value.filter(x => x !== v) : [...value, v])}
            className={cn("min-h-11 rounded-full border px-4 text-[13.5px] font-medium", on ? "border-primary bg-[var(--haip-primary-tint)] text-primary" : "border-[var(--haip-border)]")}>{l}</button>
        );
      })}
    </div>
  );
}
