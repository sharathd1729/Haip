"use client";
// Calling from the lead page. POST /calls/click-to-call with the lead's inquiry_id: HAIP rings the agent's own phone
// from the business number, then dials the guest once the agent picks up. HAIP cannot hang up or follow the call
// live (no such API), so the panel only says what it knows: the request went out, then the call once it is logged
// (the feed is polled while the panel waits). Never a tel: link.
import { useEffect, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import api from "@/lib/api";
import { Loader2, Phone, X } from "@/lib/icons";
import { StatusPill } from "@/components/ui/page";
import { durationText } from "./format";
import type { FeedItem } from "./types";

export type CallPhase = "idle" | "starting" | "ringing" | "waiting" | "logged" | "failed";
const POLL_MS = 5_000;
const GIVE_UP_MS = 3 * 60_000;

function detail(e: unknown): string {
  const raw = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof raw === "string") return raw;
  if (Array.isArray(raw)) return raw.map((x: { msg?: string }) => x?.msg ?? JSON.stringify(x)).join("; ");
  return "Could not start the call. Check your connection and try again.";
}

export function useClickToCall(inquiryId: string, calls: FeedItem[], refetch: () => void) {
  const [phase, setPhase] = useState<CallPhase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [newCallId, setNewCallId] = useState<string | null>(null);
  const baseline = useRef<Set<string>>(new Set());
  const refetchRef = useRef(refetch);
  refetchRef.current = refetch;

  const start = useMutation({
    mutationFn: () => api.post("/calls/click-to-call", { inquiry_id: inquiryId }),
    onMutate: () => { baseline.current = new Set(calls.map(c => c.id)); setNewCallId(null); setError(null); setPhase("starting"); },
    onSuccess: () => setPhase("ringing"),
    onError: (e: unknown) => { setError(detail(e)); setPhase("failed"); },
  });

  // Watch the thread for the call to arrive.
  useEffect(() => {
    if (phase !== "ringing" && phase !== "waiting") return;
    const fresh = calls.find(c => !baseline.current.has(c.id));
    if (fresh) { setNewCallId(fresh.id); setPhase("logged"); }
  }, [calls, phase]);

  useEffect(() => {
    if (phase !== "ringing") return;
    const poll = setInterval(() => refetchRef.current(), POLL_MS);
    const stop = setTimeout(() => setPhase(p => (p === "ringing" ? "waiting" : p)), GIVE_UP_MS);
    return () => { clearInterval(poll); clearTimeout(stop); };
  }, [phase]);

  return {
    phase, error, newCall: calls.find(c => c.id === newCallId) ?? null,
    start: () => { if (phase !== "starting" && phase !== "ringing") start.mutate(); },
    close: () => setPhase("idle"),
  };
}

const STEPS = ["Ringing you", "Connecting", "Logged"];

