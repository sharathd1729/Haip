"use client";
// Sections of the lead details panel: tasks, quotes and bookings of this person, contact and identity, AI replies.
import { useEffect, useState } from "react";
import Link from "next/link";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { Check, Eye, FileText, Instagram, Link2, Loader2, MessageSquare, Phone, Plus, Truck } from "@/lib/icons";
import { Card, CardBody, CardHeader, StatusPill } from "@/components/ui/kit";
import { useToast } from "@/components/ui/toast";
import { channelName, inr, istDate, when } from "./format";
import type { FeedChannel, LeadDetail, LeadFeed, RunAction } from "./types";

const ghost = "inline-flex min-h-11 items-center gap-1 rounded-lg px-2 text-[13px] font-semibold text-primary hover:bg-[var(--haip-surface)] sm:min-h-9";
const rowCls = "flex min-w-0 items-start gap-2.5 border-t border-[var(--haip-border)] py-2.5 first:border-t-0 first:pt-0";
const dot = "grid size-8 shrink-0 place-items-center rounded-full";

function errText(e: unknown, fallback: string) {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof d === "string" ? d : fallback;
}

export function TasksCard({ feed, inquiryId, closed, run }: { feed?: LeadFeed; inquiryId: string; closed: boolean; run: RunAction }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const toggle = useMutation({
    mutationFn: (id: string) => api.patch(`/tasks/${id}`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["lead-feed", inquiryId] }); toast({ variant: "success", title: "Task done" }); },
    onError: (e) => toast({ variant: "error", title: "Not changed", description: errText(e, "Please try again.") }),
  });
  const open = (feed?.tasks ?? []).filter(t => !t.is_done);
  const now = Date.now();
  return (
    <Card>
      <CardHeader title={`Tasks${open.length ? ` · ${open.length}` : ""}`} actions={<button type="button" className={ghost} onClick={() => run("task")}><Plus size={13} aria-hidden /> Add</button>} />
      <CardBody className="pt-1">
        {!feed ? <p className="text-[13px] text-[var(--haip-fg-subtle)]">Loading…</p>
          : open.length === 0 ? <p className="text-[13px] text-[var(--haip-fg-subtle)]">{closed ? "Nothing open: this lead is closed." : "Nothing open. Add a follow-up so it shows in My day."}</p>
            : (
              <ul className="grid">
                {open.map(t => {
                  const late = t.due_date && Date.parse(t.due_date) < now;
                  return (
                    <li key={t.task_id} className={rowCls}>
                      <button type="button" onClick={() => toggle.mutate(t.task_id)} disabled={toggle.isPending} aria-label={`Mark done: ${t.title}`}
                        className="-my-2.5 -ml-2 grid size-11 shrink-0 place-items-center text-[var(--haip-fg-subtle)] hover:text-primary">
                        <span className="grid size-[22px] place-items-center rounded-md border-2 border-current">
                          {toggle.isPending && toggle.variables === t.task_id ? <Loader2 size={12} className="animate-spin" aria-hidden /> : <Check size={12} className="opacity-0 hover:opacity-100" aria-hidden />}
                        </span>
                      </button>
                      <span className="grid min-w-0 flex-1 gap-0.5">
                        <span className="break-words text-[14px] font-semibold text-[var(--haip-fg)]">{t.title}</span>
                        <span className="text-[12.5px] text-[var(--haip-fg-subtle)]">{t.due_date ? `Due ${when(t.due_date)}` : "No due time"}{t.assignee_name ? ` · ${t.assignee_name}` : ""}</span>
                      </span>
                      {late && <StatusPill tone="danger">Overdue</StatusPill>}
                    </li>
                  );
                })}
              </ul>
            )}
      </CardBody>
    </Card>
  );
}

const LINK: Record<string, string> = { created: "Payment link sent", paid: "Paid", expired: "Link expired", cancelled: "Link cancelled" };

