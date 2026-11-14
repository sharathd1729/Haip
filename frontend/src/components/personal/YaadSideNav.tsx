"use client";
// Yaad's desktop navigation (md and up): a left sidebar in the Mango theme, in place of HAIP's top bar, for personal
// workspaces only (useNav().personal). Links are nav.ts PERSONAL_SECTIONS, so phone and desktop list the same places.
import Link from "next/link";
import { signOut } from "next-auth/react";
import { clearTokenCache } from "@/lib/api";
import { LogOut } from "@/lib/icons";
import { cn } from "@/lib/utils";
import { useNav } from "@/components/layout/nav";
import { YaadWordmark } from "@/components/personal/YaadMark";

export function YaadSideNav({ user }: { user?: { name?: string | null; email?: string | null; role?: string } }) {
  const nav = useNav(user?.role ?? "");
  if (!nav.personal) return null;
  return (
    <aside className="yaad hidden w-60 shrink-0 flex-col border-r border-[var(--y-line)] md:flex" aria-label="Yaad">
      <Link href="/dashboard/me" className="px-5 pb-4 pt-6" aria-label="Yaad home"><YaadWordmark /></Link>
      <nav className="flex-1 overflow-y-auto px-3">
        {nav.sections.map(section => (
          <div key={section.title} className="mb-4">
            <p className="px-3 pb-1.5 text-[11.5px] font-semibold uppercase tracking-[0.06em] text-[var(--y-ink-3)]">{section.title}</p>
            <ul className="grid gap-0.5">
              {section.links.map(link => {
                const active = nav.isActive(link.href);
                return (
                  <li key={link.href}>
                    <Link href={link.href} aria-current={active ? "page" : undefined}
                      className={cn("flex min-h-11 items-center gap-3 rounded-xl px-3 text-[14.5px] transition-colors",
                        active ? "bg-[var(--y-soft)] font-semibold text-[var(--y-soft-ink)]"
                               : "text-[var(--y-ink-2)] hover:bg-[var(--y-card)] hover:text-[var(--y-ink)]")}>
                      <link.icon size={18} aria-hidden />
                      {link.label}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>
      <div className="border-t border-[var(--y-line)] px-4 py-4">
        <p className="truncate text-[14px] font-semibold">{user?.name ?? "You"}</p>
        {user?.email && <p className="truncate text-[12.5px] text-[var(--y-ink-3)]">{user.email}</p>}
        <button type="button" onClick={() => { clearTokenCache(); signOut({ callbackUrl: "/yaad/login" }); }}
          className="y-press mt-3 inline-flex min-h-10 items-center gap-2 rounded-full border border-[var(--y-line-strong)] px-3.5 text-[13.5px] font-medium">
          <LogOut size={15} aria-hidden /> Sign out
        </button>
      </div>
    </aside>
  );
}
