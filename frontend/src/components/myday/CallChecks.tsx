"use client";
// My day's "Check the AI" card: recent calls the AI read that no person has confirmed (GET /work-queue `call_checks`,
// work_queue_signals.call_checks). A QA chore, not a person waiting, so it sits below the people lists and never counts
// toward them. Each row confirms in place with the same "Was the AI right?" control as the call page.
import Link from "next/link";
import { Card, CardHeader } from "@/components/ui/kit";
import { AiCheck } from "@/components/calls/AiCheck";
import { Phone } from "@/lib/icons";

export interface CallChecksData {
  count: number;
  calls: { call_id: string; ai_disposition: string; direction: string; created_at: string | null; duration_seconds: number; guest_name: string | null }[];
}

const when = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit", timeZone: "Asia/Kolkata" }) : "";

export function CallChecks({ data }: { data?: CallChecksData }) {
  if (!data?.count) return null;
  const more = data.count - data.calls.length;
  return (
    <Card className="overflow-hidden">
      <CardHeader icon={Phone} tone="plain" title={`Check the AI · ${data.count}`}
        description="Calls from the last 7 days. One tap each teaches HAIP what really happened." />
      <ul>
        {data.calls.map(c => (
          <li key={c.call_id} className="space-y-1 border-t border-[var(--haip-border)] px-4 py-3 first:border-t-0 sm:px-5">
            <Link href={`/dashboard/calls/${c.call_id}`} className="block min-h-11 py-1 text-sm hover:underline">
              <span className="font-semibold text-[var(--haip-fg)]">{c.guest_name || "Unknown caller"}</span>
              <span className="text-[var(--haip-fg-subtle)]"> · {c.direction === "outbound" ? "You called" : "Called in"} · {when(c.created_at)}</span>
            </Link>
            <AiCheck callId={c.call_id} ai={c.ai_disposition} />
          </li>
        ))}
      </ul>
      {more > 0 && (
        <p className="border-t border-[var(--haip-border)] px-4 py-3 text-[13px] text-[var(--haip-fg-subtle)] sm:px-5">
          {more} more after these.
        </p>
      )}
    </Card>
  );
}