export function DealsCard({ lead, feed, canQuote, canBook, canOpenBookings, run }: {
  lead: LeadDetail; feed?: LeadFeed; canQuote: boolean; canBook: boolean; canOpenBookings: boolean; run: RunAction;
}) {
  const quotes = (lead.quote_history ?? []).filter(q => (q.option_rank ?? 1) === 1);
  const bookings = feed?.bookings ?? [];
  const hasLive = bookings.some(b => b.status !== "cancelled" && b.inquiry_id === lead.inquiry_id);
  return (
    <Card>
      <CardHeader title="Quotes and bookings" actions={canQuote ? <button type="button" className={ghost} onClick={() => run("quote")}><Plus size={13} aria-hidden /> Quote</button> : undefined} />
      <CardBody className="grid gap-2 pt-1">
        {quotes.length === 0 ? <p className="text-[13px] text-[var(--haip-fg-subtle)]">No quote yet.</p> : (
          <ul className="grid">
            {quotes.map(q => (
              <li key={q.id} className={rowCls}>
                <span className={cn(dot, "bg-[var(--haip-status-warning-bg)] text-[var(--haip-status-warning-fg)]")}><FileText size={14} aria-hidden /></span>
                <span className="grid min-w-0 flex-1 gap-0.5">
                  <span className="break-words text-[14px] font-semibold text-[var(--haip-fg)]">{q.label || "Quote"}</span>
                  <span className="text-[12.5px] text-[var(--haip-fg-subtle)]">
                    {q.status === "pending_approval" ? "Waiting for the owner's OK" : q.shared_via === "sent" ? "Sent on WhatsApp" : q.shared_via === "copied" ? "Copied" : "Saved, not sent"}
                    {q.created_at ? ` · ${istDate(q.created_at)}` : ""}{q.valid_until && q.is_active ? ` · valid till ${istDate(q.valid_until)}` : ""}
                  </span>
                  <span className="flex flex-wrap gap-1">
                    {!q.is_active && <StatusPill tone="neutral">{(q.status || "older").replace(/_/g, " ")}</StatusPill>}
                    {q.payment_link_status && <StatusPill tone={q.payment_link_status === "paid" ? "success" : "neutral"}>{LINK[q.payment_link_status]}</StatusPill>}
                  </span>
                </span>
                <span className="whitespace-nowrap text-[15px] font-bold tabular-nums text-[var(--haip-fg)]">{inr(q.amount)}</span>
              </li>
            ))}
          </ul>
        )}
        <p className="mt-1 text-[12px] font-bold uppercase tracking-wide text-[var(--haip-fg-subtle)]">Bookings</p>
        {!feed ? <p className="text-[13px] text-[var(--haip-fg-subtle)]">Loading…</p> : bookings.length === 0 ? <p className="text-[13px] text-[var(--haip-fg-subtle)]">No booking for this person yet.</p> : (
          <ul className="grid">
            {bookings.map(b => {
              const inner = (
                <>
                  <span className={cn(dot, "bg-[var(--haip-status-info-bg)] text-[var(--haip-status-info-fg)]")}><Truck size={14} aria-hidden /></span>
                  <span className="grid min-w-0 flex-1 gap-0.5">
                    <span className="break-words text-[14px] font-semibold text-[var(--haip-fg)]">{b.property_name || "Vehicle not chosen"} · {istDate(b.check_in)} → {istDate(b.check_out)}</span>
                    <span className="text-[12.5px] text-[var(--haip-fg-subtle)]">
                      {b.status.replace(/_/g, " ")} · {b.guests} guests{b.inquiry_id && b.inquiry_id !== lead.inquiry_id ? " · from an earlier lead" : ""}
                      {!b.amount_restricted && (b.outstanding ?? 0) > 0 ? ` · ${inr(b.outstanding)} due` : ""}
                    </span>
                  </span>
                  {!b.amount_restricted && b.total != null && <span className="whitespace-nowrap text-[15px] font-bold tabular-nums text-[var(--haip-fg)]">{inr(b.total)}</span>}
                </>
              );
              return (
                <li key={b.booking_id}>
                  {canOpenBookings ? <Link href={`/dashboard/bookings/${b.booking_id}`} className={cn(rowCls, "rounded-lg hover:bg-[var(--haip-surface)]")}>{inner}</Link>
                    : <div className={rowCls}>{inner}</div>}
                </li>
              );
            })}
          </ul>
        )}
        {canBook && !hasLive && (
          <button type="button" onClick={() => run("book")} className="inline-flex min-h-11 items-center justify-center gap-1.5 justify-self-start rounded-xl border border-[var(--haip-border-strong)] px-3 text-[13.5px] font-semibold text-[var(--haip-fg-2)]">
            Add booking{lead.check_in ? ` for ${istDate(lead.check_in)}` : ""}
          </button>
        )}
      </CardBody>
    </Card>
  );
}

/** The real number for 30 seconds, from the audited reveal endpoint. */
export function useReveal(inquiryId: string) {
  const { toast } = useToast();
  const [shown, setShown] = useState<{ phone?: string | null; email?: string | null } | null>(null);
  useEffect(() => { if (!shown) return; const t = setTimeout(() => setShown(null), 30_000); return () => clearTimeout(t); }, [shown]);
  const reveal = useMutation({
    mutationFn: () => api.post(`/leads/${inquiryId}/contact/reveal`).then(r => r.data as { phone?: string | null; email?: string | null }),
    onSuccess: (d) => { setShown(d); toast({ title: "Shown for 30 seconds", description: "Logged in the audit trail." }); },
    onError: (e) => toast({ variant: "error", title: "Couldn't show the number", description: errText(e, "Your role may not be allowed to see it.") }),
  });
  return { shown, reveal: () => reveal.mutate(), pending: reveal.isPending };
}

