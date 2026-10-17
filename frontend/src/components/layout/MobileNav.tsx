"use client";
// Phone navigation, Hospitality Hybrid. A light bottom bar with four destinations around a raised "Now" button that opens
// My day (with how many people are waiting), and a full menu sheet opened from the header's menu button. Both read the one
// nav model (components/layout/nav.ts), so nothing reachable on desktop is phone-only-by-URL or the other way round.
import Link from "next/link";
import { signOut } from "next-auth/react";
import { useQuery } from "@tanstack/react-query";
import api, { clearTokenCache } from "@/lib/api";
import { LogOut, X, Zap } from "@/lib/icons";
import { cn } from "@/lib/utils";
import { AppVersionRow } from "@/components/AppVersionRow";
import { UserAvatar } from "@/components/crm/UserAvatar";
import { useBrandTheme } from "@/components/providers/BrandThemeProvider";
import { NOW_HREF, PHONE_TABS, useNav } from "./nav";

interface MobileNavProps {
  user?: { name?: string | null; email?: string | null; role?: string };
}

const SHORT: Record<string, string> = { "/dashboard": "Home", "/dashboard/portfolio/calendar": "Calendar" };

export function MobileNav({ user }: MobileNavProps) {
  const nav = useNav(user?.role ?? "");
  const tabs = PHONE_TABS.map(h => nav.byHref.get(h)).filter(Boolean) as NonNullable<ReturnType<typeof nav.byHref.get>>[];
  const now = nav.byHref.get(NOW_HREF);
  const slots: (typeof tabs[number] | "now")[] = now ? [...tabs.slice(0, 2), "now", ...tabs.slice(2)] : tabs;
  const nowActive = nav.isActive(NOW_HREF);

  return (
    <nav aria-label="Primary"
      className="fixed inset-x-0 bottom-0 z-50 flex items-stretch border-t border-[var(--haip-border)] bg-[var(--haip-card)] md:hidden"
      style={{ paddingBottom: "env(safe-area-inset-bottom)", paddingLeft: "env(safe-area-inset-left)", paddingRight: "env(safe-area-inset-right)" }}>
      {slots.map(slot => {
        if (slot === "now") {
          return (
            <Link key="now" href={NOW_HREF} aria-current={nowActive ? "page" : undefined}
              aria-label={nav.waiting ? `Now: ${nav.waiting} people waiting` : "Now: nobody waiting"}
              className="relative flex min-h-[60px] flex-1 flex-col items-center justify-end pb-1.5">
              <span className={cn("absolute -top-5 flex size-14 flex-col items-center justify-center rounded-2xl text-primary-foreground ring-4 ring-[var(--haip-app-bg)] transition-transform active:scale-95",
                "bg-primary shadow-[0_8px_20px_-6px_color-mix(in_srgb,var(--primary)_70%,transparent)]")}>
                <Zap size={20} />
                <span className="num text-[11px] font-bold leading-none">{nav.waiting > 99 ? "99+" : nav.waiting}</span>
              </span>
              <span className={cn("text-[11px] font-semibold", nowActive ? "text-primary" : "text-[var(--haip-fg-muted)]")}>Now</span>
            </Link>
          );
        }
        const active = nav.isActive(slot.href);
        const n = nav.badge(slot.href);
        return (
          <Link key={slot.href} href={slot.href} aria-current={active ? "page" : undefined}
            className="relative flex min-h-[60px] min-w-0 flex-1 flex-col items-center justify-center gap-1 transition-opacity active:opacity-70">
            <span className="relative">
              <slot.icon size={21} className={active ? "text-primary" : "text-[var(--haip-icon-neutral)]"} />
              {n > 0 && <span className="num absolute -right-2.5 -top-1.5 min-w-4 rounded-full bg-primary px-1 text-center text-[10px] font-bold leading-4 text-primary-foreground">{n > 9 ? "9+" : n}</span>}
            </span>
            <span className={cn("text-[11px] font-semibold", active ? "text-primary" : "text-[var(--haip-fg-muted)]")}>{SHORT[slot.href] ?? slot.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}

/** The full menu on phones: every page the person can open, grouped like the desktop "More" menu, plus their account. */
export function MobileMenuSheet({ open, onClose, user }: { open: boolean; onClose: () => void; user?: MobileNavProps["user"] }) {
  const nav = useNav(user?.role ?? "");
  const { theme } = useBrandTheme();
  const { data: me } = useQuery({ queryKey: ["users", "me"], queryFn: () => api.get("/users/me").then(r => r.data), staleTime: 60_000 });
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-[60] flex md:hidden">
      <button type="button" aria-label="Close menu" onClick={onClose} className="absolute inset-0 bg-[rgb(28_25_23/0.45)] backdrop-blur-[2px]" />
      <div role="dialog" aria-modal="true" aria-label="Menu"
        className="relative flex h-full w-[min(21rem,88vw)] flex-col overflow-y-auto overscroll-contain bg-[var(--haip-card)] shadow-[var(--haip-shadow-lg)] animate-in slide-in-from-left duration-200"
        style={{ paddingTop: "env(safe-area-inset-top)" }}>
        <div className="flex items-center justify-between px-5 py-3">
          <span className="font-[family-name:var(--font-display)] text-[18px] font-semibold">{theme.companyName ?? "HAIP"}</span>
          <button type="button" onClick={onClose} aria-label="Close menu" className="flex size-11 items-center justify-center rounded-xl text-[var(--haip-icon-neutral)] hover:bg-[var(--hover-bg)]"><X size={19} /></button>
        </div>
        <nav aria-label="All pages" className="flex-1 px-3 pb-3">
          {nav.sections.map(section => (
            <div key={section.title} className="mb-3">
              <p className="px-2 pb-1 pt-2 text-[12px] font-semibold text-[var(--haip-fg-subtle)]">{section.title}</p>
              {section.links.map(link => {
                const active = nav.isActive(link.href);
                const n = nav.badge(link.href);
                return (
                  <Link key={link.href} href={link.href} onClick={onClose} aria-current={active ? "page" : undefined}
                    className={cn("mb-0.5 flex min-h-11 items-center gap-3 rounded-xl px-3 text-[15px] transition-colors",
                      active ? "bg-[var(--haip-primary-tint)] font-semibold text-primary" : "text-[var(--haip-fg)] active:bg-[var(--hover-bg)]")}>
                    <link.icon size={18} className={active ? "text-primary" : "text-[var(--haip-icon-neutral)]"} />
                    <span className="flex-1">{link.label}</span>
                    {n > 0 && <span className="num rounded-full bg-primary px-2 text-[11px] font-bold leading-5 text-primary-foreground">{n > 99 ? "99+" : n}</span>}
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>
        <div className="border-t border-[var(--haip-border)] p-4" style={{ paddingBottom: "calc(1rem + env(safe-area-inset-bottom))" }}>
          <div className="mb-3 flex items-center gap-3">
            <UserAvatar name={user?.name} photoUrl={me?.avatar_url} size="md" className="size-10" />
            <div className="min-w-0 flex-1"><p className="truncate text-[15px] font-semibold">{user?.name ?? "User"}</p><p className="truncate text-[12.5px] text-[var(--haip-fg-subtle)]">{user?.email ?? ""}</p></div>
          </div>
          <button type="button" onClick={() => { clearTokenCache(); signOut({ callbackUrl: "/login" }); }}
            className="flex min-h-11 w-full items-center gap-2.5 rounded-xl px-3 text-[15px] font-semibold text-[var(--haip-status-danger-fg)] hover:bg-[var(--haip-status-danger-bg)]">
            <LogOut size={17} />Sign out
          </button>
          <div className="mt-1 border-t border-[var(--haip-border)] pt-2"><AppVersionRow /></div>
        </div>
      </div>
    </div>
  );
}
