"use client";
// The composer at the bottom of the lead thread. Picks WhatsApp or Instagram (the chats this person has), and keeps to
// WhatsApp's 24-hour rule: free text while the window is open, an approved template once it has closed. Sends through
// the Inbox's endpoints (conversations.send on the server). On phones the Call / Quote / Book / More row sits above it.
import { forwardRef, useImperativeHandle, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { Calendar, Calculator, ChevronDown, Instagram, Loader2, MessageSquare, MoreHorizontal, Phone, Send } from "@/lib/icons";
import { TemplatePicker } from "./TemplatePicker";
import { when } from "./format";
import type { FeedChannel, RunAction } from "./types";

const DAY = 86_400_000;

export function windowOpenUntil(ch: FeedChannel | undefined, now = Date.now()): number | null {
  if (!ch?.last_inbound_at) return null;
  const until = Date.parse(ch.last_inbound_at) + DAY;
  return until > now ? until : null;
}

export interface ComposerHandle { focus: () => void }

export const LeadComposer = forwardRef<ComposerHandle, {
  channels: FeedChannel[]; name: string; canSend: boolean; canQuote: boolean; canBook: boolean; hasPhone: boolean;
  run: RunAction; onSent: (channel: string) => void; onError: (msg: string) => void; now?: number;
}>(function LeadComposer({ channels, name, canSend, canQuote, canBook, hasPhone, run, onSent, onError, now }, ref) {
  const sendable = channels.filter(c => c.can_send);
  const [chId, setChId] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [showTemplates, setShowTemplates] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const ch = sendable.find(c => c.conversation_id === chId) ?? sendable[0];
  const isWa = ch?.channel === "whatsapp";
  const openUntil = windowOpenUntil(ch, now);
  const templateMode = isWa && openUntil === null;

  useImperativeHandle(ref, () => ({ focus: () => { if (templateMode) setShowTemplates(true); else inputRef.current?.focus(); } }), [templateMode]);

  const send = useMutation({
    mutationFn: (body: string) => api.post(`/conversations/${ch!.conversation_id}/messages`, { body, direction: "outbound" },
      { headers: { "Idempotency-Key": crypto.randomUUID() } }),
    onSuccess: () => { setText(""); onSent(ch!.channel); },
    onError: (e: unknown) => {
      const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      onError(typeof d === "string" ? d : typeof d === "object" && d && "message" in d ? String((d as { message: unknown }).message) : "The message was not sent. Please try again.");
    },
  });
  const submit = () => { const body = text.trim(); if (body && ch && !send.isPending) send.mutate(body); };

  const btn = "inline-flex min-h-11 flex-1 items-center justify-center gap-1.5 rounded-xl border border-[var(--haip-border-strong)] bg-[var(--haip-card)] px-1.5 text-[13px] font-semibold text-[var(--haip-fg-2)]";
  return (
    <div className="grid gap-1.5 border-t border-[var(--haip-border)] bg-[var(--haip-app-bg)] pt-2 pb-[max(0.5rem,env(safe-area-inset-bottom))]" data-testid="lead-composer">
      <div className="flex gap-1.5 md:hidden" role="group" aria-label="Lead actions">
        {hasPhone && <button type="button" onClick={() => run("call")} className={cn(btn, "border-primary bg-primary text-primary-foreground")}><Phone size={14} aria-hidden />Call</button>}
        {canQuote && <button type="button" onClick={() => run("quote")} className={btn}><Calculator size={14} aria-hidden />Quote</button>}
        {canBook && <button type="button" onClick={() => run("book")} className={btn}><Calendar size={14} aria-hidden />Book</button>}
        <button type="button" onClick={() => run("more")} className={btn}><MoreHorizontal size={14} aria-hidden />More</button>
      </div>

      {!ch ? (
        <p className="rounded-xl bg-[var(--haip-surface)] px-3 py-2.5 text-[13px] text-[var(--haip-fg-muted)]">
          No WhatsApp or Instagram chat with {name} yet.{hasPhone ? " Call, or send a quote from the rate calculator: it opens the WhatsApp chat." : ""}
        </p>
      ) : !canSend ? (
        <p className="rounded-xl bg-[var(--haip-surface)] px-3 py-2.5 text-[13px] text-[var(--haip-fg-muted)]">Your role can read this chat but not send messages.</p>
      ) : (
        <>
          <div className="flex items-end gap-1.5">
            <button type="button" disabled={sendable.length < 2}
              onClick={() => { const next = sendable[(sendable.indexOf(ch) + 1) % sendable.length]; setChId(next.conversation_id); setShowTemplates(false); }}
              aria-label={`Reply on ${isWa ? "WhatsApp" : "Instagram"}${sendable.length > 1 ? ", switch channel" : ""}`}
              className={cn("inline-flex min-h-11 shrink-0 items-center gap-1 rounded-full border border-[var(--haip-border-strong)] bg-[var(--haip-card)] px-3 text-[13px] font-bold",
                isWa ? "text-[var(--haip-status-success-fg)]" : "text-[var(--haip-accent-ink)]")}>
              {isWa ? <MessageSquare size={14} aria-hidden /> : <Instagram size={14} aria-hidden />}{isWa ? "WA" : "IG"}
              {sendable.length > 1 && <ChevronDown size={13} aria-hidden />}
            </button>
            {templateMode ? (
              <button type="button" onClick={() => setShowTemplates(v => !v)} aria-expanded={showTemplates}
                className="inline-flex min-h-11 flex-1 items-center justify-center rounded-full border border-[var(--haip-status-warning-border)] bg-[var(--haip-status-warning-bg)] px-3 text-[13.5px] font-semibold text-[var(--haip-status-warning-fg)]">
                WhatsApp window closed · pick a template
              </button>
            ) : (
              <>
                <textarea ref={inputRef} value={text} onChange={e => setText(e.target.value)} rows={1}
                  onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); } }}
                  placeholder={`Message ${name} on ${isWa ? "WhatsApp" : "Instagram"}…`} aria-label="Message"
                  className="max-h-32 min-h-11 flex-1 resize-none rounded-3xl border border-[var(--haip-border-strong)] bg-[var(--haip-card)] px-4 py-2.5 text-[16px] text-[var(--haip-fg)]" />
                <button type="button" onClick={submit} disabled={!text.trim() || send.isPending} aria-label="Send"
                  className="grid size-11 shrink-0 place-items-center rounded-full bg-primary text-primary-foreground disabled:opacity-50">
                  {send.isPending ? <Loader2 size={17} className="animate-spin" aria-hidden /> : <Send size={17} aria-hidden />}
                </button>
              </>
            )}
          </div>
          {templateMode && showTemplates && (
            <TemplatePicker conversationId={ch.conversation_id} name={name} onError={onError}
              onSent={() => { setShowTemplates(false); onSent("whatsapp"); }} />
          )}
          <p className="px-1 text-[12.5px] text-[var(--haip-fg-subtle)]" data-testid="window-hint">
            {templateMode
              ? `${name} last wrote ${ch.last_inbound_at ? when(ch.last_inbound_at) : "never on WhatsApp"}. WhatsApp only allows an approved template until they reply.`
              : openUntil
                ? `${isWa ? "WhatsApp" : "Instagram"}: free text until ${when(new Date(openUntil).toISOString())}.`
                : `Instagram: ${name} has not written in the last 24 hours, so Instagram may not deliver this.`}
          </p>
        </>
      )}
    </div>
  );
});
