"use client";
// The Ops screens side by side: Today (what needs you), Fleet (each vehicle's papers, defects, services, stock), Map (live
// GPS) and Staff (drivers and helpers; they never log in, they use WhatsApp). Pills, 44px tall, scrolls sideways never.
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { useBusinessType } from "@/components/providers/WorkspaceProvider";

const LINKS = [
  { href: "/dashboard/ops", label: "Today" },
  { href: "/dashboard/ops/fleet", label: "Fleet" },
  { href: "/dashboard/ops/map", label: "Map" },
  { href: "/dashboard/ops/staff", label: "Staff" },
];
const VEHICLE_ONLY = ["/dashboard/ops/fleet", "/dashboard/ops/map"];

export function OpsNav() {
  const path = usePathname();
  const villa = (useBusinessType() ?? "").startsWith("villa");  // Fleet + Map = vehicles: caravan pack only
  return (
    <nav aria-label="Ops" className="flex gap-2">
      {LINKS.filter(l => !(villa && VEHICLE_ONLY.includes(l.href))).map(l => {
        const on = path === l.href || (l.href === "/dashboard/ops/staff" && path.startsWith(`${l.href}/`));
        return (
          <Link key={l.href} href={l.href} aria-current={on ? "page" : undefined}
            className={cn("inline-flex min-h-11 flex-1 items-center justify-center rounded-full border px-4 text-[15px] font-semibold sm:flex-none",
              on ? "border-primary bg-primary text-primary-foreground" : "border-[var(--haip-border)] bg-[var(--haip-card)] text-[var(--haip-fg)]")}>
            {l.label}
          </Link>
        );
      })}
    </nav>
  );
}
