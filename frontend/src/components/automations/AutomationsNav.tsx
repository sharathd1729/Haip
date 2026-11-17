"use client";
// The four Automations pages as one home (workspace redesign plan: "Automations, one home, four tabs"): WhatsApp and rules,
// Instagram, Lead workflows, Flows and drips. Links come from the ONE nav model (components/layout/nav.ts), so a person
// sees only the pages their role may open. Pills, 44px tall, scroll sideways inside their own row on a phone.
import Link from "next/link";
import { useSession } from "next-auth/react";
import { cn } from "@/lib/utils";
import { useNav } from "@/components/layout/nav";

export function AutomationsNav({ className }: { className?: string }) {
  const role = (useSession().data?.user as { role?: string } | undefined)?.role ?? "";
  const nav = useNav(role);
  const links = nav.sections.find(s => s.key === "automations")?.links ?? [];
  if (links.length < 2) return null;
  return (
    <nav aria-label="Automations" className={cn("-mx-1 flex gap-2 overflow-x-auto px-1 pb-1", className)}>
      {links.map(l => {
        const on = nav.isCurrent(l.href, links.map(x => x.href));
        return (
          <Link key={l.href} href={l.href} aria-current={on ? "page" : undefined}
            className={cn("inline-flex min-h-11 shrink-0 items-center rounded-full border px-4 text-[14px] font-semibold",
              on ? "border-primary bg-primary text-primary-foreground" : "border-[var(--haip-border)] bg-[var(--haip-card)] text-[var(--haip-fg)]")}>
            {l.label}
          </Link>
        );
      })}
    </nav>
  );
}
