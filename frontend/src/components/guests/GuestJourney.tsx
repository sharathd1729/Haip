"use client";
import { useQuery } from "@tanstack/react-query";
import {
  MessageSquare, Phone, GitBranch, Sparkles, Zap, Merge, Circle,
} from "lucide-react";
import api from "@/lib/api";

/**
 * Guest Journey — the guest's whole history, read from the guest_events ledger.
 *
 * Distinct from the legacy "Activity timeline", which is assembled per request
 * from calls and stays only and never emits messages at all. This spans every
 * module and every inquiry the guest has ever had.
 */

interface GuestEvent {
  id: string;
  guest_id: string | null;
  inquiry_id: string | null;
  entity_type: string;
  entity_id: string;
  event_type: string;
  source_module: string;
  occurred_at: string;
  channel: string | null;
  direction: string | null;
  preview: string | null;
  is_ai_generated: boolean;
}

interface JourneyResponse {
  guest_id: string;
  events: GuestEvent[];
  total_returned: number;
  capped: boolean;
}

const ICONS: Record<string, typeof MessageSquare> = {
  "message.received": MessageSquare,
  "message.sent": MessageSquare,
  "call.completed": Phone,
  "call.analyzed": Phone,
  "inquiry.created": GitBranch,
  "inquiry.stage_moved": GitBranch,
  "inquiry.merged": Merge,
  "automation.executed": Zap,
  "ai.summary_updated": Sparkles,
};

const LABELS: Record<string, string> = {
  "message.received": "Message received",
  "message.sent": "Message sent",
  "call.completed": "Call",
  "call.analyzed": "Call analysed",
  "inquiry.created": "Inquiry created",
  "inquiry.stage_moved": "Stage changed",
  "inquiry.merged": "Leads merged",
  "automation.executed": "Automation ran",
  "ai.summary_updated": "AI summary updated",
};

function formatWhen(iso: string) {
  const then = new Date(iso);
  const mins = Math.floor((Date.now() - then.getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  if (mins < 1440) return `${Math.floor(mins / 60)}h ago`;
  if (mins < 10080) return `${Math.floor(mins / 1440)}d ago`;
  return then.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

export function GuestJourney({ guestId }: { guestId: string }) {
  const { data, isLoading, isError } = useQuery<JourneyResponse>({
    queryKey: ["guest-journey", guestId],
    queryFn: () => api.get(`/guests/${guestId}/journey`).then((r) => r.data),
  });

  if (isLoading) {
    return (
      <div className="space-y-3" aria-busy="true">
        {[0, 1, 2].map((i) => (
          <div key={i} className="h-12 animate-pulse rounded-lg bg-muted" />
        ))}
      </div>
    );
  }

  if (isError) {
    return <p className="py-6 text-center text-sm text-muted-foreground">Couldn&apos;t load the journey.</p>;
  }

  const events = data?.events ?? [];

  if (events.length === 0) {
    return (
      <div className="py-8 text-center">
        <p className="text-sm text-muted-foreground">No journey events yet.</p>
        <p className="mt-1 text-xs text-muted-foreground">
          History is recorded from the point the activity ledger was enabled.
        </p>
      </div>
    );
  }

  return (
    <div>
      <ol className="relative">
        {events.map((ev, idx) => {
          const Icon = ICONS[ev.event_type] ?? Circle;
          const isLast = idx === events.length - 1;
          return (
            <li key={ev.id} className="relative flex gap-3 pb-4">
              {!isLast && (
                <span
                  className="absolute left-[13px] top-7 h-[calc(100%-1rem)] w-px bg-border"
                  aria-hidden
                />
              )}
              <span className="relative z-10 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-border bg-card">
                <Icon className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-baseline gap-x-2">
                  <span className="text-sm font-medium text-foreground">
                    {LABELS[ev.event_type] ?? ev.event_type}
                  </span>
                  {ev.channel && ev.channel !== "system" && (
                    <span className="text-xs text-muted-foreground">via {ev.channel}</span>
                  )}
                  {ev.is_ai_generated && (
                    <span className="inline-flex items-center gap-0.5 text-xs text-primary">
                      <Sparkles className="h-3 w-3" aria-hidden /> AI
                    </span>
                  )}
                  <span className="ml-auto text-xs text-muted-foreground">
                    {formatWhen(ev.occurred_at)}
                  </span>
                </div>
                {ev.preview && (
                  <p className="mt-0.5 truncate text-sm text-muted-foreground">{ev.preview}</p>
                )}
              </div>
            </li>
          );
        })}
      </ol>

      {data?.capped && (
        <p className="pt-1 text-center text-xs text-muted-foreground">
          Showing the {data.total_returned} most recent events.
        </p>
      )}
    </div>
  );
}

export default GuestJourney;
