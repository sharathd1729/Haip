"use client";
// The three Ops screens side by side: Today (what needs you), Fleet (each vehicle's papers, defects, services, stock) and
// Staff (drivers and helpers; they never log in, they use WhatsApp). Pills, 44px tall, scrolls sideways never.
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

const LINKS = [
  { href: "/dashboard/ops", label: "Today" },
  { href: "/dashboard/ops/fleet", label: "Fleet" },
  { href: "/dashboard/ops/staff", label: "Staff" },
];

export function OpsNav() {
  const path = usePathname();
  return (
    <nav aria-label="Ops" className="flex gap-2">
      {LINKS.map(l => {
        const on = path === l.href;
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
