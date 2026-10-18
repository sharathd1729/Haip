"use client";
// Full-page booking. The layout lives in BookingDetailView so the list's split view shows the same thing.
import { useParams } from "next/navigation";
import { BookingDetailView } from "@/components/bookings/BookingDetailView";

export default function BookingPage() {
  const { id } = useParams<{ id: string }>();
  return <BookingDetailView id={id} variant="page" />;
}
