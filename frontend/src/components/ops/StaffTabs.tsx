"use client";
// Ops › Staff sub-pages: People (everyone reads), Who is on duty and If nobody answers (owner/manager: they set the roster
// and the alert chain, ops.manage on the server). Links styled like the kit's Tabs track; scrolls inside itself on a phone.
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSession } from "next-auth/react";
import { cn } from "@/lib/utils";
import { canManageOps } from "@/lib/ops";

const LINKS = [
  { href: "/dashboard/ops/staff", label: "People", short: "People", manage: false },
  { href: "/dashboard/ops/staff/duty", label: "Who is on duty", short: "On duty", manage: true },
  { href: "/dashboard/ops/staff/alerts", label: "If nobody answers", short: "No answer", manage: true },
];

export function StaffTabs() {
  const path = usePathname();
  const manage = canManageOps(useSession().data?.user?.role);
  if (!manage) return null;
  return (
    <nav aria-label="Staff" className="flex w-full max-w-full gap-1 overflow-x-auto rounded-full bg-[var(--haip-tabs-track)] p-1 sm:w-fit haip-scrollbar-x">
      {LINKS.map(l => {
        const on = path === l.href;
        return (
          <Link key={l.href} href={l.href} aria-current={on ? "page" : undefined}
            className={cn("flex min-h-11 flex-1 shrink-0 items-center justify-center whitespace-nowrap rounded-full px-4 text-[14px] font-semibold transition-colors sm:flex-none",
              on ? "bg-[var(--haip-tab-active-bg)] text-[var(--haip-tab-active-fg)] shadow-[var(--haip-shadow-sm)]" : "text-[var(--haip-tab-fg)] hover:bg-[var(--hover-bg)]")}>
            <span className="sm:hidden">{l.short}</span><span className="max-sm:hidden">{l.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}
