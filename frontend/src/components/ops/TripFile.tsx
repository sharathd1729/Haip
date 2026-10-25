"use client";
// One caravan trip's ops file (direction A): who and where, the six steps, ONE big "Next step" button, then the checklist,
// extras, money (Saleem report shape), team and timeline. Reads GET /ops/files/{id}; every tap posts to /ops/files/{id}/... and
// shows the server's answer (the server checks every rule again; its message is shown as is when it says no).
import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { useHydrated } from "@/lib/bookingAgenda";
import { canManageOps, canWriteOps, EXPENSE_LABELS, nextAction, rupees, type ChecklistItem, type OpsFileFull } from "@/lib/ops";
import { useToast } from "@/components/ui/toast";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardBody, CardHeader, EmptyState, PageHeader, StatusPill } from "@/components/ui/kit";
import { TripSheets, type SheetKind } from "./TripSheets";

const BOX = {
  green: "bg-[var(--haip-status-success-bg)] text-[var(--haip-status-success-fg)]",
  red: "bg-[var(--haip-status-danger-bg)] text-[var(--haip-status-danger-fg)]",
  pending: "border-[1.5px] border-dashed border-[var(--haip-border-strong)] text-[var(--haip-fg-subtle)]",
};
const BEFORE_ROAD = ["handed_over", "crew_assigned", "readiness", "dispatch_ready"];

function errorText(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof d === "string" ? d : "Check your connection and try again.";
}

function Row({ label, value, hint, strong }: { label: string; value: string; hint?: string; strong?: boolean }) {
  return (
    <div className="flex items-start justify-between gap-3 border-t border-[var(--haip-border)] py-2.5 first:border-t-0">
      <span className="min-w-0 text-[15px]">{label}{hint && <span className="block text-[13px] text-[var(--haip-fg-subtle)]">{hint}</span>}</span>
      <b className={cn("whitespace-nowrap tabular-nums", strong && "text-[var(--haip-accent-ink)]")}>{value}</b>
    </div>
  );
}

