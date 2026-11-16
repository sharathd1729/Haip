"use client";
import { useRef, useState } from "react";
import { Loader2, Plus, Trash2, Upload } from "@/lib/icons";
import { cn } from "@/lib/utils";
import api from "@/lib/api";
import {
  LIMITS, MEDIA_ACCEPT, newButton, newCard,
  type ButtonType, type CardDraft, type TemplateForm, type TemplateFormat,
} from "./templateModel";

// Marketing-only template formats (WhatsApp step 2e): limited-time offer and carousel.
// Backend rules: wa_template_service._offer_errors / _carousel_errors.

type Patch = (fn: (f: TemplateForm) => TemplateForm) => void;

const SMALL = "w-full px-2.5 py-1.5 border border-[var(--haip-border)] rounded-lg text-base sm:text-xs focus:outline-none focus:ring-2 focus:ring-primary/30";

const FORMATS: { value: TemplateFormat; label: string; hint: string }[] = [
  { value: "standard", label: "Standard", hint: "Text, a header and buttons" },
  { value: "offer", label: "Limited-time offer", hint: "Offer banner, optional countdown" },
  { value: "carousel", label: "Carousel", hint: "2 to 10 swipeable cards" },
];

export function FormatField({ form, patch }: { form: TemplateForm; patch: Patch }) {
  const choose = (format: TemplateFormat) => patch(f => ({
    ...f, format,
    cards: format === "carousel" && f.cards.length === 0 ? [newCard(), newCard()] : f.cards,
    footer: format === "offer" ? "" : f.footer,
    headerKind: format === "offer" && (f.headerKind === "text" || f.headerKind === "document") ? "none" : f.headerKind,
  }));
  return (
    <fieldset>
      <legend className="text-xs font-semibold text-[var(--haip-fg-2)] mb-1.5">Format</legend>
      <div className="grid grid-cols-3 gap-2">
        {FORMATS.map(o => (
          <label key={o.value} className={cn("flex flex-col gap-0.5 p-2.5 rounded-xl border cursor-pointer text-xs transition-colors",
            form.format === o.value ? "border-primary bg-[var(--haip-primary-tint)]" : "border-[var(--haip-border)] hover:border-[var(--haip-border-strong)]")}>
            <input type="radio" name="template-format" value={o.value} checked={form.format === o.value} onChange={() => choose(o.value)} className="sr-only" />
            <span className="font-semibold text-[var(--haip-fg)]">{o.label}</span>
            <span className="text-[11.5px] text-[var(--haip-fg-subtle)] leading-snug">{o.hint}</span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

export function OfferField({ form, patch }: { form: TemplateForm; patch: Patch }) {
  return (
    <div className="border border-[var(--haip-border)] rounded-xl p-3 space-y-2">
      <label htmlFor="offer-text" className="text-xs font-semibold text-[var(--haip-fg-2)] block">Offer banner</label>
      <input id="offer-text" value={form.offerText} maxLength={LIMITS.offerText} placeholder="Diwali offer"
        onChange={e => patch(f => ({ ...f, offerText: e.target.value }))} className={SMALL} />
      <label className="flex items-start gap-2 text-xs text-[var(--haip-fg-2)] min-h-11 cursor-pointer">
        <input type="checkbox" checked={form.offerCountdown} className="mt-0.5"
          onChange={e => patch(f => ({ ...f, offerCountdown: e.target.checked }))} />
        <span>Show a countdown. Each campaign sets when the offer ends, and the template then needs an offer code button.</span>
      </label>
      <p className="text-[11.5px] text-[var(--haip-fg-subtle)]">Offers need a link button, take an image or video header (or none), and have no footer.</p>
    </div>
  );
}

function CardEditor({ card, index, total, onChange, onRemove }: {
  card: CardDraft; index: number; total: number;
  onChange: (next: CardDraft) => void; onRemove: () => void;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const rules = MEDIA_ACCEPT[card.kind];

  const upload = async (file: File) => {
    if (file.size > rules.maxMb * 1024 * 1024) { setError(`That file is over ${rules.maxMb} MB.`); return; }
    setError(""); setUploading(true);
    try {
      const fd = new FormData();
      fd.append("format", card.kind.toUpperCase());
      fd.append("file", file);
      const res = await api.post("/messaging/templates/media", fd, { headers: { "Content-Type": "multipart/form-data" } });
      onChange({ ...card, media: { key: res.data.media_key, handle: res.data.header_handle, previewUrl: res.data.preview_url ?? null, fileName: file.name } });
    } catch (err: unknown) {
      setError((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || "Upload failed. Try again.");
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };
  const setButton = (id: string, change: Partial<CardDraft["buttons"][number]>) =>
    onChange({ ...card, buttons: card.buttons.map(b => (b.id === id ? { ...b, ...change } : b)) });

  return (
    <div className="border border-[var(--haip-border)] rounded-xl p-3 space-y-2">
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-[var(--haip-fg-2)]">Card {index + 1}</p>
        <button type="button" onClick={onRemove} disabled={total <= LIMITS.minCards} aria-label={`Remove card ${index + 1}`}
          className="w-11 h-11 flex items-center justify-center text-[var(--haip-fg-subtle)] hover:text-[var(--haip-status-danger-fg)] disabled:opacity-30">
          <Trash2 size={13} />
        </button>
      </div>
      <input ref={fileRef} type="file" accept={rules.accept} className="sr-only" onChange={e => { const f = e.target.files?.[0]; if (f) upload(f); }} />
      <button type="button" onClick={() => fileRef.current?.click()} disabled={uploading}
        className="w-full min-h-11 flex items-center gap-2 px-3 border border-dashed border-[var(--haip-border)] rounded-lg text-xs text-[var(--haip-fg-muted)] hover:bg-[var(--haip-surface)]">
        {uploading ? <Loader2 size={13} className="animate-spin" /> : <Upload size={13} />}
        <span className="truncate">{card.media ? card.media.fileName : `Upload the ${card.kind} (${rules.hint})`}</span>
      </button>
      {error && <p className="text-[11.5px] text-[var(--haip-status-danger-fg)]">{error}</p>}
      <textarea value={card.body} maxLength={LIMITS.cardBody + 20} rows={2} placeholder="Coorg loop, 3 nights"
        onChange={e => onChange({ ...card, body: e.target.value })} aria-label={`Card ${index + 1} text`} className={SMALL} />
      {card.buttons.map(b => (
        <div key={b.id} className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)] gap-2">
          <input value={b.text} maxLength={LIMITS.buttonText} placeholder={b.type === "URL" ? "View route" : b.type === "PHONE_NUMBER" ? "Call us" : "Interested"}
            onChange={e => setButton(b.id, { text: e.target.value })} aria-label="Button label" className={SMALL} />
          {b.type === "URL" ? (
            <input value={b.url} placeholder="https://yoursite.com/route" onChange={e => setButton(b.id, { url: e.target.value })} aria-label="Link" className={SMALL} />
          ) : b.type === "PHONE_NUMBER" ? (
            <input value={b.phone} placeholder="+919876543210" onChange={e => setButton(b.id, { phone: e.target.value })} aria-label="Phone number" className={SMALL} />
          ) : <span className="text-[11.5px] text-[var(--haip-fg-subtle)] self-center">Quick reply</span>}
        </div>
      ))}
    </div>
  );
}

export function CardsField({ form, patch }: { form: TemplateForm; patch: Patch }) {
  const first = form.cards[0];
  const setCard = (id: string, next: CardDraft) => patch(f => ({ ...f, cards: f.cards.map(c => (c.id === id ? next : c)) }));
  // Every card shares the first card's file kind and button types (Meta's rule), so those are chosen once here.
  const setKind = (kind: CardDraft["kind"]) => patch(f => ({ ...f, cards: f.cards.map(c => ({ ...c, kind, media: c.kind === kind ? c.media : null })) }));
  const setButtonTypes = (types: ButtonType[]) => patch(f => ({ ...f, cards: f.cards.map(c => ({
    ...c, buttons: types.map((t, i) => (c.buttons[i]?.type === t ? c.buttons[i] : newButton(t))),
  })) }));
  const types = first?.buttons.map(b => b.type) ?? ["URL"];

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <label className="text-xs text-[var(--haip-fg-2)] flex items-center gap-2">Cards show
          <select value={first?.kind ?? "image"} onChange={e => setKind(e.target.value as CardDraft["kind"])}
            className="px-2 py-1.5 border border-[var(--haip-border)] rounded-lg text-xs">
            <option value="image">Images</option><option value="video">Videos</option>
          </select>
        </label>
        <label className="text-xs text-[var(--haip-fg-2)] flex items-center gap-2">Buttons
          <select value={types.join(",")} onChange={e => setButtonTypes(e.target.value.split(",") as ButtonType[])}
            className="px-2 py-1.5 border border-[var(--haip-border)] rounded-lg text-xs">
            <option value="URL">Link</option>
            <option value="QUICK_REPLY">Quick reply</option>
            <option value="URL,QUICK_REPLY">Link + quick reply</option>
            <option value="QUICK_REPLY,QUICK_REPLY">Two quick replies</option>
            <option value="URL,PHONE_NUMBER">Link + call</option>
          </select>
        </label>
      </div>
      {form.cards.map((c, i) => (
        <CardEditor key={c.id} card={c} index={i} total={form.cards.length}
          onChange={next => setCard(c.id, next)}
          onRemove={() => patch(f => ({ ...f, cards: f.cards.filter(x => x.id !== c.id) }))} />
      ))}
      <button type="button" disabled={form.cards.length >= LIMITS.cards}
        onClick={() => patch(f => ({ ...f, cards: [...f.cards, newCard(first?.kind ?? "image", first)] }))}
        className="min-h-11 flex items-center gap-1.5 px-3 rounded-lg text-xs font-medium bg-[var(--haip-status-neutral-bg)] text-[var(--haip-fg-2)] hover:bg-[var(--haip-border)] disabled:opacity-40">
        <Plus size={12} /> Add card <span className="text-[var(--haip-fg-subtle)] tabular-nums">{form.cards.length}/{LIMITS.cards}</span>
      </button>
      <p className="text-[11.5px] text-[var(--haip-fg-subtle)]">Card text and links are the same for everyone. Personalise the message above the cards instead.</p>
    </div>
  );
}
