"use client";
import api, { clearTokenCache } from "@/lib/api";
import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useNotificationsStore } from "@/store/useNotificationsStore";
import { useTheme } from "next-themes";
import { signOut } from "next-auth/react";
import { Bell, Search, User, Settings, CreditCard, HelpCircle, LogOut, ChevronDown, X, Sun, Moon, Monitor } from "@/lib/icons";
import { UserAvatar } from "@/components/crm/UserAvatar";

// ─── Types ────────────────────────────────────────────────────────────────────

interface TopBarProps {
  user?: {
    name?: string | null;
    email?: string | null;
    role?: string;
    tenantId?: string;
  };
  workspaceName?: string;
}

// ─── Theme toggle ─────────────────────────────────────────────────────────────

function ThemeToggle() {
  const { theme, setTheme } = useTheme();

  // Cycle: light → dark → system → light
  function cycle() {
    if (theme === "light") setTheme("dark");
    else if (theme === "dark") setTheme("system");
    else setTheme("light");
  }

  const Icon = theme === "light" ? Sun : theme === "dark" ? Moon : Monitor;
  const label = theme === "light" ? "Light" : theme === "dark" ? "Dark" : "System";

  return (
    <button
      onClick={cycle}
      title={`Theme: ${label} — click to cycle`}
      className="w-9 h-9 flex items-center justify-center rounded-lg transition-colors duration-150"
      style={{ color: "var(--haip-fg-subtle)" }}
      onMouseEnter={e => {
        (e.currentTarget as HTMLElement).style.background = "color-mix(in srgb, var(--primary) 8%, transparent)";
        (e.currentTarget as HTMLElement).style.color = "var(--primary)";
      }}
      onMouseLeave={e => {
        (e.currentTarget as HTMLElement).style.background = "transparent";
        (e.currentTarget as HTMLElement).style.color = "var(--haip-fg-subtle)";
      }}
    >
      <Icon size={15} />
    </button>
  );
}

// ─── Search bar ───────────────────────────────────────────────────────────────

function GlobalSearch() {
  const [query, setQuery] = useState("");
  const [focused, setFocused] = useState(false);
  const router = useRouter();

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" && query.trim()) {
      router.push(`/dashboard/guests?q=${encodeURIComponent(query.trim())}`);
      setQuery("");
    }
    if (e.key === "Escape") {
      setQuery("");
      (e.target as HTMLInputElement).blur();
    }
  }

  return (
    <div
      className="flex items-center gap-2 flex-1 max-w-md px-3 py-[7px] rounded-md transition-all duration-150"
      style={{
        background: "var(--input-bg, var(--muted))",
        border: focused
          ? "1px solid var(--primary)"
          : "1px solid var(--haip-border)",
        boxShadow: focused ? "0 0 0 3px color-mix(in srgb, var(--primary) 10%, transparent)" : "none",
      }}
    >
      <Search size={13} style={{ color: focused ? "var(--primary)" : "var(--haip-fg-subtle)", flexShrink: 0 }} />
      <input
        value={query}
        onChange={e => setQuery(e.target.value)}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        onKeyDown={handleKeyDown}
        placeholder="Search guests, calls, properties…"
        className="flex-1 bg-transparent text-[13px] outline-none min-w-0"
        style={{
          color: "var(--haip-fg)",
          caretColor: "var(--primary)",
        }}
      />
      {query && (
        <button
          onClick={() => setQuery("")}
          style={{ color: "var(--haip-fg-subtle)", flexShrink: 0 }}
        >
          <X size={12} />
        </button>
      )}
    </div>
  );
}

// ─── Notification bell ────────────────────────────────────────────────────────

function timeAgo(ts: number): string {
  const secs = Math.floor((Date.now() - ts) / 1000);
  if (secs < 60) return "just now";
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
  return `${Math.floor(secs / 86400)}d ago`;
}

