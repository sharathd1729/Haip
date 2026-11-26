// Inbox composer attachments: WhatsApp's own limits, checked before upload so the agent hears why straight away.
// The server checks the file's real bytes again (backend/app/services/inbox_attachments.py); keep both in step.

export type AttachmentKind = "image" | "video" | "audio" | "document";

export interface Attachment {
  key: string;
  kind: AttachmentKind;
  filename: string;
  size: number;
  preview_url?: string | null;
}

const MB = 1024 * 1024;
const RULES: { test: (type: string) => boolean; kind: AttachmentKind; max: number; label: string }[] = [
  { test: t => t === "image/jpeg" || t === "image/png", kind: "image", max: 5 * MB, label: "Photos" },
  { test: t => t === "video/mp4", kind: "video", max: 16 * MB, label: "Videos" },
  { test: t => ["audio/mpeg", "audio/mp4", "audio/x-m4a", "audio/aac", "audio/ogg", "audio/amr"].includes(t), kind: "audio", max: 16 * MB, label: "Audio files" },
  { test: t => t === "application/pdf", kind: "document", max: 100 * MB, label: "PDFs" },
];

/** What the file picker offers. */
export const ATTACH_ACCEPT = "image/jpeg,image/png,video/mp4,audio/mpeg,audio/mp4,audio/x-m4a,audio/aac,audio/ogg,audio/amr,application/pdf";

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < MB) return `${Math.round(n / 1024)} KB`;
  return `${(n / MB).toFixed(1)} MB`;
}

/** Why this file can't go on WhatsApp, or null when it can. */
export function attachmentProblem(file: { type: string; size: number }): string | null {
  const rule = RULES.find(r => r.test(file.type));
  if (!rule) return "WhatsApp takes JPEG or PNG photos, MP4 videos, audio files and PDFs.";
  if (file.size > rule.max) return `${rule.label} can be up to ${rule.max / MB} MB on WhatsApp. This one is ${formatBytes(file.size)}.`;
  return null;
}
