"use client";
// Desktop top bar for direction C: the pages toggle, ONE box for both asking HAIP and finding a guest, booking or page
// (opens the command palette, components/ui/CommandPalette.tsx), then theme, notifications and the one account menu.
import { LayoutGrid, Search } from "@/lib/icons";
import { useNav } from "@/components/layout/nav";
import { NotificationBell, ThemeToggle, UserMenu } from "./TopBar";
import { PANEL_EVENT } from "./RailNav";

interface Props { user?: { name?: string | null; email?: string | null; role?: string; tenantId?: string } }

export const COMMAND_EVENT = "haip:open-command";

export function CommandBar({ user }: Props) {
  const nav = useNav(user?.role ?? "");
  if (nav.personal) return null;
  const canAsk = user?.role === "owner";
  return (
    <header className="sticky top-0 z-30 flex h-16 shrink-0 items-center gap-3 border-b border-[var(--haip-nav-border)] bg-[var(--haip-nav-bg)] px-4 text-[var(--haip-nav-fg)] lg:px-6">
      <button type="button" onClick={() => window.dispatchEvent(new Event(PANEL_EVENT))}
        aria-label={`Show or hide ${nav.activeArea?.title ?? ""} pages`} title="Pages"
        className="flex size-10 shrink-0 items-center justify-center rounded-xl text-[var(--haip-nav-fg-dim)] hover:bg-[var(--haip-nav-hover)] hover:text-[var(--haip-nav-fg)]">
        <LayoutGrid size={18} />
      </button>
      <button type="button" onClick={() => window.dispatchEvent(new Event(COMMAND_EVENT))}
        className="mx-auto flex h-11 w-full max-w-[640px] min-w-0 items-center gap-2.5 rounded-2xl border border-[var(--haip-nav-border)] bg-[var(--haip-nav-field)] px-3.5 text-left text-[15px] text-[var(--haip-nav-field-placeholder)] transition-colors hover:border-[var(--haip-btn-secondary-border,var(--haip-nav-border))]">
        <Search size={18} className={canAsk ? "shrink-0 text-primary" : "shrink-0"} />
        <span className="min-w-0 flex-1 truncate">{canAsk ? "Ask HAIP, or find a guest, booking or page" : "Find a guest, booking or page"}</span>
        <kbd className="hidden shrink-0 rounded-md border border-[var(--haip-nav-border)] bg-[var(--haip-card)] px-1.5 py-0.5 font-mono text-[12px] sm:block">Ctrl K</kbd>
      </button>
      <div className="flex shrink-0 items-center gap-1">
        <ThemeToggle onDark />
        <NotificationBell onDark />
        <UserMenu user={user} onDark />
      </div>
    </header>
  );
}
