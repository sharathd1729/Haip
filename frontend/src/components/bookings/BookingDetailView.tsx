"use client";
// One booking (Bookings layout B · Agenda): the guest and what to do now (Call, WhatsApp, Collect, Check in / out), the stay,
// the money (total, paid, still due, the schedule, the security deposit kept apart), add-ons, notes, invoice and timeline.
// Used by the full booking page (variant "page") and by the agenda's pane / phone sheet (variant "pane").
// Sizes follow the container, not the window, so the same layout works in a 520px pane and a full page.
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useSession } from "next-auth/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ChevronLeft, CreditCard, MessageCircle, Phone } from "@/lib/icons";
import api from "@/lib/api";
import { cn, formatINR, formatPhone } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { Card, CardBody, CardHeader, StatusPill, Timeline } from "@/components/ui/kit";
import { GuestAvatar } from "@/components/crm/GuestAvatar";
import { AddOnsPanel } from "@/components/bookings/AddOnsPanel";
import { PaymentsPanel } from "@/components/bookings/PaymentsPanel";
import { SchedulePanel } from "@/components/bookings/SchedulePanel";
import { DepositPanel } from "@/components/bookings/DepositPanel";
import { ServiceRequestsPanel } from "@/components/bookings/ServiceRequestsPanel";
import { ChangeGuestDialog } from "@/components/bookings/ChangeGuestDialog";
import { InvoicesMessagesCard } from "@/components/bookings/InvoicesMessagesCard";
import { CollectSheet, refreshBooking } from "@/components/bookings/CollectSheet";
import { WhatsAppSheet } from "@/components/bookings/WhatsAppSheet";
import { VehicleTag } from "@/components/bookings/agenda/AgendaDays";
import { useGuestCall } from "@/components/bookings/useGuestCall";
import {
  CHANNEL_STYLE, PAYMENT_STYLE, PAYMENT_TONE, STATUS_OPTIONS, STATUS_STYLE, STATUS_TONE, LOAD_FAILURES, describeActivity, errorMessage, fmtDate, httpStatus, loadFailure,
  type BookingDetail,
} from "@/lib/bookings";
import { addDays, canEditBookings, clock, shortDay, todayIST, vehicleSlot } from "@/lib/bookingAgenda";

const field = "w-full text-sm border border-[var(--haip-border)] rounded-lg px-2.5 py-2 bg-[var(--haip-card)] text-[var(--haip-fg)] focus:outline-none focus:ring-2 focus:ring-primary disabled:bg-[var(--haip-surface)] disabled:text-[var(--haip-fg-subtle)]";
const label = "block text-xs font-medium text-[var(--haip-fg-subtle)]";
const chipBtn = "inline-flex min-h-9 pointer-coarse:min-h-11 items-center gap-1.5 rounded-lg border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 text-xs font-semibold text-[var(--haip-fg-2)] hover:bg-[var(--haip-surface)] disabled:opacity-50";
const bigBtn = "inline-flex min-h-11 items-center justify-center gap-1.5 rounded-xl px-2 text-[14px] font-semibold disabled:opacity-50";

interface Draft {
  property_id: string; check_in: string; check_out: string; check_in_time: string; check_out_time: string;
  adults: string; children: string; total_amount: string; occasion: string; special_requests: string; internal_notes: string; concierge_notes: string;
}

function toDraft(b: BookingDetail): Draft {
  return {
    property_id: b.property?.id ?? "", check_in: b.check_in, check_out: b.check_out,
    check_in_time: b.check_in_time ?? "", check_out_time: b.check_out_time ?? "",
    adults: String(b.adults), children: String(b.children), total_amount: String(b.financials.stay_charge),
    occasion: b.occasion ?? "", special_requests: b.special_requests, internal_notes: b.internal_notes, concierge_notes: b.concierge_notes,
  };
}

/** "Fri 30 Oct, 12:00 pm" (the time only when one is set). */
function dayAndTime(date: string, time: string | null): string {
  const t = clock(time);
  return t ? `${shortDay(date)}, ${t}` : shortDay(date);
}

