"use client";
// The images exactly as they will be posted: drawn by the server from a saved version with the same code the publisher
// uses (GET /content/{id}/preview). A carousel or story scrolls sideways inside its own strip, never the page.
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { Skeleton } from "@/components/ui/skeleton";
import { STUDIO, studioError, type Kind } from "./types";

export interface PreviewFrame { src: string; asset_id: string; headline: string | null; style: string }
interface Preview { version_id: string; frames: PreviewFrame[]; problems: string[] }

export function RenderedPreview({ itemId, versionId, kind, note }: { itemId: string; versionId: string; kind: Kind; note?: string }) {
  const q = useQuery<Preview>({
    queryKey: ["studio-preview", itemId, versionId], staleTime: Infinity,
    queryFn: () => api.get(`${STUDIO}/content/${itemId}/preview`, { params: { version_id: versionId } }).then(r => r.data),
  });
  const story = kind === "story";
  const tile = story ? "w-[132px] aspect-[9/16]" : "w-[168px] aspect-[4/5]";
  return (
    <section className="space-y-2" aria-label="How it will look on Instagram">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-[13px] font-bold text-[var(--haip-fg)]">How it will look</h3>
        {note && <span className="text-xs text-[var(--haip-fg-subtle)]">{note}</span>}
      </div>
      {q.isLoading ? (
        <div className="flex gap-2"><Skeleton className={`${tile} rounded-lg`} /><Skeleton className={`${tile} rounded-lg`} /></div>
      ) : q.isError ? (
        <p className="text-sm text-[var(--haip-status-danger-fg)]">{studioError(q.error, "Could not draw the preview.")}</p>
      ) : q.data && q.data.frames.length === 0 ? (
        <p className="rounded-lg bg-[var(--haip-status-warning-bg)] p-3 text-sm text-[var(--haip-status-warning-fg)]">
          {q.data.problems.join(" ") || "Nothing to show yet."}
        </p>
      ) : (
        <ol className="-mx-1 flex snap-x snap-mandatory gap-2 overflow-x-auto px-1 pb-1">
          {q.data?.frames.map((f, i) => (
            <li key={`${f.asset_id}-${i}`} className="shrink-0 snap-start">
              <img src={f.src} alt={f.headline ?? `Image ${i + 1}`} className={`${tile} rounded-lg border border-[var(--haip-border)] object-cover`} />
              {q.data.frames.length > 1 && <span className="mt-1 block text-center text-xs text-[var(--haip-fg-subtle)]">{i + 1} of {q.data.frames.length}</span>}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
