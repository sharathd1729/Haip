"use client";
// Brand review of the current text (GET/POST /content/{id}/review). "Checks" are deterministic and always current;
// a "must fix" one stops the agency from sending the draft for approval. "Editor's notes" are the AI editor's advice.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill, type Tone } from "@/components/ui/kit";
import { STUDIO, btn, studioError } from "./types";

interface Finding { rule: string; severity: "high" | "medium" | "low"; where: string; message: string; quote: string | null; suggestion: string | null }
type Scores = Record<"hook" | "specificity" | "voice" | "clarity" | "ask", number>;
interface Review {
  status: "none" | "skipped" | "pending" | "ready" | "failed"; blocking: boolean; findings: Finding[]; advice: Finding[];
  summary: string | null; error: string | null; scores?: Scores | null; weak?: string[];
}
const SCORE_LABEL: Record<keyof Scores, string> = { hook: "Hook", specificity: "Specific", voice: "Voice", clarity: "Clear", ask: "Ask" };

/** The critic's 1-5 marks (agency M3). Below the bar the agency rewrites once; the marks never block a person. */
function ScoreRow({ scores, weak }: { scores: Scores; weak: string[] }) {
  return (
    <ul className="flex flex-wrap gap-1.5" aria-label="Critic's marks out of 5">
      {(Object.keys(SCORE_LABEL) as (keyof Scores)[]).map(k => (
        <li key={k}><StatusPill tone={scores[k] <= 2 ? "danger" : weak.includes(k) ? "warning" : "success"}>{SCORE_LABEL[k]} {scores[k]}/5</StatusPill></li>
      ))}
    </ul>
  );
}

const SEVERITY: Record<Finding["severity"], { label: string; tone: Tone }> = {
  high: { label: "Must fix", tone: "danger" }, medium: { label: "Should fix", tone: "warning" }, low: { label: "Polish", tone: "neutral" },
};

function Item({ f }: { f: Finding }) {
  return (
    <li className="space-y-1 rounded-lg border border-[var(--haip-border)] p-3">
      <p className="flex flex-wrap items-center gap-2 text-xs text-[var(--haip-fg-subtle)]">
        <StatusPill tone={SEVERITY[f.severity].tone}>{SEVERITY[f.severity].label}</StatusPill>{f.where}
      </p>
      <p className="text-sm text-[var(--haip-fg)]">{f.message}</p>
      {f.quote && <p className="text-sm text-[var(--haip-fg-2)]">“{f.quote}”</p>}
      {f.suggestion && <p className="text-xs text-[var(--haip-fg-subtle)]">{f.suggestion}</p>}
    </li>
  );
}

export function BrandReviewPanel({ itemId, versionId, canAsk }: { itemId: string; versionId: string; canAsk: boolean }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const key = ["studio-review", itemId, versionId];
  const q = useQuery<Review>({
    queryKey: key, queryFn: () => api.get(`${STUDIO}/content/${itemId}/review`).then(r => r.data),
    refetchInterval: d => (d.state.data?.status === "pending" ? 4000 : false),
  });
  const ask = useMutation({
    mutationFn: () => api.post(`${STUDIO}/content/${itemId}/review`).then(r => r.data as Review),
    onSuccess: d => qc.setQueryData(key, d),
    onError: e => toast({ variant: "error", title: "Review not started", description: studioError(e, "Try again.") }),
  });
  const r = q.data;
  return (
    <section className="space-y-2" aria-label="Brand review">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-[13px] font-bold text-[var(--haip-fg)]">Brand review</h3>
        {canAsk && r && r.status !== "pending" && (
          <button type="button" className={btn} disabled={ask.isPending} onClick={() => ask.mutate()}>
            {r.status === "ready" ? "Ask the editor again" : "Ask the AI editor"}
          </button>
        )}
      </div>
      {q.isLoading ? <Skeleton className="h-16 w-full" /> : q.isError ? (
        <p className="text-sm text-[var(--haip-status-danger-fg)]">{studioError(q.error, "Could not load the review.")}</p>
      ) : r && (
        <>
          {r.blocking ? (
            <p className="rounded-lg bg-[var(--haip-status-danger-bg)] p-3 text-sm text-[var(--haip-status-danger-fg)]">
              Fix the items marked “Must fix” before this goes out. The agency won't send it for approval while they stand.
            </p>
          ) : r.findings.length === 0 ? (
            <p className="text-sm text-[var(--haip-fg-subtle)]">The checks found nothing to fix.</p>
          ) : null}
          {r.findings.length > 0 && <ul className="space-y-2">{r.findings.map((f, i) => <Item key={`c${i}`} f={f} />)}</ul>}
          {r.status === "pending" && <p className="text-sm text-[var(--haip-fg-subtle)]">The AI editor is reading the draft…</p>}
          {r.status === "failed" && r.error && <p className="text-sm text-[var(--haip-status-danger-fg)]">{r.error}</p>}
          {r.status === "ready" && (
            <div className="space-y-2">
              {r.scores && <ScoreRow scores={r.scores} weak={r.weak ?? []} />}
              <p className="text-[13px] font-semibold text-[var(--haip-fg-2)]">Editor's notes{r.summary ? `: ${r.summary}` : ""}</p>
              {r.advice.length > 0 && <ul className="space-y-2">{r.advice.map((f, i) => <Item key={`a${i}`} f={f} />)}</ul>}
            </div>
          )}
        </>
      )}
    </section>
  );
}