function Fact({ name, wide, children }: { name: string; wide?: boolean; children: React.ReactNode }) {
  return (
    <div className={cn("grid min-w-0", wide && "col-span-2")}>
      <span className="text-xs font-semibold text-[var(--haip-fg-subtle)]">{name}</span>
      <span className="text-[14.5px] font-medium text-[var(--haip-fg)] [overflow-wrap:anywhere]">{children}</span>
    </div>
  );
}

export function BookingDetailView({ id, variant = "page", onClose }: { id: string; variant?: "page" | "pane"; onClose?: () => void }) {
  const { data: session } = useSession();
  const role = session?.user?.role;
  const canEdit = canEditBookings(role);
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const pane = variant === "pane";
  const call = useGuestCall();

  const { data: booking, isLoading, isError, error, refetch, isFetching } = useQuery<BookingDetail>({
    queryKey: ["booking", id],
    queryFn: () => api.get(`/bookings/${id}`).then(r => r.data),
    // a definite answer (not found, no permission, signed out) will not change on retry; a network or server error might
    retry: (count, err) => !LOAD_FAILURES.has(httpStatus(err) ?? 0) && count < 2,
    // pick up a Razorpay payment that arrives while the page is open
    refetchInterval: q => (q.state.data?.payment_links.some(l => l.status === "created") ? 20_000 : false),
  });
  const { data: properties = [] } = useQuery<{ id: string; name: string }[]>({
    queryKey: ["bookable-properties"],
    queryFn: () => api.get("/bookings/properties").then(r => r.data),
    staleTime: 5 * 60_000,
  });

  const [draft, setDraft] = useState<Draft | null>(null);
  const [editing, setEditing] = useState(false);
  const [changingGuest, setChangingGuest] = useState(false);
  const [sheet, setSheet] = useState<"collect" | "whatsapp" | null>(null);
  useEffect(() => { if (booking) setDraft(toDraft(booking)); }, [booking]);
  // A different booking in the pane starts closed.
  useEffect(() => { setEditing(false); setChangingGuest(false); setSheet(null); }, [id]);

  const setBooking = (b: BookingDetail) => refreshBooking(queryClient, b);

  const dirty = useMemo(() => !!booking && !!draft && JSON.stringify(toDraft(booking)) !== JSON.stringify(draft), [booking, draft]);

  const calendarSync = useMutation({
    mutationFn: (locked: boolean) => api.put(`/bookings/${id}/calendar-sync`, { locked }).then(() => api.get<BookingDetail>(`/bookings/${id}`)),
    onSuccess: res => { setBooking(res.data); toast({ variant: "success", title: res.data.calendar_sync?.locked ? "Kept as it is here" : "Following the calendar again" }); },
    onError: e => toast({ variant: "error", title: errorMessage(e, "Could not change this") }),
  });

  const save = useMutation({
    mutationFn: async (patch: Record<string, unknown>) => {
      await api.patch(`/bookings/${id}`, patch);
      return api.get<BookingDetail>(`/bookings/${id}`);
    },
    onSuccess: (res, patch) => {
      setBooking(res.data); setEditing(false);
      const st = (patch as { status?: string }).status;
      toast({ variant: "success", title: st === "checked_in" ? "Checked in" : st === "checked_out" ? "Checked out" : st === "cancelled" ? "Booking cancelled" : "Saved" });
    },
    onError: (e, patch) => {
      const detail = (e as { response?: { data?: { detail?: { code?: string; message?: string } } } })?.response?.data?.detail;
      if (detail && typeof detail === "object" && detail.code === "date_conflict") {
        if (confirm(`${detail.message}\n\nSave anyway?`)) save.mutate({ ...patch, force: true });
        return;
      }
      toast({ variant: "error", title: errorMessage(e, "Could not save") });
    },
  });

  if (isLoading || !booking || !draft) {
    return (
      <div className={cn("space-y-4", pane ? "p-4" : "mx-auto max-w-5xl p-6")}>
        {pane && onClose && (
          <button type="button" onClick={onClose} aria-label="Close booking" className="flex size-11 items-center justify-center rounded-xl text-[var(--haip-fg-2)] hover:bg-[var(--haip-surface)]">
            <ChevronLeft size={20} />
          </button>
        )}
        {isError ? (() => {
          const f = loadFailure(error);
          return (
            <div role="alert" className="py-16 text-center">
              <p className="text-base font-semibold text-[var(--haip-fg)]">{f.title}</p>
              <p className="mt-1 text-sm text-[var(--haip-fg-subtle)]">{f.body}</p>
              <div className="mt-4 flex items-center justify-center gap-4">
                {f.retry && (
                  <button type="button" onClick={() => refetch()} disabled={isFetching}
                    className="min-h-11 rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground disabled:opacity-60">
                    {isFetching ? "Trying…" : "Try again"}
                  </button>
                )}
                {!pane && <Link href="/dashboard/bookings" className="inline-flex min-h-11 items-center text-sm font-medium text-primary hover:underline">Back to bookings</Link>}
              </div>
            </div>
          );
        })() : (
          <>
            <Skeleton className="h-40 rounded-2xl" />
            <Skeleton className="h-56 rounded-2xl" />
          </>
        )}
      </div>
    );
  }

  const set = (k: keyof Draft) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) =>
    setDraft(d => d && { ...d, [k]: e.target.value });

  function submit() {
    if (!draft || !booking) return;
    if (draft.check_out < draft.check_in) { toast({ variant: "error", title: "Check-out can't be before check-in" }); return; }
    save.mutate({
      property_id: draft.property_id || undefined, check_in: draft.check_in, check_out: draft.check_out,
      check_in_time: draft.check_in_time, check_out_time: draft.check_out_time,
      adults: Math.max(1, Number(draft.adults) || 1), children: Math.max(0, Number(draft.children) || 0),
      total_amount: Number(draft.total_amount) || 0, occasion: draft.occasion,
      special_requests: draft.special_requests, internal_notes: draft.internal_notes, concierge_notes: draft.concierge_notes,
    });
  }

  function setStatus(next: string) {
    if (next === "cancelled" && !confirm("Cancel this booking? The dates will be freed. Any money already received stays in the ledger.")) return;
    save.mutate({ status: next });
  }

  const guest = booking.guest;
  const canErase = role === "owner" || role === "compliance";
  const cancelled = booking.status === "cancelled";
  const showForm = editing || dirty;
  const name = guest?.name || (guest ? formatPhone(guest.phone) : "Booking");
  const Title = pane ? "h2" : "h1";
  const f = booking.financials;
  const today = todayIST();
  const nights = booking.nights;
  const slot = vehicleSlot(booking.property?.name, properties.map(p => p.name));
  const nextStep = !canEdit ? null
    : booking.status === "confirmed" && booking.check_in <= addDays(today, 1) ? { label: "Check in", status: "checked_in" }
      : booking.status === "checked_in" ? { label: "Check out", status: "checked_out" } : null;
  const statusPill = <StatusPill tone={STATUS_TONE[booking.status] ?? "info"}>{(STATUS_STYLE[booking.status] ?? STATUS_STYLE.confirmed).label}</StatusPill>;

  return (
    <div className={cn("@container", pane ? "min-h-full" : "h-full overflow-y-auto bg-[var(--haip-bg,var(--background))]")}>
      {pane && (
        <div className="sticky top-0 z-10 flex items-center gap-1.5 border-b border-[var(--haip-border)] bg-[var(--haip-bg,var(--background))] px-2 py-1.5 sm:px-3">
          {onClose && (
            <button type="button" onClick={onClose} aria-label="Close booking" className="flex size-11 shrink-0 items-center justify-center rounded-xl text-[var(--haip-fg-2)] hover:bg-[var(--haip-surface)]">
              <ChevronLeft size={20} />
            </button>
          )}
          <div className="grid min-w-0 flex-1">
            <b className="truncate text-[15px] text-[var(--haip-fg)]">{name}</b>
            <span className="truncate text-[12.5px] text-[var(--haip-fg-subtle)]">
              {booking.property?.name ?? "No vehicle"} · {shortDay(booking.check_in)}{nights ? ` → ${shortDay(booking.check_out)} · ${nights} night${nights === 1 ? "" : "s"}` : " · day trip"}
            </span>
          </div>
          {statusPill}
          <Link href={`/dashboard/bookings/${booking.id}`} className={cn(chipBtn, "hidden @md:inline-flex")}>Full page</Link>
        </div>
      )}
      <div className={cn("space-y-3", pane ? "p-3 sm:p-4" : "mx-auto max-w-5xl p-4 sm:p-6")}>
        {!pane && (
          <Link href="/dashboard/bookings" className="inline-flex min-h-9 pointer-coarse:min-h-11 items-center gap-1.5 text-sm text-[var(--haip-fg-subtle)] hover:text-[var(--haip-fg)]">
            <ArrowLeft size={14} /> Bookings
          </Link>
        )}

        {/* The guest, and what to do now. */}
        <Card>
          <CardBody className="space-y-3 pt-4">
            <div className="flex items-center gap-3">
              <GuestAvatar name={guest?.name} phone={guest?.phone} size="lg" />
              <div className="min-w-0 flex-1">
                <Title className={cn("font-[family-name:var(--font-display)] text-[22px] font-semibold leading-tight tracking-[-0.015em] text-[var(--haip-fg)] [overflow-wrap:anywhere]", !pane && "haip-page-title haip-page-title--keep")}>{name}</Title>
                <p className="text-[13px] tabular-nums text-[var(--haip-fg-subtle)]">
                  {guest?.phone ? formatPhone(guest.phone) : "No phone"} · {CHANNEL_STYLE[(booking.channel ?? "direct").toLowerCase()]?.label ?? booking.channel}
                </p>
                <div className="mt-0.5 flex flex-wrap gap-x-3">
                  {booking.inquiry_id && <Link href={`/dashboard/leads/${booking.inquiry_id}`} className="inline-flex min-h-9 items-center text-[13px] font-semibold text-primary hover:underline">Open lead</Link>}
                  {guest && <Link href={`/dashboard/bookings?guest=${guest.id}`} className="inline-flex min-h-9 items-center text-[13px] font-semibold text-primary hover:underline">All their bookings</Link>}
                  {guest && canEdit && <button type="button" onClick={() => setChangingGuest(true)} className="inline-flex min-h-9 items-center text-[13px] font-semibold text-primary hover:underline">Change guest</button>}
                </div>
              </div>
              {!pane && statusPill}
            </div>
            <div className="grid grid-cols-3 gap-2">
              <button type="button" className={cn(bigBtn, "bg-primary text-primary-foreground")} disabled={!guest?.phone || call.isPending}
                onClick={() => guest?.phone && call.mutate({ phone: guest.phone, name: name.split(" ")[0] })}>
                <Phone size={16} /> {call.isPending ? "Calling…" : "Call"}
              </button>
              <button type="button" className={cn(bigBtn, "bg-[var(--haip-primary-tint)] text-primary")} disabled={!guest?.phone} onClick={() => setSheet("whatsapp")}>
                <MessageCircle size={16} /> WhatsApp
              </button>
              <button type="button" disabled={f.outstanding <= 0 || cancelled || !canEdit} onClick={() => setSheet("collect")}
                className={cn(bigBtn, f.outstanding > 0 && !cancelled ? "bg-[var(--haip-accent-light)] text-[var(--haip-accent-ink)]" : "border border-[var(--haip-border)] text-[var(--haip-fg-subtle)]")}>
                <CreditCard size={16} /> {f.outstanding > 0 && !cancelled ? "Collect" : cancelled ? "Cancelled" : "Paid"}
              </button>
            </div>
            {nextStep && (
              <button type="button" className={cn(bigBtn, "w-full bg-primary px-4 text-primary-foreground @md:w-auto")} disabled={save.isPending}
                onClick={() => setStatus(nextStep.status)}>
                {save.isPending ? "Saving…" : nextStep.label}
              </button>
            )}
          </CardBody>
        </Card>

        {booking.pms_managed && (
          <p className="rounded-lg border border-[var(--haip-status-warning-border)] bg-[var(--haip-status-warning-bg)] px-3 py-2 text-xs text-[var(--haip-status-warning-fg)]">
            This booking is synced from your PMS. Changes made here can be overwritten by the next sync.
          </p>
        )}

        {booking.calendar_sync && (
          <div className="flex flex-wrap items-center gap-2 rounded-lg border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 py-2 text-xs text-[var(--haip-fg-2)]">
            <span className="min-w-0 flex-1">
              {booking.calendar_sync.locked
                ? "Linked to a Google Calendar event. You changed this booking here, so the calendar no longer overwrites it."
                : "Linked to a Google Calendar event. Dates, total and guest count follow the calendar until you change them here."}
            </span>
            {role !== "foh" && (
              <button onClick={() => calendarSync.mutate(!booking.calendar_sync!.locked)} disabled={calendarSync.isPending} className={cn(chipBtn, "min-h-11 sm:min-h-9")}>
                {booking.calendar_sync.locked ? "Follow the calendar again" : "Keep as it is here"}
              </button>
            )}
          </div>
        )}

        {!booking.property && !cancelled && (
          <p className="rounded-lg border border-[var(--haip-status-warning-border)] bg-[var(--haip-status-warning-bg)] px-3 py-2 text-xs text-[var(--haip-status-warning-fg)]">
            No vehicle is assigned yet. Use Edit on the stay to pick one.
          </p>
        )}

        {/* The stay. */}
        <Card>
          <CardHeader title="Stay" actions={canEdit && (
            <button type="button" onClick={() => setEditing(v => !v)} aria-expanded={showForm} className={chipBtn}>{showForm ? "Close editing" : "Edit"}</button>
          )} />
          <CardBody>
            <div className="grid grid-cols-2 gap-x-3 gap-y-2.5">
              <Fact name="Vehicle">{booking.property ? <VehicleTag name={booking.property.name} slot={slot} /> : "Not assigned"}</Fact>
              <Fact name="Guests">{booking.adults} adult{booking.adults === 1 ? "" : "s"}{booking.children ? `, ${booking.children} child${booking.children === 1 ? "" : "ren"}` : ""}</Fact>
              <Fact name="Pickup (check-in)">{dayAndTime(booking.check_in, booking.check_in_time)}</Fact>
              <Fact name="Drop (check-out)">{dayAndTime(booking.check_out, booking.check_out_time)}</Fact>
              <Fact name="Trip" wide>{booking.trip ? `${booking.trip} · ` : ""}{nights ? `${nights} night${nights === 1 ? "" : "s"}` : "Day trip"}</Fact>
              {booking.occasion && <Fact name="Reason for travel" wide>{booking.occasion}</Fact>}
              <Fact name="Total"><span className={cn("tabular-nums", cancelled && "text-[var(--haip-fg-subtle)] line-through")}>{formatINR(f.total)}</span>
                {!cancelled && <> <StatusPill tone={PAYMENT_TONE[f.payment_status]}>{PAYMENT_STYLE[f.payment_status].label}</StatusPill></>}
              </Fact>
              <Fact name="Booked">{booking.created_at ? fmtDate(booking.created_at) : "Not recorded"}</Fact>
            </div>
          </CardBody>
        </Card>

        {showForm && (
          <Card>
            <CardHeader title="Edit trip" description="Dates, vehicle, guests, the stay charge, status and notes." />
            <div className="grid grid-cols-1 gap-3 px-4 pb-1 pt-2 @lg:grid-cols-2 sm:px-5">
              <label className={cn(label, "@lg:col-span-2")}>Vehicle
                <select className={cn(field, "mt-1")} value={draft.property_id} onChange={set("property_id")}>
                  {!properties.some(p => p.id === draft.property_id) && <option value={draft.property_id}>{booking.property?.name ?? "Unassigned"}</option>}
                  {properties.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
                </select>
              </label>
              <label className={label}>Check-in date
                <input type="date" className={cn(field, "mt-1")} value={draft.check_in} onChange={set("check_in")} />
              </label>
              <label className={label}>Check-in time
                <input type="time" className={cn(field, "mt-1")} value={draft.check_in_time} onChange={set("check_in_time")} />
              </label>
              <label className={label}>Check-out date
                <input type="date" className={cn(field, "mt-1")} min={draft.check_in} value={draft.check_out} onChange={set("check_out")} />
              </label>
              <label className={label}>Check-out time
                <input type="time" className={cn(field, "mt-1")} value={draft.check_out_time} onChange={set("check_out_time")} />
              </label>
              <label className={label}>Adults
                <input type="number" min={1} className={cn(field, "mt-1")} value={draft.adults} onChange={set("adults")} />
              </label>
              <label className={label}>Children
                <input type="number" min={0} className={cn(field, "mt-1")} value={draft.children} onChange={set("children")} />
              </label>
              <label className={label}>Stay charge (₹)
                <input inputMode="decimal" className={cn(field, "mt-1")} value={draft.total_amount}
                  onChange={e => setDraft(d => d && { ...d, total_amount: e.target.value.replace(/[^0-9.]/g, "") })} />
              </label>
              <label className={label}>Reason for travel
                <input className={cn(field, "mt-1")} placeholder="Birthday, anniversary, workation..." value={draft.occasion} onChange={set("occasion")} />
              </label>
              <label className={cn(label, "@lg:col-span-2")}>Status
                <select aria-label="Change status" className={cn(field, "mt-1")} value={booking.status} onChange={e => setStatus(e.target.value)} disabled={save.isPending}>
                  {STATUS_OPTIONS.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
                </select>
              </label>
              <label className={cn(label, "@lg:col-span-2")}>Guest message
                <textarea rows={2} className={cn(field, "mt-1 resize-none")} value={draft.special_requests} onChange={set("special_requests")} />
              </label>
              <label className={cn(label, "@lg:col-span-2")}>Notes <span className="font-normal text-[var(--haip-fg-subtle)]">(staff only)</span>
                <textarea rows={2} className={cn(field, "mt-1 resize-none")} placeholder="Which caravan: Black Ratha / White Ratha. Anything the team should know." value={draft.internal_notes} onChange={set("internal_notes")} />
              </label>
              <label className={cn(label, "@lg:col-span-2")}>Concierge notes <span className="font-normal text-[var(--haip-fg-subtle)]">(for the on-site team)</span>
                <textarea rows={2} className={cn(field, "mt-1 resize-none")} placeholder="Gate code, arrival time, preferences..." value={draft.concierge_notes} onChange={set("concierge_notes")} />
              </label>
            </div>
            <div className="flex flex-wrap items-center gap-2 px-4 pb-4 pt-3 sm:px-5">
              <button onClick={submit} disabled={!dirty || save.isPending}
                className="min-h-11 rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground disabled:opacity-40">
                {save.isPending ? "Saving..." : "Save changes"}
              </button>
              <button onClick={() => { setDraft(toDraft(booking)); setEditing(false); }} className="min-h-11 px-2 text-sm text-[var(--haip-fg-subtle)] hover:text-[var(--haip-fg)]">
                {dirty ? "Discard changes" : "Close"}
              </button>
            </div>
          </Card>
        )}

        {booking.next_due && !cancelled && (
          <p className={cn("rounded-lg border px-3 py-2 text-xs",
            booking.next_due.overdue
              ? "border-[var(--haip-status-danger-border)] bg-[var(--haip-status-danger-bg)] text-[var(--haip-status-danger-fg)]"
              : "border-[var(--haip-border)] bg-[var(--haip-card)] text-[var(--haip-fg-2)]")}>
            {booking.next_due.overdue ? "Overdue: " : "Next payment: "}
            <b className="tabular-nums">{formatINR(booking.next_due.amount)}</b> ({booking.next_due.label}) {booking.next_due.overdue ? "was due" : "due"} {fmtDate(booking.next_due.due_date)}
          </p>
        )}

        {/* The money: total, paid, still due, the plan for the rest, and the deposit kept apart (never revenue). */}
        <div className="grid items-start gap-3 @3xl:grid-cols-2">
          <PaymentsPanel booking={booking} onChange={setBooking} onCollect={canEdit ? () => setSheet("collect") : undefined} />
          <SchedulePanel booking={booking} onChange={setBooking} />
          <DepositPanel booking={booking} onChange={setBooking} />
          <AddOnsPanel booking={booking} onChange={setBooking} />
          <ServiceRequestsPanel booking={booking} onChange={setBooking} />

          <Card>
            <CardHeader title="Notes" description="Staff only, never sent to the guest." actions={canEdit && <button onClick={() => setEditing(true)} className="min-h-9 pointer-coarse:min-h-11 text-xs font-semibold text-primary hover:underline">Edit</button>} />
            <CardBody>
              <dl className="grid grid-cols-[minmax(0,7.5rem)_minmax(0,1fr)] gap-x-3 gap-y-2 text-sm">
                <dt className="text-[var(--haip-fg-subtle)]">Staff notes</dt><dd className="min-w-0 whitespace-pre-line text-[var(--haip-fg)]">{booking.internal_notes || "None"}</dd>
                <dt className="text-[var(--haip-fg-subtle)]">On-site team</dt><dd className="min-w-0 whitespace-pre-line text-[var(--haip-fg)]">{booking.concierge_notes || "None"}</dd>
                <dt className="text-[var(--haip-fg-subtle)]">Guest message</dt><dd className="min-w-0 whitespace-pre-line text-[var(--haip-fg)]">{booking.special_requests || "None"}</dd>
              </dl>
            </CardBody>
          </Card>

          <InvoicesMessagesCard booking={booking} watch={booking.payment_links.some(l => l.status === "created")} />

          <Card>
            <CardHeader title="Timeline" description="Times in IST" />
            <CardBody>
              <Timeline empty="No changes recorded yet." entries={booking.activity.map(a => ({
                id: a.id, title: describeActivity(a), detail: a.by ?? "System",
                time: a.at ? new Date(a.at).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" }) : "",
              }))} />
            </CardBody>
          </Card>
        </div>

        {canEdit && !cancelled && booking.status === "confirmed" && (
          <button type="button" onClick={() => setStatus("cancelled")} disabled={save.isPending}
            className="min-h-11 rounded-lg px-2 text-sm font-semibold text-[var(--haip-status-danger-fg)] hover:bg-[var(--haip-status-danger-bg)] disabled:opacity-50">
            Cancel booking
          </button>
        )}

        {canErase && guest && (
          <section className="rounded-2xl border border-[var(--haip-status-danger-border)] bg-[var(--haip-card)] p-4">
            <h2 className="text-sm font-semibold text-[var(--haip-status-danger-fg)]">Guest data</h2>
            <p className="mt-1 text-xs text-[var(--haip-fg-subtle)]">Start a DPDP erasure request. The guest is hidden now and their data is permanently deleted after 30 days.</p>
            <button
              onClick={async () => {
                if (!confirm(`Request erasure of all data for ${guest.name || "this guest"}? This also removes their bookings.`)) return;
                try {
                  await api.post(`/bookings/${id}/dpdp-delete`);
                  toast({ variant: "success", title: "Erasure requested" });
                  queryClient.invalidateQueries({ queryKey: ["bookings"] });
                  window.location.assign("/dashboard/bookings");
                } catch (e) {
                  toast({ variant: "error", title: errorMessage(e, "Could not start erasure") });
                }
              }}
              className="mt-3 min-h-11 rounded-lg border border-[var(--haip-status-danger-border)] px-3 text-xs font-semibold text-[var(--haip-status-danger-fg)] hover:bg-[var(--haip-status-danger-bg)]"
            >
              Request data erasure
            </button>
          </section>
        )}
      </div>
      {changingGuest && <ChangeGuestDialog booking={booking} onClose={() => setChangingGuest(false)} onChange={setBooking} />}
      <CollectSheet bookingId={booking.id} open={sheet === "collect"} onClose={() => setSheet(null)} />
      <WhatsAppSheet bookingId={booking.id} open={sheet === "whatsapp"} onClose={() => setSheet(null)} />
    </div>
  );
}
