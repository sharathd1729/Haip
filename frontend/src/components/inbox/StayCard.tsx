"use client";
// Stay card (Hospitality Hybrid inbox): the guest's stay that matters right now, at the top of the Guest panel. A stay in
// progress wins; otherwise the next one coming up. Reads GET /bookings?guest_id= (needs bookings.read, so roles without it
// never see the card or its amounts). Opens the full booking.
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { BOOKING_READ_ROLES } from "@/lib/permissions";
import { ArrowRight, Calendar, Users } from "@/lib/icons";
import { StatusPill, type Tone } from "@/components/ui/page";

export interface BookingRow {
  id: string; checkin: string; checkout: string; status: string; adults?: number | null; children?: number | null;
  payment_status?: string | null; total?: number | null; total_outstanding?: number | null; payment_overdue?: boolean;
  property?: { name?: string | null } | null; currency?: { symbol?: string | null } | null;
}

const IST = "Asia/Kolkata";
const todayIst = () => new Intl.DateTimeFormat("en-CA", { timeZone: IST, year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
const day = (iso: string) => new Date(`${iso.slice(0, 10)}T12:00:00+05:30`).toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short", timeZone: IST });
const nights = (a: string, b: string) => Math.max(0, Math.round((Date.parse(b.slice(0, 10)) - Date.parse(a.slice(0, 10))) / 86_400_000));

/** The stay to show: one starting or in progress today, else the soonest upcoming one. Cancelled stays never count. */
export function pickStay(rows: BookingRow[], today: string): { row: BookingRow; when: "today" | "now" | "next" } | null {
  const live = rows.filter(r => r.status !== "cancelled" && r.checkin && r.checkout);
  const now = live.find(r => r.checkin.slice(0, 10) <= today && today < r.checkout.slice(0, 10));
  if (now) return { row: now, when: now.checkin.slice(0, 10) === today ? "today" : "now" };
  const next = live.filter(r => r.checkin.slice(0, 10) >= today).sort((a, b) => a.checkin.localeCompare(b.checkin))[0];
  return next ? { row: next, when: "next" } : null;
}

const PAY: Record<string, { label: string; tone: Tone }> = {
  paid: { label: "Paid", tone: "success" }, partial: { label: "Part paid", tone: "warning" }, unpaid: { label: "Unpaid", tone: "danger" },
};

export function StayCard({ guestId, role }: { guestId?: string | null; role?: string }) {
  const allowed = !!guestId && !!role && (BOOKING_READ_ROLES as string[]).includes(role);
  const { data } = useQuery<{ data: BookingRow[] }>({
    queryKey: ["guest-bookings", guestId],
    queryFn: () => api.get("/bookings", { params: { guest_id: guestId, per_page: 20 } }).then(r => r.data),
    enabled: allowed,
    staleTime: 60_000,
  });
  if (!allowed) return null;
  const pick = pickStay(data?.data ?? [], todayIst());
  if (!pick) return null;
  const { row, when } = pick;
  const n = nights(row.checkin, row.checkout);
  const people = [row.adults ? `${row.adults} adult${row.adults > 1 ? "s" : ""}` : null, row.children ? `${row.children} child${row.children > 1 ? "ren" : ""}` : null].filter(Boolean).join(", ");
  const pay = row.payment_overdue ? { label: "Payment overdue", tone: "danger" as Tone } : PAY[row.payment_status ?? ""];
  const sym = row.currency?.symbol || "₹";

  return (
    <Link href={`/dashboard/bookings/${row.id}`}
      className="block overflow-hidden rounded-2xl border border-[color-mix(in_srgb,var(--primary)_22%,transparent)] bg-[var(--haip-primary-tint)] transition-shadow hover:shadow-[var(--haip-shadow-md)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary">
      <div className="flex items-center justify-between gap-2 px-3.5 pt-3">
        <span className="text-[12px] font-semibold text-primary">{when === "today" ? "Arrives today" : when === "now" ? "Staying now" : "Booked"}</span>
        {pay && <StatusPill tone={pay.tone}>{pay.label}</StatusPill>}
      </div>
      <p className="px-3.5 pt-1 font-[family-name:var(--font-display)] text-[17px] font-semibold leading-tight text-[var(--haip-fg)]">{row.property?.name || "Vehicle not picked yet"}</p>
      <div className="space-y-1 px-3.5 pb-3 pt-1.5 text-[13px] text-[var(--haip-fg-2)]">
        <p className="flex items-center gap-1.5"><Calendar size={13} className="shrink-0 text-[var(--haip-icon-neutral)]" />{day(row.checkin)} → {day(row.checkout)}<span className="text-[var(--haip-fg-subtle)]">· {n} night{n === 1 ? "" : "s"}</span></p>
        {people && <p className="flex items-center gap-1.5"><Users size={13} className="shrink-0 text-[var(--haip-icon-neutral)]" />{people}</p>}
      </div>
      <div className="flex items-center justify-between gap-2 border-t border-[color-mix(in_srgb,var(--primary)_15%,transparent)] bg-[var(--haip-card)] px-3.5 py-2.5 text-[13px]">
        <span className="text-[var(--haip-fg-muted)]">
          {row.total_outstanding != null && row.total_outstanding > 0
            ? <>Due <span className="num font-semibold text-[var(--haip-fg)]">{sym}{Math.round(row.total_outstanding).toLocaleString("en-IN")}</span></>
            : row.total != null ? <>Total <span className="num font-semibold text-[var(--haip-fg)]">{sym}{Math.round(row.total).toLocaleString("en-IN")}</span></> : "Open booking"}
        </span>
        <span className="inline-flex items-center gap-1 font-semibold text-primary">Open<ArrowRight size={13} /></span>
      </div>
    </Link>
  );
}
