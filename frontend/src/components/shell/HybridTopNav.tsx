"use client";
// Desktop app shell (greens + terracotta): one forest top bar instead of a sidebar, so pages get the full width. Primary tabs
// for the daily destinations, each with its icon (My day and Inbox carry live counts in terracotta), a "More" menu with
// every other page grouped by section, then search, theme, notifications and the account menu. Tabs that only fit from
// 1024px move into "More" below that, and tab labels show from 1024px (icons only, with a tooltip, below).
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { ChevronDown, Search } from "@/lib/icons";
import { cn } from "@/lib/utils";
import { useBrandTheme } from "@/components/providers/BrandThemeProvider";
import { PRIMARY_TABS, useNav } from "@/components/layout/nav";
import { MORE_ICON } from "@/components/layout/PageIcon";
import { GlobalSearch, NotificationBell, ThemeToggle, UserMenu } from "./TopBar";

interface Props { user?: { name?: string | null; email?: string | null; role?: string; tenantId?: string } }

// The house wordmark is a teal image that disappears on the forest bar; it gets the lime letter tile instead. A tenant's
// own logo still shows (its dark-background variant when uploaded, else the logo on a small white plate).
const HOUSE_LOGOS = new Set(["/logo-wordmark.png", "/logo.png"]);
const isOwnLogo = (u?: string) => !!u && !HOUSE_LOGOS.has(u);

function Count({ n }: { n: number }) {
  if (!n) return null;
  return (
    <span className="num min-w-5 rounded-full bg-[var(--haip-accent)] px-1.5 text-center text-[11px] font-bold leading-5 text-[var(--haip-on-accent)]">
      {n > 99 ? "99+" : n}
    </span>
  );
}

const TAB = "relative h-10 items-center gap-2 rounded-full px-3 text-[14px] font-semibold transition-colors";
const TAB_IDLE = "text-[var(--haip-nav-fg-dim)] hover:bg-[var(--haip-nav-hover)] hover:text-[var(--haip-nav-fg)]";
const TAB_ON = "bg-[var(--haip-nav-active-bg)] text-[var(--haip-nav-active-fg)]";

