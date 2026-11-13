"use client";
// One call on its own page (narrow screens; wide screens show it beside the list on /dashboard/me).
import { useParams } from "next/navigation";
import { CallDetail } from "@/components/personal/CallDetail";

export default function YaadCallPage() {
  const { id } = useParams<{ id: string }>();
  return (
    <div className="yaad min-h-full px-4 py-4 sm:px-6">
      <CallDetail id={id} backHref="/dashboard/me" />
    </div>
  );
}
