"use client";
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useSession } from "next-auth/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Phone } from "@/lib/icons";
import api from "@/lib/api";
import { cn, formatPhone } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { AddOnsPanel } from "@/components/bookings/AddOnsPanel";
import { PaymentsPanel } from "@/components/bookings/PaymentsPanel";
import {
  STATUS_OPTIONS, STATUS_STYLE, describeActivity, errorMessage, fmtDate,
  type BookingDetail,
} from "@/lib/bookings";

const field = "w-full text-sm border border-gray-200 rounded-lg px-2.5 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-teal-500 disabled:bg-gray-50 disabled:text-gray-400";
const label = "block text-xs font-medium text-gray-500";

interface Draft {
  property_id: string; check_in: string; check_out: string; check_in_time: string; check_out_time: string;
  adults: string; children: string; total_amount: string; occasion: string; special_requests: string; internal_notes: string;
}

function toDraft(b: BookingDetail): Draft {
  return {
    property_id: b.property?.id ?? "", check_in: b.check_in, check_out: b.check_out,
    check_in_time: b.check_in_time ?? "", check_out_time: b.check_out_time ?? "",
    adults: String(b.adults), children: String(b.children), total_amount: String(b.financials.stay_charge),
    occasion: b.occasion ?? "", special_requests: b.special_requests, internal_notes: b.internal_notes,
  };
}

