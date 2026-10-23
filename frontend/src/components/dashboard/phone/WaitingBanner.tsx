"use client";
// "3 people waiting for you" on the phone Home. Read off the ONE work queue (GET /work-queue, work_queue_service) with the SAME
// query key as My day and the Now button, so the three can never disagree. People, not rows; the cold tail ("stale") is left
// out, as everywhere on Home. Plain DMs with no phone number are never on it (they are not leads).
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { Skeleton } from "@/components/ui/skeleton";

interface QueueItem { kind: string; severity: string; guest_id: string | null; owner_id?: string | null }
interface Queue { people_waiting?: number; total: number; unowned: number; severity?: { stale?: number }; items: QueueItem[] }

const KIND_WORDS: Record<string, [string, string]> = {
  callback: ["call-back", "call-backs"],
  new_lead: ["new lead", "new leads"],
  reply: ["reply", "replies"],
  consult: ["question from the AI", "questions from the AI"],
  no_reply: ["not replying", "not replying"],
  followup: ["follow-up", "follow-ups"],
};

/** "2 call-backs · 1 new lead · 3 replies": the three biggest reasons among people still waiting (not gone cold). */
export function waitingBreakdown(items: QueueItem[]): string {
  const n: Record<string, number> = {};
  for (const i of items) {
    if (i.kind === "clash" || i.severity === "stale" || !KIND_WORDS[i.kind]) continue;
    n[i.kind] = (n[i.kind] ?? 0) + 1;
  }
  return Object.keys(KIND_WORDS).filter(k => n[k]).slice(0, 3)
    .map(k => `${n[k]} ${KIND_WORDS[k][n[k] === 1 ? 0 : 1]}`).join(" · ");
}

export function WaitingBanner() {
  const { data, isError, refetch } = useQuery<Queue>({
    queryKey: ["work-queue", ""],
    queryFn: () => api.get("/work-queue").then(r => r.data),
    staleTime: 30_000,
    refetchInterval: 60_000,
  });
  if (isError) {
    return (
      <div role="alert" className="haip-card px-4 py-3 text-[13px] text-[var(--haip-fg-2)]">
        Couldn&apos;t load who is waiting. <button type="button" onClick={() => refetch()} className="min-h-11 font-semibold text-primary underline">Try again</button>
      </div>
    );
  }
  if (!data) return <Skeleton className="h-[104px] rounded-2xl" />;
  const n = data.people_waiting ?? Math.max(0, data.total - (data.severity?.stale ?? 0));
  const why = waitingBreakdown(data.items ?? []);
  // New leads nobody owns, among the people counted above (the server's `unowned` also counts the cold tail).
  const unowned = (data.items ?? []).filter(i => i.kind === "new_lead" && !i.owner_id && i.severity !== "stale").length;
  return (
    <section aria-label="Waiting for you" className="grid gap-2 rounded-[calc(var(--radius)+4px)] bg-[var(--haip-stat-dark-bg)] px-4 py-3 text-[var(--haip-stat-dark-fg)]">
      <h2 className="font-[family-name:var(--font-display)] text-[17px] font-semibold leading-tight">
        {n === 0 ? "Nobody is waiting on you" : `${n} ${n === 1 ? "person" : "people"} waiting for you`}
      </h2>
      <p className="text-[13px] text-[var(--haip-stat-dark-muted)]">{n === 0 ? "Every lead has been contacted. Nice." : why || "right now"}</p>
      <div className="flex flex-wrap gap-2">
        <Link href="/dashboard/my-day" className="inline-flex min-h-11 items-center rounded-full bg-[var(--haip-logo-bg)] px-4 text-[13.5px] font-bold text-[var(--haip-logo-fg)]">
          Open My day
        </Link>
        {unowned > 0 && (
          <Link href="/dashboard/my-day?kind=new_lead" className="inline-flex min-h-11 items-center rounded-full bg-[color-mix(in_srgb,var(--haip-stat-dark-fg)_14%,transparent)] px-4 text-[13.5px] font-bold text-[var(--haip-stat-dark-fg)]">
            Assign {unowned}
          </Link>
        )}
      </div>
    </section>
  );
}
