"use client";
// Pick a photo from the library for one slot (post, carousel slide, story frame). Only approved images are offered;
// Instagram needs JPEG, so non-JPEG photos are marked (make a creative from them to get a JPEG).
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { STUDIO, inputCls, type Asset } from "./types";

type Media = { asset_id?: string | null; alt_text?: string | null };

export function PhotoPicker({ value, onChange, disabled }: { value: Media | undefined; onChange: (m: Media) => void; disabled?: boolean }) {
  const q = useQuery<Asset[]>({ queryKey: ["studio-media"], queryFn: () => api.get(`${STUDIO}/media`).then(r => r.data), staleTime: 60_000 });
  const usable = (q.data ?? []).filter(a => (a.status ?? "active") === "active");
  const chosen = usable.find(a => a.id === value?.asset_id);
  const label = (a: Asset) => `${a.source === "ai" ? "AI image" : a.source === "template" ? "Creative" : "Photo"}${a.mime_type !== "image/jpeg" ? " (not JPEG)" : ""} · ${new Date(a.created_at).toLocaleDateString("en-IN", { day: "numeric", month: "short" })}`;
  return (
    <div className="flex items-center gap-2">
      {chosen?.url ? <img src={chosen.url} alt={chosen.alt_text ?? ""} className="size-11 shrink-0 rounded-lg object-cover" /> : <div className="size-11 shrink-0 rounded-lg bg-[var(--haip-surface)]" />}
      <select className={inputCls} aria-label="Photo" disabled={disabled || q.isLoading} value={value?.asset_id ?? ""}
        onChange={e => onChange({ ...(value ?? {}), asset_id: e.target.value || null })}>
        <option value="">{usable.length ? "No photo yet" : "Library is empty: upload photos first"}</option>
        {usable.map(a => <option key={a.id} value={a.id}>{label(a)}</option>)}
      </select>
    </div>
  );
}
