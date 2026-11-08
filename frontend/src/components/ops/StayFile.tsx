"use client";
// One villa stay's ops file (villa pack, direction A): who and which villa, the six steps, ONE big "Next step" button, then
// the Ready to welcome checklist (the check-out inspection once the guest has left), the people, the meal plan, mid-stay
// cleaning, the booking's requests, extras, money with the deposit decision, and the timeline. No odometer, no crew.
// TripFile loads the file and hands a villa here; every tap goes through its `submit` (the server checks every rule again).
import { useState } from "react";
import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import { cn } from "@/lib/utils";
import {
  EXPENSE_LABELS, FOOD_LABELS, rupees, stayNextAction, type ChecklistItem, type Meal, type OpsFileFull,
} from "@/lib/ops";
import { Card, CardBody, CardHeader, PageHeader, StatusPill } from "@/components/ui/kit";
import { TripSheets, type SheetKind } from "./TripSheets";
import { StaySheets, type StaySheetKind } from "./StaySheets";
import { GuestFormCard } from "./TripCards";

type Submit = (path: string, body?: object, method?: "post" | "put" | "delete") => Promise<boolean>;

const BOX = {
  green: "bg-[var(--haip-status-success-bg)] text-[var(--haip-status-success-fg)]",
  red: "bg-[var(--haip-status-danger-bg)] text-[var(--haip-status-danger-fg)]",
  pending: "border-[1.5px] border-dashed border-[var(--haip-border-strong)] text-[var(--haip-fg-subtle)]",
};
const BEFORE_WELCOME = ["preparing", "ready"];
const MEAL_LABEL: Record<Meal["meal"], string> = { breakfast: "Breakfast", lunch: "Lunch", dinner: "Dinner" };

const day = (iso: string) =>
  new Date(`${iso.slice(0, 10)}T00:00:00Z`).toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" });

function Row({ label, value, hint, strong }: { label: string; value: string; hint?: string; strong?: boolean }) {
  return (
    <div className="flex items-start justify-between gap-3 border-t border-[var(--haip-border)] py-2.5 first:border-t-0">
      <span className="min-w-0 text-[15px]">{label}{hint && <span className="block text-[13px] text-[var(--haip-fg-subtle)]">{hint}</span>}</span>
      <b className={cn("whitespace-nowrap tabular-nums", strong && "text-[var(--haip-accent-ink)]")}>{value}</b>
    </div>
  );
}

function Checklist({ items, disabled, onPick }: { items: ChecklistItem[]; disabled: boolean; onPick: (i: ChecklistItem) => void }) {
  return (
    <>
      {items.map(i => (
        <button key={i.key} type="button" disabled={disabled} onClick={() => onPick(i)}
          className="grid min-h-[56px] w-full grid-cols-[28px_1fr_auto] items-center gap-3 border-t border-[var(--haip-border)] py-2.5 text-left first:border-t-0 disabled:cursor-default">
          <span aria-hidden className={cn("grid size-7 place-items-center rounded-lg text-[14px] font-bold", BOX[i.status])}>
            {i.status === "green" ? "✓" : i.status === "red" ? "!" : ""}
          </span>
          <span className="min-w-0 text-[15px]">
            {i.label}{i.critical && <span className="sr-only"> (must be green)</span>}
            <span className="block text-[13px] text-[var(--haip-fg-subtle)]">
              {i.note ?? (i.status === "green" ? (i.has_photo ? "Photo checked" : "Done") :
                i.source === "staff" ? "Waiting for the caretaker's photo" : i.source === "system" ? "From the booking" : "Your check")}
            </span>
          </span>
          <span className="text-[12px] font-semibold text-[var(--haip-fg-subtle)]">
            {i.status === "red" ? "Problem" : i.critical && i.status !== "green" ? "Must do" : ""}
          </span>
        </button>
      ))}
    </>
  );
}

