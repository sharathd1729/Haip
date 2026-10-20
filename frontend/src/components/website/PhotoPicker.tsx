"use client";
// Pick a photo from the workspace's library (shared with Marketing Studio) or upload one. Only active (approved)
// photos are offered: AI images waiting for review can't go on a public site.
import { useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Drawer, EmptyState } from "@/components/ui/kit";
import { btnPrimary } from "@/components/marketing/studio/types";
import { useToast } from "@/components/ui/toast";
import { webApi, webError, type MediaItem } from "@/lib/website";

export function PhotoPicker({ open, onClose, media, onPick, loading }: {
  open: boolean; onClose: () => void; media: MediaItem[]; onPick: (ref: string) => void; loading?: boolean;
}) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const upload = async (files: FileList | null) => {
    if (!files?.length) return;
    setBusy(true);
    try {
      let last: MediaItem | null = null;
      for (const f of Array.from(files).slice(0, 10)) last = await webApi.upload(f);
      await qc.invalidateQueries({ queryKey: ["web-media"] });
      if (last && files.length === 1) { onPick(last.ref); onClose(); }
      toast({ variant: "success", title: files.length > 1 ? `${files.length} photos added` : "Photo added" });
    } catch (e) {
      toast({ variant: "error", title: "Upload failed", description: webError(e, "Use a JPEG, PNG or WebP under 10 MB.") });
    } finally { setBusy(false); }
  };
  return (
    <Drawer open={open} onOpenChange={o => !o && onClose()} title="Choose a photo" description="Your photo library, shared with Marketing Studio" wide
      footer={<>
        <input ref={input} type="file" accept="image/jpeg,image/png,image/webp" multiple hidden onChange={e => upload(e.target.files)} />
        <button type="button" className={btnPrimary} disabled={busy} onClick={() => input.current?.click()}>{busy ? "Uploading…" : "Upload photos"}</button>
      </>}>
      {loading ? <p className="text-sm text-[var(--haip-fg-muted)]">Loading photos…</p> : !media.length ? (
        <EmptyState title="No photos yet" hint="Upload your best photos: rooms, views, food, the team. They're re-saved without location data." />
      ) : (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          {media.map(m => (
            <button key={m.id} type="button" className="group overflow-hidden rounded-xl border border-[var(--haip-border)] text-left focus-visible:ring-2 focus-visible:ring-[var(--primary)]"
              onClick={() => { onPick(m.ref); onClose(); }}>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              {m.url ? <img src={m.url} alt={m.alt_text || ""} className="aspect-[4/3] w-full object-cover transition group-hover:opacity-90" /> : <div className="aspect-[4/3] bg-[var(--haip-surface)]" />}
              <span className="block truncate px-2 py-1.5 text-xs text-[var(--haip-fg-muted)]">{m.alt_text || (m.source === "ai" ? "AI image" : "Photo")}</span>
            </button>
          ))}
        </div>
      )}
    </Drawer>
  );
}
