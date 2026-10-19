"use client";
// One call's detail -- the single detail view of the Calls page (replaces
// the old slide-over). Recording, what happened + next step, QA, transcript
// and wrap-up. The agent's wrap-up notes are stored separately from the AI
// summary (POST /calls/{id}/wrap-up saves them to disposition_note).
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useSession } from "next-auth/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, Loader2, MessageSquare, Phone, X } from "@/lib/icons";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { useToast } from "@/components/ui/toast";
import { ChannelBadges } from "@/components/inbox/ChannelBadges";
import { SendQuoteButton } from "@/components/quotes/SendQuoteButton";
import type { GuestChannel } from "@/store/inbox";

interface CallDetail {
  id: string;
  direction: "inbound" | "outbound";
  is_missed?: boolean;
  duration_seconds: number;
  guest_name?: string | null;
  guest_phone?: string | null;
  agent_name?: string | null;
  inquiry_id?: string | null;
  created_at?: string | null;
  started_at?: string | null;
  recording_url?: string | null;
  ai_summary?: string | null;
  ai_next_action?: string | null;
  wrap_up_notes?: string | null;
  disposition?: string | null;
  transcription_status?: string | null;
  transcript?: { turns: { speaker: string; text: string; t0?: number }[] } | null;
  score?: { total_score: number; max_score: number; criteria: { criterion: string; score: number; max_score: number }[] } | null;
  recommended_actions?: { action_type: string; label: string; action_config?: { message_id?: string; conversation_id?: string } }[];
}

// Real CallDisposition values (backend models/call.py). The old filter and
// wrap-up used pending/qualified/spam, which the server never accepted.
export const OUTCOMES: { value: string; label: string; tone: string }[] = [
  { value: "booked", label: "Booked", tone: "bg-violet-50 text-violet-700 border-violet-200" },
  { value: "hot", label: "Hot lead", tone: "bg-rose-50 text-rose-700 border-rose-200" },
  { value: "quoted", label: "Quoted", tone: "bg-primary/10 text-primary border-primary/30" },
  { value: "callback", label: "Callback", tone: "bg-[var(--haip-status-warning-bg)] text-[var(--haip-status-warning-fg)] border-[var(--haip-status-warning-border)]" },
  { value: "lost", label: "Lost", tone: "bg-[var(--haip-status-danger-bg)] text-[var(--haip-status-danger-fg)] border-[var(--haip-status-danger-border)]" },
  { value: "no_answer", label: "No answer", tone: "bg-[var(--haip-surface)] text-[var(--haip-fg-2)] border-[var(--haip-border)]" },
  { value: "voicemail", label: "Voicemail", tone: "bg-[var(--haip-surface)] text-[var(--haip-fg-2)] border-[var(--haip-border)]" },
];

