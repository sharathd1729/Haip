"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RotateCcw } from "@/lib/icons";
import api from "@/lib/api";
import { timeAgo } from "@/lib/utils";
import { useToast } from "@/components/ui/toast";
import { Skeleton } from "@/components/ui/skeleton";
import { Drawer } from "@/components/ui/kit";

interface Change { from: unknown; to: unknown }
interface Event { id: string; action: string; at: string; actor_user_id?: string | null; changes?: Record<string, Change> | null; values?: Record<string, unknown> | null }

const FIELD: Record<string, string> = {
  category: "Category", question: "Question", content: "Answer", property_id: "Property", priority: "Priority",
  is_active: "In use", review_status: "Review", alt_phrasings: "Other phrasings",
};
const ACTION: Record<string, string> = {
  created: "Added", updated: "Edited", deleted: "Deleted", rolled_back: "Earlier wording restored", reindex_requested: "Re-indexing requested",
};
const show = (v: unknown) => (v == null || v === "" ? "—" : Array.isArray(v) ? v.join("; ") || "—" : typeof v === "boolean" ? (v ? "yes" : "no") : String(v));

/** Who changed a knowledge entry and what it said before. An edit can be undone; the restored wording is re-indexed before the AI uses it. */
export function KnowledgeHistoryDrawer({ entryId, onClose }: { entryId: string | null; onClose: () => void }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const { data = [], isLoading, isError } = useQuery<Event[]>({
    queryKey: ["knowledge-history", entryId], enabled: !!entryId,
    queryFn: () => api.get(`/knowledge/${entryId}/history`).then(r => r.data),
  });
  const restore = useMutation({
    mutationFn: (eventId: string) => api.post(`/knowledge/${entryId}/rollback`, { event_id: eventId }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["knowledge"] });
      qc.invalidateQueries({ queryKey: ["knowledge-stats"] });
      qc.invalidateQueries({ queryKey: ["knowledge-history", entryId] });
      toast({ variant: "success", title: "Earlier wording restored", description: "The AI uses it once indexing shows as done." });
      onClose();
    },
    onError: (e: unknown) => {
      const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      toast({ variant: "error", title: "Couldn't restore that wording", description: typeof d === "string" ? d : "Try again." });
    },
  });

  return (
    <Drawer open={!!entryId} onOpenChange={o => { if (!o) onClose(); }} title="History" description="Every change to this entry, newest first.">
      {isLoading ? <Skeleton className="h-24 rounded-xl" /> : isError ? (
        <p role="alert" className="text-sm text-[var(--haip-status-danger-fg)]">Couldn&apos;t load the history. Try again in a moment.</p>
      ) : data.length === 0 ? (
        <p className="text-sm text-[var(--haip-fg-subtle)]">No recorded changes yet.</p>
      ) : (
        <ol className="space-y-3">
          {data.map(ev => (
            <li key={ev.id} className="space-y-2 rounded-xl border border-[var(--haip-border)] p-3">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="text-sm font-bold">{ACTION[ev.action] ?? ev.action}</span>
                <span className="text-[11px] text-[var(--haip-fg-subtle)]">{timeAgo(ev.at)}</span>
              </div>
              {ev.changes && Object.entries(ev.changes).map(([f, c]) => (
                <p key={f} className="break-words text-xs">
                  <span className="font-semibold">{FIELD[f] ?? f}:</span>{" "}
                  <span className="text-[var(--haip-fg-subtle)] line-through">{show(c.from)}</span> → <span>{show(c.to)}</span>
                </p>
              ))}
              {ev.action === "updated" && ev.changes && (
                <button disabled={restore.isPending} onClick={() => { if (window.confirm("Put the earlier wording back? The AI stops using this entry until it is re-indexed.")) restore.mutate(ev.id); }}
                  className="flex min-h-11 items-center gap-1 rounded-lg border border-[var(--haip-border)] px-3 text-xs font-semibold hover:bg-[var(--haip-surface)] sm:min-h-9">
                  <RotateCcw size={12} /> Undo this edit
                </button>
              )}
            </li>
          ))}
        </ol>
      )}
    </Drawer>
  );
}
