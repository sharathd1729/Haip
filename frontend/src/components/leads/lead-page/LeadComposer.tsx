"use client";
// The composer at the bottom of the lead thread. Picks WhatsApp or Instagram (the chats this person has) and starts on the
// one that can deliver now: a chat whose 24-hour window is open, else WhatsApp with a template. WhatsApp outside its window
// = an approved template; Instagram outside its window = no send at all (Meta drops it), WhatsApp is offered instead. A
// guest with a number but no WhatsApp chat (wrote on Instagram, typed their number) gets "Start on WhatsApp": a template to
// that number from the business WhatsApp (POST /guests/{id}/whatsapp/start). Sends through the Inbox's endpoints
// (conversations.send on the server). On phones the Call / Quote / Book / More row sits above it.
import { forwardRef, useImperativeHandle, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { Calendar, Calculator, ChevronDown, Instagram, Loader2, MessageSquare, MoreHorizontal, Phone, Send } from "@/lib/icons";
import { TemplatePicker } from "./TemplatePicker";
import { when } from "./format";
import type { FeedChannel, RunAction } from "./types";

const DAY = 86_400_000;
const START = "__whatsapp_start";

export function windowOpenUntil(ch: FeedChannel | undefined, now = Date.now()): number | null {
  if (!ch?.last_inbound_at) return null;
  const until = Date.parse(ch.last_inbound_at) + DAY;
  return until > now ? until : null;
}

/** Best first: a chat that takes free text now (WhatsApp before Instagram), WhatsApp with a template, Start on WhatsApp,
 * and last an Instagram chat whose window has closed. */
export function deliverableOrder(options: FeedChannel[], now = Date.now()): FeedChannel[] {
  const rank = (c: FeedChannel) => {
    const wa = c.channel === "whatsapp";
    if (windowOpenUntil(c, now) !== null) return wa ? 0 : 1;
    if (wa) return c.conversation_id === START ? 3 : 2;
    return 4;
  };
  return [...options].sort((a, b) => rank(a) - rank(b));
}

export interface ComposerHandle { focus: (channel?: "whatsapp") => void }

export const LeadComposer = forwardRef<ComposerHandle, {
  channels: FeedChannel[]; name: string; canSend: boolean; canQuote: boolean; canBook: boolean; hasPhone: boolean;
  run: RunAction; onSent: (channel: string) => void; onError: (msg: string) => void; now?: number;
  /** The guest has a usable number: offer Start on WhatsApp when there is no WhatsApp chat to send on. */
  startWhatsApp?: { guestId: string; inquiryId?: string | null } | null;
}>(function LeadComposer({ channels, name, canSend, canQuote, canBook, hasPhone, run, onSent, onError, now, startWhatsApp }, ref) {
  const sendable = channels.filter(c => c.can_send);
  const startOption: FeedChannel | null = startWhatsApp && !sendable.some(c => c.channel === "whatsapp")
    ? { conversation_id: START, channel: "whatsapp", can_send: true, ai_enabled: false, last_inbound_at: null } : null;
  const options = deliverableOrder(startOption ? [...sendable, startOption] : sendable, now);
  const [chId, setChId] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [showTemplates, setShowTemplates] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const ch = options.find(c => c.conversation_id === chId) ?? options[0];
  const isWa = ch?.channel === "whatsapp";
  const starting = ch?.conversation_id === START;
  const openUntil = windowOpenUntil(ch, now);
  const templateMode = isWa && openUntil === null;
  const igClosed = !!ch && !isWa && openUntil === null;
  const waOption = options.find(c => c.channel === "whatsapp");

  const pickWhatsApp = () => {
    if (!waOption) return false;
    setChId(waOption.conversation_id);
    if (windowOpenUntil(waOption, now) === null) setShowTemplates(true);
    else setTimeout(() => inputRef.current?.focus(), 0);
    return true;
  };

  useImperativeHandle(ref, () => ({
    focus: (channel?: "whatsapp") => {
      if (channel === "whatsapp" && pickWhatsApp()) return;
      if (templateMode) setShowTemplates(true); else inputRef.current?.focus();
    },
  }));

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
  const warn = "inline-flex min-h-11 flex-1 items-center justify-center gap-1.5 rounded-full border border-[var(--haip-status-warning-border)] bg-[var(--haip-status-warning-bg)] px-3 text-[13.5px] font-semibold text-[var(--haip-status-warning-fg)]";
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
            <button type="button" disabled={options.length < 2}
              onClick={() => { const next = options[(options.indexOf(ch) + 1) % options.length]; setChId(next.conversation_id); setShowTemplates(false); }}
              aria-label={`Reply on ${isWa ? "WhatsApp" : "Instagram"}${options.length > 1 ? ", switch channel" : ""}`}
              className={cn("inline-flex min-h-11 shrink-0 items-center gap-1 rounded-full border border-[var(--haip-border-strong)] bg-[var(--haip-card)] px-3 text-[13px] font-bold",
                isWa ? "text-[var(--haip-status-success-fg)]" : "text-[var(--haip-accent-ink)]")}>
              {isWa ? <MessageSquare size={14} aria-hidden /> : <Instagram size={14} aria-hidden />}{isWa ? "WA" : "IG"}
              {options.length > 1 && <ChevronDown size={13} aria-hidden />}
            </button>
            {templateMode ? (
              <button type="button" onClick={() => setShowTemplates(v => !v)} aria-expanded={showTemplates} className={warn}>
                {starting ? "Start on WhatsApp · pick a template" : "WhatsApp window closed · pick a template"}
              </button>
            ) : igClosed ? (
              waOption ? (
                <button type="button" onClick={pickWhatsApp} className={warn}>
                  <MessageSquare size={14} aria-hidden />Instagram window closed · message on WhatsApp
                </button>
              ) : (
                <p className={warn}>Instagram window closed{hasPhone ? " · call them" : ""}</p>
              )
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
            <TemplatePicker conversationId={starting ? undefined : ch.conversation_id} startFor={starting ? startWhatsApp ?? undefined : undefined}
              name={name} onError={onError}
              onSent={() => { setShowTemplates(false); setChId(null); onSent("whatsapp"); }} />
          )}
          <p className="px-1 text-[12.5px] text-[var(--haip-fg-subtle)]" data-testid="window-hint">
            {starting
              ? `No WhatsApp chat with ${name} yet. An approved template to their number starts one from the business WhatsApp.`
              : templateMode
                ? `${name} last wrote ${ch.last_inbound_at ? when(ch.last_inbound_at) : "never on WhatsApp"}. WhatsApp only allows an approved template until they reply.`
                : openUntil
                  ? `${isWa ? "WhatsApp" : "Instagram"}: free text until ${when(new Date(openUntil).toISOString())}.`
                  : `${name} last wrote on Instagram ${ch.last_inbound_at ? when(ch.last_inbound_at) : "more than a day ago"}. Instagram only delivers within 24 hours of their last message.`}
          </p>
        </>
      )}
    </div>
  );
});
