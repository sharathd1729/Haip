"use client";
// The one navigation model for the app shell (workspace redesign, Nov 2026: owner picked direction C, icon rail + area
// panel + one bar for Ask HAIP and search). Eight AREAS, each a group of pages; Settings is one hub with its own groups.
// The desktop rail and panel, the phone bottom bar and the phone menu all read this, so a page is reachable the same way
// everywhere. Visibility rules (role via canSeeNav, onlyRoles, business type, owner-only) live here only.
// Plan: claude.ai/artifact/TmeAnWuJg4XTagvhdhrkpf. URLs are unchanged in this step.
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { useAppPathname } from "@/lib/useAppPathname";
import type { ComponentType } from "react";
import api from "@/lib/api";
import {
  AtSign, BadgeCheck, BarChart2, BellRing, Bot, BookOpen, BookmarkIcon, Building, Building2, Calculator, Calendar, CalendarClock,
  ClipboardList, CreditCard, FileText, FlaskConical, Globe, HelpCircle, Key, KeyRound, Link2, ListChecks, MapPin, Megaphone,
  AskBubble, MessageCircle, Palette, Phone, Send, Settings, Shield, ShieldCheck, Shuffle, Sparkles, Target, TrendingUp, UserCircle,
  UsersRound, Wallet, Workflow, Zap,
} from "@/lib/icons";
import { GitBranch, UserCheck } from "lucide-react";
import { ROUTE_ICONS as I } from "./PageIcon";
import { OPS_READ_ROLES } from "@/lib/ops";
import { SOPS_READ_ROLES } from "@/lib/sops";
import { BOOKING_READ_ROLES, QUOTE_WRITE_ROLES, REVENUE_READ_ROLES, canSeeNav, type Resource } from "@/lib/permissions";
import { useBusinessType, usePersonalMode } from "@/components/providers/WorkspaceProvider";
import { OPS_BUSINESS_TYPES, segmentFor } from "@/lib/segments";
import { useInboxStore } from "@/store/inbox";

export type NavIcon = ComponentType<{ size?: number; className?: string; strokeWidth?: number }>;

export interface NavLink {
  label: string;
  href: string;
  icon: NavIcon;
  resource: Resource;
  hideForBusinessTypes?: string[];
  /** Shown only for these business types (hidden while the type is still unknown). */
  onlyForBusinessTypes?: string[];
  onlyRoles?: string[];
  ownerOnly?: boolean;
}
export interface NavSection {
  title: string;
  links: NavLink[];
  /** Areas: a stable key and the rail icon. */
  key?: string;
  icon?: NavIcon;
  /** Settings: its pages in named groups (links holds them all, flattened). */
  groups?: { title: string; links: NavLink[] }[];
}

const MANAGERS = ["owner", "manager"];
const MARKETERS = ["owner", "manager", "marketing"];
const STAFF_TYPES = ["caravan", "villa", "villa_resort"];

export const SETTINGS_KEY = "settings";