export function ContactCard({ lead, feed, canReveal, reveal, onAddSignal }: {
  lead: LeadDetail; feed?: LeadFeed; canReveal: boolean; reveal: ReturnType<typeof useReveal>; onAddSignal?: () => void;
}) {
  const c = feed?.contact;
  const merges = feed?.merges ?? [];
  const wa = feed?.channels.find(ch => ch.channel === "whatsapp");
  const ig = feed?.channels.find(ch => ch.channel === "instagram");
  return (
    <Card>
      <CardHeader title="Contact and identity"
        actions={onAddSignal ? <button type="button" className={ghost} onClick={onAddSignal}><Plus size={13} aria-hidden /> Phone or email</button> : undefined} />
      <CardBody className="pt-1">
        <ul className="grid">
          <li className={rowCls}>
            <span className={cn(dot, "bg-[var(--haip-surface)] text-[var(--haip-fg-2)]")}><Phone size={14} aria-hidden /></span>
            <span className="grid min-w-0 flex-1 gap-0.5">
              <span className="text-[14px] font-semibold tabular-nums text-[var(--haip-fg)]">{reveal.shown?.phone || c?.phone_masked || "No phone number yet"}</span>
              <span className="text-[12.5px] text-[var(--haip-fg-subtle)]">Phone{reveal.shown?.email || c?.email_masked ? ` · ${reveal.shown?.email || c?.email_masked}` : ""}</span>
            </span>
            {canReveal && c?.has_phone && !reveal.shown && (
              <button type="button" className={ghost} onClick={reveal.reveal} disabled={reveal.pending}><Eye size={13} aria-hidden /> Show</button>
            )}
          </li>
          <li className={rowCls}>
            <span className={cn(dot, "bg-[var(--haip-status-success-bg)] text-[var(--haip-status-success-fg)]")}><MessageSquare size={14} aria-hidden /></span>
            <span className="grid min-w-0 flex-1 gap-0.5">
              <span className="text-[14px] font-semibold text-[var(--haip-fg)]">{c?.has_whatsapp ? "WhatsApp" : "No WhatsApp chat yet"}</span>
              {wa?.last_inbound_at && <span className="text-[12.5px] text-[var(--haip-fg-subtle)]">Last message from them {when(wa.last_inbound_at)}</span>}
            </span>
          </li>
          {(c?.has_instagram || ig) && (
            <li className={rowCls}>
              <span className={cn(dot, "bg-[var(--haip-accent-light)] text-[var(--haip-accent-ink)]")}><Instagram size={14} aria-hidden /></span>
              <span className="grid min-w-0 flex-1 gap-0.5">
                <span className="text-[14px] font-semibold text-[var(--haip-fg)]">Instagram</span>
                {ig?.last_inbound_at && <span className="text-[12.5px] text-[var(--haip-fg-subtle)]">Last DM from them {when(ig.last_inbound_at)}</span>}
              </span>
            </li>
          )}
          {merges.map(m => (
            <li key={m.merge_id} className={rowCls}>
              <span className={cn(dot, "bg-[var(--haip-surface)] text-[var(--haip-fg-2)]")}><Link2 size={14} aria-hidden /></span>
              <span className="grid min-w-0 flex-1 gap-0.5">
                <span className="text-[14px] font-semibold text-[var(--haip-fg)]">{m.undone ? "Joined record (undone)" : "Another record joined"}</span>
                <span className="text-[12.5px] text-[var(--haip-fg-subtle)]">{when(m.at)} · {m.by_name}{m.joined.length ? ` · ${m.joined.join(", ")}` : ""}</span>
              </span>
            </li>
          ))}
        </ul>
        {c?.first_touch_channel && <p className="mt-2 text-[12.5px] text-[var(--haip-fg-subtle)]">First contact: {channelName(c.first_touch_channel)}{c.first_touch_at ? `, ${istDate(c.first_touch_at)}` : ""}.</p>}
        {(lead.identity_signals ?? []).length === 0 && !c?.has_phone && <p className="mt-2 text-[12.5px] text-[var(--haip-fg-subtle)]">No identity signals yet.</p>}
      </CardBody>
    </Card>
  );
}

export function AiRepliesToggle({ channels, inquiryId }: { channels: FeedChannel[]; inquiryId: string }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const sendable = channels.filter(c => c.can_send);
  const on = sendable.some(c => c.ai_enabled);
  const set = useMutation({
    mutationFn: (v: boolean) => Promise.all(sendable.map(c => api.patch(`/conversations/${c.conversation_id}`, { ai_enabled: v }))),
    onSuccess: (_r, v) => { qc.invalidateQueries({ queryKey: ["lead-feed", inquiryId] }); toast({ title: `AI replies ${v ? "on" : "off"} for this person` }); },
    onError: (e) => toast({ variant: "error", title: "Not changed", description: errText(e, "Please try again.") }),
  });
  if (sendable.length === 0) return null;
  return (
    <label className="flex min-h-11 cursor-pointer items-center gap-3 text-[14px] text-[var(--haip-fg)]">
      <input type="checkbox" role="switch" checked={on} disabled={set.isPending} onChange={e => set.mutate(e.target.checked)} className="size-5 accent-[var(--primary)]" />
      <span><strong>AI replies {on ? "on" : "off"}</strong> <span className="text-[12.5px] text-[var(--haip-fg-subtle)]">· for this person&apos;s chats; prices follow the workspace rule</span></span>
    </label>
  );
}
