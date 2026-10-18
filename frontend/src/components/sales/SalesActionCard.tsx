"use client";
// A quote the AI sales agent prepared and that waits for a person: what it is, what would stop it, and Approve / Reject.
// Shown in the inbox thread (by conversation) and on the lead page (by lead). Renders nothing when there is nothing pending,
// or when the caller may not read leads. Approve sends THAT quote + its payment link (the same path as the quote builder's
// "Send quote"); the server re-checks everything and answers 409 if someone already decided.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "@/lib/icons";
import api from "@/lib/api";
import { formatINR } from "@/lib/utils";
import { Card, CardBody, CardHeader, StatusPill } from "@/components/ui/kit";
import { useToast } from "@/components/ui/toast";
import { BTN, BTN_PRIMARY } from "@/components/quotes/ui";

type QuoteOption = {
  quote_id: string; package_name: string | null; destination: string | null; check_in: string | null; check_out: string | null;
  guests: number | null; total: string | null; advance: string | null; valid_until: string | null; at_actuals: string[];
};
export type SalesAction = {
  id: string; inquiry_id: string; conversation_id: string | null; quote_id: string; mode: "suggest" | "autopilot";
  status: "pending" | "sending" | "sent" | "rejected" | "superseded" | "failed";
  summary: QuoteOption & { quote_number?: string; fallback: QuoteOption | null };
  hold_reasons: string[]; last_error: string | null; can_decide: boolean;
  readiness: { can_send: boolean; blockers: { code: string; message: string }[]; warnings: { code: string; message: string }[] } | null;
};

const day = (d: string | null) => (d ? new Date(`${d}T00:00:00`).toLocaleDateString("en-IN", { day: "numeric", month: "short" }) : "?");
const money = (v: string | null) => (v == null ? "to confirm" : formatINR(Number(v)));

function errorText(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: { message?: string } | string } } })?.response?.data?.detail;
  return typeof d === "string" ? d : d?.message ?? "Something went wrong. Try again.";
}

function Option({ title, o }: { title: string; o: QuoteOption }) {
  return (
    <div className="min-w-0 rounded-lg border border-[var(--haip-border)] p-3">
      <p className="text-[12px] font-semibold text-[var(--haip-fg-subtle)]">{title}</p>
      <p className="mt-0.5 break-words text-[14px] font-semibold text-[var(--haip-fg)]">
        {o.destination ? `${o.destination} · ` : ""}{o.package_name ?? "Trip"}
      </p>
      <p className="text-[13px] text-[var(--haip-fg-2)]">{day(o.check_in)} → {day(o.check_out)} · {o.guests ?? "?"} guests</p>
      <p className="mt-1 text-[13px] text-[var(--haip-fg)]">
        Total <span className="num font-semibold">{money(o.total)}</span> incl. GST · advance <span className="num font-semibold">{money(o.advance)}</span>
      </p>
      {o.at_actuals.length > 0 && <p className="text-[12px] text-[var(--haip-fg-subtle)]">At actuals, outside the total: {o.at_actuals.join(", ")}</p>}
      {o.valid_until && <p className="text-[12px] text-[var(--haip-fg-subtle)]">Valid until {day(o.valid_until)}</p>}
    </div>
  );
}

export function SalesActionCard({ conversationId, inquiryId }: { conversationId?: string | null; inquiryId?: string | null }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const params = inquiryId ? { inquiry_id: inquiryId, status: "pending" } : { conversation_id: conversationId, status: "pending" };
  const key = ["sales-actions", inquiryId ?? null, conversationId ?? null];
  const { data, isPending, isError } = useQuery<SalesAction[]>({
    queryKey: key,
    queryFn: () => api.get("/sales-actions", { params }).then(r => r.data),
    enabled: Boolean(inquiryId || conversationId),
    retry: (n, e) => (e as { response?: { status?: number } })?.response?.status !== 403 && n < 1,
  });
  const decide = useMutation({
    mutationFn: ({ id, verb }: { id: string; verb: "approve" | "reject" }) => api.post(`/sales-actions/${id}/${verb}`).then(r => r.data),
    onSuccess: (_d, v) => {
      toast({ variant: "success", title: v.verb === "approve" ? "Quote and payment link sent" : "Quote dismissed" });
      qc.invalidateQueries({ queryKey: ["sales-actions"] });
      qc.invalidateQueries({ queryKey: ["quotes"] });
    },
    onError: e => {
      toast({ variant: "error", title: "Not sent", description: errorText(e) });
      qc.invalidateQueries({ queryKey: ["sales-actions"] });
    },
  });

  if (isPending || isError || !data?.length) return null;          // only shown when something waits for a person

  return (
    <div className="space-y-2 px-3 pt-2 sm:px-4">
      {data.map(a => {
        const blockers = a.readiness?.blockers ?? [];
        const busy = decide.isPending && decide.variables?.id === a.id;
        return (
          <Card key={a.id} aria-label="Quote prepared by the AI">
            <CardHeader
              title={`Quote ready to send${a.summary.quote_number ? ` · ${a.summary.quote_number}` : ""}`}
              description="Prepared by the AI from your published plans and the booking calendar. Nothing has been sent yet."
              actions={<StatusPill tone={blockers.length ? "warning" : "info"}>{blockers.length ? "Needs a fix" : "Waiting for you"}</StatusPill>}
            />
            <CardBody className="space-y-3">
              <div className="grid gap-2 sm:grid-cols-2">
                <Option title={a.summary.fallback ? "Option 1" : "The quote"} o={a.summary} />
                {a.summary.fallback && <Option title="Option 2" o={a.summary.fallback} />}
              </div>
              {(blockers.length > 0 || a.hold_reasons.length > 0 || a.last_error) && (
                <ul className="space-y-1 text-[13px] text-[var(--haip-fg-2)]">
                  {a.last_error && <li>Last try: {a.last_error}</li>}
                  {blockers.map(b => <li key={b.code}>{b.message}</li>)}
                  {a.hold_reasons.filter(r => !blockers.some(b => b.message === r)).map(r => <li key={r}>{r}</li>)}
                </ul>
              )}
              {a.can_decide ? (
                <div className="flex flex-wrap gap-2">
                  <button type="button" className={BTN_PRIMARY} disabled={busy || blockers.length > 0}
                    onClick={() => decide.mutate({ id: a.id, verb: "approve" })}>
                    {busy && decide.variables?.verb === "approve" ? <Loader2 size={14} className="animate-spin" /> : "Send quote + payment link"}
                  </button>
                  <button type="button" className={BTN} disabled={busy} onClick={() => decide.mutate({ id: a.id, verb: "reject" })}>
                    Dismiss
                  </button>
                  <a className={BTN} href="/dashboard/quotes">Open the quote builder</a>
                </div>
              ) : (
                <p className="text-[13px] text-[var(--haip-fg-subtle)]">A teammate who can send quotes will review this.</p>
              )}
            </CardBody>
          </Card>
        );
      })}
    </div>
  );
}
