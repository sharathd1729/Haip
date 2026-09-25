"use client";
import { Fragment, type ReactNode } from "react";
import { FileText, Link2, Phone, Play, Reply, Image as ImageIcon } from "@/lib/icons";
import { cn } from "@/lib/utils";
import { fillExamples, orderedButtons, type ButtonDraft, type HeaderKind, type TemplateForm } from "./templateModel";

// WhatsApp's own inline formatting: *bold*  _italic_  ~strike~
function formatInline(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /(\*[^*\n]+\*|_[^_\n]+_|~[^~\n]+~)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const tok = m[0];
    const inner = tok.slice(1, -1);
    if (tok[0] === "*") out.push(<strong key={i++}>{inner}</strong>);
    else if (tok[0] === "_") out.push(<em key={i++}>{inner}</em>);
    else out.push(<s key={i++}>{inner}</s>);
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

// {{n}} that has no example yet is shown as a marker, so you can see where the
// value will land.
function withMarkers(text: string): ReactNode[] {
  return text.split(/(\{\{\d+\}\})/g).map((part, i) =>
    /^\{\{\d+\}\}$/.test(part)
      ? <span key={i} className="rounded bg-amber-100 px-1 text-amber-800">{part}</span>
      : <Fragment key={i}>{formatInline(part)}</Fragment>
  );
}

function MediaHeader({ kind, url }: { kind: HeaderKind; url: string | null }) {
  if (kind === "image" && url) {
    // eslint-disable-next-line @next/next/no-img-element
    return <img src={url} alt="Header" className="h-36 w-full rounded-md object-cover" />;
  }
  if (kind === "video" && url) {
    return <video src={url} className="h-36 w-full rounded-md bg-black object-cover" muted playsInline controls />;
  }
  return (
    <div className="flex h-28 w-full flex-col items-center justify-center gap-1 rounded-md bg-gray-100 text-gray-400">
      {kind === "image" && <ImageIcon size={22} />}
      {kind === "video" && <Play size={22} />}
      {kind === "document" && <FileText size={22} />}
      <span className="text-[10px] capitalize">{kind === "document" ? "PDF document" : `${kind} header`}</span>
    </div>
  );
}

function ButtonRow({ b }: { b: ButtonDraft }) {
  const Icon = b.type === "URL" ? Link2 : b.type === "PHONE_NUMBER" ? Phone : Reply;
  return (
    <div className="flex items-center justify-center gap-1.5 rounded-lg bg-white py-2 text-[12px] font-medium text-[#027EB5] shadow-sm">
      <Icon size={13} />
      <span className="truncate">{b.text.trim() || "Button label"}</span>
    </div>
  );
}

export function WhatsAppPreview({ form, className }: { form: TemplateForm; className?: string }) {
  const header = form.headerKind === "text" && form.headerText.trim()
    ? fillExamples(form.headerText, { 1: form.headerExample })
    : null;
  const body = fillExamples(form.body, form.bodyExamples);
  const empty = !header && !form.body.trim() && form.headerKind === "none" && !form.footer.trim();
  const buttons = orderedButtons(form.buttons);

  return (
    <div className={cn("rounded-2xl bg-[#ECE5DD] p-3", className)}>
      <div className="mx-auto max-w-[300px]">
        <div className="rounded-lg rounded-tl-none bg-white p-2 shadow-sm">
          {form.headerKind !== "none" && form.headerKind !== "text" && (
            <div className="mb-1.5"><MediaHeader kind={form.headerKind} url={form.media?.previewUrl ?? null} /></div>
          )}
          {header && <p className="mb-1 text-[13px] font-bold leading-snug text-gray-900">{withMarkers(header)}</p>}
          {form.body.trim() ? (
            <p className="whitespace-pre-wrap break-words text-[13px] leading-snug text-gray-800">{withMarkers(body)}</p>
          ) : (
            <p className="text-[13px] italic leading-snug text-gray-300">Your message appears here as you type…</p>
          )}
          {form.footer.trim() && <p className="mt-1.5 text-[11px] leading-snug text-gray-500">{form.footer}</p>}
          <p className="mt-1 text-right text-[10px] text-gray-400">10:42 AM</p>
        </div>
        {buttons.length > 0 && (
          <div className="mt-1 space-y-1">
            {buttons.map(b => <ButtonRow key={b.id} b={b} />)}
          </div>
        )}
        {empty && buttons.length === 0 && (
          <p className="mt-2 text-center text-[10px] text-gray-500">This is how guests will see the message.</p>
        )}
      </div>
    </div>
  );
}