function NotificationBell() {
  const [open, setOpen] = useState(false);
  const router = useRouter();
  const items = useNotificationsStore(s => s.items);
  const markAllRead = useNotificationsStore(s => s.markAllRead);
  const unreadCount = useNotificationsStore(s => s.unreadCount);
  const unread = unreadCount();

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(o => !o)}
        className="relative w-9 h-9 flex items-center justify-center rounded-lg transition-colors duration-150"
        style={{ color: "var(--haip-fg-subtle)" }}
        onMouseEnter={e => {
          (e.currentTarget as HTMLElement).style.background = "color-mix(in srgb, var(--primary) 8%, transparent)";
          (e.currentTarget as HTMLElement).style.color = "var(--primary)";
        }}
        onMouseLeave={e => {
          (e.currentTarget as HTMLElement).style.background = "transparent";
          (e.currentTarget as HTMLElement).style.color = "var(--haip-fg-subtle)";
        }}
      >
        <Bell size={15} />
        {unread > 0 && (
          <span
            className="absolute top-1.5 right-1.5 w-[7px] h-[7px] rounded-full"
            style={{ background: "var(--haip-red)" }}
          />
        )}
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} />
          <div
            className="absolute right-0 top-full mt-2 z-40 w-80 rounded-xl overflow-hidden shadow-md"
            style={{
              background: "var(--haip-card)",
              border: "1px solid var(--haip-border)",
            }}
          >
            {/* Header */}
            <div
              className="flex items-center justify-between px-4 py-3"
              style={{ borderBottom: "1px solid var(--haip-border)" }}
            >
              <span
                className="text-[10px] font-semibold uppercase tracking-widest"
                style={{ color: "var(--haip-fg-subtle)" }}
              >
                Notifications
              </span>
              {unread > 0 && (
                <span
                  className="text-[10px] px-2 py-0.5 rounded-full font-semibold"
                  style={{
                    background: "color-mix(in srgb, var(--primary) 10%, transparent)",
                    color: "var(--primary)",
                  }}
                >
                  {unread} new
                </span>
              )}
            </div>

            {/* Items */}
            {items.length === 0 ? (
              <div className="px-4 py-6 text-center">
                <p className="text-xs" style={{ color: "var(--haip-fg-subtle)" }}>No notifications yet</p>
              </div>
            ) : (
              items.map(n => (
                <div
                  key={n.id}
                  className="px-4 py-3 transition-colors duration-150 cursor-pointer"
                  style={{
                    borderBottom: "1px solid var(--haip-border)",
                    background: !n.read
                      ? "color-mix(in srgb, var(--primary) 4%, transparent)"
                      : "transparent",
                  }}
                  onClick={() => { setOpen(false); router.push(n.url); }}
                  onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = "var(--hover-bg)"; }}
                  onMouseLeave={e => {
                    (e.currentTarget as HTMLElement).style.background = !n.read
                      ? "color-mix(in srgb, var(--primary) 4%, transparent)"
                      : "transparent";
                  }}
                >
                  <p className="text-xs font-semibold mb-0.5" style={{ color: "var(--haip-fg)" }}>
                    {n.title}
                  </p>
                  <p className="text-xs leading-relaxed mb-0.5" style={{ color: "var(--haip-fg-2)" }}>
                    {n.body}
                  </p>
                  <p className="text-[10px]" style={{ color: "var(--haip-fg-subtle)" }}>{timeAgo(n.ts)}</p>
                </div>
              ))
            )}

            {/* Footer */}
            {items.length > 0 && (
              <div className="px-4 py-2.5 text-center">
                <button
                  onClick={markAllRead}
                  className="text-xs font-semibold transition-colors duration-150"
                  style={{ color: "var(--primary)" }}
                >
                  Mark all read
                </button>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

// ─── User avatar / menu ───────────────────────────────────────────────────────

function UserMenu({ user }: { user?: TopBarProps["user"] }) {
  const [open, setOpen] = useState(false);
  const { data: me } = useQuery({
    queryKey: ["users", "me"],
    queryFn: () => api.get("/users/me").then(r => r.data),
    staleTime: 60_000,
  });

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(o => !o)}
        className="flex items-center gap-1.5 rounded-lg px-1.5 py-1 transition-colors duration-150"
        onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = "var(--hover-bg)"; }}
        onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = "transparent"; }}
      >
        <UserAvatar name={user?.name} photoUrl={me?.avatar_url} size="sm" />
        <ChevronDown size={11} style={{ color: "var(--haip-fg-subtle)" }} />
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} />
          <div
            className="absolute right-0 top-full mt-2 z-40 w-52 rounded-xl overflow-hidden shadow-md"
            style={{
              background: "var(--haip-card)",
              border: "1px solid var(--haip-border)",
            }}
          >
            {/* User info */}
            <div
              className="px-4 py-3"
              style={{ borderBottom: "1px solid var(--haip-border)" }}
            >
              <p className="text-[13px] font-semibold truncate" style={{ color: "var(--haip-fg)" }}>
                {user?.name ?? "User"}
              </p>
              <p className="text-[11px] truncate" style={{ color: "var(--haip-fg-subtle)" }}>
                {user?.email}
              </p>
              <span
                className="inline-flex items-center mt-1.5 text-[10px] px-2 py-0.5 rounded-full font-medium capitalize"
                style={{
                  background: "color-mix(in srgb, var(--primary) 10%, transparent)",
                  color: "var(--primary)",
                }}
              >
                {user?.role ?? "member"}
              </span>
            </div>

            {/* Menu items */}
            <div className="p-1.5">
              {[
                { icon: <User size={13} />,       label: "Profile",        href: "/dashboard/profile" },
                { icon: <Settings size={13} />,   label: "Settings",       href: "/dashboard/settings" },
                { icon: <CreditCard size={13} />, label: "Billing",        href: "/dashboard/billing" },
                { icon: <HelpCircle size={13} />, label: "Help & support", href: "/dashboard/help" },
              ].map(item => (
                <Link
                  key={item.label}
                  href={item.href}
                  onClick={() => setOpen(false)}
                  className="flex items-center gap-2.5 px-3 py-2 text-xs rounded-lg transition-colors duration-150"
                  style={{ color: "var(--haip-fg-muted)" }}
                  onMouseEnter={e => {
                    (e.currentTarget as HTMLElement).style.background = "var(--hover-bg)";
                    (e.currentTarget as HTMLElement).style.color = "var(--haip-fg)";
                  }}
                  onMouseLeave={e => {
                    (e.currentTarget as HTMLElement).style.background = "transparent";
                    (e.currentTarget as HTMLElement).style.color = "var(--haip-fg-muted)";
                  }}
                >
                  <span style={{ color: "var(--haip-fg-subtle)" }}>{item.icon}</span>
                  {item.label}
                </Link>
              ))}

              <div className="h-px my-1" style={{ background: "var(--haip-border)" }} />

              <button
                onClick={() => { clearTokenCache(); signOut({ callbackUrl: "/login" }); }}
                className="w-full flex items-center gap-2.5 px-3 py-2 text-xs rounded-lg transition-colors duration-150"
                style={{ color: "var(--haip-red)" }}
                onMouseEnter={e => {
                  (e.currentTarget as HTMLElement).style.background = "rgba(239,68,68,0.06)";
                }}
                onMouseLeave={e => {
                  (e.currentTarget as HTMLElement).style.background = "transparent";
                }}
              >
                <LogOut size={13} />
                Sign out
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

// ─── Main TopBar ──────────────────────────────────────────────────────────────

export function TopBar({ user, workspaceName }: TopBarProps) {
  return (
    <div
      className="h-14 flex items-center justify-between px-5 flex-shrink-0 gap-4 bg-background"
      style={{
        borderBottom: "1px solid var(--haip-border)",
        zIndex: 10,
      }}
    >
      {/* Left: page title area (workspace name on desktop) */}
      <div className="flex items-center gap-3 flex-shrink-0">
        <span
          className="font-semibold text-sm hidden sm:block tracking-tight"
          style={{ color: "var(--haip-fg)" }}
        >
          {workspaceName ?? "HAIP Platform"}
        </span>
      </div>

      {/* Center: Search */}
      <div className="flex-1 max-w-md mx-4">
        <GlobalSearch />
      </div>

      {/* Right: theme toggle + bell + user */}
      <div className="flex items-center gap-1 flex-shrink-0">
        <ThemeToggle />
        <NotificationBell />
        <UserMenu user={user} />
      </div>
    </div>
  );
}
