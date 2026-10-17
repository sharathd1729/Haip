"use client";
// What a shared Google Calendar has done: the bookings it made, and the upcoming events that stayed calendar blocks, with why.
// Loaded only when opened. No money or phone numbers here.
import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { Skeleton } from "@/components/ui/skeleton";

interface Activity {
  bookings: { stay_id: string; guest_name: string | null; status: string; check_in: string; check_out: string; vehicle: string | null; locked: boolean; lead_linked: boolean }[];
  skipped: { title: string | null; from: string; to: string; reasons: string[] }[];
}

export function CalendarActivity({ feedId }: { feedId: string }) {
  const [open, setOpen] = useState(false);
  const { data, isLoading, isError } = useQuery<Activity>({
    queryKey: ["ical-activity", feedId],
    queryFn: () => api.get(`/ical-feeds/${feedId}/activity`).then(r => r.data),
    enabled: open,
  });

  return (
    <div className="text-xs">
      <button onClick={() => setOpen(o => !o)} aria-expanded={open}
        className="min-h-11 sm:min-h-0 font-semibold text-primary hover:underline">
        {open ? "Hide what this calendar did" : "See what this calendar did"}
      </button>
      {open && (
        <div className="mt-2 space-y-3">
          {isLoading && <Skeleton className="h-16 rounded-lg" />}
          {isError && <p className="text-red-600">Could not load this. Try again in a moment.</p>}
          {data && (
            <>
              <div>
                <p className="font-medium text-[var(--haip-fg-subtle)] mb-1">Bookings made</p>
                {data.bookings.length === 0 ? <p className="text-[var(--haip-fg-subtle)]">None yet.</p> : (
                  <ul className="divide-y divide-[var(--haip-border)] border border-[var(--haip-border)] rounded-lg">
                    {data.bookings.map(b => (
                      <li key={b.stay_id} className="px-3 py-2 flex flex-wrap items-center gap-x-3 gap-y-1">
                        <Link href={`/dashboard/bookings/${b.stay_id}`} className="font-semibold text-[var(--haip-fg)] hover:underline">{b.guest_name || "Guest"}</Link>
                        <span className="text-[var(--haip-fg-subtle)]">{b.check_in} to {b.check_out}</span>
                        <span className={b.vehicle ? "text-[var(--haip-fg-2)]" : "text-amber-700"}>{b.vehicle ?? "Vehicle not chosen yet"}</span>
                        {b.status !== "confirmed" && <span className="text-[var(--haip-fg-subtle)] capitalize">{b.status.replace("_", " ")}</span>}
                        {b.locked && <span className="text-[var(--haip-fg-subtle)]">Edited here</span>}
                        {b.lead_linked && <span className="text-green-700">Lead marked sold</span>}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <div>
                <p className="font-medium text-[var(--haip-fg-subtle)] mb-1">Upcoming events that are not bookings</p>
                {data.skipped.length === 0 ? <p className="text-[var(--haip-fg-subtle)]">None. Every upcoming event became a booking.</p> : (
                  <ul className="divide-y divide-[var(--haip-border)] border border-[var(--haip-border)] rounded-lg">
                    {data.skipped.map((s, i) => (
                      <li key={`${s.title}-${i}`} className="px-3 py-2">
                        <span className="font-semibold text-[var(--haip-fg)]">{s.title || "Untitled event"}</span>
                        <span className="text-[var(--haip-fg-subtle)]"> · {s.from} to {s.to}</span>
                        <p className="text-amber-700">Held as a block: {s.reasons.join(", ")}.</p>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