function MoreMenu({ nav }: { nav: ReturnType<typeof useNav> }) {
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);
  useEffect(() => { setOpen(false); }, [nav.pathname]);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    const onDown = (e: MouseEvent) => { if (wrap.current && !wrap.current.contains(e.target as Node)) setOpen(false); };
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onDown);
    return () => { window.removeEventListener("keydown", onKey); window.removeEventListener("mousedown", onDown); };
  }, [open]);
  const activeElsewhere = nav.sections.some(s => s.links.some(l => nav.isActive(l.href) && !PRIMARY_TABS.some(t => t.href === l.href)));
  const MoreIcon = MORE_ICON;
  return (
    // Not `relative`: the menu positions against the sticky header so it spans the bar, not the button's edge.
    <div ref={wrap}>
      <button type="button" onClick={() => setOpen(o => !o)} aria-expanded={open} aria-haspopup="true" aria-label="More pages"
        className={cn(TAB, "flex", open || activeElsewhere ? TAB_ON : TAB_IDLE)}>
        <MoreIcon size={17} />
        <span className="hidden lg:inline">More</span>
        <ChevronDown size={15} className={cn("transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <div role="menu" aria-label="All pages"
          className="absolute inset-x-4 top-full z-50 mx-auto mt-2 max-h-[calc(100dvh-88px)] max-w-[960px] overflow-y-auto origin-top rounded-2xl border border-[var(--haip-border)] bg-[var(--haip-card)] p-4 text-[var(--haip-fg)] shadow-[var(--haip-shadow-lg)] animate-in fade-in-0 zoom-in-[0.98] duration-150">
          <div className="grid grid-cols-2 gap-x-6 gap-y-5 lg:grid-cols-4">
            {nav.sections.map(section => (
              <div key={section.title} className="min-w-0">
                <p className="mb-1.5 px-2 text-[12px] font-semibold text-[var(--haip-fg-subtle)]">{section.title}</p>
                <ul>
                  {section.links.map(link => {
                    const active = nav.isActive(link.href);
                    return (
                      <li key={link.href}>
                        <Link href={link.href} role="menuitem" onClick={() => setOpen(false)}
                          className={cn("flex min-h-9 items-center gap-2.5 rounded-lg px-2 text-[13.5px] transition-colors",
                            active ? "bg-[var(--haip-tabbar-active-bg)] font-semibold text-[var(--haip-tabbar-active-fg)]" : "text-[var(--haip-fg)] hover:bg-[var(--hover-bg)]")}>
                          <link.icon size={16} className={active ? "text-primary" : "text-[var(--haip-icon-neutral)]"} />
                          <span className="min-w-0 flex-1 truncate">{link.label}</span>
                          <Count n={nav.badge(link.href)} />
                        </Link>
                      </li>
                    );
                  })}
                </ul>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export function HybridTopNav({ user }: Props) {
  const role = user?.role ?? "";
  const nav = useNav(role);
  const { theme } = useBrandTheme();
  const tabs = PRIMARY_TABS.map(t => ({ ...t, link: nav.byHref.get(t.href) })).filter(t => t.link);
  const darkLogo = isOwnLogo(theme.logoDarkUrl) ? theme.logoDarkUrl : null;
  const plateLogo = !darkLogo && isOwnLogo(theme.logoUrl) ? theme.logoUrl : null;

  return (
    <header className="sticky top-0 z-40 flex h-16 flex-shrink-0 items-center gap-2 border-b border-[var(--haip-nav-border)] bg-[var(--haip-nav-bg)] px-4 text-[var(--haip-nav-fg)] lg:px-6">
      <Link href="/dashboard" aria-label={`${theme.companyName ?? "HAIP"} home`} className="mr-2 flex shrink-0 items-center gap-2.5">
        {darkLogo ? (
          <img src={darkLogo} alt={theme.companyName ?? "HAIP"} className="h-7 w-auto max-w-[120px] object-contain" />
        ) : plateLogo ? (
          <span className="flex h-9 items-center rounded-xl bg-white px-2">
            <img src={plateLogo} alt={theme.companyName ?? "HAIP"} className="h-6 w-auto max-w-[110px] object-contain" />
          </span>
        ) : (
          <span className="flex size-9 items-center justify-center rounded-xl bg-[var(--haip-logo-bg)] font-[family-name:var(--font-display)] text-[17px] font-bold text-[var(--haip-logo-fg)]">
            {(theme.companyName ?? "H").slice(0, 1).toUpperCase()}
          </span>
        )}
      </Link>

      <nav aria-label="Primary" className="flex min-w-0 items-center gap-1">
        {tabs.map(({ href, wide, link }) => {
          const active = nav.isActive(href);
          const Icon = link!.icon;
          return (
            <Link key={href} href={href} aria-current={active ? "page" : undefined} title={link!.label}
              className={cn(TAB, wide ? "hidden lg:flex" : "flex", active ? TAB_ON : TAB_IDLE)}>
              <Icon size={17} />
              <span className="sr-only lg:not-sr-only">{link!.label}</span>
              <Count n={nav.badge(href)} />
            </Link>
          );
        })}
        <MoreMenu nav={nav} />
      </nav>

      <div className="ml-auto flex shrink-0 items-center gap-1">
        <div className="hidden w-[260px] xl:block"><GlobalSearch onDark /></div>
        <button type="button" aria-label="Search (Ctrl K)" title="Search (Ctrl K)"
          onClick={() => window.dispatchEvent(new KeyboardEvent("keydown", { key: "k", ctrlKey: true, metaKey: true }))}
          className="flex size-10 items-center justify-center rounded-xl text-[var(--haip-nav-fg-dim)] hover:bg-[var(--haip-nav-hover)] hover:text-[var(--haip-nav-fg)] xl:hidden">
          <Search size={18} />
        </button>
        <ThemeToggle onDark />
        <NotificationBell onDark />
        <UserMenu user={user} onDark />
      </div>
    </header>
  );
}
