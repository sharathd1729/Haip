"use client";
import { useEffect } from "react";
import { useParams, useRouter } from "next/navigation";

// Guest 360 was removed. Links that still point at a guest (compliance log,
// command palette) open that guest's bookings instead.
export default function GuestRedirect() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  useEffect(() => { router.replace(`/dashboard/bookings?guest=${encodeURIComponent(id)}`); }, [id, router]);
  return null;
}
