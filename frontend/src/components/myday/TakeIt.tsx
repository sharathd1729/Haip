"use client";
// "Take it" on a My day row (owner, 1 Nov 2026, S10): claim a lead nobody owns. POST /work-queue/take/{inquiry} is one guarded
// update on the server (lead_assignment_service.take_unowned, audited), so two people tapping at once cannot both win: the
// second gets a 409 with the reason. Refreshes the shared work-queue query (My day, Home, the Now badge).
import { useMutation, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { useToast } from "@/components/ui/toast";

export function TakeIt({ inquiryId, name, className }: { inquiryId: string; name: string; className?: string }) {
  const { toast } = useToast();
  const qc = useQueryClient();
  const take = useMutation({
    mutationFn: () => api.post(`/work-queue/take/${inquiryId}`),
    onSuccess: () => {
      toast({ variant: "success", title: "It's yours", description: `${name} is now your lead.` });
      qc.invalidateQueries({ queryKey: ["work-queue"] });
    },
    onError: (err: unknown) => {
      const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      toast({ variant: "error", title: "Couldn't take it", description: typeof detail === "string" ? detail : "Try again." });
      qc.invalidateQueries({ queryKey: ["work-queue"] });
    },
  });
  return (
    <button type="button" onClick={() => take.mutate()} disabled={take.isPending} aria-label={`Take ${name}`}
      className={className ?? "haip-btn-secondary min-h-11 whitespace-nowrap px-3 text-[13px]"}>
      {take.isPending ? "Taking…" : "Take it"}
    </button>
  );
}
