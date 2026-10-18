"use client";
// One booking, laid out as a trip (Bookings layout B): what the trip is, then the money, then the guest and the extras.
// Used by the full booking page (variant "page") and by the list's split view on wide screens (variant "pane").
// Sizes follow the container, not the window, so the same layout works in a 840px pane and a full page.
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useSession } from "next-auth/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Phone } from "@/lib/icons";
import api from "@/lib/api";
import { cn, formatINR, formatPhone } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { Card, CardBody, CardHeader, StatusPill } from "@/components/ui/kit";
import { AddOnsPanel } from "@/components/bookings/AddOnsPanel";
import { PaymentsPanel } from "@/components/bookings/PaymentsPanel";
import { SchedulePanel } from "@/components/bookings/SchedulePanel";
import { DepositPanel } from "@/components/bookings/DepositPanel";
import { ServiceRequestsPanel } from "@/components/bookings/ServiceRequestsPanel";
import { ChangeGuestDialog } from "@/components/bookings/ChangeGuestDialog";
import { InvoicesMessagesCard } from "@/components/bookings/InvoicesMessagesCard";
import {
  CHANNEL_STYLE, PAYMENT_STYLE, PAYMENT_TONE, STATUS_OPTIONS, STATUS_STYLE, STATUS_TONE, LOAD_FAILURES, describeActivity, errorMessage, fmtDate, httpStatus, loadFailure,
  type BookingDetail,
} from "@/lib/bookings";

const field = "w-full text-sm border border-[var(--haip-border)] rounded-lg px-2.5 py-2 bg-[var(--haip-card)] text-[var(--haip-fg)] focus:outline-none focus:ring-2 focus:ring-primary disabled:bg-[var(--haip-surface)] disabled:text-[var(--haip-fg-subtle)]";
const label = "block text-xs font-medium text-[var(--haip-fg-subtle)]";
const chipBtn = "inline-flex min-h-9 pointer-coarse:min-h-11 items-center gap-1.5 rounded-lg border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 text-xs font-semibold text-[var(--haip-fg-2)] hover:bg-[var(--haip-surface)] disabled:opacity-50";

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

/** "Fri 30 Oct" plus the time when one is set. */
function dayAndTime(date: string, time: string | null): string {
  const d = new Date(`${date}T00:00:00`).toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" });
  if (!time) return d;
  const [h, m] = time.split(":").map(Number);
  const t = new Date(2000, 0, 1, h, m || 0).toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" });
  return `${d}, ${t}`;
}

function Fact({ name, children }: { name: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0 border-t border-[var(--haip-border)] px-4 py-3 sm:px-5">
      <p className="text-xs font-medium text-[var(--haip-fg-subtle)]">{name}</p>
      <p className="mt-0.5 truncate text-sm font-semibold text-[var(--haip-fg)]">{children}</p>
    </div>
  );
}

