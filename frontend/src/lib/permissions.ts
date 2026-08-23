/**
 * HAIP Role-Based Access Control
 *
 * Roles (match backend UserRole enum):
 *   owner        — full access
 *   manager      — everything except compliance/audit
 *   concierge    — inbox + calls (read)
 *   reservations — inquiries + guests
 *   compliance   — audit + compliance center only
 */

import React from "react";

// ─── Role enum ────────────────────────────────────────────────────────────────

export type UserRole =
  | "owner"
  | "manager"
  | "concierge"
  | "reservations"
  | "marketing"
  | "compliance"
  | "foh"
  | "read_only";

// ─── Resource keys (match sidebar nav + API resource names) ──────────────────

export type Resource =
  | "dashboard"
  | "calls"
  | "inbox"
  | "inquiries"
  | "guests"
  | "properties"
  | "analytics"
  | "qa"
  | "compliance"
  | "settings"
  | "users"
  | "integrations"
  | "messaging"
  | "templates"
  | "campaigns"
  | "subscribers"
  | "flows"
  | "reports"
  | "billing"
  | "help"
  | "profile"
  | "branding";

// ─── navByRole — which nav items each role can see ───────────────────────────
// Used in sidebar.tsx to conditionally render nav items.

export const navByRole: Record<UserRole, Resource[]> = {
  read_only: [
    "dashboard", "calls", "inbox", "inquiries", "guests", "analytics",
    "profile", "help",
  ],
  owner: [
    "dashboard", "calls", "inbox", "inquiries", "guests", "properties",
    "analytics", "qa", "compliance", "settings", "users", "integrations",
    "messaging", "templates", "campaigns", "subscribers", "flows",
    "reports", "billing", "profile", "help", "branding",
  ],
  manager: [
    "dashboard", "calls", "inbox", "inquiries", "guests", "properties",
    "analytics", "qa", "settings", "users", "messaging", "templates",
    "campaigns", "subscribers", "flows", "reports", "profile", "help", "branding",
  ],
  concierge: [
    "dashboard", "calls", "inbox", "guests", "profile", "help",
  ],
  reservations: [
    "dashboard", "calls", "inquiries", "guests", "inbox", "profile", "help",
  ],
  compliance: [
    "compliance", "analytics", "profile", "help",
  ],
  marketing: [
    "dashboard", "guests", "messaging", "templates", "campaigns",
    "subscribers", "flows", "analytics", "profile", "help",
  ],
  foh: [
    "dashboard", "inbox", "calls", "guests", "inquiries", "profile", "help",
  ],
};

// ─── Action-level permission map ─────────────────────────────────────────────

type Action = "read" | "write" | "delete" | "manage";

const permissions: Record<UserRole, Record<Resource, Action[]>> = {
  owner: {
    dashboard:    ["read"],
    calls:        ["read", "write", "delete"],
    inbox:        ["read", "write"],
    inquiries:    ["read", "write", "delete", "manage"],
    guests:       ["read", "write", "delete"],
    properties:   ["read", "write", "delete", "manage"],
    analytics:    ["read"],
    qa:           ["read", "write", "manage"],
    compliance:   ["read", "manage"],
    settings:     ["read", "write", "manage"],
    users:        ["read", "write", "delete", "manage"],
    integrations: ["read", "write", "manage"],
    messaging:    ["read", "write", "manage"],
    templates:    ["read", "write", "delete", "manage"],
    campaigns:    ["read", "write", "delete", "manage"],
    subscribers:  ["read", "write", "manage"],
    flows:        ["read", "write", "delete", "manage"],
    reports:      ["read", "write", "manage"],
    billing:      ["read", "write", "manage"],
    help:         ["read"],
    profile:      ["read", "write"],
    branding:     ["read", "write", "manage"],
  },
  manager: {
    dashboard:    ["read"],
    calls:        ["read", "write"],
    inbox:        ["read", "write"],
    inquiries:    ["read", "write", "manage"],
    guests:       ["read", "write"],
    properties:   ["read", "write"],
    analytics:    ["read"],
    qa:           ["read", "write"],
    compliance:   [],
    settings:     ["read", "write"],
    users:        ["read", "write"],
    integrations: ["read"],
    messaging:    ["read", "write", "manage"],
    templates:    ["read", "write", "manage"],
    campaigns:    ["read", "write", "manage"],
    subscribers:  ["read", "write"],
    flows:        ["read", "write", "manage"],
    reports:      ["read", "write"],
    billing:      ["read"],
    help:         ["read"],
    profile:      ["read", "write"],
    branding:     ["read", "write"],
  },
  concierge: {
    dashboard:    ["read"],
    calls:        ["read"],
    inbox:        ["read", "write"],
    inquiries:    [],
    guests:       ["read"],
    properties:   [],
    analytics:    [],
    qa:           [],
    compliance:   [],
    settings:     [],
    users:        [],
    integrations: [],
    messaging:    [],
    templates:    [],
    campaigns:    [],
    subscribers:  [],
    flows:        [],
    reports:      [],
    billing:      [],
    help:         ["read"],
    profile:      ["read", "write"],
    branding:     [],
  },
  reservations: {
    dashboard:    ["read"],
    calls:        [],
    inbox:        ["read", "write"],
    inquiries:    ["read", "write"],
    guests:       ["read", "write"],
    properties:   ["read"],
    analytics:    [],
    qa:           [],
    compliance:   [],
    settings:     [],
    users:        [],
    integrations: [],
    messaging:    [],
    templates:    [],
    campaigns:    [],
    subscribers:  [],
    flows:        [],
    reports:      [],
    billing:      [],
    help:         ["read"],
    profile:      ["read", "write"],
    branding:     [],
  },
  compliance: {
    dashboard:    [],
    calls:        ["read"],
    inbox:        [],
    inquiries:    ["read"],
    guests:       ["read"],
    properties:   [],
    analytics:    ["read"],
    qa:           ["read"],
    compliance:   ["read", "manage"],
    settings:     [],
    users:        ["read"],
    integrations: [],
    messaging:    [],
    templates:    ["read"],
    campaigns:    ["read"],
    subscribers:  ["read"],
    flows:        [],
    reports:      ["read"],
    billing:      [],
    help:         ["read"],
    profile:      ["read", "write"],
    branding:     [],
  },
  marketing: {
    dashboard:    ["read"],
    calls:        [],
    inbox:        [],
    inquiries:    ["read"],
    guests:       ["read"],
    properties:   ["read"],
    analytics:    ["read"],
    qa:           [],
    compliance:   [],
    settings:     [],
    users:        [],
    integrations: [],
    messaging:    ["read", "write", "manage"],
    templates:    ["read", "write", "manage"],
    campaigns:    ["read", "write", "manage"],
    subscribers:  ["read", "write"],
    flows:        ["read", "write"],
    reports:      ["read"],
    billing:      [],
    help:         ["read"],
    profile:      ["read", "write"],
    branding:     [],
  },
  foh: {
    dashboard:    ["read"],
    calls:        ["read"],
    inbox:        ["read", "write"],
    inquiries:    ["read", "write"],
    guests:       ["read"],
    properties:   ["read"],
    analytics:    [],
    qa:           [],
    compliance:   [],
    settings:     [],
    users:        [],
    integrations: [],
    messaging:    [],
    templates:    [],
    campaigns:    [],
    subscribers:  [],
    flows:        [],
    reports:      [],
    billing:      [],
    help:         ["read"],
    profile:      ["read", "write"],
    branding:     [],
  },
  read_only: {
    dashboard:    ["read"],
    calls:        ["read"],
    inbox:        ["read"],
    inquiries:    ["read"],
    guests:       ["read"],
    properties:   ["read"],
    analytics:    ["read"],
    qa:           ["read"],
    compliance:   ["read"],
    settings:     [],
    users:        ["read"],
    integrations: [],
    messaging:    ["read"],
    templates:    ["read"],
    campaigns:    ["read"],
    subscribers:  ["read"],
    flows:        ["read"],
    reports:      ["read"],
    billing:      [],
    help:         ["read"],
    profile:      ["read", "write"],
    branding:     [],
  },
};

