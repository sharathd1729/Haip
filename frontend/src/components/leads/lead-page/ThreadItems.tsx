"use client";
// One row of the lead thread. Messages are chat bubbles (theirs on the left, ours on the right); calls, quotes and
// bookings are cards inside the conversation; stage changes, tasks and merges are one quiet centred line.
import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { CalendarCheck, CheckSquare, FileText, Flag, Instagram, Link2, Loader2, MessageSquare, PhoneIncoming, PhoneMissed, PhoneOutgoing, Play, Sparkles, StickyNote, Truck } from "@/lib/icons";
import { StatusPill } from "@/components/ui/page";
import { useToast } from "@/components/ui/toast";
import { durationText, inr, istDate, istTime } from "./format";
import type { FeedItem } from "./types";

const DELIVERY: Record<string, string> = { read: "✓✓ read", delivered: "✓✓", sent: "✓", queued: "sending…", pending: "sending…", failed: "not delivered", rejected: "not delivered" };

function errText(e: unknown, fallback: string) {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof d === "string" ? d : fallback;
}

function ChannelTag({ channel }: { channel?: string | null }) {
  if (channel === "instagram") return <span className="inline-flex items-center gap-1 text-[11.5px] font-bold text-[var(--haip-accent-ink)]"><Instagram size={11} aria-hidden /> Instagram</span>;
  return <span className="inline-flex items-center gap-1 text-[11.5px] font-bold text-[var(--haip-status-success-fg)]"><MessageSquare size={11} aria-hidden /> WhatsApp</span>;
}

export function MessageBubble({ item, canSend, inquiryId }: { item: FeedItem; canSend: boolean; inquiryId: string }) {
  const out = item.direction === "outbound";
  if (item.is_internal) {
    return (
      <div className="mx-auto flex max-w-[92%] items-start gap-1.5 rounded-xl border border-[var(--haip-status-warning-border)] bg-[var(--haip-status-warning-bg)] px-3 py-2 text-[13px] text-[var(--haip-status-warning-fg)]">
        <StickyNote size={13} className="mt-0.5 shrink-0" aria-hidden /> <span className="min-w-0 break-words">Note{item.sender_name ? ` by ${item.sender_name}` : ""}: {item.text}</span>
      </div>
    );
  }
  if (item.is_draft) return <DraftBubble item={item} canSend={canSend} inquiryId={inquiryId} />;
  return (
    <div data-testid="thread-message" className={cn("flex", out ? "justify-end" : "justify-start")}>
      <div className={cn("grid max-w-[min(82%,520px)] gap-0.5 rounded-2xl px-3 pb-1.5 pt-2 text-[14.5px] shadow-[var(--haip-shadow-sm)]",
        out ? "rounded-br-md bg-[var(--haip-status-success-bg)] text-[var(--haip-fg)]" : "rounded-bl-md border border-[var(--haip-border)] bg-[var(--haip-card)] text-[var(--haip-fg)]")}>
        <span className="flex flex-wrap items-center gap-x-1.5">
          <ChannelTag channel={item.channel} />
          {out && <span className="text-[11.5px] font-semibold text-[var(--haip-fg-muted)]">· {item.is_ai ? "AI reply" : item.sender_name || "Team"}</span>}
          {item.is_template && <span className="text-[11.5px] text-[var(--haip-fg-subtle)]">· template</span>}
        </span>
        <span className="whitespace-pre-wrap break-words">{item.text || (item.media_type ? `[${item.media_type}]` : "—")}</span>
        <span className="flex items-center justify-end gap-1.5 text-[11.5px] text-[var(--haip-fg-subtle)]">
          {istTime(item.at)}
          {out && item.delivery && (
            <span className={cn(item.delivery === "failed" || item.delivery === "rejected" ? "font-semibold text-[var(--haip-status-danger-fg)]" : "")}>
              {DELIVERY[item.delivery] ?? item.delivery}
            </span>
          )}
        </span>
      </div>
    </div>
  );
}