export default function BookingPage() {
  const { id } = useParams<{ id: string }>();
  const { data: session } = useSession();
  const role = session?.user?.role;
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const { data: booking, isLoading, isError } = useQuery<BookingDetail>({
    queryKey: ["booking", id],
    queryFn: () => api.get(`/bookings/${id}`).then(r => r.data),
    // pick up a Razorpay payment that arrives while the page is open
    refetchInterval: q => (q.state.data?.payment_links.some(l => l.status === "created") ? 20_000 : false),
  });
  const { data: properties = [] } = useQuery<{ id: string; name: string }[]>({
    queryKey: ["bookable-properties"],
    queryFn: () => api.get("/bookings/properties").then(r => r.data),
    staleTime: 5 * 60_000,
  });

  const [draft, setDraft] = useState<Draft | null>(null);
  useEffect(() => { if (booking) setDraft(toDraft(booking)); }, [booking]);

  function setBooking(b: BookingDetail) {
    queryClient.setQueryData(["booking", id], b);
    queryClient.invalidateQueries({ queryKey: ["bookings"] });
  }

  const dirty = useMemo(() => !!booking && !!draft && JSON.stringify(toDraft(booking)) !== JSON.stringify(draft), [booking, draft]);

  const save = useMutation({
    mutationFn: async (patch: Record<string, unknown>) => {
      await api.patch(`/bookings/${id}`, patch);
      return api.get<BookingDetail>(`/bookings/${id}`);
    },
    onSuccess: res => { setBooking(res.data); toast({ variant: "success", title: "Saved" }); },
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
      <div className="p-6 max-w-5xl mx-auto space-y-4">
        {isError ? (
          <div className="text-center py-20 text-sm text-gray-500">
            Booking not found. <Link href="/dashboard/bookings" className="text-teal-600 font-medium hover:underline">Back to bookings</Link>
          </div>
        ) : (
          <>
            <Skeleton className="h-10 w-72" />
            <Skeleton className="h-64 rounded-xl" />
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
      special_requests: draft.special_requests, internal_notes: draft.internal_notes,
    });
  }

  function setStatus(next: string) {
    if (next === "cancelled" && !confirm("Cancel this booking? The dates will be freed. Any money already received stays in the ledger.")) return;
    save.mutate({ status: next });
  }

  const st = STATUS_STYLE[booking.status] ?? STATUS_STYLE.confirmed;
  const guest = booking.guest;
  const canErase = role === "owner" || role === "compliance";
  const digits = (guest?.phone ?? "").replace(/\D/g, "");

  return (
    <div className="h-full overflow-y-auto bg-[#F8FAFC]">
      <div className="max-w-5xl mx-auto p-4 sm:p-6 space-y-5">
        <Link href="/dashboard/bookings" className="inline-flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-800">
          <ArrowLeft size={14} /> Bookings
        </Link>

        <header className="flex flex-wrap items-start gap-3">
          <div className="min-w-0">
            <h1 className="haip-page-title truncate">{guest?.name || (guest ? formatPhone(guest.phone) : "Booking")}</h1>
            <p className="text-sm text-gray-500">
              {booking.property?.name ?? "No property"} · {fmtDate(booking.check_in, false)} to {fmtDate(booking.check_out)} · {booking.nights} night{booking.nights === 1 ? "" : "s"}
            </p>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <span className={cn("inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold", st.cls)}>{st.label}</span>
            <select
              aria-label="Change status"
              value={booking.status}
              onChange={e => setStatus(e.target.value)}
              disabled={save.isPending}
              className="text-xs border border-gray-200 rounded-lg bg-white px-2 py-1.5 focus:outline-none focus:ring-2 focus:ring-teal-500"
            >
              {STATUS_OPTIONS.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
            </select>
          </div>
        </header>

        {booking.pms_managed && (
          <p className="text-xs text-amber-800 bg-amber-50 border border-amber-100 rounded-lg px-3 py-2">
            This booking is synced from your PMS. Changes made here can be overwritten by the next sync.
          </p>
        )}

        <div className="grid gap-5 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
          <div className="space-y-5 min-w-0">
            <section className="haip-card">
              <div className="haip-card-head"><h2 className="haip-card-title">Stay details</h2></div>
              <div className="p-4 grid grid-cols-2 gap-3">
                <label className={cn(label, "col-span-2")}>Property
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
                <label className={label}>Occasion
                  <input className={cn(field, "mt-1")} placeholder="Birthday, anniversary..." value={draft.occasion} onChange={set("occasion")} />
                </label>
                <label className={cn(label, "col-span-2")}>Guest requests
                  <textarea rows={2} className={cn(field, "mt-1 resize-none")} value={draft.special_requests} onChange={set("special_requests")} />
                </label>
                <label className={cn(label, "col-span-2")}>Internal notes <span className="text-gray-400 font-normal">(staff only)</span>
                  <textarea rows={3} className={cn(field, "mt-1 resize-none")} value={draft.internal_notes} onChange={set("internal_notes")} />
                </label>
              </div>
              <div className="px-4 pb-4 flex items-center gap-2">
                <button
                  onClick={submit}
                  disabled={!dirty || save.isPending}
                  className="text-sm font-semibold bg-teal-500 hover:bg-teal-600 disabled:opacity-40 text-white px-4 py-2 rounded-lg"
                >
                  {save.isPending ? "Saving..." : "Save changes"}
                </button>
                {dirty && <button onClick={() => setDraft(toDraft(booking))} className="text-sm text-gray-500 hover:text-gray-800">Discard</button>}
              </div>
            </section>

            <AddOnsPanel booking={booking} onChange={setBooking} />

            <section className="haip-card">
              <div className="haip-card-head"><h2 className="haip-card-title">Activity</h2></div>
              <ol className="p-4 space-y-3">
                {booking.activity.length === 0 && <li className="text-sm text-gray-400">No changes recorded yet.</li>}
                {booking.activity.map(a => (
                  <li key={a.id} className="flex gap-3 text-sm">
                    <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-teal-400 flex-shrink-0" aria-hidden />
                    <div className="min-w-0">
                      <p className="text-gray-800">{describeActivity(a)}</p>
                      <p className="text-xs text-gray-400">{a.by ?? "System"}{a.at ? ` · ${new Date(a.at).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" })}` : ""}</p>
                    </div>
                  </li>
                ))}
              </ol>
            </section>
          </div>

          <div className="space-y-5 min-w-0">
            <section className="haip-card">
              <div className="haip-card-head"><h2 className="haip-card-title">Guest</h2></div>
              <div className="p-4 space-y-3 text-sm">
                {guest ? (
                  <>
                    <div>
                      <p className="font-semibold text-gray-900">{guest.name || "Unnamed guest"}</p>
                      <p className="text-gray-500">{guest.phone ? formatPhone(guest.phone) : "No phone"}</p>
                      {guest.email && <p className="text-gray-500 truncate">{guest.email}</p>}
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {guest.phone && (
                        <a href={`tel:${guest.phone}`} className="inline-flex items-center gap-1.5 text-xs font-semibold border border-gray-200 px-3 py-1.5 rounded-lg hover:bg-gray-50">
                          <Phone size={12} /> Call
                        </a>
                      )}
                      {digits && (
                        <a href={`https://wa.me/${digits}`} target="_blank" rel="noopener noreferrer" className="text-xs font-semibold border border-gray-200 px-3 py-1.5 rounded-lg hover:bg-gray-50">
                          WhatsApp
                        </a>
                      )}
                      <Link href={`/dashboard/bookings?guest=${guest.id}`} className="text-xs font-semibold border border-gray-200 px-3 py-1.5 rounded-lg hover:bg-gray-50">
                        All their bookings
                      </Link>
                      {booking.inquiry_id && (
                        <Link href={`/dashboard/leads/${booking.inquiry_id}`} className="text-xs font-semibold border border-gray-200 px-3 py-1.5 rounded-lg hover:bg-gray-50">
                          Original lead
                        </Link>
                      )}
                    </div>
                  </>
                ) : <p className="text-gray-400">Guest details are not available.</p>}
                <p className="text-xs text-gray-400">
                  Source: {booking.channel ?? "direct"}{booking.created_at ? ` · created ${fmtDate(booking.created_at)}` : ""}
                </p>
              </div>
            </section>

            <PaymentsPanel booking={booking} onChange={setBooking} />

            {canErase && guest && (
              <section className="rounded-xl border border-red-100 bg-white p-4">
                <h2 className="text-xs font-semibold text-red-700 uppercase tracking-wide">Guest data</h2>
                <p className="text-xs text-gray-500 mt-1">Start a DPDP erasure request. The guest is hidden now and their data is permanently deleted after 30 days.</p>
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
                  className="mt-3 text-xs font-semibold text-red-700 border border-red-200 px-3 py-1.5 rounded-lg hover:bg-red-50"
                >
                  Request data erasure
                </button>
              </section>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