// Callbacks stay calls (sales team, 22 Oct 2026): after an unanswered call the panel offers another try or logging a call
// made from the agent's own phone, never "WhatsApp instead".
export function CallPanel({ phase, error, newCall, name, onClose, onRetry, onLogCall, onSendPackage }: {
  phase: CallPhase; error: string | null; newCall: FeedItem | null; name: string;
  onClose: () => void; onRetry: () => void; onLogCall?: () => void; onSendPackage?: () => void;
}) {
  const packageBtn = onSendPackage && (
    <button type="button" onClick={onSendPackage} className="inline-flex min-h-11 items-center rounded-xl border border-[var(--haip-border-strong)] px-4 text-[14px] font-semibold text-[var(--haip-fg-2)]">Send package</button>
  );
  const logBtn = onLogCall && (
    <button type="button" onClick={onLogCall} className="inline-flex min-h-11 items-center rounded-xl border border-[var(--haip-border-strong)] px-4 text-[14px] font-semibold text-[var(--haip-fg-2)]">Log a call</button>
  );
  if (phase === "idle") return null;
  const step = phase === "logged" ? 2 : phase === "starting" ? 0 : 1;
  return (
    <section role="dialog" aria-label="Call through HAIP" aria-live="polite" data-testid="call-panel"
      className="fixed inset-x-0 bottom-0 z-50 grid gap-2.5 rounded-t-3xl border-t border-[var(--haip-border)] bg-[var(--haip-card)] px-4 pb-[max(1rem,env(safe-area-inset-bottom))] pt-3 shadow-[var(--haip-shadow-lg)] md:inset-x-auto md:bottom-6 md:right-6 md:w-[380px] md:rounded-3xl md:border">
      <div className="flex items-center justify-between gap-2">
        <StatusPill tone="brand"><Phone size={12} aria-hidden /> Call through HAIP</StatusPill>
        <button type="button" onClick={onClose} aria-label="Close" className="grid size-11 place-items-center rounded-xl text-[var(--haip-fg-muted)] hover:bg-[var(--haip-surface)]">
          <X size={18} aria-hidden />
        </button>
      </div>
      {phase !== "failed" && (
        <ol className="grid grid-cols-3 gap-1">
          {STEPS.map((s, i) => (
            <li key={s} className={i < step || (i === 2 && phase === "logged") ? "border-t-[3px] border-primary pt-1 text-[11.5px] font-semibold text-primary"
              : i === step ? "border-t-[3px] border-[var(--haip-accent)] pt-1 text-[11.5px] font-semibold text-[var(--haip-fg)]"
                : "border-t-[3px] border-[var(--haip-border-strong)] pt-1 text-[11.5px] font-semibold text-[var(--haip-fg-subtle)]"}>{s}</li>
          ))}
        </ol>
      )}
      {phase === "starting" && (
        <p className="flex items-center gap-2 text-[15px] font-semibold text-[var(--haip-fg)]"><Loader2 size={16} className="animate-spin" aria-hidden /> Starting the call…</p>
      )}
      {phase === "ringing" && (
        <>
          <h2 className="font-[family-name:var(--font-display)] text-[19px] font-semibold text-[var(--haip-fg)]">Ringing your phone…</h2>
          <p className="text-[14px] text-[var(--haip-fg-2)]">Pick up, then we connect {name}. {name} sees the business number, not yours. The call is recorded.</p>
          <p className="text-[12.5px] text-[var(--haip-fg-subtle)]">Talk and hang up on your phone. The call appears in this conversation once it is logged.</p>
        </>
      )}
      {phase === "waiting" && (
        <>
          <p className="text-[14px] text-[var(--haip-fg-2)]">The call has not been logged yet. It appears in the conversation as soon as the phone company reports it, usually right after you hang up.</p>
          {logBtn && <p className="flex flex-wrap items-center gap-2 text-[12.5px] text-[var(--haip-fg-subtle)]">Called from your own phone instead? {logBtn}</p>}
        </>
      )}
      {phase === "logged" && newCall && (
        <>
          <h2 className="font-[family-name:var(--font-display)] text-[19px] font-semibold text-[var(--haip-fg)]">
            {newCall.answered ? `Call logged · ${durationText(newCall.duration_seconds)}` : `${name} didn't answer`}
          </h2>
          <p className="text-[14px] text-[var(--haip-fg-2)]">
            {newCall.answered ? "The recording, transcript and AI summary appear in the conversation in a few minutes."
              : "Logged as a call attempt. Try again in a while; if they ring you back on your own phone, log that call here."}
          </p>
          {newCall.answered && packageBtn && <div className="flex flex-wrap gap-2">{packageBtn}</div>}
          {!newCall.answered && (
            <div className="flex flex-wrap gap-2">
              <button type="button" onClick={onRetry} className="inline-flex min-h-11 items-center rounded-xl bg-primary px-4 text-[14px] font-semibold text-primary-foreground">Try again</button>
              {logBtn}
            </div>
          )}
        </>
      )}
      {phase === "failed" && (
        <>
          <h2 className="font-[family-name:var(--font-display)] text-[19px] font-semibold text-[var(--haip-fg)]">The call did not start</h2>
          <p className="text-[14px] text-[var(--haip-status-danger-fg)]">{error}</p>
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={onRetry} className="inline-flex min-h-11 items-center rounded-xl border border-[var(--haip-border-strong)] px-4 text-[14px] font-semibold text-[var(--haip-fg-2)]">Try again</button>
            {logBtn}
          </div>
        </>
      )}
    </section>
  );
}