function fmt(s: number) {
  const m = Math.floor(s / 60);
  return `${m}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
}

function humanize(key: string) {
  return key.replace(/[_-]+/g, " ").replace(/^\w/, c => c.toUpperCase());
}

export function CallDetailPanel({
  callId, channels, autoPlay, onClose, className,
}: {
  callId: string;
  channels?: GuestChannel[];
  autoPlay?: boolean;
  onClose?: () => void;
  className?: string;
}) {
  const { toast } = useToast();
  const qc = useQueryClient();
  const { data: session } = useSession();
  const audioRef = useRef<HTMLAudioElement>(null);

  const { data: call, isLoading } = useQuery<CallDetail>({
  queryKey: ["call-detail", callId],
  queryFn: () => api.get(`/calls/${callId}`).then(r => r.data),
  staleTime: 60_000,
  });

  const [outcome, setOutcome] = useState<string>("");
  const [notes, setNotes] = useState("");
  useEffect(() => {
  setOutcome(call?.disposition && call.disposition !== "pending" ? call.disposition : "");
  setNotes(call?.wrap_up_notes ?? "");
  }, [call?.id, call?.disposition, call?.wrap_up_notes]);

  useEffect(() => {
  if (autoPlay && call?.recording_url) audioRef.current?.play().catch(() => { /* autoplay blocked */ });
  }, [autoPlay, call?.recording_url]);

  const callBack = useMutation({
  mutationFn: (guest_number: string) => api.post("/calls/click-to-call", { guest_number }),
  onSuccess: () => toast({ variant: "success", title: "Calling…", description: "Your phone will ring shortly." }),
  onError: (err: any) => toast({ variant: "error", title: "Call failed", description: err?.response?.data?.detail ?? "Could not start call" }),
  });

  const sendDraft = useMutation({
  mutationFn: ({ conversationId, messageId }: { conversationId: string; messageId: string }) =>
  api.post(`/conversations/${conversationId}/messages/${messageId}/approve`),
  onSuccess: () => {
  toast({ variant: "success", title: "Reply sent" });
  qc.invalidateQueries({ queryKey: ["call-detail", callId] });
  },
  onError: (err: any) => toast({ variant: "error", title: "Send failed", description: err?.response?.data?.detail ?? "Please try again." }),
  });

  const saveWrapUp = useMutation({
  mutationFn: () => api.post(`/calls/${callId}/wrap-up`, { disposition: outcome || undefined, notes }),
  onSuccess: () => {
  toast({ variant: "success", title: "Wrap-up saved" });
  qc.invalidateQueries({ queryKey: ["call-detail", callId] });
  qc.invalidateQueries({ queryKey: ["calls"] });
  },
  onError: (err: any) => toast({ variant: "error", title: "Couldn't save", description: err?.response?.data?.detail ?? "Please try again." }),
  });

  // Local recordings come back as a relative API path; <audio> can't send
  // an Authorization header, so the session token goes in the query string
  // (same as the full call page -- the old slide-over omitted it).
  const recordingSrc = call?.recording_url
  ? call.recording_url.startsWith("/")
  ? `${(process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1").replace(/\/api\/v1$/, "")}${call.recording_url}?token=${encodeURIComponent((session as { accessToken?: string } | null)?.accessToken ?? "")}`
  : call.recording_url
  : null;

  const draftAction = call?.recommended_actions?.find(a => a.action_type === "send_whatsapp_draft" && a.action_config?.conversation_id && a.action_config?.message_id);
  const criteria = [...(call?.score?.criteria ?? [])].sort((a, b) => (a.score / (a.max_score || 1)) - (b.score / (b.max_score || 1)));
  const score = call?.score?.total_score != null ? Math.round((call.score.total_score / (call.score.max_score || 100)) * 100) : null;
  const when = call?.created_at ?? call?.started_at;

  return (
  <aside className={cn("flex flex-col min-h-0 overflow-hidden", className)} style={{ background: "var(--haip-card)" }} aria-label="Call details">
  <div className="px-5 py-4 flex items-start gap-3 flex-shrink-0" style={{ borderBottom: "1px solid var(--haip-border)" }}>
  <div className="min-w-0 flex-1">
  <p className="text-lg font-bold truncate" style={{ color: "var(--haip-fg)", fontFamily: "var(--font-display)" }}>
  {isLoading ? "Loading…" : call?.guest_name || call?.guest_phone || "Unknown caller"}
  </p>
  {call && (
  <p className="text-xs mt-0.5" style={{ color: "var(--haip-fg-subtle)" }}>
  {call.is_missed ? "Missed" : call.direction === "outbound" ? "Outgoing" : "Incoming"}
  {call.agent_name ? ` · ${call.agent_name}` : ""}
  {when ? ` · ${new Date(when).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" })}` : ""}
  {call.duration_seconds > 0 ? ` · ${fmt(call.duration_seconds)}` : ""}
  </p>
  )}
  <ChannelBadges channels={channels} size={14} className="mt-1.5" />
  </div>
  <div className="flex items-center gap-2 flex-shrink-0">
  {call?.inquiry_id && (
  <Link href={`/dashboard/leads/${call.inquiry_id}`} className="text-xs font-semibold px-3 py-1.5 rounded-lg border hover:bg-[color:var(--muted)]"
  style={{ borderColor: "var(--haip-border)", color: "var(--haip-fg)" }}>
  Open lead
  </Link>
  )}
  {call?.guest_phone && (
  <button onClick={() => callBack.mutate(call.guest_phone!)} disabled={callBack.isPending}
  className="inline-flex items-center gap-1.5 text-xs font-bold px-3 py-1.5 rounded-lg bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-60">
  {callBack.isPending ? <Loader2 size={12} className="animate-spin" /> : <Phone size={12} />} Call
  </button>
  )}
  {onClose && (
  <button onClick={onClose} aria-label="Close" className="w-8 h-8 flex items-center justify-center rounded-lg hover:bg-[color:var(--muted)]" style={{ color: "var(--haip-fg-subtle)" }}>
  <X size={15} />
  </button>
  )}
  </div>
  </div>

  <div className="flex-1 overflow-y-auto haip-scrollbar px-5 py-4 space-y-5">
  {isLoading || !call ? (
  <div className="py-16 flex justify-center"><Loader2 size={18} className="animate-spin" style={{ color: "var(--haip-fg-subtle)" }} /></div>
  ) : (
  <>
  {recordingSrc ? (
  <audio ref={audioRef} controls preload="none" className="w-full" src={recordingSrc} />
  ) : (
  <p className="text-xs rounded-xl px-4 py-3" style={{ background: "var(--muted)", color: "var(--haip-fg-subtle)" }}>
  {call.is_missed ? "Missed call — no conversation was recorded." : "Recording not available yet."}
  </p>
  )}

  {(call.ai_summary || call.ai_next_action) && (
  <section className="rounded-xl bg-primary/10  p-4">
  <h3 className="text-[10px] font-bold uppercase tracking-wider text-primary ">What happened</h3>
  {call.ai_summary && <p className="text-sm mt-1.5 leading-relaxed" style={{ color: "var(--haip-fg)" }}>{call.ai_summary}</p>}
  {call.ai_next_action && <p className="text-sm font-semibold mt-2 text-primary ">Next: {call.ai_next_action}</p>}
  {draftAction && (
  <button
  onClick={() => sendDraft.mutate({ conversationId: draftAction.action_config!.conversation_id!, messageId: draftAction.action_config!.message_id! })}
  disabled={sendDraft.isPending}
  className="mt-3 inline-flex items-center gap-1.5 text-xs font-bold px-3 py-1.5 rounded-lg bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-60">
  {sendDraft.isPending ? <Loader2 size={12} className="animate-spin" /> : <MessageSquare size={12} />}
  {draftAction.label}
  </button>
  )}
  </section>
  )}

  {score != null && (
  <section>
  <h3 className="text-[10px] font-bold uppercase tracking-wider" style={{ color: "var(--haip-fg-subtle)" }}>QA score</h3>
  <div className="flex items-start gap-4 mt-2">
  <span className={cn("w-14 h-14 rounded-full flex items-center justify-center text-xl font-extrabold flex-shrink-0",
  score >= 85 ? "bg-[var(--haip-status-success-bg)] text-[var(--haip-status-success-fg)]" : score >= 70 ? "bg-[var(--haip-status-warning-bg)] text-[var(--haip-status-warning-fg)]" : "bg-[var(--haip-status-danger-bg)] text-[var(--haip-status-danger-fg)]")}>
  {score}
  </span>
  <div className="flex-1 space-y-1.5 min-w-0">
  {criteria.slice(0, 4).map(c => {
  const pct = Math.max(0, Math.min(1, c.score / (c.max_score || 1)));
  return (
  <div key={c.criterion} className="flex items-center gap-2 text-xs">
  <span className="w-36 truncate" style={{ color: "var(--haip-fg-2, var(--haip-fg))" }}>{humanize(c.criterion)}</span>
  <span className="flex-1 h-1.5 rounded-full bg-[var(--haip-border-strong)]  overflow-hidden">
  <span className={cn("block h-full rounded-full", pct >= 0.85 ? "bg-[var(--haip-status-success-fg)]" : pct >= 0.6 ? "bg-amber-500" : "bg-red-500")} style={{ width: `${pct * 100}%` }} />
  </span>
  <span className="tabular-nums w-8 text-right" style={{ color: "var(--haip-fg-subtle)" }}>{c.score}/{c.max_score}</span>
  </div>
  );
  })}
  {criteria.length > 4 && (
  <Link href={`/dashboard/calls/${call.id}`} className="text-xs font-semibold text-primary">See all {criteria.length} criteria</Link>
  )}
  </div>
  </div>
  </section>
  )}

  {call.transcript?.turns?.length ? (
  <section>
  <div className="flex items-center justify-between">
  <h3 className="text-[10px] font-bold uppercase tracking-wider" style={{ color: "var(--haip-fg-subtle)" }}>Transcript</h3>
  <Link href={`/dashboard/calls/${call.id}`} className="inline-flex items-center gap-1 text-xs font-semibold text-primary">
  Full page <ExternalLink size={11} />
  </Link>
  </div>
  <div className="mt-2 space-y-2.5 max-h-80 overflow-y-auto haip-scrollbar pr-1">
  {call.transcript.turns.map((t, i) => {
  const agent = /agent/i.test(t.speaker);
  return (
  <div key={i}>
  <p className={cn("text-[11px] font-bold", agent ? "text-primary" : "")} style={agent ? undefined : { color: "var(--haip-fg-subtle)" }}>
  {agent ? call.agent_name || "Agent" : call.guest_name || "Guest"}{t.t0 != null ? ` · ${fmt(t.t0)}` : ""}
  </p>
  <p className="text-sm" style={{ color: "var(--haip-fg)" }}>{t.text}</p>
  </div>
  );
  })}
  </div>
  </section>
  ) : !call.is_missed && call.transcription_status && call.transcription_status !== "done" ? (
  <p className="text-xs" style={{ color: "var(--haip-fg-subtle)" }}>Transcript is being prepared.</p>
  ) : null}
  </>
  )}
  </div>

  {call && (
  <div className="px-5 py-3 flex-shrink-0 space-y-2" style={{ borderTop: "1px solid var(--haip-border)" }}>
  <div className="flex items-center justify-between gap-2">
  <p className="text-[10px] font-bold uppercase tracking-wider" style={{ color: "var(--haip-fg-subtle)" }}>Wrap-up</p>
  {/* Price the trip from the call without leaving it (missed call with no lead: phone-only prefill). */}
  <SendQuoteButton variant="primary" args={{ callId: call.id, inquiryId: call.inquiry_id ?? null, phone: call.inquiry_id ? null : call.guest_phone ?? null,
    from: "call", name: call.guest_name || null }} />
  </div>
  <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="Outcome">
  {OUTCOMES.map(o => (
  <button key={o.value} role="radio" aria-checked={outcome === o.value} onClick={() => setOutcome(o.value)}
  className={cn("text-xs font-semibold px-2.5 py-1 rounded-full border", outcome === o.value ? o.tone : "border-[color:var(--haip-border)]")}
  style={outcome === o.value ? undefined : { color: "var(--haip-fg-2, var(--haip-fg))" }}>
  {o.label}
  </button>
  ))}
  </div>
  <div className="flex gap-2">
  <input value={notes} onChange={e => setNotes(e.target.value)} placeholder="Your notes (kept separate from the AI summary)"
  aria-label="Wrap-up notes"
  className="flex-1 min-w-0 text-sm rounded-lg px-3 py-2 outline-none focus-visible:ring-2 focus-visible:ring-primary"
  style={{ background: "var(--muted)", color: "var(--haip-fg)" }} />
  <button onClick={() => saveWrapUp.mutate()} disabled={saveWrapUp.isPending || (!outcome && !notes)}
  className="text-xs font-bold px-4 rounded-lg bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-50">
  {saveWrapUp.isPending ? <Loader2 size={12} className="animate-spin" /> : "Save"}
  </button>
  </div>
  </div>
  )}
  </aside>
  );
}