function DraftBubble({ item, canSend, inquiryId }: { item: FeedItem; canSend: boolean; inquiryId: string }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const send = useMutation({
    mutationFn: () => api.post(`/conversations/${item.conversation_id}/messages/${item.id.replace(/^msg-/, "")}/approve`),
    onSuccess: () => {
      toast({ variant: "success", title: "Reply sent", description: "It is on its way and logged on this lead." });
      qc.invalidateQueries({ queryKey: ["lead-feed", inquiryId] });
      qc.invalidateQueries({ queryKey: ["lead", inquiryId] });
    },
    onError: (e) => toast({ variant: "error", title: "Not sent", description: errText(e, "Please try again.") }),
  });
  return (
    <div className="flex justify-end" data-testid="thread-draft">
      <div className="grid max-w-[min(88%,520px)] gap-1.5 rounded-2xl rounded-br-md border border-dashed border-[color-mix(in_srgb,var(--primary)_40%,transparent)] bg-[var(--haip-primary-tint)] px-3 py-2 text-[14.5px]">
        <span className="flex items-center gap-1 text-[11.5px] font-bold text-primary"><Sparkles size={11} aria-hidden /> AI draft · not sent</span>
        <span className="whitespace-pre-wrap break-words text-[var(--haip-fg)]">{item.text}</span>
        {canSend && item.conversation_id && (
          <button type="button" onClick={() => send.mutate()} disabled={send.isPending}
            className="inline-flex min-h-11 items-center justify-center gap-1.5 justify-self-end rounded-full bg-primary px-4 text-[13px] font-semibold text-primary-foreground disabled:opacity-60 sm:min-h-9">
            {send.isPending && <Loader2 size={13} className="animate-spin" aria-hidden />} Send this reply
          </button>
        )}
      </div>
    </div>
  );
}

function Recording({ callId }: { callId: string }) {
  const { data, isPending, isError } = useQuery({
    queryKey: ["call", callId],
    queryFn: () => api.get(`/calls/${callId}`).then(r => r.data as { recording_url?: string | null }),
    staleTime: 5 * 60_000,
  });
  if (isPending) return <p className="text-[12.5px] text-[var(--haip-fg-subtle)]">Loading the recording…</p>;
  if (isError || !data?.recording_url) return <p className="text-[12.5px] text-[var(--haip-fg-subtle)]">The recording is not available yet.</p>;
  return <audio controls autoPlay preload="none" src={data.recording_url} className="h-11 w-full" aria-label="Call recording" />;
}

export function CallCard({ item }: { item: FeedItem }) {
  const [play, setPlay] = useState(false);
  const inbound = item.direction === "inbound";
  const Icon = !item.answered ? PhoneMissed : inbound ? PhoneIncoming : PhoneOutgoing;
  const title = !item.answered
    ? `${inbound ? "Missed call" : "Outgoing call"} · not answered`
    : `${inbound ? "Incoming call" : "Outgoing call"} · ${durationText(item.duration_seconds)}`;
  return (
    <div data-testid="thread-call" className="mx-auto grid w-full max-w-[560px] gap-2 rounded-2xl border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 py-2.5">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className={cn("grid size-8 shrink-0 place-items-center rounded-full",
          item.answered ? "bg-[var(--haip-primary-tint)] text-primary" : "bg-[var(--haip-status-danger-bg)] text-[var(--haip-status-danger-fg)]")}>
          <Icon size={15} aria-hidden />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-[14px] font-semibold text-[var(--haip-fg)]">{title}</span>
          <span className="block text-[12.5px] text-[var(--haip-fg-subtle)]">
            {istTime(item.at)}{item.by_name ? ` · ${inbound ? "answered by" : "by"} ${item.by_name}` : ""}
            {!item.answered && !inbound ? " · logged as an attempt" : ""}
            {item.manual ? " · from a personal phone, logged by hand" : ""}
          </span>
        </span>
      </div>
      {item.manual && item.text && <p className="text-[13.5px] text-[var(--haip-fg-2)]">{item.text}</p>}
      {item.answered && (item.summary || item.summary_pending) && (
        <div className="grid gap-0.5 rounded-xl bg-[var(--haip-primary-tint)] px-3 py-2 text-[13.5px]">
          <span className="flex items-center gap-1 text-[11.5px] font-bold text-primary"><Sparkles size={11} aria-hidden /> AI call summary</span>
          <p className="text-[var(--haip-fg)]">{item.summary || "Writing the transcript and summary… usually a few minutes."}</p>
        </div>
      )}
      {item.answered && (item.has_recording || item.has_transcript) && (
        <div className="flex flex-wrap items-center gap-2">
          {item.has_recording && !play && (
            <button type="button" onClick={() => setPlay(true)}
              className="inline-flex min-h-11 items-center gap-1.5 rounded-full bg-primary px-4 text-[13px] font-semibold text-primary-foreground sm:min-h-9">
              <Play size={13} aria-hidden /> Play recording
            </button>
          )}
          {item.has_transcript && item.call_id && (
            <Link href={`/dashboard/calls/${item.call_id}`} className="inline-flex min-h-11 items-center px-2 text-[13px] font-semibold text-primary hover:underline sm:min-h-9">
              Transcript
            </Link>
          )}
          {play && item.call_id && <div className="w-full"><Recording callId={item.call_id} /></div>}
        </div>
      )}
    </div>
  );
}

