"use client";
// Profile: "Lead alerts on my WhatsApp". When a lead waits too long, Lead workflows can WhatsApp the person on their own
// number (from the business number, with Acknowledge / I'll take it buttons). Only after they agree here; otherwise push only.
// Backend: GET/PUT /workflows/alerts/me (self-service, audited). Needs the phone number saved above.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { Card, CardBody, CardHeader } from "@/components/ui/kit";
import { useToast } from "@/components/ui/toast";
import { Switch } from "@/components/workflows/Switch";

interface Me { whatsapp_opt_in: boolean; has_phone: boolean }

export function WhatsAppAlertsCard() {
  const qc = useQueryClient();
  const { toast } = useToast();
  const me = useQuery<Me>({ queryKey: ["workflows-alerts-me"], queryFn: () => api.get("/workflows/alerts/me").then(r => r.data) });
  const save = useMutation({
    mutationFn: (enabled: boolean) => api.put("/workflows/alerts/me", { enabled }).then(r => r.data as Me),
    onSuccess: fresh => {
      qc.setQueryData(["workflows-alerts-me"], fresh);
      toast({ variant: "success", title: fresh.whatsapp_opt_in ? "Lead alerts will come on your WhatsApp" : "WhatsApp lead alerts off" });
    },
    onError: (e: unknown) => {
      const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      toast({ variant: "error", title: "Couldn't save", description: typeof detail === "string" ? detail : "Try again." });
    },
  });
  const data = me.data;
  return (
    <Card>
      <CardHeader title="Lead alerts on my WhatsApp"
        description="When a lead you own waits too long, HAIP can message you on WhatsApp, with buttons to acknowledge it or take it. Otherwise you get app notifications only." />
      <CardBody className="flex items-center justify-between gap-4">
        <p className="text-[13px] text-[var(--haip-fg-muted)]">
          {me.isPending ? "Loading…" : me.isError ? "Couldn't load this setting. Refresh to try again."
            : !data?.has_phone ? "Save your phone number above first."
            : data.whatsapp_opt_in ? "On: alerts come to the phone number above." : "Off: app notifications only."}
        </p>
        <Switch on={!!data?.whatsapp_opt_in} label="Lead alerts on my WhatsApp"
          disabled={!data || !data.has_phone || save.isPending} onChange={v => save.mutate(v)} />
      </CardBody>
    </Card>
  );
}
