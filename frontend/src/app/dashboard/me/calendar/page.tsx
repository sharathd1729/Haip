"use client";
// Yaad calendar (layout A): month grid + event panel; phones get the month as a list and the panel as a sheet.
import { CalendarView } from "@/components/personal/CalendarView";
import { istDay } from "@/lib/personal";
import { useEffect, useState } from "react";

export default function YaadCalendarPage() {
  // The month comes from the clock after mount, so the server render and the first client render match.
  const [month, setMonth] = useState<string | null>(null);
  useEffect(() => { setMonth(istDay(new Date()).slice(0, 7)); }, []);
  return (
    <div className="yaad min-h-full px-4 py-5 sm:px-8 sm:py-8">
      <div className="mx-auto max-w-[1240px]">
        {month ? <CalendarView initialMonth={month} /> : <div className="h-[560px] animate-pulse rounded-[20px] bg-[var(--y-line)]" aria-busy="true" />}
      </div>
    </div>
  );
}
