"use client";
// One memory on its own page (layout B): the memory, and on a wide screen Ask Yaad docked beside it.
import { useParams } from "next/navigation";
import { CallDetail } from "@/components/personal/CallDetail";

export default function YaadCallPage() {
  const { id } = useParams<{ id: string }>();
  return (
    <div className="yaad min-h-full px-4 py-4 sm:px-8 sm:py-8">
      <div className="mx-auto max-w-[1240px]">
        <CallDetail id={id} backHref="/dashboard/me" />
      </div>
    </div>
  );
}
