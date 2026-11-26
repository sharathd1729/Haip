"use client";
// Upload a photo / video / audio / file for a media block (POST /messaging/flows/media). Shows the file name, lets you
// remove it. The server checks type and size (WhatsApp limits); its message is shown when it refuses.
import { useRef, useState } from "react";
import { AlertCircle, FileText, Loader2, Trash2, Upload } from "@/lib/icons";
import api from "@/lib/api";
import type { MediaKind, NodeData } from "./flowModel";

const ACCEPT: Record<MediaKind, string> = {
  image: "image/jpeg,image/png", video: "video/mp4", audio: "audio/mpeg,audio/ogg,audio/aac", document: "application/pdf",
};
const LIMIT_HINT: Record<MediaKind, string> = {
  image: "JPEG or PNG, up to 5 MB", video: "MP4, up to 16 MB", audio: "MP3, OGG or AAC, up to 16 MB", document: "PDF, up to 100 MB",
};

export function MediaUpload({ data, onChange }: { data: NodeData; onChange: (patch: Partial<NodeData>) => void }) {
  const kind = data.media_kind ?? "document";
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const upload = async (file: File) => {
    setBusy(true);
    setError("");
    try {
      const body = new FormData();
      body.append("file", file);
      const res = await api.post<{ kind: MediaKind; key: string; filename: string }>("/messaging/flows/media", body, {
        headers: { "Content-Type": "multipart/form-data" }, timeout: 180_000,
      });
      onChange({ file_key: res.data.key, filename: res.data.filename, media_kind: res.data.kind ?? kind });
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      setError(typeof detail === "string" ? detail : "Upload failed. Check the file type and size.");
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  };

  return (
    <div className="space-y-2">
      {data.file_key ? (
        <div className="flex min-h-11 items-center gap-2 rounded-xl border border-[var(--haip-border)] bg-[var(--haip-surface)] px-3">
          <FileText size={15} className="shrink-0 text-[var(--haip-fg-subtle)]" />
          <span className="min-w-0 flex-1 truncate text-sm text-[var(--haip-fg)]">{data.filename || "Uploaded file"}</span>
          <button type="button" aria-label="Remove file" onClick={() => onChange({ file_key: undefined, filename: undefined })}
            className="-mr-2 flex size-11 items-center justify-center rounded-lg text-[var(--haip-fg-subtle)] hover:text-[var(--haip-status-danger-fg)]">
            <Trash2 size={15} />
          </button>
        </div>
      ) : (
        <button type="button" onClick={() => input.current?.click()} disabled={busy}
          className="flex min-h-11 w-full items-center justify-center gap-2 rounded-xl border border-dashed border-[var(--haip-border-strong)] text-sm font-medium text-[var(--haip-fg-2)] hover:border-primary hover:text-primary disabled:opacity-60">
          {busy ? <Loader2 size={15} className="animate-spin" /> : <Upload size={15} />}
          {busy ? "Uploading..." : "Upload a file"}
        </button>
      )}
      <input ref={input} type="file" accept={ACCEPT[kind]} className="hidden" aria-label="Choose a file"
        onChange={e => { const f = e.target.files?.[0]; if (f) void upload(f); }} />
      <p className="text-[12px] text-[var(--haip-fg-subtle)]">{LIMIT_HINT[kind]}</p>
      {error && <p className="flex items-center gap-1.5 text-[12.5px] text-[var(--haip-status-danger-fg)]"><AlertCircle size={13} /> {error}</p>}
    </div>
  );
}
