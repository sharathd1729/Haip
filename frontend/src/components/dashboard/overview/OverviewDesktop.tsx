"use client";
// Home's Overview on tablets and desktops (one-glance layout, owner 28 Nov 2026; mockup: the "Home, desktop" board). One
// screen on a 1280x800 laptop: who is waiting, the period's four numbers, three small charts side by side, the next 7 days,
// then two short lists (who is waiting, who arrives next; two rows each so the screen needs no scroll). Built from the same parts as the phone Home, so the two agree.
// Everything reflows: tiles 4 -> 2, charts 3 -> 2 -> 1, lists 2 -> 1.
import { useSegment } from "@/lib/segments";
import { isRestricted } from "@/components/dashboard/command/types";
import type { Overview } from "@/components/dashboard/command/CommandCenter";
import { dueThisWeek, useTripsNext7 } from "@/components/dashboard/phone/PhoneHome";
import { ArrivalsList, CallsChart, FunnelCard, LeadsChart, OverviewTiles, WaitingList, WaitingStrip, WeekRow } from "./OverviewParts";

export function OverviewDesktop({ data, periodLabel }: { data: Overview; periodLabel: string }) {
  const b = useSegment().booking;
  const canBookings = data.access.bookings;
  const trips = useTripsNext7(canBookings);
  const tripRows = (trips.data?.data ?? []).filter(r => r.raw_status !== "cancelled");
  const due = dueThisWeek(tripRows);
  const checkOuts = isRestricted(data.bookings) ? null : data.bookings.upcoming_checkouts;
  return (
    <div className="grid gap-3">
      <WaitingStrip wide />
      <OverviewTiles data={data} periodLabel={periodLabel} />
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
        <LeadsChart data={data} yAxis height={72} />
        <CallsChart data={data} height={72} />
        <FunnelCard data={data} periodLabel={periodLabel} className="md:col-span-2 xl:col-span-1" />
      </div>
      {canBookings && (
        <WeekRow loading={trips.isPending} checkIns={trips.isError ? null : tripRows.length} checkOuts={checkOuts}
          due={trips.isError ? null : due.amount} />
      )}
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <WaitingList limit={2} />
        {canBookings && (
          <ArrivalsList rows={tripRows} total={tripRows.length} loading={trips.isPending} error={trips.isError}
            onRetry={() => trips.refetch()} limit={2} many={b.many} />
        )}
      </div>
    </div>
  );
}
