"use client";
import { useState } from "react";
import { useSession } from "next-auth/react";
import { Phone, ChevronDown, TrendingUp } from "@/lib/icons";
import Link from "next/link";
import { CallPlayer } from "@/components/calls/CallPlayer";

/** HAIP Inbox prototype-wiring plan, ticket 2/5: renders one call item from
 * GET /conversations/{id}/timeline in the merged thread. Only real fields --
 * no per-segment sentiment, no buying_signals/objections (those don't exist
 * on the Call/Transcript models, unlike the prototype's mock data). */

export interface CallTimelineItem {
  id: string;
  direction: "inbound" | "outbound";
  duration_seconds: number;
  started_at?: string | null;
  recording_url?: string | null;
  ai_summary?: string | null;
  conversion_probability?: number | null;
  turns: { speaker: string; text: string; t0: number; t1: number }[];
}

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}m ${s}s`;
}

export function CallLogCard({ call }: { call: CallTimelineItem }) {
  const [expanded, setExpanded] = useState(false);
  const { data: session } = useSession();

  // HAIP Inbox full-parity pass, ticket 6: reuses the exact same local-file
  // token-append pattern /dashboard/calls/[id]/page.tsx already uses --
  // local recordings come back as a relative /api/v1/... path and need the
  // session token as a query param so the bare <audio> element (no custom
  // headers) can authenticate.
  const resolvedRecordingUrl = call.recording_url
    ? call.recording_url.startsWith("/")
      ? (() => {
          const base = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1").replace(/\/api\/v1$/, "");
          const tok = (session as any)?.accessToken ?? "demo";
          return `${base}${call.recording_url}?token=${encodeURIComponent(tok)}`;
        })()
      : call.recording_url
    : null;

  return (
    <div className="my-2 max-w-2xl mx-auto w-full">
      <div className="p-3.5 rounded-2xl border bg-white shadow-sm" style={{ borderColor: "var(--haip-border, #e5e7eb)" }}>
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <div className="p-1.5 rounded-lg bg-blue-50 text-blue-600 flex-shrink-0">
              <Phone size={14} />
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-1.5 text-xs font-bold text-[var(--haip-fg)]">
Call · {call.direction}
                <span className="text-[9px] font-bold px-1.5 py-0.5 rounded-full bg-blue-50 text-blue-600 border border-blue-100">
                  Sarvam AI
                </span>
              </div>
              <p className="text-[11px] text-[var(--haip-fg-subtle)]">{formatDuration(call.duration_seconds)}</p>
            </div>
          </div>
          {call.conversion_probability != null && (
            <span className="flex items-center gap-1 text-[10px] font-bold text-emerald-600 flex-shrink-0">
              <TrendingUp size={11} /> {call.conversion_probability}%
            </span>
          )}
        </div>

        {resolvedRecordingUrl && (
          <div className="mt-2">
            <CallPlayer recordingUrl={resolvedRecordingUrl} duration={call.duration_seconds} className="p-2.5" />
          </div>
        )}

        {call.ai_summary && (
          <p className="mt-2 text-xs text-[var(--haip-fg-muted)] leading-relaxed">{call.ai_summary}</p>
        )}

        {call.turns.length > 0 && (
          <div className="mt-2 pt-2 border-t border-[var(--haip-border)]">
            <button
              type="button"
              onClick={() => setExpanded(v => !v)}
              className="text-[11px] font-bold text-primary flex items-center justify-between w-full"
            >
              <span>View transcript</span>
              <ChevronDown size={13} className={expanded ? "rotate-180 transition-transform" : "transition-transform"} />
            </button>
            {expanded && (
              <div className="mt-2 p-2.5 rounded-xl bg-[var(--haip-surface)] space-y-1.5 text-[11px] font-mono max-h-56 overflow-y-auto">
                {call.turns.map((t, i) => (
                  <div key={i} className="flex gap-1.5 text-[var(--haip-fg-2)]">
                    <span className="font-bold text-primary flex-shrink-0">{t.speaker}:</span>
                    <span className="font-sans text-[var(--haip-fg-muted)]">{t.text}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        <div className="mt-2 pt-2 border-t border-[var(--haip-border)]">
          <Link
            href={`/dashboard/calls/${call.id}`}
            className="text-[11px] font-semibold text-primary hover:underline"
          >
            View full call detail →
          </Link>
        </div>
      </div>
    </div>
  );
}
