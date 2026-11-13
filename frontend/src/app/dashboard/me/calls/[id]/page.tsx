"use client";
// One call on its own page (narrow screens; wide screens show it beside the list on /dashboard/me).
import { useParams } from "next/navigation";
import { CallDetail } from "@/components/personal/CallDetail";

export default function YaadCallPage() {
  const { id } = useParams<{ id: string }>();
  return (
    <div className="yaad -mx-4 -my-5 min-h-[calc(100dvh-112px)] px-4 py-4 sm:-mx-6 sm:px-6 md:min-h-[calc(100dvh-64px)]">
      <CallDetail id={id} backHref="/dashboard/me" />
    </div>
  );
}
