"use client";
// Send the published packages (a WhatsApp list) or HAIP's booking form (a WhatsApp Flow) in the open chat.
// Backend: POST /conversations/{id}/send-packages | send-booking-form (endpoints/wa_growth.py).
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ClipboardList, List, Loader2 } from "@/lib/icons";
import api from "@/lib/api";

export function ChatSellBar({ conversationId }: { conversationId: string }) {
  const qc = useQueryClient();
  const [error, setError] = useState("");
  const send = useMutation({
    mutationFn: (what: "send-packages" | "send-booking-form") => api.post(`/conversations/${conversationId}/${what}`),
    onSuccess: () => { setError(""); qc.invalidateQueries({ queryKey: ["conversation", conversationId] }); },
    onError: (e) => setError((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || "Couldn't send. Try again."),
  });
  const btn = "inline-flex min-h-9 items-center gap-1.5 text-[13px] font-medium text-primary disabled:opacity-50";
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-[var(--haip-border)] px-4 py-1.5">
      <button type="button" className={btn} disabled={send.isPending} onClick={() => send.mutate("send-packages")}>
        {send.isPending && send.variables === "send-packages" ? <Loader2 size={14} className="animate-spin" /> : <List size={14} />} Send packages
      </button>
      <button type="button" className={btn} disabled={send.isPending} onClick={() => send.mutate("send-booking-form")}>
        {send.isPending && send.variables === "send-booking-form" ? <Loader2 size={14} className="animate-spin" /> : <ClipboardList size={14} />} Send booking form
      </button>
      {error && <span role="alert" className="text-[12px] text-[var(--haip-status-danger-fg)]">{error}</span>}
    </div>
  );
}
