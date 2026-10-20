"use client";
// Call a booking's guest through HAIP (POST /calls/click-to-call): the IVR rings the agent's own phone from the business number,
// then dials the guest. Nothing rings in the browser and there is no hang-up from here: the call ends on the phone.
import { useMutation } from "@tanstack/react-query";
import api from "@/lib/api";
import { useToast } from "@/components/ui/toast";

export function useGuestCall() {
  const { toast } = useToast();
  return useMutation({
    mutationFn: ({ phone }: { phone: string; name: string }) => api.post("/calls/click-to-call", { guest_number: phone }),
    onSuccess: (_res, { name }) => toast({
      variant: "success", title: "Calling…",
      description: `Your phone rings first. Pick up and HAIP dials ${name} from the business number. The call is logged on their record.`,
    }),
    onError: (err: unknown) => {
      const raw = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      toast({ variant: "error", title: "Call not started", description: typeof raw === "string" ? raw : "Could not start the call. Try again." });
    },
  });
}
