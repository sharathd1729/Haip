"use client";
// Instagram profile score out of 100 (Instagram toolkit phase 3). Twelve items; each one that loses points says how to
// fix it. The items are the steps of the "Instagram profile" checklist, so ticking a step (or HAIP's own check passing)
// raises the score. Read-only here: the checklist is where things get done.
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardBody, CardHeader } from "@/components/ui/kit";
import { STUDIO, btn, studioError } from "./types";

interface ScoreItem { id: string; label: string; points: number; max: number; source: "measured" | "checklist" | "todo"; detail: string; fix: string | null }
interface ProfileScoreData { score: number; total: number; started: boolean; sop_id: string | null; items: ScoreItem[] }

export function ProfileScoreCard() {
  const q = useQuery<ProfileScoreData>({ queryKey: ["studio-profile-score"], queryFn: () => api.get(`${STUDIO}/profile-score`).then(r => r.data) });
  const d = q.data;
  const lost = d?.items.filter(i => i.points < i.max) ?? [];
  return (
    <Card>
      <CardHeader title="Instagram profile score" description="Twelve things a guest checks on your profile before they message you." />
      <CardBody>
        {q.isLoading ? <Skeleton className="h-24 w-full" /> : q.isError || !d ? (
          <p className="text-sm text-[var(--haip-status-danger-fg)]">{studioError(q.error, "Could not load the score.")}</p>
        ) : (
          <div className="space-y-3">
            <div className="flex flex-wrap items-baseline gap-2">
              <span className="font-[family-name:var(--font-display)] text-4xl font-extrabold tabular-nums leading-none text-[var(--haip-fg)]">{d.score}</span>
              <span className="text-sm text-[var(--haip-fg-subtle)]">/ {d.total}{lost.length ? ` · fix the top three to gain ${lost.slice(0, 3).reduce((n, i) => n + i.max - i.points, 0)} points` : " · nothing left to fix"}</span>
            </div>
            {!d.started && (
              <p className="rounded-lg bg-[var(--haip-status-info-bg)] p-3 text-sm text-[var(--haip-status-info-fg)]">
                Start the “Instagram profile” checklist: HAIP then checks your name, bio, link and posts, and each step you tick counts here.
              </p>
            )}
            <ul className="divide-y divide-[var(--haip-border)]">
              {d.items.map(i => (
                <li key={i.id} className="py-2">
                  <div className="flex items-start justify-between gap-3 text-sm">
                    <span className="min-w-0 font-medium text-[var(--haip-fg)]">{i.label}</span>
                    <span className="shrink-0 font-mono tabular-nums text-[var(--haip-fg-2)]">{i.points} / {i.max}</span>
                  </div>
                  {i.fix && <p className="text-xs text-[var(--haip-fg-subtle)]">{i.source === "measured" ? `${i.detail} ` : ""}{i.fix}</p>}
                  <progress className="mt-1 h-1.5 w-full accent-[var(--primary)]" value={i.points} max={i.max} aria-label={`${i.label}: ${i.points} of ${i.max}`} />
                </li>
              ))}
            </ul>
            <a className={btn} href={d.sop_id ? `/dashboard/marketing/sops/${d.sop_id}` : "/dashboard/marketing/sops"}>
              {d.sop_id ? "Open the checklist" : "Start the checklist"}
            </a>
          </div>
        )}
      </CardBody>
    </Card>
  );
}
