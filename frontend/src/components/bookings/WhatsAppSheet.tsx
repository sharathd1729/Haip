"use client";
// WhatsApp the booking's guest from the business number, inside HAIP (the inbox send endpoints, conversations.send).
// Inside the 24-hour window any message can go; outside it only an approved template, until the guest replies.
import { useEffect, useState } from "react";
import Link from "next/link";
import dynamic from "next/dynamic";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Send } from "@/lib/icons";
import api from "@/lib/api";
import { cn, timeAgo } from "@/lib/utils";
import { useToast } from "@/components/ui/toast";
import { Skeleton } from "@/components/ui/skeleton";
import { ActionSheet, SheetChip, sheetBtn, sheetInput, sheetLabel } from "@/components/bookings/ActionSheet";
import { errorMessage, fmtDate, type BookingDetail, type WhatsAppState } from "@/lib/bookings";

const TemplatePickerModal = dynamic(() => import("@/components/inbox/TemplatePickerModal").then(m => m.TemplatePickerModal), { ssr: false });

const QUICK = ["Your driver will call 30 minutes before pickup.", "Sharing the payment link now.", "Your pickup time is confirmed."];

export function WhatsAppSheet({ bookingId, open, onClose }: { bookingId: string; open: boolean; onClose: () => void }) {
  const { toast } = useToast();
  const qc = useQueryClient();
  const { data: b } = useQuery<BookingDetail>({
    queryKey: ["booking", bookingId], queryFn: () => api.get(`/bookings/${bookingId}`).then(r => r.data), enabled: open,
  });
  const [text, setText] = useState("");
  const [picker, setPicker] = useState<string | null>(null);   // conversation id for the template picker
  useEffect(() => { if (open) setText(""); }, [open]);

  const wa = b?.whatsapp;
  const first = (b?.guest?.name || "The guest").split(" ")[0];
  const noPhone = !!b && !b.guest?.phone;

  const send = useMutation({
    mutationFn: () => api.post(`/conversations/${wa!.conversation_id}/messages`, { body: text.trim() },
      { headers: { "Idempotency-Key": crypto.randomUUID() } }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["booking", bookingId] });
      qc.invalidateQueries({ queryKey: ["conversations"] });
      toast({ variant: "success", title: "Sent on WhatsApp", description: "It is in the guest's chat in the Inbox." });
      onClose();
    },
    onError: e => toast({ variant: "error", title: errorMessage(e, "Could not send the message") }),
  });

  // A template goes in the guest's WhatsApp thread; one is opened for a guest who never wrote on WhatsApp.
  const thread = useMutation({
    mutationFn: () => api.post<WhatsAppState>(`/bookings/${bookingId}/whatsapp-thread`).then(r => r.data),
    onSuccess: s => { if (s.conversation_id) setPicker(s.conversation_id); },
    onError: e => toast({ variant: "error", title: errorMessage(e, "Could not open the WhatsApp chat") }),
  });

  return (
    <>
      <ActionSheet open={open && !picker} onClose={onClose} title={`WhatsApp ${first}`}>
        {!b ? <Skeleton className="h-32 rounded-xl" /> : noPhone ? (
          <p className="text-sm text-[var(--haip-fg-2)]">This guest has no phone number, so there is no WhatsApp chat to send to.</p>
        ) : (
          <>
            <div className={cn("rounded-xl px-3 py-2.5 text-[13.5px]",
              wa?.window_open ? "bg-[var(--haip-status-success-bg)] text-[var(--haip-status-success-fg)]" : "bg-[var(--haip-status-warning-bg)] text-[var(--haip-status-warning-fg)]")}>
              {wa?.window_open
                ? `${first} wrote ${timeAgo(wa.last_inbound_at)}: the 24-hour window is open, so any message can go.`
                : `${first} ${wa?.last_inbound_at ? `last wrote ${timeAgo(wa.last_inbound_at)}` : "has not written on WhatsApp yet"}. WhatsApp only allows an approved template until they reply.`}
            </div>
            <p className="text-[13px] text-[var(--haip-fg-subtle)]">{b.property?.name ?? "No vehicle yet"} · {fmtDate(b.check_in, false)} to {fmtDate(b.check_out, false)}</p>
            {wa?.window_open && wa.conversation_id ? (
              <>
                <div className="flex flex-wrap gap-1.5">
                  {QUICK.map(q => <SheetChip key={q} on={text === q} onClick={() => setText(q)}>{q}</SheetChip>)}
                </div>
                <label className={sheetLabel}>Message
                  <textarea className={`${sheetInput} min-h-24 py-2`} rows={3} value={text} onChange={e => setText(e.target.value)} placeholder="Type a message" />
                </label>
                <div className="flex flex-wrap gap-2">
                  <button type="button" className={sheetBtn.primary} disabled={!text.trim() || send.isPending} onClick={() => send.mutate()}>
                    <Send size={15} /> {send.isPending ? "Sending…" : "Send"}
                  </button>
                </div>
              </>
            ) : (
              <div className="flex flex-wrap gap-2">
                <button type="button" className={sheetBtn.primary} disabled={thread.isPending} onClick={() => thread.mutate()}>
                  {thread.isPending ? "Opening…" : "Choose a template"}
                </button>
              </div>
            )}
            <p className="text-[12.5px] text-[var(--haip-fg-subtle)]">
              Sent from the business WhatsApp number inside HAIP and kept in the guest&apos;s chat.
              {wa?.conversation_id && <> <Link href={`/dashboard/inbox?conversation=${wa.conversation_id}`} className="font-semibold text-primary hover:underline">Open the chat</Link></>}
            </p>
          </>
        )}
      </ActionSheet>
      {picker && (
        <TemplatePickerModal conversationId={picker} onClose={() => { setPicker(null); onClose(); }}
          onSent={() => { qc.invalidateQueries({ queryKey: ["booking", bookingId] }); toast({ variant: "success", title: "Template sent on WhatsApp" }); }} />
      )}
    </>
  );
}
