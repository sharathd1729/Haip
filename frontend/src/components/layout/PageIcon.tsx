"use client";
// One icon per main destination, shared by the nav model (nav.ts: top bar, More menu, phone bars) and the PageHeader icon
// tile, so a page wears the same glyph everywhere. Kept apart from nav.ts so the shared PageHeader does not pull in the
// nav's queries and stores.
import type { ComponentType } from "react";
import { usePathname } from "next/navigation";
import {
  BarChart2, Calendar, CalendarCheck, Home, LayoutGrid, MessageSquare, Phone, Settings, Sparkles, Sun, Truck, Users,
} from "@/lib/icons";
import { cn } from "@/lib/utils";

export type RouteIcon = ComponentType<{ size?: number; className?: string; strokeWidth?: number; "aria-hidden"?: boolean }>;

export const ROUTE_ICONS = {
  "/dashboard/my-day": Sun,
  "/dashboard/ops": Truck,
  "/dashboard": Home,
  "/dashboard/operations": Home,
  "/dashboard/inbox": MessageSquare,
  "/dashboard/leads": Users,
  "/dashboard/portfolio/calendar": Calendar,
  "/dashboard/bookings": CalendarCheck,
  "/dashboard/calls": Phone,
  "/dashboard/reports": BarChart2,
  "/dashboard/marketing/studio": Sparkles,
  "/dashboard/settings": Settings,
} satisfies Record<string, RouteIcon>;

/** The "More" menu button in the top bar. */
export const MORE_ICON: RouteIcon = LayoutGrid;

/** The PageHeader icon tile: 46px, sea green with a lime glyph. Shows only on the main pages (ROUTE_ICONS, exact path)
 *  unless the page passes its own icon; `icon={false}` turns it off. Hidden on phones, where the header bar names the page. */
export function PageIconTile({ icon }: { icon?: RouteIcon | false }) {
  const pathname = (usePathname() ?? "").replace(/\/$/, "") || "/";
  const Icon = icon === false ? null : icon ?? (ROUTE_ICONS as Record<string, RouteIcon>)[pathname] ?? null;
  if (!Icon) return null;
  return (
    <span aria-hidden className={cn("hidden size-[46px] shrink-0 items-center justify-center rounded-[14px] sm:flex",
      "bg-[var(--haip-tile-bg)] text-[var(--haip-tile-fg)]")}>
      <Icon size={22} strokeWidth={1.8} />
    </span>
  );
}