const QUOTE_HOW: Record<string, string> = { sent: "Sent on WhatsApp", copied: "Copied to send" };

export function QuoteCard({ item }: { item: FeedItem }) {
  const live = ["issued", "accepted", "pending_approval"].includes(item.status || "");
  return (
    <div data-testid="thread-quote" className="ml-auto grid w-[min(88%,440px)] gap-1 rounded-2xl border border-[var(--haip-status-warning-border)] bg-[var(--haip-card)] px-3 py-2.5">
      <span className="flex flex-wrap items-center gap-1.5 text-[14px] font-semibold text-[var(--haip-fg)]">
        <FileText size={14} className="text-[var(--haip-status-warning-fg)]" aria-hidden /> Quote · <span className="tabular-nums">{inr(item.amount)}</span>
        <StatusPill tone={item.status === "pending_approval" ? "warning" : item.shared_via ? "success" : "neutral"}>
          {item.status === "pending_approval" ? "Waiting for OK" : QUOTE_HOW[item.shared_via || ""] ?? "Saved, not sent"}
        </StatusPill>
        {!live && item.status && <StatusPill tone="neutral">{item.status.replace(/_/g, " ")}</StatusPill>}
      </span>
      {item.label && <span className="text-[12.5px] text-[var(--haip-fg-muted)]">{item.label}{item.guests ? ` · ${item.guests} guests` : ""}</span>}
      <span className="text-[12.5px] text-[var(--haip-fg-subtle)]">
        {istTime(item.at)}{item.by_name ? ` · by ${item.by_name}` : ""}{item.valid_until_text && live ? ` · valid till ${item.valid_until_text}` : ""}
      </span>
    </div>
  );
}

export function BookingCard({ item, canOpen }: { item: FeedItem; canOpen: boolean }) {
  const body = (
    <>
      <span className="flex flex-wrap items-center gap-1.5 text-[14px] font-semibold text-[var(--haip-fg)]">
        <Truck size={14} className="text-[var(--haip-status-info-fg)]" aria-hidden /> Booking{item.label ? ` · ${item.label}` : ""}
        {item.status && <StatusPill tone={item.status === "cancelled" ? "danger" : item.status === "checked_out" ? "neutral" : "info"}>{item.status.replace(/_/g, " ")}</StatusPill>}
      </span>
      <span className="text-[12.5px] text-[var(--haip-fg-muted)]">
        {istDate(item.check_in)} → {istDate(item.check_out)}{item.guests ? ` · ${item.guests} guests` : ""}
        {!item.amount_restricted && item.amount != null ? ` · ${inr(item.amount)}` : ""}
      </span>
    </>
  );
  const cls = "mx-auto grid w-full max-w-[560px] gap-1 rounded-2xl border border-[var(--haip-status-info-border)] bg-[var(--haip-card)] px-3 py-2.5";
  return canOpen && item.booking_id
    ? <Link data-testid="thread-booking" href={`/dashboard/bookings/${item.booking_id}`} className={cn(cls, "hover:bg-[var(--haip-surface)]")}>{body}</Link>
    : <div data-testid="thread-booking" className={cls}>{body}</div>;
}

export function SysLine({ item }: { item: FeedItem }) {
  const Icon = item.kind === "task" ? CheckSquare : item.kind === "merge" ? Link2 : item.kind === "booking" ? CalendarCheck : Flag;
  const text = item.kind === "stage"
    ? `Stage: ${item.from_label ? `${item.from_label} → ` : ""}${item.to_label}${item.reason ? ` · ${item.reason}` : ""}`
    : item.kind === "task" ? `Task: ${item.text}${item.status === "done" ? " (done)" : ""}` : item.text;
  return (
    <p data-testid={`thread-${item.kind}`} className="mx-auto flex max-w-[92%] flex-wrap items-center justify-center gap-1.5 text-center text-[12.5px] text-[var(--haip-fg-subtle)]">
      <Icon size={12} aria-hidden /> <span className="break-words">{text}</span>
      <span>· {istTime(item.at)}{item.by_name ? ` · ${item.by_name}` : ""}</span>
    </p>
  );
}