const SETTINGS_GROUPS: { title: string; links: NavLink[] }[] = [
  { title: "Business", links: [
    { label: "Business details", href: "/dashboard/settings", icon: Settings, resource: "settings" },
    { label: "Notifications", href: "/dashboard/settings?tab=notifications", icon: BellRing, resource: "settings" },
    { label: "Branding", href: "/dashboard/settings/branding", icon: Palette, resource: "branding" },
    { label: "Invoice details", href: "/dashboard/settings/invoices", icon: FileText, resource: "settings", onlyRoles: MANAGERS },
    { label: "Guest details form", href: "/dashboard/settings/guest-form", icon: ClipboardList, resource: "settings", onlyRoles: OPS_READ_ROLES, onlyForBusinessTypes: OPS_BUSINESS_TYPES },
    { label: "Packages and routes", href: "/dashboard/settings/quotes", icon: Calculator, resource: "settings", onlyRoles: MANAGERS, onlyForBusinessTypes: ["caravan"] },
  ] },
  { title: "Team and access", links: [
    { label: "Team", href: "/dashboard/settings/team", icon: UsersRound, resource: "users" },
    { label: "Roles and permissions", href: "/dashboard/settings/permissions", icon: ShieldCheck, resource: "users", onlyRoles: ["owner"] },
    { label: "Security and sign-in", href: "/dashboard/settings?tab=security", icon: Shield, resource: "settings" },
  ] },
  { title: "Channels and integrations", links: [
    { label: "Integrations", href: "/dashboard/settings/integrations", icon: Link2, resource: "integrations" },
    { label: "Calls (IVR)", href: "/dashboard/settings/ivr", icon: Phone, resource: "settings", onlyRoles: MANAGERS },
    { label: "Calls app phones", href: "/dashboard/settings/calls-app", icon: Phone, resource: "users", onlyRoles: MANAGERS },
    { label: "Calendar sync", href: "/dashboard/settings/calendar-sync", icon: Calendar, resource: "settings" },
    { label: "Razorpay payments", href: "/dashboard/settings/payments", icon: CreditCard, resource: "settings" },
    { label: "GPS trackers", href: "/dashboard/settings/gps", icon: MapPin, resource: "settings", onlyRoles: MANAGERS, onlyForBusinessTypes: ["caravan"] },
    { label: "Developers and API", href: "/dashboard/settings/developers", icon: Key, resource: "settings" },
    { label: "AI connectors (MCP)", href: "/dashboard/settings/mcp-access", icon: KeyRound, resource: "settings", onlyRoles: MANAGERS },
  ] },
  { title: "Leads and replies", links: [
    { label: "Lead assignment", href: "/dashboard/settings/lead-assignment", icon: Shuffle, resource: "settings" },
    { label: "Lead rules", href: "/dashboard/settings/lead-rules", icon: BadgeCheck, resource: "settings", onlyRoles: MANAGERS },
    { label: "Saved replies", href: "/dashboard/settings/saved-replies", icon: BookmarkIcon, resource: "templates" },
  ] },
  { title: "Plan and privacy", links: [
    { label: "Billing", href: "/dashboard/billing", icon: CreditCard, resource: "billing" },
    { label: "Privacy and compliance", href: "/dashboard/compliance", icon: Shield, resource: "compliance" },
  ] },
];