export function BookingDetailView({ id, variant = "page" }: { id: string; variant?: "page" | "pane" }) {
  const { data: session } = useSession();
  const role = session?.user?.role;
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const pane = variant === "pane";

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
  useEffect(() => { if (booking) setDraft(toDraft(booking)); }, [booking]);
  // A different booking in the pane starts closed.
  useEffect(() => { setEditing(false); setChangingGuest(false); }, [id]);

  function setBooking(b: BookingDetail) {
    queryClient.setQueryData(["booking", id], b);
    queryClient.invalidateQueries({ queryKey: ["bookings"] });
  }

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
    onSuccess: res => { setBooking(res.data); setEditing(false); toast({ variant: "success", title: "Saved" }); },
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
      <div className={cn("space-y-4", pane ? "p-5" : "mx-auto max-w-5xl p-6")}>
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
  const digits = (guest?.phone ?? "").replace(/\D/g, "");
  const cancelled = booking.status === "cancelled";
  const showForm = editing || dirty;
  const name = guest?.name || (guest ? formatPhone(guest.phone) : "Booking");
  const Title = pane ? "h2" : "h1";

  return (
    <div className={cn("@container", pane ? "p-4 sm:p-5" : "h-full overflow-y-auto bg-[var(--haip-bg,var(--background))]")}>
      <div className={cn("space-y-4", !pane && "mx-auto max-w-5xl p-4 sm:p-6")}>
        {!pane && (
          <Link href="/dashboard/bookings" className="inline-flex min-h-9 pointer-coarse:min-h-11 items-center gap-1.5 text-sm text-[var(--haip-fg-subtle)] hover:text-[var(--haip-fg)]">
            <ArrowLeft size={14} /> Bookings
          </Link>
        )}

        {/* The trip: who, which vehicle, when, and where things stand. */}
        <Card>
          <div className="flex flex-wrap items-start gap-3 px-4 pt-4 sm:px-5">
            {/* The name keeps at least 16rem; on a narrow screen the actions drop to their own row instead of squeezing it. */}
            <div className="min-w-0 flex-1 basis-64">
              <div className="flex flex-wrap items-center gap-1.5">
                {booking.property
                  ? <StatusPill tone="brand">{booking.property.name}</StatusPill>
                  : <StatusPill tone="warning">No property yet</StatusPill>}
                <StatusPill tone={STATUS_TONE[booking.status] ?? "info"}>{(STATUS_STYLE[booking.status] ?? STATUS_STYLE.confirmed).label}</StatusPill>
                {!cancelled && <StatusPill tone={PAYMENT_TONE[booking.financials.payment_status]}>{PAYMENT_STYLE[booking.financials.payment_status].label}</StatusPill>}
              </div>
              <Title className={cn("mt-2 truncate font-[family-name:var(--font-display)] text-[22px] font-semibold tracking-[-0.015em] text-[var(--haip-fg)]", !pane && "haip-page-title haip-page-title--keep")}>{name}</Title>
              <p className="mt-0.5 text-sm text-[var(--haip-fg-subtle)]">
                {booking.property?.name ?? "No property"} · {fmtDate(booking.check_in, false)} to {fmtDate(booking.check_out)}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {pane && <Link href={`/dashboard/bookings/${booking.id}`} className={chipBtn}>Open full page</Link>}
              {digits && <a href={`https://wa.me/${digits}`} target="_blank" rel="noopener noreferrer" className={chipBtn}>Message</a>}
              <button type="button" onClick={() => setEditing(v => !v)} aria-expanded={showForm} className={chipBtn}>{showForm ? "Close editing" : "Edit trip"}</button>
              <select aria-label="Change status" value={booking.status} onChange={e => setStatus(e.target.value)} disabled={save.isPending}
                className="min-h-9 pointer-coarse:min-h-11 rounded-lg border border-[var(--haip-border)] bg-[var(--haip-card)] px-2 text-xs text-[var(--haip-fg)] focus:outline-none focus:ring-2 focus:ring-primary">
                {STATUS_OPTIONS.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
              </select>
            </div>
          </div>
          <div className="mt-4 grid grid-cols-2 @xl:grid-cols-3 @3xl:grid-cols-6">
            <Fact name="Starts">{dayAndTime(booking.check_in, booking.check_in_time)}</Fact>
            <Fact name="Ends">{dayAndTime(booking.check_out, booking.check_out_time)}</Fact>
            <Fact name="Length">{booking.nights ? `${booking.nights} night${booking.nights === 1 ? "" : "s"}` : "Day trip"}</Fact>
            <Fact name="Guests">{booking.adults} adult{booking.adults === 1 ? "" : "s"}{booking.children ? `, ${booking.children} child${booking.children === 1 ? "" : "ren"}` : ""}</Fact>
            <Fact name="Total"><span className={cn("tabular-nums", cancelled && "text-[var(--haip-fg-subtle)] line-through")}>{formatINR(booking.financials.total)}</span></Fact>
            <Fact name="Came from">{CHANNEL_STYLE[(booking.channel ?? "direct").toLowerCase()]?.label ?? booking.channel}</Fact>
          </div>
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
            No property is assigned yet. Use Edit trip to pick one.
          </p>
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

        {showForm && (
          <Card>
            <CardHeader title="Edit trip" description="Dates, property, guests, the stay charge and notes." />
            <div className="grid grid-cols-1 gap-3 px-4 pb-1 pt-2 @lg:grid-cols-2 sm:px-5">
              <label className={cn(label, "@lg:col-span-2")}>Property
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
                className="min-h-10 rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground disabled:opacity-40">
                {save.isPending ? "Saving..." : "Save changes"}
              </button>
              <button onClick={() => { setDraft(toDraft(booking)); setEditing(false); }} className="min-h-10 px-2 text-sm text-[var(--haip-fg-subtle)] hover:text-[var(--haip-fg)]">
                {dirty ? "Discard changes" : "Close"}
              </button>
              {!cancelled && (
                <button onClick={() => setStatus("cancelled")} disabled={save.isPending}
                  className="ml-auto min-h-10 rounded-lg border border-[var(--haip-status-danger-border)] px-3 text-sm font-semibold text-[var(--haip-status-danger-fg)] hover:bg-[var(--haip-status-danger-bg)] disabled:opacity-50">
                  Cancel booking
                </button>
              )}
            </div>
          </Card>
        )}

        {/* The money: what was paid, and the plan for the rest. */}
        <div className="grid gap-4 @3xl:grid-cols-2">
          <PaymentsPanel booking={booking} onChange={setBooking} />
          <SchedulePanel booking={booking} onChange={setBooking} />
        </div>

        <div className="grid items-start gap-4 @3xl:grid-cols-2">
          <Card>
            <CardHeader title="Guest" actions={guest && <button onClick={() => setChangingGuest(true)} className="min-h-9 pointer-coarse:min-h-11 text-xs font-semibold text-primary hover:underline">Change</button>} />
            <CardBody className="space-y-3 text-sm">
              {guest ? (
                <>
                  <div className="min-w-0">
                    <p className="font-semibold text-[var(--haip-fg)]">{guest.name || "Unnamed guest"}</p>
                    <p className="text-[var(--haip-fg-subtle)]">{guest.phone ? formatPhone(guest.phone) : "No phone"}</p>
                    {guest.email && <p className="truncate text-[var(--haip-fg-subtle)]">{guest.email}</p>}
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {guest.phone && <a href={`tel:${guest.phone}`} className={chipBtn}><Phone size={12} /> Call</a>}
                    {digits && <a href={`https://wa.me/${digits}`} target="_blank" rel="noopener noreferrer" className={chipBtn}>WhatsApp</a>}
                    <Link href={`/dashboard/bookings?guest=${guest.id}`} className={chipBtn}>All their bookings</Link>
                    {booking.inquiry_id && <Link href={`/dashboard/leads/${booking.inquiry_id}`} className={chipBtn}>Original lead</Link>}
                  </div>
                </>
              ) : <p className="text-[var(--haip-fg-subtle)]">Guest details are not available.</p>}
              <p className="text-xs text-[var(--haip-fg-subtle)]">
                Source: {booking.channel ?? "direct"}{booking.created_at ? ` · created ${fmtDate(booking.created_at)}` : ""}
              </p>
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="Notes" actions={<button onClick={() => setEditing(true)} className="min-h-9 pointer-coarse:min-h-11 text-xs font-semibold text-primary hover:underline">Edit</button>} />
            <CardBody>
              <dl className="grid grid-cols-[minmax(0,7.5rem)_minmax(0,1fr)] gap-x-3 gap-y-2 text-sm">
                <dt className="text-[var(--haip-fg-subtle)]">Occasion</dt><dd className="min-w-0 text-[var(--haip-fg)]">{booking.occasion || "Not noted"}</dd>
                <dt className="text-[var(--haip-fg-subtle)]">Guest message</dt><dd className="min-w-0 whitespace-pre-line text-[var(--haip-fg)]">{booking.special_requests || "None"}</dd>
                <dt className="text-[var(--haip-fg-subtle)]">Staff notes</dt><dd className="min-w-0 whitespace-pre-line text-[var(--haip-fg)]">{booking.internal_notes || "None"}</dd>
                <dt className="text-[var(--haip-fg-subtle)]">On-site team</dt><dd className="min-w-0 whitespace-pre-line text-[var(--haip-fg)]">{booking.concierge_notes || "None"}</dd>
              </dl>
            </CardBody>
          </Card>

          <AddOnsPanel booking={booking} onChange={setBooking} />
          <ServiceRequestsPanel booking={booking} onChange={setBooking} />
          <DepositPanel booking={booking} onChange={setBooking} />
          <InvoicesMessagesCard booking={booking} watch={booking.payment_links.some(l => l.status === "created")} />

          <Card>
            <CardHeader title="Activity" />
            <ol className="space-y-3 px-4 pb-4 pt-2 sm:px-5">
              {booking.activity.length === 0 && <li className="text-sm text-[var(--haip-fg-subtle)]">No changes recorded yet.</li>}
              {booking.activity.map(a => (
                <li key={a.id} className="flex gap-3 text-sm">
                  <span className="mt-1.5 size-1.5 flex-shrink-0 rounded-full bg-primary" aria-hidden />
                  <div className="min-w-0">
                    <p className="text-[var(--haip-fg)]">{describeActivity(a)}</p>
                    <p className="text-xs text-[var(--haip-fg-subtle)]">{a.by ?? "System"}{a.at ? ` · ${new Date(a.at).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" })}` : ""}</p>
                  </div>
                </li>
              ))}
            </ol>
          </Card>
        </div>

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
              className="mt-3 min-h-9 rounded-lg border border-[var(--haip-status-danger-border)] px-3 text-xs font-semibold text-[var(--haip-status-danger-fg)] hover:bg-[var(--haip-status-danger-bg)]"
            >
              Request data erasure
            </button>
          </section>
        )}
      </div>
      {changingGuest && <ChangeGuestDialog booking={booking} onClose={() => setChangingGuest(false)} onChange={setBooking} />}
    </div>
  );
}