export function TripFile({ id }: { id: string }) {
  const hydrated = useHydrated();
  const qc = useQueryClient();
  const { toast } = useToast();
  const { data: session } = useSession();
  const role = session?.user?.role;
  const [sheet, setSheet] = useState<SheetKind>(null);
  const [item, setItem] = useState<ChecklistItem | null>(null);

  const { data: f, isPending, isError, error, refetch } = useQuery<OpsFileFull>({
    queryKey: ["ops-file", id], queryFn: () => api.get(`/ops/files/${id}`).then(r => r.data), staleTime: 10_000, refetchInterval: 60_000,
  });
  const act = useMutation({
    mutationFn: ({ path, body, method }: { path: string; body?: object; method?: "post" | "put" }) =>
      (method === "put" ? api.put(path, body ?? {}) : api.post(path, body ?? {})).then(r => r.data as OpsFileFull),
    onSuccess: data => { qc.setQueryData(["ops-file", id], data); qc.invalidateQueries({ queryKey: ["ops-today"] }); },
  });
  const submit = async (path: string, body?: object, method?: "post" | "put") => {
    try { await act.mutateAsync({ path, body, method }); toast({ title: "Saved", variant: "success" }); return true; }
    catch (e) { toast({ title: "Not saved", description: errorText(e), variant: "error" }); return false; }
  };

  if (!hydrated || isPending) {
    return <div className="mx-auto flex w-full max-w-3xl flex-col gap-3" aria-busy="true"><Skeleton className="h-20" /><Skeleton className="h-32" /><Skeleton className="h-64" /></div>;
  }
  if (isError || !f) {
    const status = (error as { response?: { status?: number } })?.response?.status;
    return (
      <Card className="mx-auto w-full max-w-3xl">
        <EmptyState title={status === 404 ? "Trip not found" : status === 403 ? "You don't have access to Ops" : "Couldn't load this trip"}
          hint={status === 404 || status === 403 ? undefined : "Check your connection, then try again."}
          action={status === 404 || status === 403
            ? <Link href="/dashboard/ops" className="haip-btn-secondary min-h-12">Back to Ops today</Link>
            : <button type="button" className="haip-btn-primary min-h-12" onClick={() => refetch()}>Try again</button>} />
      </Card>
    );
  }

  const write = canWriteOps(role), manage = canManageOps(role);
  const s = f.stay, a = f.account;
  const na = nextAction(f.stage.next_key, manage);
  const beforeRoad = BEFORE_ROAD.includes(f.state);
  const party = `${s.adults} adult${s.adults === 1 ? "" : "s"}${s.children ? ` + ${s.children} kid${s.children === 1 ? "" : "s"}` : ""}`;
  const dates = `${new Date(s.check_in).toLocaleDateString("en-IN", { day: "numeric", month: "short" })} – ${new Date(s.check_out).toLocaleDateString("en-IN", { day: "numeric", month: "short" })}`;
  const scrollTo = (el: string) => document.getElementById(el)?.scrollIntoView({ behavior: "smooth", block: "start" });

  const runNext = () => {
    if (!na) return;
    if (na.kind === "accept" || na.kind === "crew" || na.kind === "dispatch" || na.kind === "return") setSheet(na.kind);
    else if (na.kind === "checklist") scrollTo("ops-checklist");
    else if (na.kind === "extras") scrollTo("ops-extras");
    else if (na.kind === "settle") submit(`/ops/files/${f.id}/settle`, { step: na.step });
    else if (na.kind === "close") submit(`/ops/files/${f.id}/close`);
  };
  const waiting = f.extras.filter(x => x.status === "proposed");

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-4">
      <Link href="/dashboard/ops" className="text-[14px] font-semibold text-primary">← Ops today</Link>
      <div className="flex flex-col gap-1">
        <StatusPill tone="brand" className="self-start">{s.property_name ?? "Trip"}</StatusPill>
        <PageHeader title={s.guest_name} keepOnPhone icon={false}
          subtitle={`${f.details.route ?? "Route not set yet"} · ${dates} · ${party}`} />
      </div>

      <div aria-label={`Step ${f.stage.step} of 6: ${f.stage.step_name}`}>
        <div className="flex gap-1">
          {f.stage.step_names.map((n, i) => (
            <span key={n} className={cn("h-1.5 flex-1 rounded-full",
              i + 1 < f.stage.step ? "bg-primary" : i + 1 === f.stage.step ? "bg-[var(--haip-accent)]" : "bg-[var(--haip-border)]")} />
          ))}
        </div>
        <div className="mt-1 flex justify-between gap-2 text-[12px] text-[var(--haip-fg-subtle)]">
          <span>{f.stage.step_names[0]}</span><b className="text-[var(--haip-accent-ink)]">Now: {f.stage.step_name}</b><span>{f.stage.step_names[5]}</span>
        </div>
      </div>

      {f.stage.next && (
        <section className="rounded-2xl bg-[var(--haip-nav-bg)] p-4 text-[var(--haip-nav-fg)]">
          <p className="text-[12px] font-bold uppercase tracking-[0.08em] opacity-75">Next step</p>
          <p className="mt-1 text-[17px] font-semibold leading-snug">{f.stage.next}</p>
          {na?.kind === "booking" ? (
            <Link href={`/dashboard/bookings/${s.id}`} className="haip-btn-primary mt-3 min-h-12 w-full text-[16px]">{na.label}</Link>
          ) : na ? (
            <button type="button" disabled={act.isPending || (!write && na.kind !== "checklist" && na.kind !== "extras")}
              onClick={runNext} className="haip-btn-primary mt-3 min-h-12 w-full text-[16px]">
              {na.label}
            </button>
          ) : f.stage.next_key && f.stage.next_key !== "wait" ? (
            <p className="mt-2 text-[13.5px] opacity-80">A manager does this step.</p>
          ) : null}
          {f.close_blockers.length > 0 && <p className="mt-2 text-[13.5px] opacity-80">Still to do: {f.close_blockers.join(", ")}.</p>}
        </section>
      )}

      <Card id="ops-checklist">
        <CardHeader title="Ready to leave" description={`${f.gate.green} of ${f.gate.total} green${f.gate.blocking.length ? `, ${f.gate.blocking.length} critical still open` : ""}`} />
        <CardBody className="px-4 pb-2">
          {f.checklist.map(i => (
            <button key={i.key} type="button" disabled={!write || !beforeRoad}
              onClick={() => { setItem(i); setSheet("item"); }}
              className="grid min-h-[56px] w-full grid-cols-[28px_1fr_auto] items-center gap-3 border-t border-[var(--haip-border)] py-2.5 text-left first:border-t-0 disabled:cursor-default">
              <span aria-hidden className={cn("grid size-7 place-items-center rounded-lg text-[14px] font-bold", BOX[i.status])}>
                {i.status === "green" ? "✓" : i.status === "red" ? "!" : ""}
              </span>
              <span className="min-w-0 text-[15px]">
                {i.label}{i.critical && <span className="sr-only"> (must be green to leave)</span>}
                <span className="block text-[13px] text-[var(--haip-fg-subtle)]">
                  {i.note ?? (i.status === "green" ? (i.has_photo ? "Photo checked" : "Done") :
                    i.source === "staff" ? "Waiting for the helper's photo" : i.source === "system" ? "From the booking" : "Your check")}
                </span>
              </span>
              <span className="text-[12px] font-semibold text-[var(--haip-fg-subtle)]">
                {i.status === "red" ? "Problem" : i.critical && i.status !== "green" ? "Must do" : ""}
              </span>
            </button>
          ))}
        </CardBody>
      </Card>

      <Card id="ops-extras">
        <CardHeader title="Extras" description={waiting.length ? `${waiting.length} waiting for a manager` : "Asked for during the trip"}
          actions={write && f.state !== "closed" ? <button type="button" className="haip-btn-secondary min-h-11" onClick={() => setSheet("extra")}>Add</button> : undefined} />
        <CardBody className="px-4 pb-3">
          {f.extras.filter(x => x.status !== "removed").length === 0 ? (
            <p className="py-2 text-[14px] text-[var(--haip-fg-subtle)]">Nothing extra yet.</p>
          ) : f.extras.filter(x => x.status !== "removed").map(x => (
            <div key={x.id} className="flex flex-wrap items-center gap-2 border-t border-[var(--haip-border)] py-2.5 first:border-t-0">
              <span className="min-w-0 flex-1 text-[15px]">{x.label} <b className="tabular-nums">{rupees(x.amount)}</b></span>
              {x.status === "approved" ? <StatusPill tone="success">On the bill</StatusPill> : manage ? (
                <span className="flex gap-2">
                  <button type="button" className="haip-btn-primary min-h-11" disabled={act.isPending}
                    onClick={() => submit(`/ops/files/${f.id}/extras/${x.id}/approve`)}>Approve</button>
                  <button type="button" className="haip-btn-secondary min-h-11" disabled={act.isPending}
                    onClick={() => submit(`/ops/files/${f.id}/extras/${x.id}/remove`)}>Don&apos;t charge</button>
                </span>
              ) : <StatusPill tone="warning">Waiting</StatusPill>}
            </div>
          ))}
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Money" description="This trip so far, GST included"
          actions={write && f.state !== "closed" ? <button type="button" className="haip-btn-secondary min-h-11" onClick={() => setSheet("expense")}>Add expense</button> : undefined} />
        <CardBody className="px-4 pb-3">
          <Row label="Package" value={rupees(a.package_total)} />
          {Number(a.addons_total) > 0 && <Row label="Extras and extra distance" value={rupees(a.addons_total)}
            hint={a.extra_km ? `${a.extra_km.toLocaleString("en-IN")} km over the ${Number(a.allowance_km ?? 0).toLocaleString("en-IN")} km included` : undefined} />}
          <Row label="Total" value={rupees(a.total_revenue)} />
          <Row label="Paid" value={rupees(a.paid)} />
          <Row label="Balance" value={rupees(a.outstanding)} strong={Number(a.outstanding) > 0} />
          {a.deposit && <Row label="Deposit" value={rupees(a.deposit.amount)} hint={a.deposit.status === "held" ? "Held, refund within 48 h of return" : a.deposit.status} />}
          {Object.entries(a.expenses_by_category).map(([k, v]) => <Row key={k} label={`Expense: ${EXPENSE_LABELS[k] ?? k}`} value={rupees(v)} />)}
          <Row label="Net after expenses" value={rupees(a.net_cash)} />
          {f.state === "on_trip" && (
            <button type="button" className="haip-btn-secondary mt-2 min-h-12 w-full" onClick={() => setSheet("return")}>Vehicle is back: enter odometer</button>
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Team" tone="plain"
          actions={write && beforeRoad ? <button type="button" className="haip-btn-secondary min-h-11" onClick={() => setSheet("crew")}>Change</button> : undefined} />
        <CardBody className="flex flex-wrap gap-2 px-4 pb-4">
          <StatusPill tone="neutral">Driver: {f.crew.driver ?? "not set"}</StatusPill>
          <StatusPill tone="neutral">Helper: {f.crew.helper ?? "not set"}</StatusPill>
          {s.concierge_notes && <p className="w-full text-[14px] text-[var(--haip-fg-muted)]">Notes: {s.concierge_notes}</p>}
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="What happened" tone="plain" />
        <CardBody className="px-4 pb-4">
          <ol className="flex flex-col gap-2">
            {[...f.timeline].reverse().slice(0, 30).map((t, i) => (
              <li key={`${t.at}-${i}`} className="grid grid-cols-[92px_1fr] gap-3 text-[14px]">
                <span className="tabular-nums text-[var(--haip-fg-subtle)]">
                  {new Date(t.at).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" })}
                </span>
                <span>{t.text}</span>
              </li>
            ))}
          </ol>
        </CardBody>
      </Card>

      <TripSheets file={f} kind={sheet} item={item} busy={act.isPending}
        onClose={() => { setSheet(null); setItem(null); }} submit={submit} />
    </div>
  );
}