export const NAV_SECTIONS: NavSection[] = [
  { key: "home", title: "Home", icon: I["/dashboard"], links: [
    { label: "My day", href: "/dashboard/my-day", icon: I["/dashboard/my-day"], resource: "inbox" },
    { label: "Dashboard", href: "/dashboard", icon: I["/dashboard"], resource: "dashboard" },
    { label: "Targets", href: "/dashboard/targets", icon: TrendingUp, resource: "guests", onlyRoles: REVENUE_READ_ROLES },
    { label: "Reports", href: "/dashboard/reports", icon: I["/dashboard/reports"], resource: "reports" },
    { label: "Lead activity report", href: "/dashboard/leads-activity", icon: ClipboardList, resource: "reports" },
  ] },
  { key: "inbox", title: "Inbox", icon: I["/dashboard/inbox"], links: [
    { label: "All conversations", href: "/dashboard/inbox", icon: I["/dashboard/inbox"], resource: "inbox" },
    { label: "AI conversations", href: "/dashboard/inbox?ch=ai", icon: Sparkles, resource: "inbox", hideForBusinessTypes: ["caravan"] },
    { label: "Calls", href: "/dashboard/calls", icon: I["/dashboard/calls"], resource: "calls" },
    { label: "Personal WhatsApp", href: "/dashboard/settings/whatsapp-personal", icon: MessageCircle, resource: "whatsapp_personal" },
  ] },
  { key: "leads", title: "Leads", icon: I["/dashboard/leads"], links: [
    { label: "Pipeline", href: "/dashboard/leads", icon: I["/dashboard/leads"], resource: "guests" },
    { label: "Segments", href: "/dashboard/leads/segments", icon: UsersRound, resource: "guests", onlyRoles: MANAGERS },
    { label: "Quotes", href: "/dashboard/quotes", icon: Calculator, resource: "guests", onlyRoles: QUOTE_WRITE_ROLES, onlyForBusinessTypes: ["caravan"] },
    { label: "Rate calculator", href: "/dashboard/calculator", icon: Calculator, resource: "properties", hideForBusinessTypes: ["caravan"] },
  ] },
  { key: "bookings", title: "Bookings", icon: I["/dashboard/bookings"], links: [
    { label: "Calendar", href: "/dashboard/portfolio/calendar", icon: I["/dashboard/portfolio/calendar"], resource: "properties" },
    { label: "Bookings", href: "/dashboard/bookings", icon: I["/dashboard/bookings"], resource: "guests", onlyRoles: BOOKING_READ_ROLES },
    { label: "Properties", href: "/dashboard/properties", icon: Building, resource: "properties", hideForBusinessTypes: ["caravan"] },
    { label: "Channel manager", href: "/dashboard/inbox/channel-manager", icon: Building2, resource: "inbox", hideForBusinessTypes: ["caravan"] },
  ] },
  // Ops module: every segment with an ops pack (lib/segments.ts). Roster and alert chain: owner/manager (ops.manage).
  { key: "ops", title: "Ops", icon: I["/dashboard/ops"], links: [
    { label: "Today and {booking} files", href: "/dashboard/ops", icon: I["/dashboard/ops"], resource: "inbox", onlyRoles: OPS_READ_ROLES, onlyForBusinessTypes: OPS_BUSINESS_TYPES },
    { label: "Money", href: "/dashboard/ops/money", icon: Wallet, resource: "inbox", onlyRoles: OPS_READ_ROLES, onlyForBusinessTypes: OPS_BUSINESS_TYPES },
    { label: "Vehicle map", href: "/dashboard/ops/map", icon: MapPin, resource: "inbox", onlyRoles: OPS_READ_ROLES, onlyForBusinessTypes: ["caravan"] },
    { label: "Who is on duty", href: "/dashboard/ops/staff/duty", icon: CalendarClock, resource: "inbox", onlyRoles: MANAGERS, onlyForBusinessTypes: STAFF_TYPES },
    { label: "If nobody answers", href: "/dashboard/ops/staff/alerts", icon: BellRing, resource: "inbox", onlyRoles: MANAGERS, onlyForBusinessTypes: STAFF_TYPES },
  ] },
  { key: "marketing", title: "Marketing", icon: Megaphone, links: [
    { label: "Overview", href: "/dashboard/marketing", icon: Megaphone, resource: "analytics", onlyRoles: MARKETERS },
    { label: "WhatsApp overview", href: "/dashboard/messaging", icon: Send, resource: "settings" },
    { label: "Campaigns", href: "/dashboard/messaging/campaigns", icon: Megaphone, resource: "campaigns" },
    { label: "Templates", href: "/dashboard/messaging/templates", icon: FileText, resource: "templates" },
    { label: "WhatsApp contacts", href: "/dashboard/messaging/subscribers", icon: UserCheck, resource: "subscribers" },
    { label: "Growth tools", href: "/dashboard/messaging/growth", icon: Link2, resource: "campaigns", onlyRoles: MARKETERS },
    { label: "Website", href: "/dashboard/marketing/website", icon: Globe, resource: "analytics", onlyRoles: MARKETERS },
    { label: "Get found", href: "/dashboard/marketing/sops", icon: ListChecks, resource: "inbox", onlyRoles: SOPS_READ_ROLES },
    { label: "Instagram insights", href: "/dashboard/instagram-insights", icon: AtSign, resource: "analytics" },
  ] },
  // One home for everything that runs on its own (it used to be four places).
  { key: "automations", title: "Automations", icon: Zap, links: [
    { label: "WhatsApp and rules", href: "/dashboard/automations", icon: Zap, resource: "settings" },
    { label: "Instagram", href: "/dashboard/instagram-automations", icon: AtSign, resource: "settings", onlyRoles: MANAGERS },
    { label: "Lead workflows", href: "/dashboard/workflows", icon: Workflow, resource: "settings", onlyRoles: MANAGERS },
    { label: "Flows and drips", href: "/dashboard/messaging/flows", icon: GitBranch, resource: "flows" },
  ] },
  { key: "ai", title: "AI", icon: Sparkles, links: [
    { label: "HAIP Executive", href: "/dashboard/analyst", icon: Target, resource: "analytics", onlyRoles: MANAGERS },
    { label: "AI Concierge and sales agent", href: "/dashboard/settings?tab=ai", icon: Bot, resource: "settings" },
    { label: "Knowledge and business data", href: "/dashboard/settings/knowledge", icon: BookOpen, resource: "settings" },
    { label: "AI learning", href: "/dashboard/settings/learning", icon: FlaskConical, resource: "settings", onlyRoles: MANAGERS },
    { label: "Lead autopilot", href: "/dashboard/settings/lead-autopilot", icon: Bot, resource: "settings", onlyRoles: MANAGERS },
  ] },
  { key: SETTINGS_KEY, title: "Settings", icon: I["/dashboard/settings"], groups: SETTINGS_GROUPS,
    links: SETTINGS_GROUPS.flatMap(g => g.links) },
];

