"use client";
// Paperclip + chip for the inbox composer: uploads one file to POST /conversations/{id}/attachments, then the composer
// sends its key as media_url (the typed text becomes the caption).
import { useRef, useState } from "react";
import { FileText, Film, Image as ImageIcon, Loader2, Paperclip, Volume2, X } from "@/lib/icons";
import api from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { ATTACH_ACCEPT, attachmentProblem, formatBytes, type Attachment } from "./attachment";

const KIND_ICON = { image: ImageIcon, video: Film, audio: Volume2, document: FileText } as const;

export function AttachButton({ conversationId, onAttached, disabled }: {
  conversationId: string; onAttached: (a: Attachment) => void; disabled?: boolean;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const { toast } = useToast();

  const upload = async (file: File) => {
    const problem = attachmentProblem(file);
    if (problem) { toast({ variant: "error", title: "Can't attach this file", description: problem }); return; }
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await api.post(`/conversations/${conversationId}/attachments`, fd, { headers: { "Content-Type": "multipart/form-data" } });
      onAttached(res.data);
    } catch (e: any) {
      const detail = e?.response?.data?.detail;
      toast({ variant: "error", title: "Upload failed", description: typeof detail === "string" ? detail : "Check your connection and try again." });
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  return (
    <>
      <button type="button" onClick={() => inputRef.current?.click()} disabled={busy || disabled}
        aria-label="Attach a photo, video, audio or PDF" title="Attach a photo, video, audio or PDF"
        className="h-10 w-10 flex-shrink-0 rounded-full flex items-center justify-center text-[var(--haip-fg-subtle)] hover:bg-[var(--haip-surface)] hover:text-[var(--haip-fg-2)] disabled:opacity-50 pointer-coarse:h-11 pointer-coarse:w-11">
        {busy ? <Loader2 size={16} className="animate-spin" /> : <Paperclip size={18} />}
      </button>
      <input ref={inputRef} type="file" accept={ATTACH_ACCEPT} className="hidden"
        onChange={e => { const f = e.target.files?.[0]; if (f) void upload(f); }} />
    </>
  );
}

export function AttachmentChip({ attachment, onRemove }: { attachment: Attachment; onRemove: () => void }) {
  const Icon = KIND_ICON[attachment.kind] ?? FileText;
  return (
    <div className="mb-2 flex items-center gap-2 rounded-xl border border-[var(--haip-border)] bg-[var(--haip-card)] pl-2 pr-1">
      {attachment.kind === "image" && attachment.preview_url
        // eslint-disable-next-line @next/next/no-img-element -- short-lived presigned link, not a static asset
        ? <img src={attachment.preview_url} alt="" className="h-9 w-9 rounded-lg object-cover" />
        : <Icon size={16} className="text-[var(--haip-fg-subtle)] flex-shrink-0" />}
      <div className="min-w-0 flex-1 py-1.5">
        <p className="truncate text-sm text-[var(--haip-fg)]">{attachment.filename}</p>
        <p className="text-[11.5px] text-[var(--haip-fg-subtle)]">
          {formatBytes(attachment.size)} · {attachment.kind === "audio" ? "sent without a caption" : "type a caption below (optional)"}
        </p>
      </div>
      <button type="button" onClick={onRemove} aria-label="Remove the attachment"
        className="grid h-11 w-11 place-items-center rounded-full text-[var(--haip-fg-subtle)] hover:text-[var(--haip-status-danger-fg)]">
        <X size={15} />
      </button>
    </div>
  );
}