export function StayFile({ f, submit, busy, write, manage, onReport, reportBusy }: {
  f: OpsFileFull; submit: Submit; busy: boolean; write: boolean; manage: boolean; onReport: () => void; reportBusy: boolean;
}) {
  const qc = useQueryClient();
  const [sheet, setSheet] = useState<SheetKind>(null);
  const [stay, setStay] = useState<StaySheetKind>(null);
  const [item, setItem] = useState<ChecklistItem | null>(null);
  const s = f.stay, a = f.account, d = f.details;
  const base = `/ops/files/${f.id}`;
  const na = stayNextAction(f.stage.next_key, manage);
  const before = BEFORE_WELCOME.includes(f.state);
  const inspecting = f.state === "checked_out";
  const over = f.state === "closed" || f.state === "cancelled";
  const meals = d.meals ?? [];
  const waiting = f.extras.filter(x => x.status === "proposed");
  const openClean = (f.cleaning ?? []).filter(j => j.status === "open");
  const party = `${s.adults} adult${s.adults === 1 ? "" : "s"}${s.children ? ` + ${s.children} kid${s.children === 1 ? "" : "s"}` : ""}`;
  const scrollTo = (el: string) => document.getElementById(el)?.scrollIntoView({ behavior: "smooth", block: "start" });

  const runNext = () => {
    if (!na) return;
    if (na.kind === "people" || na.kind === "checkin" || na.kind === "deposit") setStay(na.kind);
    else if (na.kind === "checklist" || na.kind === "inspection") scrollTo("ops-checklist");
    else if (na.kind === "extras") scrollTo("ops-extras");
    else if (na.kind === "meals") scrollTo("ops-meals");
    else if (na.kind === "cleaning") scrollTo("ops-cleaning");
    else if (na.kind === "checkout") submit(`${base}/check-out`);
    else if (na.kind === "settle") submit(`${base}/settle`, { step: na.step });
    else if (na.kind === "close") submit(`${base}/close`);
  };
  const checklist = inspecting || f.state === "settling" ? (f.inspection ?? []) : f.checklist;
  const deposit = a.deposit;

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 p-4 sm:p-6">
      <Link href="/dashboard/ops" className="text-[14px] font-semibold text-primary">← Ops today</Link>
      <div className="flex flex-col gap-1">
        <StatusPill tone="brand" className="self-start">{s.property_name ?? "Villa"}</StatusPill>
        <PageHeader title={s.guest_name} keepOnPhone icon={false}
          subtitle={`${day(s.check_in)} – ${day(s.check_out)}${s.check_in_time ? `, arrives ${s.check_in_time}` : ""} · ${party}`} />
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
            <button type="button" disabled={busy || (!write && !["checklist", "inspection", "extras", "meals", "cleaning"].includes(na.kind))}
              onClick={runNext} className="haip-btn-primary mt-3 min-h-12 w-full text-[16px]">{na.label}</button>
          ) : f.stage.next_key && f.stage.next_key !== "wait" ? (
            <p className="mt-2 text-[13.5px] opacity-80">A manager does this step.</p>
          ) : null}
          {f.close_blockers.length > 0 && <p className="mt-2 text-[13.5px] opacity-80">Still to do: {f.close_blockers.join(", ")}.</p>}
        </section>
      )}

      <Card id="ops-checklist">
        <CardHeader title={inspecting || f.state === "settling" ? "Check-out inspection" : "Ready to welcome"}
          description={inspecting || f.state === "settling"
            ? "Compared with the arrival photos. Send each area's photo on WhatsApp."
            : `${f.gate.green} of ${f.gate.total} green${f.gate.blocking.length ? `, ${f.gate.blocking.length} must-do still open` : ""}`} />
        <CardBody className="px-4 pb-2">
          {checklist.length === 0
            ? <p className="py-2 text-[14px] text-[var(--haip-fg-subtle)]">The inspection opens when the guest checks out.</p>
            : <Checklist items={checklist} disabled={!write || !(before || inspecting)} onPick={i => { setItem(i); setSheet("item"); }} />}
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="People" tone="plain"
          actions={write && !over ? <button type="button" className="haip-btn-secondary min-h-11" onClick={() => setStay("people")}>Change</button> : undefined} />
        <CardBody className="flex flex-wrap gap-2 px-4 pb-4">
          <StatusPill tone="neutral">Caretaker: {f.people?.caretaker ?? "not set"}</StatusPill>
          <StatusPill tone="neutral">Cook: {f.people?.cook ?? "not set"}</StatusPill>
          <StatusPill tone="neutral">Cleaner: {f.people?.cleaner ?? "not set"}</StatusPill>
          {s.concierge_notes && <p className="w-full text-[14px] text-[var(--haip-fg-muted)]">Notes: {s.concierge_notes}</p>}
        </CardBody>
      </Card>

      <Card id="ops-meals">
        <CardHeader title="Meal plan" description={meals.length ? `${meals.filter(m => !m.confirmed_at).length} not confirmed by the cook` : "What the cook makes, day by day"}
          actions={write && !over && f.state !== "settling" ? <button type="button" className="haip-btn-secondary min-h-11" onClick={() => setStay("meal")}>Add</button> : undefined} />
        <CardBody className="px-4 pb-3">
          {meals.length === 0 ? <p className="py-2 text-[14px] text-[var(--haip-fg-subtle)]">No meals planned.</p> : meals.map(m => (
            <div key={m.id} className="flex flex-wrap items-center gap-2 border-t border-[var(--haip-border)] py-2.5 first:border-t-0">
              <span className="min-w-0 flex-1 text-[15px]">
                {day(m.date)} · {MEAL_LABEL[m.meal]}
                <span className="block text-[13px] text-[var(--haip-fg-subtle)]">
                  {m.guests} guests, {FOOD_LABELS[m.food]}{m.notes ? ` · ${m.notes}` : ""}
                </span>
              </span>
              {m.confirmed_at ? <StatusPill tone="success">{m.confirmed_by === "cook" ? "Cook confirmed" : "Confirmed"}</StatusPill> : write ? (
                <span className="flex gap-2">
                  <button type="button" className="haip-btn-secondary min-h-11" disabled={busy}
                    onClick={() => submit(`${base}/meals/confirm`, { meal_ids: [m.id] })}>Mark confirmed</button>
                  <button type="button" className="min-h-11 px-2 text-[14px] font-semibold text-[var(--haip-fg-muted)]" disabled={busy}
                    onClick={() => submit(`${base}/meals/${m.id}`, undefined, "delete")}>Remove</button>
                </span>
              ) : <StatusPill tone="warning">Waiting</StatusPill>}
            </div>
          ))}
          {write && meals.some(m => !m.confirmed_at) && f.people?.cook && (
            <button type="button" className="haip-btn-secondary mt-2 min-h-12 w-full" disabled={busy}
              onClick={() => submit(`${base}/meals/send`)}>Send the plan to {f.people.cook} on WhatsApp</button>
          )}
        </CardBody>
      </Card>

      {(f.cleaning?.length || f.service_requests?.length) ? (
        <Card id="ops-cleaning">
          <CardHeader title="During the stay" tone="plain" description="Mid-stay cleaning every 3rd day, and what the guest asked for" />
          <CardBody className="px-4 pb-3">
            {(f.cleaning ?? []).filter(j => j.status !== "cancelled").map(j => (
              <div key={j.id} className="flex items-center gap-2 border-t border-[var(--haip-border)] py-2.5 first:border-t-0">
                <span className="min-w-0 flex-1 text-[15px]">Cleaning {j.due_at ? day(j.due_at) : ""}</span>
                {j.status === "done" ? <StatusPill tone="success">Done</StatusPill> : write ? (
                  <button type="button" className="haip-btn-secondary min-h-11" disabled={busy}
                    onClick={() => submit(`${base}/cleaning/${j.id}/done`)}>Mark done</button>
                ) : <StatusPill tone="warning">To do</StatusPill>}
              </div>
            ))}
            {(f.service_requests ?? []).map(r => (
              <div key={r.id} className="flex items-center gap-2 border-t border-[var(--haip-border)] py-2.5 first:border-t-0">
                <span className="min-w-0 flex-1 text-[15px]">{r.title}{r.due_date && <span className="block text-[13px] text-[var(--haip-fg-subtle)]">By {day(r.due_date)}</span>}</span>
                <StatusPill tone={r.status === "done" ? "success" : "warning"}>{r.status === "done" ? "Done" : "Open"}</StatusPill>
              </div>
            ))}
            {openClean.length === 0 && !(f.service_requests ?? []).length && <p className="py-2 text-[14px] text-[var(--haip-fg-subtle)]">Nothing open.</p>}
            <Link href={`/dashboard/bookings/${s.id}`} className="mt-1 inline-block py-2 text-[14px] font-semibold text-primary">Add a request on the booking</Link>
          </CardBody>
        </Card>
      ) : null}

      <Card id="ops-extras">
        <CardHeader title="Extras" description={waiting.length ? `${waiting.length} waiting for a manager` : "Asked for during the stay"}
          actions={write && !over ? <button type="button" className="haip-btn-secondary min-h-11" onClick={() => setSheet("extra")}>Add</button> : undefined} />
        <CardBody className="px-4 pb-3">
          {f.extras.filter(x => x.status !== "removed").length === 0 ? (
            <p className="py-2 text-[14px] text-[var(--haip-fg-subtle)]">Nothing extra yet.</p>
          ) : f.extras.filter(x => x.status !== "removed").map(x => (
            <div key={x.id} className="flex flex-wrap items-center gap-2 border-t border-[var(--haip-border)] py-2.5 first:border-t-0">
              <span className="min-w-0 flex-1 text-[15px]">{x.label} <b className="tabular-nums">{rupees(x.amount)}</b></span>
              {x.status === "approved" ? <StatusPill tone="success">On the bill</StatusPill> : manage ? (
                <span className="flex gap-2">
                  <button type="button" className="haip-btn-primary min-h-11" disabled={busy} onClick={() => submit(`${base}/extras/${x.id}/approve`)}>Approve</button>
                  <button type="button" className="haip-btn-secondary min-h-11" disabled={busy} onClick={() => submit(`${base}/extras/${x.id}/remove`)}>Don&apos;t charge</button>
                </span>
              ) : <StatusPill tone="warning">Waiting</StatusPill>}
            </div>
          ))}
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Money" description="This stay so far, GST included"
          actions={write && !over ? <button type="button" className="haip-btn-secondary min-h-11" onClick={() => setSheet("expense")}>Add expense</button> : undefined} />
        <CardBody className="px-4 pb-3">
          <Row label="Stay" value={rupees(a.package_total)} />
          {Number(a.addons_total) > 0 && <Row label="Extras" value={rupees(a.addons_total)} />}
          <Row label="Total" value={rupees(a.total_revenue)} />
          <Row label="Paid" value={rupees(a.paid)} />
          <Row label="Balance" value={rupees(a.outstanding)} strong={Number(a.outstanding) > 0} />
          {deposit && (
            <Row label="Security deposit" value={rupees(deposit.amount)}
              hint={deposit.status === "held" ? "Held. Decide after the check-out inspection"
                : deposit.status === "pending" ? "Not collected"
                : Number(deposit.deducted) > 0 ? `${rupees(deposit.deducted)} kept${d.deposit_reason ? `: ${d.deposit_reason}` : ""}` : "Refunded in full"} />
          )}
          {Object.entries(a.expenses_by_category).map(([k, v]) => <Row key={k} label={`Expense: ${EXPENSE_LABELS[k] ?? k}`} value={rupees(v)} />)}
          <Row label="Net after expenses" value={rupees(a.net_cash)} />
          {manage && f.state === "settling" && deposit?.status === "held" && (
            <button type="button" className="haip-btn-secondary mt-2 min-h-12 w-full" onClick={() => setStay("deposit")}>Decide the deposit</button>
          )}
          {f.state === "staying" && write && (
            <button type="button" className="haip-btn-secondary mt-2 min-h-12 w-full" disabled={busy} onClick={() => submit(`${base}/check-out`)}>Guest has left: check out</button>
          )}
          {manage && (
            <button type="button" className="haip-btn-secondary mt-2 min-h-12 w-full" disabled={reportBusy} onClick={onReport}>
              {reportBusy ? "Making the report…" : "Stay account report (PDF)"}
            </button>
          )}
        </CardBody>
      </Card>

      <GuestFormCard f={f} canWrite={write} canManage={manage}
        onSent={() => qc.invalidateQueries({ queryKey: ["ops-file", f.id] })} />

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

      <TripSheets file={f} kind={sheet} item={item} busy={busy} onClose={() => { setSheet(null); setItem(null); }} submit={submit} />
      <StaySheets file={f} kind={stay} busy={busy} onClose={() => setStay(null)} submit={submit} />
    </div>
  );
}
