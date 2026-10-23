"use client";
// Click-to-call from a My day row (POST /calls/click-to-call): the IVR rings your phone first, then connects the guest. A lead is
// named by its enquiry (the server holds the number); a lead with no enquiry yet, or a missed call, carries its own number.
// Same rule as the desktop My day row.
import { useMutation } from "@tanstack/react-query";
import api from "@/lib/api";
import { useToast } from "@/components/ui/toast";

export type DialPayload = { inquiry_id: string } | { guest_number: string };

export function dialPayload(item: { kind: string; inquiry_id: string | null; guest_phone: string | null }): DialPayload | null {
  if (item.kind === "new_lead" && item.inquiry_id) return { inquiry_id: item.inquiry_id };
  if ((item.kind === "new_lead" || item.kind === "callback") && item.guest_phone) return { guest_number: item.guest_phone };
  return null;
}

export function useDial(name: string) {
  const { toast } = useToast();
  return useMutation({
    mutationFn: (payload: DialPayload) => api.post("/calls/click-to-call", payload),
    onSuccess: () => toast({ variant: "success", title: "Calling…", description: `Your phone will ring first, then we'll connect you to ${name}.` }),
    onError: (err: unknown) => {
      const raw = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      const description = typeof raw === "string" ? raw
        : Array.isArray(raw) ? raw.map((e: { msg?: string }) => e?.msg ?? JSON.stringify(e)).join("; ") : "Could not start the call.";
      toast({ variant: "error", title: "Call failed", description });
    },
  });
}
