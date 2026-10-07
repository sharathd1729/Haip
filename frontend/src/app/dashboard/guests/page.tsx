"use client";
import { Suspense, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";

// The guest profile grid was removed: bookings are the working view. Old links
// (top-bar search, call page, bookmarks) land here and are forwarded, keeping
// the search text.
function Forward() {
  const router = useRouter();
  const params = useSearchParams();
  useEffect(() => {
    const q = params.get("q") ?? params.get("phone");
    router.replace(q ? `/dashboard/bookings?q=${encodeURIComponent(q)}` : "/dashboard/bookings");
  }, [router, params]);
  return null;
}

export default function GuestsRedirect() {
  return <Suspense fallback={null}><Forward /></Suspense>;
}
