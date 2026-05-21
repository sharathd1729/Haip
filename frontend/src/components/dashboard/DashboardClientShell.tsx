"use client";

/**
 * Client-side shell that mounts all global overlay components for the
 * dashboard. Imported once in dashboard/layout.tsx (server component).
 *
 * Components mounted here:
 *   - CommandPalette   (X6) — Cmd+K global shortcut, rendered outside flow
 *   - ChecklistWidget  (O5) — setup progress widget, fixed bottom-right
 *
 * NOTE: StatusBar (X8) is rendered inline within the main column via
 * StatusBarSlot so it participates in flex layout between topbar and content.
 */

import { CommandPalette } from "@/components/ui/CommandPalette";

export function DashboardClientShell() {
  return (
    <>
      {/* Global Cmd+K command palette — renders as a portal overlay */}
      <CommandPalette />
    </>
  );
}

// Separate named export for the inline StatusBar slot — placed between
// TopBar and page content in the server layout.
export { StatusBar as StatusBarSlot } from "@/components/dashboard/StatusBar";
