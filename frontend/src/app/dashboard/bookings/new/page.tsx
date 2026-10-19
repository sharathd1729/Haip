"use client";
// New booking (/dashboard/bookings/new). Opened from Bookings, a lead (?inquiry=), a guest (?guest=), a saved quote (?quote=) or
// a calendar slot (?property=&from=YYYY-MM-DD&to=YYYY-MM-DD). The flow lives in components/bookings/new.
import { Suspense, useMemo } from "react";
import { useSearchParams } from "next/navigation";
import { useSession } from "next-auth/react";
import { EmptyState } from "@/components/ui/kit";
import { NewBookingFlow } from "@/components/bookings/new/NewBookingFlow";
import { canCreateBookings } from "@/lib/permissions";

function Inner() {
  const sp = useSearchParams();
  const { data: session, status } = useSession();
  const params = useMemo(() => ({
    inquiry: sp.get("inquiry"), guest: sp.get("guest"), quote: sp.get("quote"), property: sp.get("property"), from: sp.get("from"), to: sp.get("to"),
  }), [sp]);
  if (status === "authenticated" && !canCreateBookings(session?.user?.role)) {
    return <EmptyState title="You can't create bookings" hint="Ask the owner, a manager or reservations to make this booking." />;
  }
  return <NewBookingFlow params={params} />;
}

export default function NewBookingPage() {
  return <Suspense fallback={null}><Inner /></Suspense>;
}
