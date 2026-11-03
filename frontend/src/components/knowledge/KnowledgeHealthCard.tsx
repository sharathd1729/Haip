"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, RefreshCw } from "@/lib/icons";
import api from "@/lib/api";
import { timeAgo } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { Card, CardBody, CardHeader, StatusPill } from "@/components/ui/kit";
import { SourceBadge } from "./SourceBadge";

/** GET /knowledge/health (backend services/knowledge_health.py). Hand-written: there is no OpenAPI generator. */
export type HealthReason = "waiting_approval" | "indexing" | "failed" | "gave_up" | "out_of_date" | "never_used" | "off" | "rejected";

export interface HealthEntry {
  id: string;
  question: string | null;
  preview: string;
  category: string;
  source: string;
  property_id: string | null;
  updated_at: string | null;
  reasons: { code: HealthReason; words: string }[];
  error: string | null;
  times_used: number;
}

export interface HealthReport {
  period_days: number;
  usable: number;
  blocked: number;
  counts: Partial<Record<HealthReason, number>>;
  words: Record<HealthReason, string>;
  replies: { recorded: number; by_search_status: Record<string, number> };
  entries: HealthEntry[];
  entries_capped: boolean;
}

// What a reply's knowledge-base search ended with (concierge_service.kb_record).
const SEARCH_WORDS: Record<string, string> = {
  ok: "found passages",
  no_match: "nothing close enough",
  embedding_unavailable: "search could not run",
  search_failed: "search errored",
  empty_query: "nothing to search with",
  unsupported: "search not available",
};

const TONE: Record<HealthReason, "danger" | "warning" | "info" | "neutral"> = {
  gave_up: "danger", failed: "danger", waiting_approval: "warning", indexing: "info",
  out_of_date: "neutral", never_used: "neutral", off: "neutral", rejected: "neutral",
};

export function KnowledgeHealthCard() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const { data, isPending, isError, error, refetch } = useQuery<HealthReport>({
    queryKey: ["knowledge-health"],
    queryFn: () => api.get("/knowledge/health").then((r) => r.data),
    retry: (count, err) => (err as { response?: { status?: number } })?.response?.status !== 403 && count < 1,
  });

  const reindex = useMutation({
    mutationFn: () => api.post("/knowledge/refresh").then((r) => r.data as { queued_for_indexing: number }),
    onSuccess: (d) => {
      for (const key of ["knowledge-health", "knowledge-freshness", "knowledge", "knowledge-stats"]) {
        queryClient.invalidateQueries({ queryKey: [key] });
      }
      toast({ variant: "success", title: "Re-index started", description: d.queued_for_indexing ? `${d.queued_for_indexing} item(s) re-indexing.` : "Nothing needed re-indexing." });
    },
    onError: () => toast({ variant: "error", title: "Couldn't start re-indexing", description: "Try again in a minute." }),
  });

  // Owner and manager only: everyone else simply does not see the card.
  if (isError && (error as { response?: { status?: number } })?.response?.status === 403) return null;

  const searches = data ? Object.entries(data.replies.by_search_status).sort((a, b) => b[1] - a[1]) : [];

  return (
    <Card>
      <CardHeader
        title="Knowledge health"
        description={data ? `Entries the bot cannot use and why, and what replies got from the knowledge base (last ${data.period_days} days).` : "Entries the bot cannot use and why."}
        actions={
          <button
            type="button"
            onClick={() => reindex.mutate()}
            disabled={reindex.isPending || isPending}
            className="inline-flex min-h-11 items-center gap-1.5 rounded-full bg-primary px-4 text-[14px] font-semibold text-white disabled:opacity-50 sm:min-h-9"
          >
            {reindex.isPending ? <Loader2 size={15} className="animate-spin" /> : <RefreshCw size={15} />} Re-index
          </button>
        }
      />
      <CardBody className="space-y-4">
        {isPending ? (
          <div className="space-y-2" aria-label="Loading">
            <Skeleton className="h-6 w-1/2" />
            <Skeleton className="h-14" />
          </div>
        ) : isError || !data ? (
          <div className="flex flex-wrap items-center gap-3 text-[14px] text-[var(--haip-status-danger-fg)]">
            Couldn&apos;t load knowledge health.
            <button type="button" onClick={() => refetch()} className="min-h-11 font-semibold underline sm:min-h-0">Try again</button>
          </div>
        ) : (
          <>
            <p className="text-[14px] text-[var(--haip-fg)]">
              <span className="font-semibold tabular-nums">{data.usable}</span> usable ·{" "}
              <span className="font-semibold tabular-nums">{data.blocked}</span> the bot cannot use yet
            </p>
            <p className="text-[13px] text-[var(--haip-fg-muted)]">
              {data.replies.recorded === 0
                ? "No replies recorded yet in this period."
                : `${data.replies.recorded} AI replies: ` + searches.map(([s, n]) => `${n} ${SEARCH_WORDS[s] ?? s}`).join(", ") + "."}
            </p>
            {data.entries.length === 0 ? (
              <p className="text-[13.5px] text-[var(--haip-fg-subtle)]">Every entry is usable and was used in this period.</p>
            ) : (
              <ul className="divide-y divide-[var(--haip-border)] rounded-xl border border-[var(--haip-border)]">
                {data.entries.map((e) => (
                  <li key={e.id} className="space-y-1 px-3 py-2.5">
                    <div className="flex flex-wrap items-center gap-2">
                      <SourceBadge source={e.source} />
                      {e.reasons.map((r) => <StatusPill key={r.code} tone={TONE[r.code]}>{r.words}</StatusPill>)}
                      {e.updated_at && <span className="text-[12px] text-[var(--haip-fg-subtle)] sm:ml-auto">updated {timeAgo(e.updated_at)}</span>}
                    </div>
                    <p className="break-words text-[13.5px] text-[var(--haip-fg)]">{e.question || e.preview}</p>
                    {e.error && <p className="break-words text-[12px] text-[var(--haip-status-danger-fg)]">{e.error}</p>}
                  </li>
                ))}
              </ul>
            )}
            {data.entries_capped && <p className="text-[12px] text-[var(--haip-fg-subtle)]">Showing the first {data.entries.length}.</p>}
          </>
        )}
      </CardBody>
    </Card>
  );
}