/** Pages reached from the avatar menu, not the rail (one entry point each). */
export const ACCOUNT_LINKS: NavLink[] = [
  { label: "Profile", href: "/dashboard/profile", icon: UserCircle, resource: "profile" },
  { label: "Help and support", href: "/dashboard/help", icon: HelpCircle, resource: "help" },
];

/** Phone bottom bar: four destinations around the raised "Now" button (My day). */
export const PHONE_TABS = ["/dashboard", "/dashboard/inbox", "/dashboard/leads", "/dashboard/portfolio/calendar"];
export const NOW_HREF = "/dashboard/my-day";

// Personal workspace (one person's own calls, services/personal_calls.py): only Calls and Reminders, no company screens.
export const PERSONAL_HOME = "/dashboard/me";
export const PERSONAL_SECTIONS: NavSection[] = [
  { title: "Yaad", links: [
    { label: "Memories", href: PERSONAL_HOME, icon: Phone, resource: "profile" },
    { label: "Reminders", href: "/dashboard/me/reminders", icon: ListChecks, resource: "profile" },
    { label: "Calendar", href: "/dashboard/me/calendar", icon: Calendar, resource: "profile" },
    { label: "Ask Yaad", href: "/dashboard/me/ask", icon: AskBubble, resource: "profile" },
  ] },
  { title: "Settings", links: [
    { label: "Yaad settings", href: "/dashboard/me/settings", icon: Settings, resource: "profile" },
    { label: "Calls app phones", href: "/dashboard/settings/calls-app", icon: Phone, resource: "users", onlyRoles: MANAGERS },
    { label: "Profile", href: "/dashboard/profile", icon: UserCircle, resource: "profile" },
    { label: "Help & support", href: "/dashboard/help", icon: HelpCircle, resource: "help" },
  ] },
];
const PERSONAL_TABS = [PERSONAL_HOME, "/dashboard/me/ask", "/dashboard/me/reminders", "/dashboard/me/calendar"];

export function isVisible(link: NavLink, role: string, businessType: string | null | undefined): boolean {
  return canSeeNav(role, link.resource)
    && (!link.onlyRoles || link.onlyRoles.includes(role))
    && (!businessType || !link.hideForBusinessTypes?.includes(businessType))
    && (!link.onlyForBusinessTypes || (!!businessType && link.onlyForBusinessTypes.includes(businessType)))
    && (!link.ownerOnly || role === "owner");
}

/** A link with a query (`/dashboard/settings?tab=ai`) is that page only when the query matches; without `search` the query
 *  is ignored (old behaviour, used for plain highlighting). */
export function linkActive(pathname: string, href: string, search?: string): boolean {
  const [path, query] = href.split("?");
  if (query !== undefined && search !== undefined) {
    const want = new URLSearchParams(query), have = new URLSearchParams(search);
    for (const [k, v] of want) if (have.get(k) !== v) return false;
  }
  if (path === "/dashboard") return pathname === "/dashboard";
  if (path === PERSONAL_HOME) return pathname === PERSONAL_HOME || pathname.startsWith(PERSONAL_HOME + "/calls");
  return pathname === path || pathname.startsWith(path + "/");
}

