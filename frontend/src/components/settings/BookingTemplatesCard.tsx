"use client";
// The four WhatsApp templates HAIP sends around a booking, with their Meta status. "Create drafts" only adds drafts;
// the owner reviews each one in the template editor (and uploads a sample PDF for document headers) and submits it.
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardBody, CardHeader, StatusPill } from "@/components/ui/kit";
import { errorMessage } from "@/lib/bookings";
import { templatePill, type PackTemplate } from "@/lib/invoices";

export function BookingTemplatesCard({ canCreate = true }: { canCreate?: boolean } = {}) {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  // isPending, not isLoading: isLoading is false during SSR, which would render the list branch and mismatch on hydration.
  const { data, isPending, isError, refetch } = useQuery<{ templates: PackTemplate[] }>({
    queryKey: ["booking-pack"], queryFn: () => api.get("/messaging/templates/booking-pack").then(r => r.data),
  });
  const create = useMutation({
    mutationFn: () => api.post<{ created: string[]; templates: PackTemplate[] }>("/messaging/templates/booking-pack"),
    onSuccess: res => {
      queryClient.setQueryData(["booking-pack"], { templates: res.data.templates });
      toast({ variant: "success", title: res.data.created.length ? `${res.data.created.length} drafts created` : "All four already exist" });
    },
    onError: e => toast({ variant: "error", title: errorMessage(e, "Could not create the drafts") }),
  });
  const templates = data?.templates ?? [];
  const missing = templates.filter(t => !t.status).length;

  return (
    <Card>
      <CardHeader
        title="WhatsApp booking messages"
        description="Sent by HAIP around a booking. Meta must approve each one before its first send; until then HAIP skips it."
        actions={canCreate && missing > 0 && (
          <button type="button" onClick={() => create.mutate()} disabled={create.isPending}
            className="min-h-11 rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground disabled:opacity-50 sm:min-h-9">
            {create.isPending ? "Creating..." : `Create ${missing === templates.length ? "the drafts" : `${missing} missing draft${missing === 1 ? "" : "s"}`}`}
          </button>
        )}
      />
      <CardBody className="space-y-3">
        {isPending ? <Skeleton className="h-32 rounded-xl" /> : isError ? (
          <p role="alert" className="text-sm text-[var(--haip-status-danger-fg)]">
            Couldn&apos;t load the templates. <button type="button" className="font-semibold underline" onClick={() => refetch()}>Try again</button>
          </p>
        ) : (
          <ul className="divide-y divide-[var(--haip-border)]">
            {templates.map(t => {
              const pill = templatePill(t.status);
              return (
                <li key={t.name} className="space-y-1 py-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="min-w-0 flex-1 text-sm font-semibold text-[var(--haip-fg)]">{t.label}</p>
                    <StatusPill tone={pill.tone}>{pill.label}</StatusPill>
                  </div>
                  <p className="break-all font-mono text-xs text-[var(--haip-fg-subtle)]">{t.name}</p>
                  <p className="text-xs text-[var(--haip-fg-muted)]">Sent when: {t.when} Header: {t.header}.</p>
                  {t.rejection_reason && <p className="text-xs text-[var(--haip-status-danger-fg)]">{t.rejection_reason}</p>}
                </li>
              );
            })}
          </ul>
        )}
        <p className="text-xs text-[var(--haip-fg-subtle)]">
          Next step for each draft: open it in the{" "}
          <Link href="/dashboard/messaging/templates" className="font-medium text-primary hover:underline">template editor</Link>,
          upload a sample PDF where the header is a document, and submit it to Meta. Pay buttons take the Razorpay link&apos;s ending,
          so keep their address as https://rzp.io/{"{{1}}"}.
        </p>
      </CardBody>
    </Card>
  );
}