// ─── Helper functions ─────────────────────────────────────────────────────────

/**
 * Check if a role can perform `action` on `resource`.
 * @example hasPermission("manager", "compliance", "read") // false
 */
export function hasPermission(
  role: UserRole | string | undefined | null,
  resource: Resource,
  action: Action = "read"
): boolean {
  if (!role) return false;
  const rolePerms = permissions[role as UserRole];
  if (!rolePerms) return false;
  return (rolePerms[resource] ?? []).includes(action);
}

/**
 * Check if a role can see a nav section.
 * @example canSeeNav("concierge", "compliance") // false
 */
export function canSeeNav(
  role: UserRole | string | undefined | null,
  resource: Resource
): boolean {
  if (!role) return false;
  return (navByRole[role as UserRole] ?? []).includes(resource);
}

// ─── React Gate Components ────────────────────────────────────────────────────

interface RoleGateProps {
  role: string | undefined | null;
  /** Resources the user must have read access to (any one of them). */
  allowed: Resource[];
  /** Action to check (default: "read"). */
  action?: Action;
  /** Rendered when access is denied. Defaults to null (render nothing). */
  fallback?: React.ReactNode;
  children: React.ReactNode;
}

/**
 * Render children only when the user's role has the required permission.
 *
 * @example
 * <RoleGate role={session?.user.role} allowed={["compliance"]}>
 *   <ComplianceCenter />
 * </RoleGate>
 */
export function RoleGate({
  role,
  allowed,
  action = "read",
  fallback = null,
  children,
}: RoleGateProps): React.ReactElement | null {
  const permitted = allowed.some(resource =>
    hasPermission(role, resource, action)
  );
  return (permitted ? children : fallback) as React.ReactElement | null;
}

interface PropertyGateProps {
  /** The property ID from the current context (URL param, store, etc.) */
  propertyId: string | undefined | null;
  /** The user's assigned property IDs (empty array = all properties). */
  userPropertyIds: string[];
  fallback?: React.ReactNode;
  children: React.ReactNode;
}

/**
 * Render children only when the user has access to the given property.
 * Owners/managers with an empty `userPropertyIds` array get full access.
 *
 * @example
 * <PropertyGate propertyId={params.id} userPropertyIds={session.user.propertyIds ?? []}>
 *   <PropertyDetail />
 * </PropertyGate>
 */
export function PropertyGate({
  propertyId,
  userPropertyIds,
  fallback = null,
  children,
}: PropertyGateProps): React.ReactElement | null {
  // Empty array = wildcard (owner/manager with all-property access)
  const permitted =
    !propertyId ||
    userPropertyIds.length === 0 ||
    userPropertyIds.includes(propertyId);
  return (permitted ? children : fallback) as React.ReactElement | null;
}