/** The area a page belongs to: the one holding the longest matching link (/dashboard/settings/knowledge is AI, not Settings). */
export function areaFor(sections: NavSection[], pathname: string, search = ""): NavSection | undefined {
  let best: { section: NavSection; len: number } | undefined;
  for (const section of sections) {
    for (const link of section.links) {
      if (!linkActive(pathname, link.href, search)) continue;
      const len = link.href.length;      // a matching query makes the link more specific
      if (!best || len > best.len) best = { section, len };
    }
  }
  return best?.section;
}

function filterSection(s: NavSection, role: string, businessType: string | null | undefined): NavSection {
  const booking = segmentFor(businessType).booking.one;   // "{booking}" in a label = the segment's word: trip | stay
  const keep = (l: NavLink) => isVisible(l, role, businessType);
  const word = (l: NavLink) => (l.label.includes("{booking}") ? { ...l, label: l.label.replace("{booking}", booking) } : l);
  const groups = s.groups?.map(g => ({ ...g, links: g.links.filter(keep).map(word) })).filter(g => g.links.length > 0);
  return { ...s, links: s.links.filter(keep).map(word), ...(groups ? { groups } : {}) };
}

/** Everything the shell needs: visible areas, a lookup by href, live badge counts, the active area and the active test. */
export function useNav(role: string) {
  const businessType = useBusinessType();
  const pathname = useAppPathname();
  const search = useSearchParams()?.toString() ?? "";
  // Yaad's own pages are personal by definition: no flash of the business tabs while the workspace context loads.
  const personal = usePersonalMode() || pathname === PERSONAL_HOME || pathname.startsWith(PERSONAL_HOME + "/");
  const { conversations } = useInboxStore();
  const canSeeMyDay = canSeeNav(role, "inbox") && !personal;
  // Same source and query key as My day, so the badge and the list always agree.
  const { data: queue } = useQuery<{ total: number; people_waiting?: number; severity?: { stale?: number } }>({
    queryKey: ["work-queue", ""],
    queryFn: () => api.get("/work-queue").then(r => r.data),
    staleTime: 30_000,
    refetchInterval: 60_000,
    enabled: canSeeMyDay,
  });
  const sections = (personal ? PERSONAL_SECTIONS : NAV_SECTIONS)
    .map(s => filterSection(s, role, businessType))
    .filter(s => s.links.length > 0);
  const account = ACCOUNT_LINKS.filter(l => isVisible(l, role, businessType));
  const byHref = new Map([...sections.flatMap(s => s.links), ...account].map(l => [l.href, l]));
  const unread = conversations.filter(c => (c as { unread_count?: number }).unread_count! > 0).length;
  // People, not rows (one person with a missed call and a task is one), and not the cold tail: work_queue_service
  // `people_waiting`. Home's "Waiting on the team" tile and the phone's Now button read this same number.
  const waiting = queue?.people_waiting ?? Math.max(0, (queue?.total ?? 0) - (queue?.severity?.stale ?? 0));
  const badge = (href: string): number => (href === "/dashboard/inbox" ? unread : href === NOW_HREF ? waiting : 0);
  /** An area's count on the rail: the badges of its pages (Home carries My day, Inbox carries unread chats). */
  const areaBadge = (s: NavSection): number => s.links.reduce((n, l) => n + badge(l.href), 0);
  const phoneTabs = personal ? PERSONAL_TABS : PHONE_TABS;
  const nowHref = personal ? null : NOW_HREF;
  const activeArea = personal ? undefined : areaFor(sections, pathname, search);
  return { sections, byHref, account, badge, areaBadge, waiting, phoneTabs, nowHref, personal, activeArea,
    isActive: (href: string) => linkActive(pathname, href),
    /** Exact match for a panel: a page with a query only when the query matches, and the plain page not when one does. */
    isCurrent: (href: string, siblings: string[] = []) => linkActive(pathname, href, search)
      && !siblings.some(o => o !== href && o.length > href.length && linkActive(pathname, o, search)),
    pathname };
}
