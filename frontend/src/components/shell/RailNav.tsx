"use client";
// Desktop shell, direction C (workspace redesign, owner pick 16 Nov 2026): a deep-green icon rail with the eight areas and
// Settings, and beside it a panel listing the current area's pages (Settings shows its groups, which makes it the
// Settings hub). Both read the one nav model (components/layout/nav.ts). The panel is open by default from 1024px; below
// that it opens over the page from the command bar's "Pages" button and closes after a pick.
import Link from "next/link";
import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import { useBrandTheme } from "@/components/providers/BrandThemeProvider";
import { SETTINGS_KEY, type NavSection, useNav } from "@/components/layout/nav";

interface Props { user?: { role?: string } }

const RAIL_LABEL: Record<string, string> = { automations: "Automate", marketing: "Marketing" };
const PANEL_KEY = "haip.panel";      // per-browser convenience: whether the panel is open on wide screens
export const PANEL_EVENT = "haip:toggle-panel";

const HOUSE_LOGOS = new Set(["/logo-wordmark.png", "/logo.png"]);

function Count({ n, onRail = false }: { n: number; onRail?: boolean }) {
  if (!n) return null;
  return (
    <span className={cn("num rounded-full bg-[var(--haip-accent)] text-center font-bold text-[var(--haip-on-accent)]",
      onRail ? "absolute right-1.5 top-1 min-w-[18px] px-1 text-[11px] leading-[18px]" : "ml-auto min-w-5 px-1.5 text-[11.5px] leading-5")}>
      {n > 99 ? "99+" : n}
    </span>
  );
}

function wide(): boolean {
  return typeof window !== "undefined" && window.matchMedia("(min-width: 1024px)").matches;
}

function PanelLinks({ area, nav, onPick }: { area: NavSection; nav: ReturnType<typeof useNav>; onPick: () => void }) {
  const groups = area.groups ?? [{ title: "", links: area.links }];
  const siblings = area.links.map(l => l.href);
  return (
    <>
      {groups.map(group => (
        <div key={group.title || "pages"} className="mb-3">
          {group.title && <p className="px-3 pb-1 pt-2 text-[12px] font-semibold text-[var(--haip-fg-subtle)]">{group.title}</p>}
          <ul>
            {group.links.map(link => {
              const current = nav.isCurrent(link.href, siblings);
              return (
                <li key={link.href}>
                  <Link href={link.href} onClick={onPick} aria-current={current ? "page" : undefined}
                    className={cn("flex min-h-10 items-center gap-2.5 rounded-xl px-3 text-[14px] transition-colors",
                      current ? "bg-[var(--haip-nav-active-bg)] font-semibold text-[var(--haip-nav-active-fg)]"
                        : "text-[var(--haip-fg)] hover:bg-[var(--haip-nav-hover)]")}>
                    <link.icon size={17} className={current ? "text-primary" : "text-[var(--haip-icon-neutral)]"} />
                    <span className="min-w-0 flex-1 truncate">{link.label}</span>
                    <Count n={nav.badge(link.href)} />
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </>
  );
}

export function RailNav({ user }: Props) {
  const nav = useNav(user?.role ?? "");
  const { theme } = useBrandTheme();
  const [open, setOpen] = useState(true);

  // Wide screens remember the choice; narrow ones start closed (the panel would cover the page).
  useEffect(() => {
    if (!wide()) { setOpen(false); return; }
    try { if (window.localStorage.getItem(PANEL_KEY) === "closed") setOpen(false); } catch { /* storage blocked: stay open */ }
  }, []);
  useEffect(() => {
    const toggle = () => setOpen(o => {
      const next = !o;
      if (wide()) { try { window.localStorage.setItem(PANEL_KEY, next ? "open" : "closed"); } catch { /* ignore */ } }
      return next;
    });
    window.addEventListener(PANEL_EVENT, toggle);
    return () => window.removeEventListener(PANEL_EVENT, toggle);
  }, []);
  useEffect(() => { if (!wide()) setOpen(false); }, [nav.pathname]);

  if (nav.personal) return null;   // Yaad (personal workspace): its own left sidebar (personal/YaadSideNav)
  const areas = nav.sections.filter(s => s.key !== SETTINGS_KEY);
  const settings = nav.sections.find(s => s.key === SETTINGS_KEY);
  const current = nav.activeArea ?? areas[0];
  const ownLogo = theme.logoUrl && !HOUSE_LOGOS.has(theme.logoUrl) ? theme.logoUrl : null;
  const closeIfNarrow = () => { if (!wide()) setOpen(false); };

  const railItem = (area: NavSection) => {
    const active = current?.key === area.key;
    const Icon = area.icon!;
    return (
      <Link key={area.key} href={area.links[0].href} aria-current={active ? "true" : undefined} title={area.title}
        className={cn("relative flex w-16 flex-col items-center gap-1 rounded-2xl py-2 text-[11.5px] font-medium transition-colors",
          active ? "bg-[var(--sidebar-accent)] font-semibold text-[var(--sidebar-accent-foreground)]"
            : "text-[var(--sidebar-foreground)] hover:bg-[color-mix(in_srgb,var(--sidebar-foreground)_12%,transparent)]")}>
        <Icon size={20} />
        <span className="max-w-full truncate px-1">{RAIL_LABEL[area.key ?? ""] ?? area.title}</span>
        <Count n={nav.areaBadge(area)} onRail />
      </Link>
    );
  };

  return (
    <>
      <nav aria-label="Areas" className="flex w-[76px] shrink-0 flex-col items-center gap-1.5 bg-[var(--sidebar)] py-3">
        <Link href="/dashboard" aria-label={`${theme.companyName ?? "HAIP"} home`} className="mb-2 flex size-10 items-center justify-center overflow-hidden rounded-xl bg-white">
          {ownLogo ? <img src={ownLogo} alt="" className="size-8 object-contain" />
            : <span className="font-[family-name:var(--font-display)] text-[16px] font-bold text-[var(--sidebar-accent-foreground)]">{(theme.companyName ?? "H").slice(0, 1).toUpperCase()}</span>}
        </Link>
        {areas.map(railItem)}
        <span className="flex-1" />
        {settings && railItem(settings)}
      </nav>

      {open && current && (
        <>
          <button type="button" aria-label="Close pages" onClick={() => setOpen(false)}
            className="fixed inset-0 z-30 bg-[rgb(15_42_32/0.25)] lg:hidden" />
          <aside aria-label={`${current.title} pages`}
            className="fixed inset-y-0 left-[76px] z-40 flex w-[232px] shrink-0 flex-col overflow-y-auto border-r border-[var(--haip-border)] bg-[var(--haip-surface)] px-2 py-4 shadow-[var(--haip-shadow-lg)] lg:static lg:z-auto lg:shadow-none">
            <p className="px-3 pb-3 font-[family-name:var(--font-display)] text-[18px] font-bold text-[var(--haip-fg)]">{current.title}</p>
            <PanelLinks area={current} nav={nav} onPick={closeIfNarrow} />
          </aside>
        </>
      )}
    </>
  );
}
