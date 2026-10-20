"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ExternalLink, X } from "@/lib/icons";
import api from "@/lib/api";
import { timeAgo } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { Card, CardBody, CardHeader } from "@/components/ui/kit";
import { FlagBadges, SourceBadge } from "./SourceBadge";

/** Sources that arrive on their own (not typed by the team) and wait here for one-click approval. */
export const QUEUED_SOURCES = ["instagram", "meta_ad", "owner_notes"];

interface QueuedEntry {
  id: string;
  source: string;
  question?: string | null;
  content: string;
  source_url?: string | null;
  source_published_at?: string | null;
  content_flags?: string[] | null;
  created_at: string;
}

export function SocialApprovalQueue() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const { data, isPending, isError, refetch } = useQuery<QueuedEntry[]>({
    queryKey: ["knowledge-approvals"],
    queryFn: () =>
      api.get("/knowledge", { params: { review_status: "pending", limit: 200 } })
        .then((r) => (r.data.items as QueuedEntry[]).filter((e) => QUEUED_SOURCES.includes(e.source))),
    retry: 1,
  });

  const decide = useMutation({
    mutationFn: ({ id, review_status }: { id: string; review_status: "approved" | "rejected" }) =>
      api.patch(`/knowledge/${id}`, { review_status }),
    onSuccess: (_d, v) => {
      for (const key of ["knowledge-approvals", "knowledge", "knowledge-stats", "knowledge-freshness"]) {
        queryClient.invalidateQueries({ queryKey: [key] });
      }
      toast({
        variant: "success",
        title: v.review_status === "approved" ? "Approved" : "Rejected",
        description: v.review_status === "approved" ? "The bot uses it as soon as it is indexed." : undefined,
      });
    },
    onError: (e: unknown) => {
      const status = (e as { response?: { status?: number } })?.response?.status;
      toast({ variant: "error", title: status === 403 ? "Only the owner can approve knowledge" : "Couldn't update that item" });
    },
  });

  if (!isPending && !isError && (data?.length ?? 0) === 0) return null;   // nothing waiting: no empty card on the page

  return (
    <Card>
      <CardHeader
        title="Waiting for your approval"
        description="Instagram posts, ads and imported notes. The bot does not use them until you approve."
      />
      <CardBody>
        {isPending ? (
          <div className="space-y-2" aria-label="Loading">
            <Skeleton className="h-20" />
            <Skeleton className="h-20" />
          </div>
        ) : isError ? (
          <div className="flex flex-wrap items-center gap-3 text-[14px] text-[var(--haip-status-danger-fg)]">
            Couldn&apos;t load the items waiting for approval.
            <button type="button" onClick={() => refetch()} className="min-h-11 font-semibold underline sm:min-h-0">Try again</button>
          </div>
        ) : (
          <ul className="space-y-2">
            {(data ?? []).map((e) => (
              <li key={e.id} className="rounded-xl border border-[var(--haip-border)] p-3">
                <div className="flex flex-wrap items-center gap-1.5">
                  <SourceBadge source={e.source} />
                  <FlagBadges flags={e.content_flags} />
                  <span className="text-[12px] text-[var(--haip-fg-subtle)]">
                    {e.source_published_at ? `posted ${timeAgo(e.source_published_at)}` : `added ${timeAgo(e.created_at)}`}
                  </span>
                  {e.source_url && (
                    <a href={e.source_url} target="_blank" rel="noopener noreferrer"
                       className="inline-flex min-h-11 items-center gap-1 text-[12.5px] font-semibold text-primary sm:min-h-0">
                      <ExternalLink size={12} /> Open
                    </a>
                  )}
                </div>
                {e.question && <p className="mt-1.5 text-[14px] font-semibold text-[var(--haip-fg)]">{e.question}</p>}
                <p className="mt-1 line-clamp-4 whitespace-pre-wrap text-[13.5px] leading-relaxed text-[var(--haip-fg-muted)] [overflow-wrap:anywhere]">{e.content}</p>
                <div className="mt-2 flex flex-wrap gap-2">
                  <button type="button" disabled={decide.isPending}
                          onClick={() => decide.mutate({ id: e.id, review_status: "approved" })}
                          className="inline-flex min-h-11 items-center gap-1.5 rounded-full bg-primary px-4 text-[14px] font-semibold text-white disabled:opacity-50 sm:min-h-9">
                    <Check size={14} /> Approve
                  </button>
                  <button type="button" disabled={decide.isPending}
                          onClick={() => decide.mutate({ id: e.id, review_status: "rejected" })}
                          className="inline-flex min-h-11 items-center gap-1.5 rounded-full border border-[var(--haip-border)] px-4 text-[14px] font-semibold text-[var(--haip-fg-2)] disabled:opacity-50 sm:min-h-9">
                    <X size={14} /> Reject
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardBody>
    </Card>
  );
}
