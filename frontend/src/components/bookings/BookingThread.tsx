"use client";
// The booking's thread across modules (workspace redesign Phase 4, mockup D): Enquiry → Chats → Quote → Booking → Money →
// Guest form → Ops file → Review, each step opening its own page, then the other records tied to this guest.
// GET /bookings/{id}/thread (services/record_thread). Scrolls sideways inside its own box on a phone, never the page.
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { ChevronRight } from "@/lib/icons";
import { Card } from "@/components/ui/kit";
import { Skeleton } from "@/components/ui/skeleton";

interface Step { key: string; label: string; value: string; state: "done" | "due" | "waiting" | "none" | "current"; href: string | null }
interface Linked { label: string; value: string | null; href: string; attention?: boolean }

const LABEL_TONE: Record<Step["state"], string> = {
  done: "text-[var(--haip-status-success-fg)]", due: "text-[var(--haip-status-danger-fg)]", waiting: "text-[var(--haip-status-warning-fg)]",
  none: "text-[var(--haip-fg-subtle)]", current: "text-primary-foreground opacity-85",
};

export function BookingThread({ bookingId }: { bookingId: string }) {
  const { data, isPending, isError } = useQuery<{ steps: Step[]; linked: Linked[] }>({
    queryKey: ["booking-thread", bookingId], queryFn: () => api.get(`/bookings/${bookingId}/thread`).then(r => r.data), staleTime: 60_000,
  });
  if (isPending) return <Skeleton className="h-20" />;
  if (isError || !data) return null;  // the booking page is complete without it; nothing to act on here
  return (
    <Card className="overflow-hidden">
      <nav aria-label="This guest's journey" className="overflow-x-auto p-2">
        <ol className="flex min-w-max items-stretch">
          {data.steps.map((s, i) => {
            const body = (
              <>
                <span className={`text-[12px] font-semibold ${LABEL_TONE[s.state]}`}>{s.label}</span>
                <span className={`text-[14px] font-semibold ${s.state === "current" ? "" : s.state === "none" ? "text-[var(--haip-fg-subtle)]" : "text-[var(--haip-fg)]"}`}>{s.value}</span>
              </>
            );
            const box = "flex min-h-14 min-w-[120px] flex-col justify-center gap-0.5 rounded-xl px-3 py-2";
            return (
              <li key={s.key} className="flex items-center">
                {s.state === "current"
                  ? <span aria-current="page" className={`${box} bg-primary text-primary-foreground`}>{body}</span>
                  : s.href ? <Link href={s.href} className={`${box} hover:bg-[var(--haip-surface)]`}>{body}</Link>
                  : <span className={box}>{body}</span>}
                {i < data.steps.length - 1 && <ChevronRight size={14} aria-hidden className="shrink-0 text-[var(--haip-border-strong)]" />}
              </li>
            );
          })}
        </ol>
      </nav>
      {data.linked.length > 0 && (
        <div className="flex flex-wrap gap-2 border-t border-[var(--haip-border)] px-3 py-2.5">
          <span className="flex min-h-9 items-center text-[13px] font-semibold text-[var(--haip-fg-subtle)]">Linked</span>
          {data.linked.map((l, i) => (
            <Link key={`${l.href}-${i}`} href={l.href}
              className={`inline-flex min-h-9 items-center gap-1.5 rounded-full border px-3 text-[13px] pointer-coarse:min-h-11 hover:bg-[var(--haip-surface)] ${l.attention ? "border-[var(--haip-status-warning-border)]" : "border-[var(--haip-border)]"}`}>
              <span className="font-semibold text-[var(--haip-fg)]">{l.label}</span>
              {l.value && <span className="text-[var(--haip-fg-subtle)]">{l.value}</span>}
            </Link>
          ))}
        </div>
      )}
    </Card>
  );
}
