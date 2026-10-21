"use client";
// Pick a photo from the library for one slot (post, carousel slide, story frame). Only approved images are offered.
// Any JPEG, PNG or WebP works: what is posted is a JPEG drawn from it (backend services/marketing_render.py).
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { STUDIO, inputCls, type Asset } from "./types";

type Media = { asset_id?: string | null; alt_text?: string | null };

const seconds = (ms?: number | null) => (ms ? `${Math.round(ms / 1000)}s` : "clip");

/** `clips`: reels may also use the library's video clips (listed first). */
export function PhotoPicker({ value, onChange, disabled, clips }: { value: Media | undefined; onChange: (m: Media) => void; disabled?: boolean; clips?: boolean }) {
  const q = useQuery<Asset[]>({ queryKey: ["studio-media"], queryFn: () => api.get(`${STUDIO}/media`).then(r => r.data), staleTime: 60_000 });
  const isClip = (a: Asset) => a.mime_type.startsWith("video/") && a.source === "upload";
  const usable = (q.data ?? []).filter(a => (a.status ?? "active") === "active" && (a.mime_type.startsWith("image/") || (clips && isClip(a))))
    .sort((a, b) => Number(isClip(b)) - Number(isClip(a)));
  const chosen = usable.find(a => a.id === value?.asset_id);
  const label = (a: Asset) => `${isClip(a) ? `Clip ${seconds(a.duration_ms)}` : a.source === "ai" ? "AI image" : a.source === "template" ? "Creative" : a.source === "canva" ? "Canva design" : "Photo"}${a.alt_text ? ` · ${a.alt_text.slice(0, 40)}` : ""} · ${new Date(a.created_at).toLocaleDateString("en-IN", { day: "numeric", month: "short" })}`;
  return (
    <div className="flex items-center gap-2">
      {chosen?.url && isClip(chosen) ? <video src={chosen.url} muted playsInline preload="metadata" className="size-11 shrink-0 rounded-lg object-cover" aria-label={chosen.alt_text ?? "Clip"} />
        : chosen?.url ? <img src={chosen.url} alt={chosen.alt_text ?? ""} className="size-11 shrink-0 rounded-lg object-cover" /> : <div className="size-11 shrink-0 rounded-lg bg-[var(--haip-surface)]" />}
      <select className={inputCls} aria-label={clips ? "Clip or photo" : "Photo"} disabled={disabled || q.isLoading} value={value?.asset_id ?? ""}
        onChange={e => onChange({ ...(value ?? {}), asset_id: e.target.value || null })}>
        <option value="">{usable.length ? "No photo yet" : "Library is empty: upload photos first"}</option>
        {usable.map(a => <option key={a.id} value={a.id}>{label(a)}</option>)}
      </select>
    </div>
  );
}
